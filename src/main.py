"""AI每日资讯推送系统 - 主程序"""

import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

# 加载 .env 文件
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from croniter import croniter

from src.config import get_timezone, load_config, merge_sources
from src.fetcher import fetch_all_feeds
from src.llm import (
    check_llm_available,
    generate_immediate_push,
    parse_immediate_push_with_metadata,
    score_batch,
)
from src.markdown_utils import extract_md_links, parse_frontmatter
from src.processor import html_to_markdown
from src.push import send_to_platforms
from src.site_sync import sync_reports_to_site
from src.sections.gaps.section import run_gaps_section
from src.sections.hackernews.section import run_hackernews_section
from src.sections.insights.section import run_insights_section
from src.sections.relevance.section import run_relevance_section
from src.sections.rss.section import run_rss_section
from src.sections.common import weekly_window, window_stats
from src.sections.weekly.section import build_weekly_top_section, run_weekly_section
from src.storage import (
    append_entries,
    assemble_with_sentinels,
    cleanup_old_files,
    get_fetch_file,
    get_notify_file,
    get_push_file,
    get_relevance_file,
    load_existing_links,
    load_pushed_links,
    load_recent_notify_content,
    load_recent_push_content,
    read_entries,
    record_pushed_links,
    save_notify_file,
    save_push_file,
)


