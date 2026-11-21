# 周报（Weekly Report）设计

> 2026-08-17 引入。周报是独立于早报/晚报的第三种推送 profile（`weekly`），每周四、周日 17:00 各推一份：周四覆盖周一至周四素材，周日覆盖周五至周日素材。（2026-09-07 曾短暂改为周三/周日，当日即回退）

## 定位与边界

- **日报保留不变**（每天 8:00《AI4S前沿观察报告》），周报叠加其上
- 周报板块 2026-09-05 起与日报一致：📋 总览 / 🌄 "高原"最新洞察 / ⛰️ "高峰"最新洞察 / 🏆 本周Top热点（消费方保留 💡 本周洞察 / 📈 趋势分析 旧标题兼容历史周报）；**不含**相关性、问题发现、Hacker News
- 总览与高原/高峰的写法完全复用日报契约（prompts/insights.md 同款嵌套结构：高原/高峰两条主分点，各含 `- **重要新闻事件**：` 小标题 + 1-3 条一句话要闻子分点；观点分点 = `- **加粗观点句** 支撑`）
- 素材：窗口期内所有 `fetch-*.json` 中 score ≥ `filter.min_score` 的条目，按 link 跨天去重（保留最高分出现）
- 周报定位是**周度回顾**，刻意不去重日报已推内容

## 窗口规则

`weekly_window(now)`（src/sections/common.py）：

| 触发日 | 窗口 |
|--------|------|
| 周一~周四 | 本周一 ~ 当天 |
| 周五~周日 | 本周五 ~ 当天 |

已知取舍：周四 17:00 之后 ~ 周五 0:00 的素材不进任何周报（由周五日报覆盖）。

## 调度与分发

- 配置 `schedule.weekly_cron`（与 `push_cron` 完全独立，互不影响早报判定语义），缺省 `[]` 即关闭
- `run_push_job` 分发顺序：**weekly → morning → default**。weekly 必须判在最前——单条 push_cron 时 `is_morning_push` 恒为 True，不先判会把周四 17:00 误判为早报
- `is_weekly_push`：对每条 weekly_cron 从 `now - 2min` 取下一次命中，落在 `(now-2min, now]` 即命中（容差吸收 loop/systemd 执行延迟；注意 croniter `get_prev` 不含当前时刻，整点触发需用 next-from-base 写法）
- systemd：`_gen_units.py` 把 push_cron + weekly_cron 渲染进**同一个** `dnews-push.timer`（service 跑 `run_push_job` 自分发）；`cron_to_oncalendar` 支持整数 dow（0/7=Sun … 6=Sat），如 `0 17 * * 4` → `Thu *-*-* 17:00:00`
- loop 模式：`push_loop` 调度 `push_cron + weekly_cron` 并集

## 板块契约

| key | 产出 | LLM | 说明 |
|-----|------|-----|------|
| `weekly` | frontmatter metadata + `## 📋 总览` `## 🌄 "高原"最新洞察` `## ⛰️ "高峰"最新洞察` | 1 次调用（prompts/weekly.md） | 输入为窗口期 top-N（`sections.weekly.top_n`，默认 40）压缩条目 + 近期推送上下文（`load_recent_push_content(section="insights")`，用于对照基线）；高原含科学通用底座/通用 AI 两个 H3，高峰含四学科 H3（同日报） |
| `weekly_top` | `## 🏆 本周Top热点` 榜单 | 不调 LLM | 按 score 降序取 `top_hot_n`（默认 10），格式 `- **[score]** [title](link) — source` + summary 缩进行 |

确定性 Top 热点的理由：分数在 fetch 期已由 LLM 评定，排序可复现、可单测、零成本；LLM 策展层由 weekly 主板块承担。

周度口径（prompt 内约束，2026-09-05 起）：与日报"当天发生了什么"不同，周报要求**纵向追踪**——同一主题在窗口期内的演化（突破 → 跟进 → 落地）、热度增减、对照近期推送基线（`recent_context`）的增量；观点允许跨天串联，要闻仍锚定窗口期内评分靠前的真实事件。旧「本周洞察 / 趋势分析」的分工（变化信号 vs 方向判断）已并入高原/高峰观点的写法要求。

