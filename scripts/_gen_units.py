#!/usr/bin/env python3
"""根据 config.json 渲染 systemd 单元模板。

被 scripts/install.sh 调用。本身不直接读环境，需要的运行时参数（user/group/uv 路径）
通过 CLI 注入，便于 install.sh 处理 sudo 场景。
"""
import argparse
import json
import sys
from pathlib import Path


def cron_to_oncalendar(expr: str) -> str:
    """5 段 cron 表达式 → systemd OnCalendar 字符串。

    本项目 push_cron 只用到 minute/hour，weekly_cron 额外允许整数 day-of-week
    （0/7=周日 … 6=周六，与 croniter 一致）。day-of-month/month 必须为 `*`。
    遇到不支持的语法直接报错，避免静默生成错误的 timer。
    """
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"无效 cron 表达式（必须 5 段）: {expr}")
    minute, hour, dom, mon, dow = parts
    for label, val in [("day-of-month", dom), ("month", mon)]:
        if val != "*":
            raise ValueError(f"暂不支持非 * 的 {label} 字段: {expr}")
    try:
        m, h = int(minute), int(hour)
    except ValueError as e:
        raise ValueError(f"minute/hour 必须是整数: {expr}") from e
    if not (0 <= m <= 59 and 0 <= h <= 23):
        raise ValueError(f"minute/hour 越界: {expr}")

    if dow == "*":
        return f"*-*-* {h:02d}:{m:02d}:00"
    dow_names = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
    try:
        d = int(dow)
    except ValueError as e:
        raise ValueError(f"day-of-week 必须是整数或 *: {expr}") from e
    if d not in dow_names:
        raise ValueError(f"day-of-week 越界（0-7）: {expr}")
    return f"{dow_names[d]} *-*-* {h:02d}:{m:02d}:00"


def render(template_path: Path, variables: dict) -> str:
    text = template_path.read_text(encoding="utf-8")
    for key, val in variables.items():
        text = text.replace(f"{{{{{key}}}}}", str(val))
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--group", required=True)
    parser.add_argument("--uv-bin", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    template_dir = project_dir / "systemd"

    config_path = project_dir / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    fetch_min = config["schedule"]["fetch_interval_minutes"]
    if not isinstance(fetch_min, int) or fetch_min <= 0:
        raise ValueError(f"fetch_interval_minutes 必须是正整数: {fetch_min}")

    push_crons = config["schedule"]["push_cron"]
    if not push_crons:
        raise ValueError("config.schedule.push_cron 不能为空")
    # 周报 cron 渲染进同一个 dnews-push.timer;push service 跑 run_push_job 自分发
    weekly_crons = config["schedule"].get("weekly_cron", [])
    push_lines = "\n".join(
        f"OnCalendar={cron_to_oncalendar(c)}" for c in [*push_crons, *weekly_crons]
    )

    log_retention = config.get("log", {}).get("retention_days", 7)
    if not isinstance(log_retention, int) or log_retention <= 0:
        raise ValueError(f"log.retention_days 必须是正整数: {log_retention}")

    common = {
        "PROJECT_DIR": str(project_dir),
        "USER": args.user,
        "GROUP": args.group,
        "UV_BIN": args.uv_bin,
    }

    output_dir.mkdir(parents=True, exist_ok=True)

    renderings = [
        ("dnews-fetch.service.tmpl", "dnews-fetch.service", {}),
        ("dnews-fetch.timer.tmpl",   "dnews-fetch.timer",
         {"FETCH_INTERVAL_MIN": fetch_min}),
        ("dnews-push.service.tmpl",  "dnews-push.service", {}),
        ("dnews-push.timer.tmpl",    "dnews-push.timer",
         {"PUSH_ONCALENDAR_LINES": push_lines}),
        ("dnews-web.service.tmpl",   "dnews-web.service", {}),
        ("journald-dnews.conf.tmpl", "journald-dnews.conf",
         {"LOG_RETENTION_DAYS": log_retention}),
    ]

    print(f"📂 输出目录: {output_dir}")
    for tpl_name, out_name, extra in renderings:
        tpl_path = template_dir / tpl_name
        if not tpl_path.exists():
            print(f"❌ 模板不存在: {tpl_path}", file=sys.stderr)
            return 2
        rendered = render(tpl_path, {**common, **extra})
        (output_dir / out_name).write_text(rendered, encoding="utf-8")
        print(f"  ✓ {out_name}")

    print(f"\n生成参数:")
    print(f"  fetch 间隔  → 每 {fetch_min} 分钟（间隔触发，从上次完成开始计时）")
    for c, line in zip(push_crons, push_lines.split("\n")[: len(push_crons)]):
        print(f"  push '{c}' → {line}")
    for c, line in zip(weekly_crons, push_lines.split("\n")[len(push_crons):]):
        print(f"  weekly '{c}' → {line}")
    print(f"  日志保留    → {log_retention} 天")
    web_cfg = config.get("web", {})
    print(
        f"  web 归档    → http://{web_cfg.get('host', '127.0.0.1')}:{web_cfg.get('port', 8000)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