async def notify_llm_errors(stage: str, errors: List[str], config: Dict):
    """LLM 异常通知:默认只打印到日志(journal);`notify.llm_error_push` 置 true 时才推送各平台。

    2026-09-08 起默认不推送——评分超时等瞬时错误在群里刷屏价值低,
    排查用 daily-news logs / journalctl。
    """
    if not errors:
        return

    lines = [
        "## LLM异常",
        "",
        f"stage: {stage}",
        f"time: {now_local(config).strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    lines.extend(f"- {error}" for error in errors)
    print("\n".join(lines))

    if not config.get("notify", {}).get("llm_error_push", False):
        return
    try:
        await send_to_platforms("\n".join(lines), config["push"])
    except Exception as e:
        print(f"⚠️ LLM异常通知发送失败: {e}")


def now_local(config: Dict = None) -> datetime:
    """获取配置时区的当前时间"""
    return datetime.now(get_timezone(config))


def _record_sent_links(content: str, sent: bool):
    """实际送达后,把推送内容中的链接记入已推送永久记录(全部平台失败时不记)"""
    if not sent:
        return
    added = record_pushed_links(extract_md_links(content))
    if added:
        print(f"📝 已推送链接记录 +{added}")


def parse_time_to_local(time_str: str, config: Dict = None) -> Optional[datetime]:
    """解析时间字符串为配置时区的datetime"""
    try:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        return dt.astimezone(get_timezone(config))
    except (ValueError, TypeError):
        return None


def calculate_push_times(
    cron_list: List[str], offset_days: int = 0, config: Dict = None
) -> List[datetime]:
    base_date = datetime.now(get_timezone(config)).date() + timedelta(days=offset_days)
    times = []
    for cron in cron_list:
        try:
            minute, hour, _, _, _ = cron.split()
            t = datetime.combine(
                base_date,
                datetime.strptime(f"{hour}:{minute}", "%H:%M").time(),
                tzinfo=get_timezone(config),
            )
            times.append(t)
        except ValueError:
            continue
    return sorted(times)


def is_morning_push(now: datetime, config: Dict) -> bool:
    """判定当前 push 是否为「早报」(触发 HN/insights/gaps 额外段)。

    规则:在 `schedule.push_cron` 列表里,now 离哪条 cron 最近,就归为那条;
    最近的那条若是当天最早的 cron,则视为早报。

    特例:
    - `push_cron` 为空 → 不视为早报
    - `push_cron` 只有一条 → 该条即"最早"也即"最近",任何触发都视为早报
    """
    cron_list = config.get("schedule", {}).get("push_cron", [])
    if not cron_list:
        return False
    if len(cron_list) == 1:
        return True

    base = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_fires = [croniter(c, base).get_next(datetime) for c in cron_list]
    closest = min(today_fires, key=lambda f: abs(now - f))
    return closest == min(today_fires)


def is_weekly_push(now: datetime, config: Dict) -> bool:
    """判定当前 push 是否命中 `schedule.weekly_cron`(周报)。

    weekly_cron 带星期约束(如周四/周日),与 push_cron 无交集时无歧义;
    容差 2 分钟,吸收 loop/systemd 的执行延迟。weekly_cron 为空 → False。
    """
    cron_list = config.get("schedule", {}).get("weekly_cron", [])
    for c in cron_list:
        if not croniter.is_valid(c):
            continue
        # croniter.get_prev 不含当前时刻,整点触发会漏判;改为从 now-2min 取 next
        base = now - timedelta(minutes=2)
        if base < croniter(c, base).get_next(datetime) <= now:
            return True
    return False


def collect_entries_for_push(
    last_push_time: Optional[datetime],
    context_days: int = 2,
    min_score: int = 60,
    data_dir: str = "news-data",
) -> tuple[List[Dict], List[Dict]]:
    """
    收集推送所需的条目，返回 (待推送条目, 上下文条目)

    逻辑：
    1. 获取 context_days 天内的所有条目
    2. 按 min_score 过滤
    3. push_time = max(last_push_time, now - 24h)
    4. 晚于 push_time 的 → 待推送条目
    5. 早于 push_time 的 → 上下文条目（用于LLM去重参考）
    """
    tz = get_timezone()
    now = datetime.now(tz)

    # 获取 context_days 天的所有条目
    all_entries = []
    today = now.date()
    for i in range(context_days):
        d = today - timedelta(days=i)
        fetch_file = get_fetch_file(d, data_dir)
        for entry in read_entries(fetch_file):
            all_entries.append(entry)

    print(
        f"📋 收集总条目: {len(all_entries)} 条 , context_days: {context_days}, min_score:{min_score}"
    )

    # 按 min_score 过滤
    qualified_entries = [e for e in all_entries if (e.get("score") or 0) >= min_score]
    print(f"📋 过滤后条目: {len(qualified_entries)} 条 ")

    # 计算推送时间边界：max(last_push_time, now - 24h)
    past_24h = now - timedelta(hours=24)
    push_cutoff = (
        last_push_time if last_push_time and last_push_time > past_24h else past_24h
    )

    print(f"推送时间边界: {push_cutoff.strftime('%Y-%m-%d %H:%M:%S')}")

    # 分割条目
    to_push = []
    context = []
    # context 只供 LLM 做去重/历史参考,不需要 content/link/fetched_at 等大字段
    CONTEXT_FIELDS = ("title", "source", "score", "summary", "tags", "published")

    for entry in qualified_entries:
        entry_time = parse_time_to_local(entry.get("fetched_at", ""))
        if entry_time and entry_time > push_cutoff:
            to_push.append(entry)
        else:
            context.append({k: entry.get(k) for k in CONTEXT_FIELDS})

    # 上下文按分数排序，取前50
    context = sorted(context, key=lambda x: x.get("score", 0), reverse=True)[:50]

    return to_push, context


async def run_fetch_job(config: Dict):
    print(f"\n{'=' * 50}")
    print(f"🔄 Fetch Job | {now_local().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 50}")

    interval = config["schedule"]["fetch_interval_minutes"]
    lookback = config["schedule"].get("fetch_lookback_minutes", 120)
    lookback = max(lookback, interval)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback)

    sources = merge_sources(config["sources"])
    print(f"📂 共 {len(sources)} 个订阅源")

    if not sources:
        print("⚠️ 没有可用的订阅源")
        return

    max_workers = config.get("fetch", {}).get("max_workers", 20)
    timeout = config.get("fetch", {}).get("timeout", 30)
    entries = await fetch_all_feeds(
        sources, cutoff, max_workers=max_workers, timeout=timeout
    )
    print(f"📥 抓取到 {len(entries)} 条原始消息")

    # Tavily 主动检索:结果与 RSS 条目同构,统一走去重+评分管线
    # 失败/限频/未配置 key 均返回空,不阻断 RSS 主流程
    try:
        from src.search_fetcher import fetch_search_entries

        search_entries, _search_errors = await fetch_search_entries(config)
        if search_entries:
            entries.extend(search_entries)
            print(f"🔍 Tavily: 新增 {len(search_entries)} 条")
    except Exception as e:
        print(f"⚠️ Tavily 搜索异常(已跳过): {e}")

    if not entries:
        return

    for entry in entries:
        entry["content"] = html_to_markdown(
            entry.get("content", ""), entry.get("link", "")
        )

    fetch_file = get_fetch_file()
    dedup_days = config["filter"].get("fetch_dedup_days", 3)
    existing_links = load_existing_links(fetch_file, days=dedup_days)
    # 永久已推送记录:同一 URL 只要推送过就永久拦截(窗口式去重对超窗重复原理性失效)
    pushed_links = load_pushed_links()
    new_entries = []
    blocked_pushed = 0
    for e in entries:
        link = e.get("link")
        if not link or link in existing_links:
            continue
        if link in pushed_links:
            blocked_pushed += 1
            continue
        new_entries.append(e)
    if blocked_pushed:
        print(f"🧱 已推送记录拦截 {blocked_pushed} 条历史重复链接")
    print(f"🆕 新消息 {len(new_entries)} 条 | 链接数：{len(existing_links)}")

    if not new_entries:
        return

    print("🤖 LLM评分中...")
    # 预处理：将所有 datetime 转换为字符串，避免 JSON 序列化错误
    for entry in new_entries:
        if isinstance(entry.get("published"), datetime):
            entry["published"] = (
                entry["published"].astimezone(get_timezone(config)).isoformat()
            )

    scored, score_errors = await score_batch(new_entries, config["llm"])
    if score_errors:
        print(f"⚠️ [score_batch] {len(score_errors)} 个错误: {score_errors[0]}")
        # 「评分结果异常」(数量不匹配,漏评条目下轮 fetch 自动补评)属可自愈,
        # 仅本地告警不推飞书;「评分失败」(网络/解析异常)才需要通知
        fatal_errors = [e for e in score_errors if "评分结果异常" not in e]
        if fatal_errors:
            await notify_llm_errors("score_batch", fatal_errors, config)

    is_new_file = not os.path.exists(fetch_file)
    if is_new_file:
        cleanup_old_files(
            days=config["filter"].get("keep_days"),
            archive_days=config["filter"].get("archive_keep_days"),
        )

    # 添加 fetched_at 时间戳
    for entry in scored:
        entry["fetched_at"] = now_local().isoformat()
        if isinstance(entry.get("published"), datetime):
            entry["published"] = (
                entry["published"].astimezone(get_timezone(config)).isoformat()
            )

    # 批量保存到 JSON 文件
    from datetime import date

    meta = {"date": date.today().isoformat()}
    append_entries(fetch_file, scored, meta)

    print(f"💾 已保存到 {fetch_file}")

    hot_threshold = config["filter"]["hot_threshold"]
    no_content_marker = config["filter"].get("no_content_marker", "[NO_NEW_CONTENT]")
    hot_entries = [e for e in scored if (e.get("score") or 0) >= hot_threshold]
    # 快讯硬过滤:已推送过的链接不再触发(fetch 级拦截的冗余保险,覆盖绕行路径)
    fresh_hot = [e for e in hot_entries if e.get("link") not in pushed_links]
    if len(fresh_hot) < len(hot_entries):
        print(f"🧱 {len(hot_entries) - len(fresh_hot)} 条热点链接已在历史推送中,跳过快讯")
    hot_entries = fresh_hot
    if hot_entries:
        print(f"🔥 发现 {len(hot_entries)} 条热点消息，即时推送...")

        # 加载近期已推送内容（仅供 LLM 查重，避免风格趋同）
        context_days = config["filter"]["context_days"]
        recent_notify = load_recent_notify_content(context_days)
        recent_push = load_recent_push_content(context_days)
        recent_context = (
            f"=== 近期即时推送 ===\n{recent_notify}\n\n"
            f"=== 近期汇总推送 ===\n{recent_push}"
        )

        push_content, immediate_push_error = await generate_immediate_push(
            hot_entries, config["llm"], recent_push_context=recent_context
        )

        if immediate_push_error:
            print(f"⚠️ [generate_immediate_push] {immediate_push_error}")
            await notify_llm_errors(
                "generate_immediate_push", [immediate_push_error], config
            )

        if not push_content:
            print("⚠️ 即时推送内容生成失败，跳过本次热点推送")
            print(
                f"✅ Fetch Job 完成 | 新消息: {len(scored)} 条 | 热点: {len(hot_entries)} 条"
            )
            return

        # 检查是否有实际内容需要推送
        if no_content_marker in push_content:
            print(f"ℹ️ 无新内容需要推送 (LLM判定为重复内容)")
        else:
            # 提取标题并构建 metadata
            now = now_local(config)
            timestamp = now.strftime("%Y-%m-%d %H:%M")
            content_without_title, metadata = parse_immediate_push_with_metadata(
                push_content, f"🚨 AI4S Daily 快讯 | {timestamp}"
            )
            metadata["pushTime"] = now.isoformat()

            sent = await send_to_platforms(
                content_without_title,
                config["push"],
                "🚨 AI4S Daily 快讯 | " + metadata["title"],
                metadata=metadata,
            )
            # 保存即时推送内容到notify文件
            notify_file = get_notify_file()
            save_notify_file(notify_file, content_without_title, metadata)
            print(f"💾 已保存即时推送到 {notify_file}")
            _record_sent_links(content_without_title, sent)

    print(f"✅ Fetch Job 完成 | 新消息: {len(scored)} 条 | 热点: {len(hot_entries)} 条")