## 失败降级

- weekly LLM 失败 → `notify_llm_errors` 告警 + 省略 weekly 段，确定性 weekly_top 照常推送（与早报 RSS-fatal 不同：**周报无致命板块**，纯榜单仍有价值）
- 窗口期无素材 → weekly 段不调 LLM 直接省略（同 gaps 策略）；两板块全空 → 跳过本次推送
- 飞书等平台推送失败沿用平台层重试（按分片指数退避）

## 飞书推送形态

- 2026-08-24 起周报与早报共享飞书折叠卡片（`FeishuPlatform._split_weekly_report`，以 `SECTION:weekly` 哨兵判定）；2026-09-05 起折叠结构与日报完全一致：仅「📋 总览」直接展示，「🌄 "高原"最新洞察」「⛰️ "高峰"最新洞察」「🏆 本周Top热点」各自一个 `collapsible_panel`（高原/高峰拆分直接复用日报 `_split_insights`），卡片末尾为「📒 AI4S-frontier汇总」归档站链接；机器人 2（feishu_no_teacher）同样去掉归档链接。旧格式周报（💡 本周洞察/📈 趋势分析）补推时回退 `_split_weekly_body` 兜底折叠，无符号旧标题兼容；任一元素超 8000 字符退回面板摊平+纯文本分片
- Discord/自定义 webhook 仍收完整版（折叠仅飞书生效，与早报一致）

## 落盘与归档

- 文件 `news-data/push-{时间戳}-week.md`（`-week` 后缀与日报 `push-{时间戳}.md` 区分，2026-08-17 起）；frontmatter `profile: "weekly"`，标题强制 `AI4S前沿观察周报（M.D–M.D）`（2026-09-07 起，此前为 `AI4S周报`）（覆盖 LLM title，同早报强制标题做法）；统计字段来自 `window_stats`（窗口期去重条数 / 来源数）
- 命名适配：`storage.get_push_file(suffix="-week")` 落盘、`extract_push_time` 剥离 `-week` 后缀取时间；归档层 `_REPORT_FILE_RE` 接受可选 `-week`，`load_report` 对同一 report_id 两种命名都尝试
- sentinel：`_SECTION_ORDER` 末尾追加 `weekly`、`weekly_top`；日报不产生这两个 key，互不影响
- 归档 Web：weekly 段按 H2 拆为 `weekly_overview` / `weekly_plateau` / `weekly_peak` 子栏目（2026-09-05 起；旧格式周报仍映射 `weekly_insights` / `weekly_trends` 历史栏目），`weekly_top` 独立栏目；前端 badge 映射 `weekly → 周报`（emerald 色）
- `report --weekly` 可任意日期手动生成审查（周一触发时窗口仅当天，仍可用于验证）；`--date YYYY-MM-DD` 可指定历史日期（按当天 17:00 触发，如 `--date 2026-08-16` 生成 8.14–8.16 窗口周报）

## 测试覆盖

- `test_weekly_detection.py`：weekly_cron 命中/容差/空配置/dow=7/非法表达式
- `test_main_weekly_push.py`：编排 happy path、LLM 失败降级、全空跳过、metadata 回退
- `test_sections_weekly.py`：weekly_window 各 weekday、load_top_entries_range 跨天/缺天/去重/截断、Top 榜单渲染
- `test_main_run_push_job.py`：weekly 优先分发
- `test_push.py::TestFeishuWeeklyFold`：飞书周报旧格式兜底折叠；`TestFeishuWeeklyFoldV2`：新格式折叠（总览可见含嵌套要闻/高原·高峰·本周Top三面板/卡片结构）
- `test_gen_units.py`：dow → OnCalendar 映射与拒绝路径
- `test_web_reports.py`：周报 frontmatter 解析、H2 拆分（旧格式 weekly_insights/weekly_trends + 新格式 weekly_plateau/weekly_peak）、无 H2 fallback 不抛 KeyError、栏目流聚合