async def run_push_job(config: Dict, deliver: bool = True):
    print(f"\n{'=' * 50}")
    print(f"📤 Push Job | {now_local().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 50}")

    # weekly 判在最前:单条 push_cron 时 is_morning_push 恒为 True,
    # 不先判的话周报触发点(如周四 17:00)会被误判为早报
    if is_weekly_push(now_local(config), config):
        await _run_weekly_push(config, deliver=deliver)
    elif is_morning_push(now_local(config), config):
        await _run_morning_push(config, deliver=deliver)
    else:
        await _run_default_push(config, deliver=deliver)


async def _run_default_push(config: Dict, deliver: bool = True):
    """晚报或非早报时段:沿用原有纯 RSS digest 流程,委托给 run_rss_section"""
    now = now_local(config)
    rss_md, metadata, rss_err = await run_rss_section(config, now)

    if rss_err and not rss_md:
        print(f"⚠️ [compose_digest] {rss_err}")
        await notify_llm_errors("compose_digest", [rss_err], config)
        raise RuntimeError(f"RSS section failed: {rss_err}")

    if not rss_md:
        # run_rss_section 在无新消息时已打印 "ℹ️ RSS: 无新消息"
        return

    # metadata 缺失兜底:parse_digest_with_metadata 失败 / LLM 输出无 frontmatter 时可能返回 None
    if not metadata:
        date_str = now.strftime("%Y-%m-%d")
        metadata = {
            "title": f"🌙 AI4S Daily 晚报 | {date_str}",
            "lead": "",
            "highlights": [],
            "profile": "default",
            "date": date_str,
        }
    metadata.setdefault("pushTime", now.isoformat())

    if deliver:
        sent = await send_to_platforms(
            rss_md,
            config["push"],
            title="📰 AI4S Daily 每日精选 | " + metadata["title"],
            metadata=metadata,
        )
        _record_sent_links(rss_md, sent)
    push_file = get_push_file()
    rss_count = rss_md.count("###")
    # 优先用 RSS 板块统计的真实数字(条目数/源数),缺失时回退标题计数
    stat_sources = metadata.get("sourceCount", rss_count)
    stat_total = metadata.get("totalEntries", rss_count)
    save_push_file(
        push_file,
        rss_md,
        stat_sources,
        stat_total,
        profile="default",
        metadata=metadata,
    )
    print(f"💾 已保存到 {push_file}")
    if not deliver:
        print(f"📝 报告已生成(未推送),审查后可执行: python -m src.main deliver {push_file}")
    print(f"✅ Push Job 完成 | 推送条目: {rss_count}")


async def _run_morning_push(config: Dict, deliver: bool = True):
    """早报编排:RSS/HN/relevance 并发 → insights/gaps 并发 → sentinel 拼装 → 推送 → 落盘。

    失败语义:
    - RSS 失败 → 整体抛 RuntimeError (核心承诺不变)
    - HN/insights/gaps 失败 → 该段省略 + 告警,其他段照推
    - relevance 失败 → 告警 + 段落省略;成功时拼进早报(insights 后、gaps 前),
      同时单独落盘 relevance-*.md 供人工核验
    """
    now = now_local(config)

    # 第一阶段:RSS/HN/relevance 三路并发(relevance 只依赖当日素材,不等板块成品)
    rss_result, hn_result, rel_result = await asyncio.gather(
        run_rss_section(config, now),
        run_hackernews_section(config, now),
        run_relevance_section(config, now),
    )

    # 早报场景:digest 的 metadata 通常会被 insights 段覆盖,
    # 但保留以便在 insights 失败时作为兜底来源(title 关键词 / lead / highlights)
    rss_md, digest_meta, rss_err = rss_result
    hn_md, hn_err = hn_result
    rel_md, rel_err = rel_result

    if hn_err:
        print(f"⚠️ [section_hackernews] {hn_err}")
        await notify_llm_errors("section_hackernews", [hn_err], config)

    # 相关性分析拼进早报(insights 后、gaps 前),同时单独落盘供人工核验
    if rel_err:
        print(f"⚠️ [relevance] {rel_err}")
        await notify_llm_errors("relevance", [rel_err], config)
    elif rel_md:
        rel_file = get_relevance_file()
        header = f"# 与当前01专项工作的相关性（{now.month}.{now.day}）\n\n"
        with open(rel_file, "w", encoding="utf-8") as f:
            f.write(header + rel_md + "\n")
        print(f"💾 相关性分析已保存到 {rel_file}")

    if rss_err and not rss_md:
        print(f"⚠️ [compose_digest] {rss_err}")
        await notify_llm_errors("compose_digest", [rss_err], config)
        raise RuntimeError(f"RSS section failed: {rss_err}")

    # insights 与 gaps 输入同源(top-N + HN 成品)、互不依赖,并发执行
    insights_result, gaps_result = await asyncio.gather(
        run_insights_section(rss_md, hn_md, config, now),
        run_gaps_section(hn_md, config, now),
    )
    insights_md, metadata, insights_err = insights_result
    gaps_md, gaps_err = gaps_result

    if insights_err:
        print(f"⚠️ [insights] {insights_err}")
        await notify_llm_errors("insights", [insights_err], config)
    if gaps_err:
        print(f"⚠️ [gaps] {gaps_err}")
        await notify_llm_errors("gaps", [gaps_err], config)

    # 如果 insights 失败,优先用 digest metadata 兜底;两者都缺再走默认
    if not metadata:
        date_str = now.strftime("%Y-%m-%d")
        fallback = digest_meta or {}
        digest_title = fallback.get("title", "")

        title = digest_title if digest_title else f"📰 AI4S Daily 每日精选 | {date_str}"
        metadata = {
            "date": date_str,
            "pushTime": now.isoformat(),
            "title": title,
            "excerpt": "",
            "seotitle": "",
            "seodescription": "",
            "lead": fallback.get("lead", ""),
            "highlights": fallback.get("highlights", []),
            "profile": "morning",
        }
    else:
        metadata.setdefault("pushTime", now.isoformat())
    metadata.setdefault("profile", "morning")

    # 早报标题固定为「AI4S前沿观察报告（M.D）」,覆盖 LLM 生成的 title
    report_title = f"AI4S前沿观察报告（{now.month}.{now.day}）"
    metadata["title"] = report_title

    # RSS digest 正文无 H2 板块头(insights/gaps/HN 段自带),早报拼装时补上;
    # relevance 输出为纯段落,同样补 H2 板块头
    rss_body = f"## 📰 今日Top热点\n\n{rss_md}" if rss_md else ""
    rel_body = f"## 🧭 与当前01专项工作的相关性\n\n{rel_md}" if rel_md else ""

    final = assemble_with_sentinels(
        {
            "rss": rss_body,
            "hackernews": hn_md,
            "insights": insights_md,
            "relevance": rel_body,
            "gaps": gaps_md,
        }
    )

    if not final.strip():
        print("ℹ️ 早报无任何段输出,跳过推送")
        return

    # 正文以 H1 标题开头;metadata 落盘 frontmatter 供归档/分析,推送内容不变
    final = f"# {report_title}\n\n{final}"

    if deliver:
        sent = await send_to_platforms(
            final,
            config["push"],
            title=report_title,
            metadata=metadata,
        )
        _record_sent_links(final, sent)
    push_file = get_push_file()
    rss_count = rss_md.count("###") if rss_md else 0
    # 早报 metadata 由 insights 覆盖,统计数字从 RSS 板块的 digest_meta 取真实值
    digest_stats = digest_meta or {}
    stat_sources = digest_stats.get("sourceCount", rss_count)
    stat_total = digest_stats.get("totalEntries", rss_count)
    save_push_file(
        push_file, final, stat_sources, stat_total, profile="morning",
        metadata=metadata,
    )
    print(f"💾 已保存早报到 {push_file}")
    if deliver:
        # 落盘后再同步,保证本次报告在镜像内
        sync_reports_to_site(config)
    if not deliver:
        print(f"📝 报告已生成(未推送),审查后可执行: python -m src.main deliver {push_file}")


async def _run_weekly_push(config: Dict, deliver: bool = True, now: datetime = None):
    """周报编排:weekly(LLM 总览/洞察/趋势) + weekly_top(确定性榜单) → sentinel 拼装 → 推送 → 落盘。

    与早报不同,周报没有致命板块:weekly LLM 失败时确定性 Top 热点榜单照常推送;
    两板块均无输出时跳过本次推送。落盘文件名带 -week 后缀与日报区分。
    now 可显式指定(report --weekly --date 回溯生成用),缺省为当前时间。
    """
    if now is None:
        now = now_local(config)
    start, end = weekly_window(now)

    weekly_md, metadata, weekly_err = await run_weekly_section(config, now)
    if weekly_err:
        print(f"⚠️ [weekly] {weekly_err}")
        await notify_llm_errors("weekly", [weekly_err], config)

    top_md = build_weekly_top_section(config, now)

    # 周报标题固定为「AI4S前沿观察周报（M.D–M.D）」,覆盖 LLM 生成的 title
    report_title = f"AI4S前沿观察周报（{start.month}.{start.day}–{end.month}.{end.day}）"

    if not metadata:
        metadata = {
            "date": now.strftime("%Y-%m-%d"),
            "pushTime": now.isoformat(),
            "title": report_title,
            "excerpt": "",
            "seotitle": "",
            "seodescription": "",
            "lead": "",
            "highlights": [],
            "profile": "weekly",
        }
    else:
        metadata.setdefault("pushTime", now.isoformat())
    metadata.setdefault("profile", "weekly")
    metadata["title"] = report_title

    final = assemble_with_sentinels(
        {
            "weekly": weekly_md,
            "weekly_top": top_md,
        }
    )

    if not final.strip():
        print("ℹ️ 周报无任何段输出,跳过推送")
        return

    # 正文以 H1 标题开头;metadata 落盘 frontmatter 供归档/分析,推送内容不变
    final = f"# {report_title}\n\n{final}"

    if deliver:
        sent = await send_to_platforms(
            final,
            config["push"],
            title=report_title,
            metadata=metadata,
        )
        _record_sent_links(final, sent)
    stats = window_stats(config, start, end)
    push_file = get_push_file(now, suffix="-week")
    save_push_file(
        push_file, final, stats["sourceCount"], stats["totalEntries"],
        profile="weekly", metadata=metadata,
    )
    print(f"💾 已保存周报到 {push_file}")
    if deliver:
        # 落盘后再同步,保证本次报告在镜像内
        sync_reports_to_site(config)
    if not deliver:
        print(f"📝 报告已生成(未推送),审查后可执行: python -m src.main deliver {push_file}")


async def fetch_loop(config: Dict):
    """Fetch循环 - 修复时间漂移并支持优雅退出"""
    import time

    interval_seconds = config["schedule"]["fetch_interval_minutes"] * 60
    print(f"🔄 Fetch循环已启动 | 严格间隔: {interval_seconds / 60}分钟")

    while True:
        start_time = time.monotonic()  # 使用 monotonic 避免系统时间修改影响

        try:
            await run_fetch_job(config)
        except asyncio.CancelledError:
            print("⚠️ Fetch循环被外部取消，正在安全退出...")
            break  # 允许外部取消任务
        except Exception as e:
            print(f"❌ Fetch Job 失败: {e}")

        # 计算任务耗时
        elapsed = time.monotonic() - start_time
        # 计算还需要睡多久（如果任务耗时超过间隔，则不睡，立刻进入下一次）
        sleep_time = max(0.0, interval_seconds - elapsed)

        if sleep_time > 0:
            print(f"⏰ 下次抓取: {sleep_time / 60:.1f}分钟后")

        try:
            await asyncio.sleep(sleep_time)
        except asyncio.CancelledError:
            print("⚠️ 睡眠被中断，Fetch循环安全退出...")
            break


async def push_loop(config: Dict):
    """Push循环 - 无状态 croniter + 原生异步睡眠"""
    cron_list = config["schedule"]["push_cron"] + config["schedule"].get("weekly_cron", [])
    tz = get_timezone(config)

    # 1. 启动前预校验 cron 表达式，过滤掉无效配置
    valid_crons = []
    for cron in cron_list:
        if croniter.is_valid(cron):
            valid_crons.append(cron)
        else:
            print(f"⚠️ 忽略无效的 cron 表达式: '{cron}'")

    if not valid_crons:
        print("❌ 没有有效的推送时间配置，Push循环退出")
        return

    print(f"📤 Push循环已启动 | 定时: {', '.join(valid_crons)} | 时区: {tz}")

    # 2. 主循环
    while True:
        try:
            now = datetime.now(tz)

            # 💡 核心优化：无状态计算。
            # 每次都基于此刻的真实时间，动态计算所有有效 cron 的下一次时间，取最近的一个。
            # 这样无论 run_push_job 执行多久，或者系统休眠过，永远都不会算错。
            next_push = min(
                croniter(cron, now).get_next(datetime) for cron in valid_crons
            )

            wait_seconds = (next_push - datetime.now(tz)).total_seconds()

            if wait_seconds > 0:
                print(
                    f"⏰ 下次推送: {next_push.strftime('%Y-%m-%d %H:%M:%S')} (等待 {wait_seconds / 60:.1f} 分钟)"
                )

                # 💡 核心优化：直接 Sleep。asyncio 天生支持被 CancelledError 瞬间打断
                await asyncio.sleep(wait_seconds)

            # 到达推送时间，执行推送
            print(f"📤 执行推送: {datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')}")
            await run_push_job(config)

            # 增加 1 秒缓冲：防止 run_push_job 执行过快（不到 1 秒），
            # 导致下一个循环的 now 仍停留在当前秒，croniter 算出重复的时间点。
            await asyncio.sleep(1)

        except asyncio.CancelledError:
            print("⚠️ Push循环收到取消信号，安全退出...")
            break  # 直接 break 退出循环即可
        except Exception as e:
            print(f"❌ Push 循环异常: {e}")
            # 遇到未知异常时休眠 60 秒，防止死循环疯狂报错打满日志
            await asyncio.sleep(60)


async def cmd_check(config: Dict) -> int:
    """校验 LLM 接口可达性（部署期使用，运行期不再校验）"""
    print("🔍 校验 LLM 接口...")
    try:
        await check_llm_available(config["llm"])
    except Exception as e:
        print(f"❌ LLM 接口不可用: {e}")
        return 1
    print("✅ LLM 接口可用")
    return 0


async def cmd_fetch(config: Dict) -> int:
    """单次抓取（systemd timer 调用）"""
    try:
        await run_fetch_job(config)
        return 0
    except Exception as e:
        print(f"❌ Fetch 任务失败: {e}")
        return 1


async def cmd_push(config: Dict) -> int:
    """单次推送（systemd timer 调用）"""
    try:
        await run_push_job(config)
        return 0
    except Exception as e:
        print(f"❌ Push 任务失败: {e}")
        return 1


async def cmd_report(config: Dict, morning: bool = False, weekly: bool = False, date_str: str = None) -> int:
    """只生成报告并落盘,不推送（测试阶段审查用）;--date 可指定周报基准日(YYYY-MM-DD)"""
    try:
        if weekly:
            now = None
            if date_str:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
                # 基准时刻取 17:00(与 weekly_cron 对齐),窗口由 weekly_window 推导
                now = datetime(d.year, d.month, d.day, 17, 0, tzinfo=get_timezone(config))
            await _run_weekly_push(config, deliver=False, now=now)
        elif morning:
            await _run_morning_push(config, deliver=False)
        else:
            await run_push_job(config, deliver=False)
        return 0
    except Exception as e:
        print(f"❌ 报告生成失败: {e}")
        return 1


async def cmd_deliver(config: Dict, filepath: str) -> int:
    """推送已落盘的报告文件（report 命令的产物,审查后补推）"""
    path = os.path.abspath(filepath)
    if not os.path.isfile(path):
        print(f"❌ 文件不存在: {filepath}")
        return 1

    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    # 早报文件无 frontmatter、以 H1 开头 → 标题取 H1;
    # 晚报文件带 frontmatter → 正文剥掉 frontmatter,标题按晚报推送惯例拼前缀
    meta, body = parse_frontmatter(text)
    content = body if meta else text
    first_line = content.lstrip().splitlines()[0] if content.strip() else ""
    if first_line.startswith("# "):
        title = first_line[2:].strip()
    elif meta.get("title"):
        title = f"📰 AI4S Daily 每日精选 | {meta['title']}"
    else:
        title = None

    try:
        sent = await send_to_platforms(content, config["push"], title=title, metadata=meta or None)
    except Exception as e:
        print(f"❌ 推送失败: {e}")
        return 1
    print(f"✅ 已推送: {filepath}" + (f" | 标题: {title}" if title else ""))
    _record_sent_links(content, sent)
    # 审查后补推的报告同步到公开网站(文件此前已落盘)
    sync_reports_to_site(config)
    return 0


async def cmd_loop(config: Dict) -> int:
    """长跑模式（本地开发/调试用）"""
    print("🔍 检查 LLM 接口可用性...")
    try:
        await check_llm_available(config["llm"])
        print("✅ LLM 接口可用")
    except Exception as e:
        print(f"❌ LLM 接口不可用: {e}")
        return 1
    await asyncio.gather(fetch_loop(config), push_loop(config))
    return 0


async def cmd_rss(config: Dict) -> int:
    """单独跑一次 RSS digest 板块,打印结果不推送"""
    print("📰 RSS Digest 单板块运行")
    try:
        md, meta, err = await run_rss_section(config, now=now_local(config))
    except Exception as e:
        print(f"❌ RSS 板块失败: {e}")
        return 1
    if err:
        print(f"❌ {err}")
        return 1
    if not md:
        print("ℹ️ 本次无内容")
        return 0
    print("\n" + "=" * 60)
    print("📑 metadata:")
    if meta:
        import json as _json

        print(_json.dumps(meta, ensure_ascii=False, indent=2))
    else:
        print("(none)")
    print("=" * 60)
    print(md)
    print("=" * 60)
    return 0


async def cmd_hackernews(config: Dict) -> int:
    """单独跑一次 Hacker News 板块,打印结果不推送"""
    print("🟧 Hacker News 单板块运行")
    try:
        md, err = await run_hackernews_section(config, now=now_local(config))
    except Exception as e:
        print(f"❌ Hacker News 板块失败: {e}")
        return 1
    if err:
        print(f"❌ {err}")
        return 1
    if not md:
        print("ℹ️ 本次无内容")
        return 0
    print("\n" + "=" * 60)
    print(md)
    print("=" * 60)
    return 0


async def cmd_relevance(config: Dict) -> int:
    """单独跑一次「与当前01专项工作的相关性」分析,打印并落盘,不进报告"""
    print("🧭 相关性分析单独运行")
    try:
        md, err = await run_relevance_section(config, now=now_local(config))
    except Exception as e:
        print(f"❌ 相关性分析失败: {e}")
        return 1
    if err:
        print(f"❌ {err}")
        return 1
    if not md:
        print("ℹ️ 本次无内容(无工作文档或无高分素材)")
        return 0
    now = now_local(config)
    rel_file = get_relevance_file()
    header = f"# 与当前01专项工作的相关性（{now.month}.{now.day}）\n\n"
    with open(rel_file, "w", encoding="utf-8") as f:
        f.write(header + md + "\n")
    print(f"💾 已保存到 {rel_file}")
    print("\n" + "=" * 60)
    print(md)
    print("=" * 60)
    return 0


async def cmd_gaps(config: Dict) -> int:
    """单独跑一次问题发现板块,打印结果不推送"""
    print("🔬 问题发现单板块运行")
    try:
        md, err = await run_gaps_section("", config, now=now_local(config))
    except Exception as e:
        print(f"❌ 问题发现板块失败: {e}")
        return 1
    if err:
        print(f"❌ {err}")
        return 1
    if not md:
        print("ℹ️ 本次无内容")
        return 0
    print("\n" + "=" * 60)
    print(md)
    print("=" * 60)
    return 0


async def cmd_search(config: Dict) -> int:
    """单独跑一次 Tavily 搜索抓取,打印结果不评分不保存"""
    print("🔍 Tavily 搜索单板块运行")
    from src.search_fetcher import fetch_search_entries

    try:
        entries, errors = await fetch_search_entries(config)
    except Exception as e:
        print(f"❌ Tavily 搜索失败: {e}")
        return 1
    for e in errors:
        print(f"⚠️ {e}")
    if not entries:
        print("ℹ️ 本次无结果(未配置 key / 限频跳过 / 查询无命中)")
        return 0
    print("\n" + "=" * 60)
    for i, e in enumerate(entries, 1):
        pub = e.get("published")
        pub_str = pub.strftime("%Y-%m-%d %H:%M") if isinstance(pub, datetime) else str(pub)
        print(f"{i}. [{e['source']}] {e['title']}")
        print(f"   {e['link']}")
        print(f"   发布时间: {pub_str} | 内容 {len(e.get('content', ''))} chars")
    print("=" * 60)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="daily-news",
        description="AI 每日资讯推送系统",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="校验 LLM 接口可达性")
    sub.add_parser("fetch", help="单次抓取并退出")
    sub.add_parser("push", help="单次推送并退出")
    report_parser = sub.add_parser(
        "report", help="只生成报告并落盘,不推送（测试审查用,deliver 补推）"
    )
    report_parser.add_argument(
        "--morning", action="store_true", help="强制走早报编排(不论当前时段)"
    )
    report_parser.add_argument(
        "--weekly", action="store_true", help="强制走周报编排(不论当前时段/星期)"
    )
    report_parser.add_argument(
        "--date", help="周报基准日(YYYY-MM-DD),配合 --weekly 回溯生成历史周报"
    )
    deliver_parser = sub.add_parser(
        "deliver", help="推送已落盘的报告文件（report 命令的产物）"
    )
    deliver_parser.add_argument("file", help="push 文件路径,如 news-data/push-xxx.md")
    sub.add_parser("loop", help="长跑模式（开发/调试用）")
    sub.add_parser("rss", help="单独跑一次 RSS Digest 板块（仅打印,不推送）")
    sub.add_parser("hackernews", help="单独跑一次 Hacker News 板块（仅打印,不推送）")
    sub.add_parser("gaps", help="单独跑一次问题发现板块（仅打印,不推送）")
    sub.add_parser("relevance", help="单独跑一次与当前01专项工作的相关性分析（打印+落盘,不进报告）")
    sub.add_parser("search", help="单独跑一次 Tavily 搜索抓取（仅打印,不评分不保存）")
    return parser.parse_args()


def main() -> int:
    print("🚀 AI每日资讯推送系统")
    args = _parse_args()

    try:
        config = load_config()
        print("✅ 配置加载成功")
    except Exception as e:
        print(f"❌ 加载配置失败: {e}")
        return 1

    if args.command == "report":
        return asyncio.run(cmd_report(config, morning=args.morning, weekly=args.weekly, date_str=args.date))
    if args.command == "deliver":
        return asyncio.run(cmd_deliver(config, args.file))

    handlers = {
        "check": cmd_check,
        "fetch": cmd_fetch,
        "push": cmd_push,
        "loop": cmd_loop,
        "rss": cmd_rss,
        "hackernews": cmd_hackernews,
        "gaps": cmd_gaps,
        "relevance": cmd_relevance,
        "search": cmd_search,
    }
    return asyncio.run(handlers[args.command](config))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n👋 程序已退出")
        sys.exit(0)
