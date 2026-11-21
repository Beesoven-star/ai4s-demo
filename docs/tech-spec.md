# tech-spec.md - 技术架构总览

> 本文档面向未来的 AI Agent 与核心开发者，目的是在阅读源码之前快速建立对项目的整体认识：项目定位、运行模式、核心数据流、模块边界、部署形态、关键约束。
>
> **本文写什么**：架构层面的"是什么、为什么、边界在哪里"；跨模块的数据流和契约；部署/运行环境约束；不读源码就无法获知的设计决策。
>
> **本文不写什么**：源码摘录、函数签名、字段清单、命令行帮助、变更日志、UI/文案。这些信息以源码、`README.md`、`docs/plan.md`、`config.json` 为准。
>
> **维护原则**：当架构边界、数据流、运行环境、部署形态或核心设计决策发生变化时同步更新本文；普通实现调整、字段增删、文案修改不在维护范围内。
>
> update: 2026-11-20

## 集成电路技术观察扩展

集成电路工作区在既有资料查询和个人库之上增加版本化技术观察层：现有SQLite公开字段 → 只读选材脚本 → `resources/ic_briefing_20261120.json` → 窗口与排名计算 → `/api/discovery/ic-briefing` → 首页双榜单及技术评价卡。事件／讨论与技术方向可以多对多关联，评价的每项理由引用明确资料ID；代理关注度与技术重要性分别计算。技术观察不调用模型或写入个人库，不随日期滚动伪造新排名。

静态导出复用相同的7／30天结果，包含公开引用摘录及资料ID。全部引用均能从导出条目找回时携带榜单，构建阶段检查榜单是否存在。当前数据截至11月20日，补查记录保存原站署名、稿件性质、判定理由及事件关联，重要性仍为待人工复核初评。设计与维护口径见 `docs/ic-technology-briefing.md`。

## 项目定位

AI 驱动的 RSS 新闻聚合与推送系统：周期性抓取 400+ 信息源，调用 LLM 评分筛选（主线为 AI4S：AI 驱动的科学研究，通用 AI 重磅为辅），按调度规则将高分内容汇总推送到 Discord / 飞书；高分热点条目在 fetch 阶段即时推送。

面向单机部署、单租户使用。原版报告流水线以本地 JSON / Markdown 持久化；2026-11-06 起，本地分子科研工作台的结构化候选资料使用 SQLite，不依赖外部数据库服务或队列。

## 本地科研工作台扩展

工作台以“分子表征与性质预测”为研究范围。当前数据流是：网页手动采集或本地每日调度 → 异步子进程运行公开元数据采集 CLI → 条目归一化与身份关联 → 本地 SQLite → FastAPI 查询接口 → Vue 列表及详情。采集更新与库内查询分开，关键词查询不触发远程请求。此流程与原版 LLM 评分、Markdown 报告生成、推送和公开站同步解耦，本地采集不调用模型或推送。

`src/discovery.py` 管理候选资料和采集运行记录，`scripts/collect_discovery.py` 负责公开元数据与 Atom/RSS 单次采集。2026-11-07 起，用户提供的 13 本期刊全部进入运行配置，另保留 Nature Communications，共 14 刊的限定 ISSN Crossref 接口、BiB 官方当前期 RSS 和 DeepModeling 新闻源，即 16 个启用接口。arXiv 和全库 Crossref 查询保留兼容但默认关闭。官方订阅受限、陈旧或返回非 XML 时登记禁用，不把替代元数据接口称作 RSS。来源、查询词与批量上限集中在 `resources/discovery_sources.json`；`resources/source_selection.json` 记录来源用途与接入状态，不能只登记候选就当作完成采集。数据库默认位于 `news-data/discovery.sqlite`，可用 `DNEWS_DISCOVERY_DB` 指定；不与原版 `fetch-*.json` 或报告文件混用。标准库 SQLite 即可运行，无需独立数据库服务器。

条目以 DOI、去版本号 arXiv 标识和规范化原始 URL 关联，新闻与论文保持类型边界。重复采集补充缺失信息、合并标签并保留来源记录，沿用稳定条目 ID 和首次收录时间；仅观察时间变化不新增来源快照。首次非空字段优先，不自动裁决互相冲突的来源；存在明确身份桥接时可归并记录，不能识别缺少共同标识的所有近似重复。公开元数据候选与历史人工核验样本保留出处，原始摘要、人工简述、发布日期、首次收录时间分别记录。日期只有年份或缺失时不伪造具体日，不能纳入发表日期范围筛选。

`src/web/discovery.py` 提供资料列表、详情、统计与采集记录查询，并增加后台采集触发、任务进度读取与每日设置保存。网页采集窗口为不晚于今天的 1～366 天；查询接口支持日期、类型、关键词、专题、发表场所与来源类别组合过滤。每源运行记录保留实际解析条目数、日期初筛数、相关候选数及入库新增/更新数，避免将空筛选结果当成期刊没有文章；日期初筛保留缺少完整日期的条目。统计接口按北京时间首次收录日期计算今日新增的独立条目，不累加 job 计数，重复采集不重复增加今日数量。期刊/会议名称与采集平台分开保存及呈现；会议年份不替代具体发表日，详情可以显示年份和 track。前端 `/discover` 为默认入口，旧报告和研究背景入口保留。主题标签目前来自人工样本，自动采集内容留作待核验与待分类；个人收藏层、模型分类与专题分析属于后续阶段。

`src/discovery_collection.py` 在 FastAPI 生命周期内管理每日调度和受控异步子进程，复用 `scripts/collect_discovery.py` 的同一采集逻辑，不阻塞 Web 事件循环。SQLite 持久化采集设置、任务状态与各来源实际开始次数。父进程的操作系统锁保证同一数据库只有一个调度拥有者，子进程自身执行锁阻止重启后尚未退出的旧采集进程与新任务并发。任务记录区分运行、完成、部分失败、失败与中断；关闭或重启时保留已落盘资料与来源结果，不将中断任务当成功。

本地预览启动器默认开启北京时间每日 08:00 采集，首次启动补查；自动窗口默认最近 7 天，可设 1～30 天。服务关闭或电脑关机时不执行，重启仅补查设置的窗口，超出部分需手动补查，RSS 历史受来源保留范围限制。每源每个自动日周期最多 2 次尝试，失败结束后等待 30 分钟，仅重试失败源，成功和正常无匹配不自动重复。这是随本地服务运行的调度，不是安装 Windows 定时任务或开机自启服务，也不替代原版 systemd 的报告流水线调度。

当前已启用 14 刊、15 个论文接口及一个新闻源，仍不能以一次空结果推断全网无新内容。限定期刊接口按发表日窗口过滤、以 indexed 排序进行 cursor 遍历（公开 API 不支持发表日排序与 cursor 同用），保存读取页数、元数据总数和覆盖状态；既有刊每源上限 3 页，新增刊多数 5 页，Pattern Recognition 为 10 页，每页 100 条，上限截断及异常游标保留覆盖提示。只有完整读完当前接口返回的窗口结果，才记录 complete；这不等于出版社内容绝对完整或元数据已无延迟。部分来源日期过粗：Chemometrics 和 Pattern Recognition 本次返回条目均缺少完整日，保留未知日期；Chemical Science 按日返回空结果也不能证明无文章，其官方历史 RSS 本机 TLS EOF 而未启用。方法关键词补充 ML、深度学习、GNN 与分子生成等表述，仍保持领域词与方法词共同匹配，不将通用 AI 内容全部放入。采集成功、无匹配与采集失败分开记录。会议年度官方目录在 `resources/conference_sources.json` 登记，尚未接入批量采集，不作为已启用来源；本次也没有接入新新闻渠道、模型调用或消息推送。

## 运行模式

| 模式 | 触发方 | 适用场景 |
|------|--------|----------|
| **生产**（推荐） | systemd timer 分别触发 `fetch` 与 `push` 单次任务 | 服务器长期运行，依赖 systemd 提供调度、重启、开机自启 |
| **开发** | `loop` 子命令在单进程内并发跑 fetch/push 双循环 | 本地调试，无需 systemd |

CLI 子命令分工（详见 `python -m src.main --help`）：

- `check`：**唯一**的 LLM 健康检查入口，仅在部署期由 `install.sh` 调用
- `fetch` / `push`：单次执行后退出，由 systemd timer 触发；运行期不再做 LLM 健康检查，异常统一打印到 journal（`notify.llm_error_push` 置 true 时才推送各平台，2026-09-08 起默认关闭）
- `report` / `deliver`：生成与推送分离的测试入口；`report` 走完整 push 编排但只落盘不推送（`--morning` 可强制早报编排），`deliver <file>` 把已落盘的报告文件补推出去
- `loop`：开发模式，启动时做一次健康检查，然后并发跑 fetch/push 循环
- `hackernews` / `gaps`：单板块手动调试入口；只跑对应板块（含 LLM 总结），打印 markdown 到终端，**不**推送、**不**写入 push 文件。仅供 prompt 调优期使用
- `relevance`：单跑「与当前01专项工作的相关性」分析；打印并落盘 `news-data/relevance-*.md`（早报编排时该板块会同时拼进报告正文）

关键约束：`fetch` / `push` 失败时进程退出码非 0，systemd 据此判定 service 失败，下个 timer 周期自动重试。

独立运行的归档 Web 服务：`python -m src.web` 启动 FastAPI + uvicorn（地址由 `config.json` 的 `web.host/port` 控制），提供报告归档浏览——`/api/reports` 列表、`/api/reports/{id}` 详情（按 sentinel 板块拆分，insights 段再按 H2 拆为「总览 overview / 高原 plateau / 高峰 peak」子板块；2026-08-27 前旧报告的「💡 今日洞察 insights」子板块 2026-08-31 起退役，拆分后直接过滤不再展示）、`/api/sections/{key}` 栏目流（跨报告聚合单一板块并剥除板块首个 H2，key ∈ overview/plateau/peak/relevance/gaps/rss/hackernews）、`/api/workdocs` 当前工作维护（ongoing_work/ 文档的列表/查看/上传/删除，raw body 上传、重名 409、限 docx/md/txt）、`/api/settings` 设置读写（llm.model 原子写回 config.json，默认 deepseek-v4-flash）、`/api/health` 探活，并托管 `web/dist` 前端产物（SPA fallback）。前端为侧边栏栏目导航（栏目页 + 当前工作维护 + 归档页 + 设置页）；报告详情页标题下不再展示 lead 导读与 highlights 要点，标题后直接进入「总览」板块。注意 workdocs 上传/删除与 settings 写回均为变更操作，服务无鉴权，务必保持 127.0.0.1 或可信网络内。systemd 部署下由常驻服务 `dnews-web.service` 管理（非 timer）。解析层 `src/web/reports.py` 为纯函数，复用 `storage.extract_section` / `markdown_utils.parse_frontmatter`，兼容三种文件形态（带 frontmatter 报告 / 无 frontmatter 存量早报 H1+sentinel / 无 sentinel 晚报归一化为单 rss 板块）。

## 核心架构

### 调度模型（生产）

```
┌─────────────────────────────────────────────────────────────┐
│                     config.json                             │
│  schedule.fetch_interval_minutes  → dnews-fetch.timer       │
│  schedule.push_cron               → dnews-push.timer        │
│  log.retention_days               → journald@dnews retention│
└────────────────────────┬────────────────────────────────────┘
                         │ scripts/install.sh 渲染并安装
            ┌────────────┴────────────┐
            ▼                         ▼
  ┌───────────────────┐     ┌───────────────────┐
  │ dnews-fetch.timer │     │ dnews-push.timer  │
  └─────────┬─────────┘     └─────────┬─────────┘
            ▼                         ▼
  ┌───────────────────┐     ┌───────────────────┐
  │ fetch.service     │     │ push.service      │
  │  抓取+评分+热点推送│     │ 收集+汇总+推送     │
  └─────────┬─────────┘     └─────────┬─────────┘
            └────────────┬────────────┘
                         ▼
                ┌─────────────────┐
                │   news-data/    │
                │   fetch-*.json  │
                │   push-*.md     │
                │   notify-*.md   │
                └─────────────────┘
```

开发模式（`loop`）以 `asyncio.gather(fetch_loop, push_loop)` 并发运行两条循环，`push_loop` 通过 croniter 计算下次触发时间，行为等价于生产模式但共享单进程。

### 数据流

```mermaid
flowchart LR
    subgraph Sources ["📡 RSS Sources"]
        RS1[Twitter/X]
        RS2[博客 / 媒体]
        RS3[微信公众号]
    end

    subgraph Fetch ["🔄 fetch job (周期触发)"]
        F1[抓取 RSS(每源限3条,Nature/Science豁免)] --> F1b[Tavily 主动检索(限频 interval_hours)]
        F1b --> F2[HTML→Markdown] --> F3[LLM 批量评分]
        F3 --> HOT{score ≥ hot_threshold?}
        HOT -->|是| IP[即时推送 + notify-*.md]
    end

    subgraph Push ["📅 push job (cron 触发)"]
        P1[读取近 N 天 fetch + 历史 push 上下文] --> P2[LLM 汇总去重] --> P3[生成 push-*.md] --> P4[推送 Discord / 飞书]
    end

    subgraph Storage ["💾 news-data/"]
        DB[(JSON / MD)]
    end

    Sources --> F1
    F3 --> DB
    IP --> DB
    DB --> P1
    P3 --> DB
```

**关键数据契约**：

- `fetch-YYYY-MM-DD.json`：当日抓取与评分结果（含 score / summary / tags / content）
- `push-YYYY-MM-DD.md`：汇总推送内容（YAML frontmatter + Markdown 正文），同时作为下一次 push 的去重上下文；早报自 2026-08-14 起同样落盘 frontmatter（此前仅 H1+正文，metadata 只随推送发出）
- `notify-YYYY-MM-DD.md`：即时推送记录，作为 LLM 即时推送时的去重上下文
- `pushed-links.json`：已推送链接永久记录（`{"updated_at", "links"}`）——每次快讯/日报/周报**实际送达后**由 `record_pushed_links` 并入推送内容中的 markdown 链接；fetch 入库时命中即永久拦截，快讯触发前再硬过滤一次（`load_pushed_links`）。解决 Tavily 不定期重复命中同一热门 URL 导致的超窗重复推送；全部平台推送失败时不记录，避免误杀未送达内容

具体字段以源码 `src/storage.py` 与样例文件为准，README "数据示例" 章节给出了一份示例。

## 关键模块边界

```
src/                       运行时代码
├── main.py                CLI 入口；定义 fetch_job / push_job / loop 的编排顺序
├── config.py              加载 config.json，合并 OPML + add/block，做配置校验
├── fetcher.py             RSS 抓取；并发控制、UA 伪装、域名通配符屏蔽；nitter/xcancel 走独立的 requests+Inoreader UA 低并发池
├── processor.py           HTML → Markdown 转换
├── llm.py                 LLM 客户端;批量评分、即时推送生成、汇总生成、错误聚合
├── storage.py             news-data 文件读写;按日期分片;过期清理
├── site_sync.py           报告推送后同步公开静态站:镜像 push-*.md 到 AI4S-Daily-HTML 仓库并 git push
└── push/                  推送平台抽象
    ├── base.py            PushPlatform 基类(validate_config / send)
    ├── discord.py
    └── feishu.py

scripts/                   部署脚本(仅生产 systemd 部署使用)
├── install.sh             一键安装:uv sync → LLM check → 渲染单元 → 装入系统 → 启用
├── uninstall.sh           卸载 systemd 单元、daily-news 包装脚本和日志 drop-in;不删数据
├── status.sh              查看 timer/service 状态(daily-news status 包装它)
├── _gen_units.py          从 config.json 渲染 systemd 单元和 daily-news 包装脚本
└── daily-news.tmpl        /usr/local/bin/daily-news 的脚本模板,封装 systemctl/journalctl

systemd/                   systemd 单元模板(由 _gen_units.py 渲染并装入 /etc/systemd/system/)
├── dnews-fetch.service.tmpl    fetch service 单元模板
├── dnews-fetch.timer.tmpl      fetch 定时器(OnUnitActiveSec 间隔触发)
├── dnews-push.service.tmpl     push service 单元模板
├── dnews-push.timer.tmpl       push 定时器(OnCalendar 日历触发)
└── journald-dnews.conf.tmpl    journald 命名空间 dnews 的日志保留 drop-in

config.json                主配置;运行参数 + 调度 + LLM + 推送渠道;唯一可热改的运行配置
prompts/                   LLM 提示词文本;score / immediate_push / digest 各自独立文件
resources/tidings-*.opml     基础 RSS 订阅源(Tidings 策展:ai/research/engineering 三份),sources.base_opml 支持路径列表,通过 sources.add/block 增量调整
.env                       敏感凭证(API Key / Webhook URL),通过环境变量注入,不入库
```

### 板块化扩展 (morning push)

早报推送在 RSS 之上扩展三个板块:Hacker News 热议 / 跨板块洞察 / 问题发现。模块结构、数据流与失败降级详见 `docs/extra-sections-design.md`。架构层关键约束:

- 仅在当天 `schedule.push_cron` 列表里最早那次触发时启用(单条 cron 时每次都启用),其余时段维持纯 RSS 行为
- 各板块封装为 `src/sections/<board>/section.py::run_xxx_section(config, now) -> (markdown, error)`;top-N 高分素材选取等共享逻辑在 `src/sections/common.py`
- `push_job` 用两阶段 `asyncio.gather`:先并发 RSS / HN / relevance,再并发 insights / gaps(两者输入同源、互不依赖);最后用 `<!-- SECTION:xxx BEGIN/END -->` sentinel 按 `insights → relevance → gaps → rss → hackernews` 顺序包入 push 文件
- insights 段以当日 fetch 数据的 top-N 高分条目(`sections.insights.top_n`)为主分析材料,HN 成品为辅,输出「总览(观点摘要) + 高原/高峰分层观点」三段并独占早报 metadata;frontmatter 解析对 LLM 整段 ``` 围栏包裹 / 缺闭合 fence / 双 frontmatter 有容错
- gaps(问题发现)段复用同一份 top-N 素材 + HN 成品,输出 1-3 个潜在 research gap;无 metadata 职责,当日无高分素材时不调 LLM 直接省略,素材不支撑时由 prompt 约束输出「本期无可靠 gap」;**2026-08-27 起默认关闭**(`sections.gaps.enabled=false`,用户决策去掉该章节),代码与 prompt 保留可恢复
- relevance(与当前01专项工作的相关性)读取 `ongoing_work/` 中 `sections.relevance.include_docs` 指定的 docx/md/txt(2026-08-27 起默认仅《以往研究内容.docx》,配置为空数组则读取全部)与 top-N 素材做映射,输出**分点列表**(2026-08-31 起每点=1-2 句支撑(进展带链接+暴露的缺口)+**结尾整句加粗的我方结论**(查缺补漏动作:补齐/建立/跟进什么),不写开头话题概括句,总长 150-300 字;此前为「进展带链接+一句关系分析」200-400 字)由早报拼装时补 `## 🧭 与当前01专项工作的相关性` 板块头,置于 insights 后、gaps 前;同时**单独落盘** `news-data/relevance-*.md` 供人工核验;无工作文档或无素材时不调 LLM 直接跳过
- 早报各板块 H2 标题自 2026-08-21 起统一带符号:📋 总览 / 📰 今日Top热点 / 🟧 Hacker News 热议(与归档 Web 栏目图标一致),🧭 相关性板块 2026-08-27 起改名「与当前01专项工作的相关性」,🔬 问题发现板块 2026-08-27 起默认关闭;insights 段洞察 H2 自 2026-08-27 起由 💡 今日洞察 改为 🌄 "高原"最新洞察(H3:科学通用底座/通用 AI)/⛰️ "高峰"最新洞察(AI4S 四学科,H3 子标题:高能物理与量子科技/化学与材料/生命科学与医学/地球科学),观点以「**加粗观点句** + 支撑」分点列出,核心是观点提炼而非事件罗列;📋 总览 内容自 2026-08-31 起由「五大应用场景分域事实梳理(150-250 字)」改为观点摘要,2026-09-01 定型为**两条主分点各挂「重要新闻事件」小标题与要闻子分点**:`- **高原**` / `- **高峰**` 观点浓缩(各 1-2 句),其下 `- **重要新闻事件**：` 小标题 + 缩进子分点列各自方向评分靠前 1-3 条新闻(每条一句话,纯事实不带链接),总 150-300 字;标题由 prompt 输出规格或拼装代码承载,归档解析保留 💡 今日洞察 及无符号旧标题映射以识别历史报告,但该子板块自 2026-08-31 起在归档界面(本地站+公开站)过滤不再展示
- 仅 RSS 失败会让 push_job 整体退出非 0;其余板块失败 → 板块整段省略 + 告警

### 板块化扩展 (weekly push)

周报在命中 `schedule.weekly_cron` 的时刻触发(周四/周日 17:00),与早报完全独立编排。模块结构、窗口规则与失败降级详见 `docs/weekly-report-design.md`。架构层关键约束:

- `run_push_job` 分发顺序:weekly → morning → default;weekly 判定容差 2 分钟(`is_weekly_push`,基于 croniter 上一命中点)
- 板块:`weekly`(一次 LLM 调用产出 metadata + 总览/高原/高峰三个 H2,2026-09-05 起与日报一致,旧格式为总览/本周洞察/趋势分析)+ `weekly_top`(确定性榜单,按 fetch 期 score 排序,不调 LLM);素材为窗口期内全部 fetch 文件 ≥min_score 条目按 link 去重(`load_top_entries_range`,common.py)
- sentinel key 为 `weekly` / `weekly_top`,落盘 frontmatter `profile: "weekly"`;归档 Web 将 weekly 段按 H2 拆为 weekly_overview/weekly_plateau/weekly_peak 三个子栏目(旧格式周报映射 weekly_insights/weekly_trends 历史栏目)
- 周报无致命板块:weekly LLM 失败 → 告警 + 只发确定性榜单;两板块全空 → 跳过推送

模块协作的关键约定：

- **fetch 与 push 之间通过文件系统解耦**：双方不直接通信，push 只读 fetch 已写入的 JSON
- **LLM 调用的错误处理由调用方决定**：`llm.py` 不做 fallback，失败时返回 `(空内容, 错误列表)`；调用方决定是否告警或跳过推送，避免一个批次失败污染整次任务
- **批量评分按 `link` 字段对齐**：LLM 返回的条目数可能少于输入，按 link 匹配并丢弃无法对齐的结果，错误聚合后由调用方统一上报
- **推送平台通过基类多态**：新增平台只需实现 `validate_config()` 与 `send()`，并在工厂函数注册，main.py 无需改动
- **飞书推送按分片独立重试**：单个分片遇网络错误（含 DNS 解析失败）或服务端 5xx 时指数退避重试（2s/4s，最多 3 次），4xx 与业务错误（code≠0）不重试；按分片重试避免多分片场景下已成功分片重复推送
- **飞书早报精简+折叠推送**：`FeishuPlatform.send` 对早报（以 `SECTION:insights` 哨兵判定）发送单条折叠卡片——仅「📋 总览」直接展示；「🌄 "高原"最新洞察」「⛰️ "高峰"最新洞察」（2026-08-27 起，旧报告 deliver 回退为「💡 今日洞察」单面板）「🧭 与当前01专项工作的相关性」「🔬 问题发现」「📰 今日Top热点」「🟧 Hacker News 热议」（每个话题仅保留「内容总结」，去掉「💬 讨论总结」）各自一个 `collapsible_panel` 折叠面板（标题符号与日报模板一致；今日Top热点 2026-08-21~26 曾整块不推，2026-08-26 起恢复为折叠面板——历史 18 天该段 1.8k~5.3k 字符，远低于上限）；最后一个元素为「📒 AI4S-frontier汇总」归档站链接。卡片 header 已展示标题时剥除正文首行重复 H1（早报/周报通用）。各部分均远低于单 markdown 元素 8000 上限；任一部分超长则退回纯文本分片兜底。即时推送及其他平台不受影响。**第二机器人** `push.feishu_no_teacher`（2026-09-04 起）：同一 `FeishuPlatform` 类经 config 变体区分——`exclude_sections`（按哨兵名剔除折叠面板，剔除段不进面板也不进可见区，默认 `["relevance"]`）与 `include_archive_link: false`（不加归档站链接），其余与主机器人一致（仅总览可见、其余折叠）。**第三机器人** `push.feishu_1`（2026-09-07 起）：env `FEISHU_WEBHOOK_URL_1`，推送逻辑与主机器人完全一致，仅 webhook 不同
- **飞书周报折叠推送**：`FeishuPlatform.send` 对周报（以 `SECTION:weekly` 哨兵判定，早报判定失败后尝试）同样发送单条折叠卡片——2026-09-05 起与日报完全一致：仅「📋 总览」直接展示，「🌄 "高原"最新洞察」「⛰️ "高峰"最新洞察」「🏆 本周Top热点」各自一个 `collapsible_panel` 折叠面板（高原/高峰拆分复用早报 `_split_insights`；旧格式周报 deliver 补推时回退 `_split_weekly_body`，「💡 本周洞察」「📈 趋势分析」面板并兼容无符号旧标题），末尾同样附归档站链接（机器人 2 除外）；超长兜底与早报一致（面板摊平后 8000 字分片）

## 数据边界与持久化

- 所有持久化数据落在项目根目录的 `news-data/`：按日期分片的 `fetch-*.json` / `push-*.md` / `notify-*.md`
- 过期文件清理由 fetch job 在每次执行后触发，分两组窗口：`filter.keep_days` 控制素材组（fetch-*.json/md），`filter.archive_keep_days` 控制归档组（push/notify/relevance 的 md）；两者均为 null（默认）时**不删除任何文件**（2026-08-14 用户决策：全部保留，供归档 Web 展示）
- 没有数据库、没有外部缓存、没有跨机器同步；状态完全可由文件系统重建
- 报告推送成功后自动同步公开网站：`site_sync.sync_reports_to_site` 把 `news-data/push-*.md` 全量镜像到 `AI4S-Daily-HTML` 仓库 `public/reports/`（目标侧多余文件删除，自愈漏同步），commit + `pull --rebase --autostash` + push 到 GitHub，由 Actions 构建部署；接入早报/周报（deliver=True 且落盘后）与 `deliver` 命令三处，`report` 子命令的待审查稿不同步；由 `config.json` 的 `site_sync.enabled/repo_path/branch` 控制，任何失败只告警不打断推送主流程
- 敏感信息（API Key、Webhook URL）只通过环境变量注入，禁止写入 `config.json` 或代码

## 配置与约束

完整配置字段说明见 `README.md` 的"配置详解"章节，本文只列出对架构有影响的约束。

### schedule

| 字段 | 约束 |
|------|------|
| `fetch_interval_minutes` | systemd 部署下用 `OnUnitActiveSec` 实现，从上次任务**完成**开始计时（非日历对齐） |
| `fetch_lookback_minutes` | 必须大于 `fetch_interval_minutes`，用作 RSS 延迟的冗余窗口，依赖 link 去重防止重复入库 |
| `push_cron` | systemd 部署下**只支持 minute/hour 字段**，其他位必须为 `*`；不支持范围、列表、`*/N`。`loop` 模式下走 croniter，支持完整语法 |
| `weekly_cron` | 周报推送时刻（缺省 `[]` 关闭）。systemd 部署下允许整数 day-of-week（0/7=周日…4=周四），dom/month 仍须为 `*`。分发上**优先于** push_cron 的早报判定（单条 push_cron 时 `is_morning_push` 恒为 True，不先判会把周报触发点误判为早报） |
| `timezone_hours` | 整数小时偏移；用于显示和 cron 计算 |

### filter

| 字段 | 约束 |
|------|------|
| `fetch_dedup_days` | fetch 入库去重的链接窗口天数（默认 3），`load_existing_links` 覆盖当天及之前 N-1 天的 fetch 文件。旧逻辑只看当天（跨天边界才带昨天），Tavily 每天重复命中同一热门 URL 会在窗口外重新入库，导致同一事件多日重复推送（2026-08-23 修复） |

### search

| 字段 | 约束 |
|------|------|
| `days` / `max_age_days` | `days` 是 Tavily 服务端回溯天数；`max_age_days`（默认 3）是客户端日期闸门——有 `published_date` 且超窗的结果直接丢弃。服务端过滤对无日期页面原理性失效（官方博客常缺日期元数据），无日期结果保留，重复由 pushed-links 永久记录兜底（2026-08-25） |

### log

`log.retention_days` 仅对 systemd 部署生效，由 `install.sh` 渲染到 journald 命名空间 `dnews` 的 drop-in 配置；修改后必须重跑 `install.sh`。

### web

`web.host` / `web.port` 控制归档 Web 服务监听地址。本机部署绑 `127.0.0.1`；需要局域网访问时改 `0.0.0.0`（注意当前无任何鉴权，不要直接暴露公网）。

### LLM

`llm.max_prompt_chars` 决定批次切分粒度，`llm.max_concurrent_batches` 决定批次并发数。这两个值同时影响吞吐和单次推送的成本上限。`llm.request_timeout`（秒，默认 300）是单次 LLM 请求的总超时——insights 等长文生成在代理慢时容易触顶 aiohttp 默认的 300s，且触顶异常 `asyncio.TimeoutError` 的 `str()` 为空，故所有 LLM 错误日志统一经 `err_text()` 补充异常类型名。

### 环境变量

敏感凭证名通过 config.json 的 `*.apiKeyName` 字段指定环境变量名，由 `os.environ` 读取；约定通过 `.env` 提供，systemd 部署时 install.sh 会注入到 service 单元的 `EnvironmentFile`。LLM 端点解析见 `llm._resolve_endpoint`：`llm.baseUrlName`（默认 `OPENAI_BASE_URL`）指定的环境变量存在时优先于 `llm.baseUrl`，实现 base URL 也可纯 env 注入（2026-08-28 起）。

| 变量 | 用途 | 未配置时行为 |
|------|------|------|
| `OPENAI_API_KEY`（llm.apiKeyName 指定，2026-08-28 由 DEEPSEEK_API_KEY 改名，表示任意 OpenAI 兼容端点） | LLM 评分/行文 | 启动校验失败退出 |
| `OPENAI_BASE_URL`（llm.baseUrlName 指定，可选） | 覆盖 llm.baseUrl | 回退 config.json 的 llm.baseUrl |
| `FEISHU_WEBHOOK_URL` | 飞书推送 | 推送失败告警 |
| `JINA_API_KEY` | HN 外链正文(Jina Reader) | 匿名额度调用 |
| `TAVILY_API_KEY` | Tavily 主动检索(search 段) | 搜索降级跳过，RSS 主流程不受影响 |

## systemd 部署形态

### 文件落点

| 文件 | 位置 | 来源 |
|------|------|------|
| `dnews-{fetch,push}.{service,timer}` | `/etc/systemd/system/` | `systemd/*.tmpl` 由 `_gen_units.py` 渲染 |
| `dnews-web.service`（常驻归档 Web） | `/etc/systemd/system/` | `systemd/dnews-web.service.tmpl`；`install.sh` 同时负责前端构建（`web/` 下 `npm ci && npm run build`） |
| `journald@dnews` retention drop-in | `/etc/systemd/journald@dnews.conf.d/` | `systemd/journald-dnews.conf.tmpl` |
| `daily-news` 包装脚本 | `/usr/local/bin/` | `scripts/daily-news.tmpl` |
| 持久化数据 | 项目目录下的 `news-data/` | 运行时生成 |

### cron → OnCalendar 转换

由 `scripts/_gen_units.py` 完成：

- `fetch_interval_minutes` → `OnActiveSec` + `OnUnitActiveSec`（间隔触发，跟随上次完成时间）
- `push_cron` → `OnCalendar`（日历触发，按指定时刻）
- 不支持的 cron 语法（范围、列表、`*/N` 在 minute/hour、非 `*` 的 day/month/dow）在 install 阶段直接报错

### 日志

- 所有 stdout/stderr 进入 journald 命名空间 `dnews`，与系统其他服务隔离
- 查询：`journalctl --namespace=dnews -u dnews-fetch -f`
- 卸载不会清理历史日志，需要时手动 `journalctl --namespace=dnews --vacuum-time=1s`

## 设计决策（重要的"为什么"）

| 决策 | 原因 |
|------|------|
| 调度交给 systemd timer 而非 asyncio 循环 | 进程崩溃和服务器重启可自愈；调度配置即声明式单元，热更新只需重跑 install.sh |
| LLM 健康检查只在 `check` 子命令做 | 每次 timer 触发都校验会产生无意义的 LLM API 调用；运行期错误由 `notify_llm_errors` 统一记录（默认只进日志，不推送） |
| LLM 失败时不生成 fallback 内容 | 避免低质量内容污染推送；由调用方决定告警或跳过 |
| 用 journald 命名空间而非文件日志 | 自动轮转、与系统日志隔离、无需写文件 IO 代码 |
| 数据全用本地文件而非数据库 | 单机单租户场景下足够；可读、可备份、可手动审阅 |
| `fetch_lookback_minutes` 冗余窗口 | RSS 源时间戳常有延迟，仅按时间过滤会漏读；冗余抓取后按 link 去重 |
| 已推送链接永久记录（pushed-links.json） | 窗口式去重（链接窗口/LLM 上下文）对超出窗口的重复原理性失效——Tavily 随机间隔重复命中同一 URL，任何有限窗口都有漏网概率（2026-08-25 OpenBind 第 4 天重复推送实锤）；「是否推送过」是可精确记录的事实，永久记录把同 URL 重复彻底变为确定性拦截 |
| Push 上下文带入近 N 天历史 push 文件 | 避免汇总推送在多个时段重复推同一条目 |

## 扩展指南

- **新推送平台**：在 `src/push/` 新建文件，继承 `PushPlatform`，在工厂注册
- **新评分维度**：编辑 `prompts/score_batch.md`，调整评分标准与主题方向
- **新 RSS 源**：编辑 `config.json` 的 `sources.add` / `sources.block` / `sources.block_domains`，无需修改 OPML

## 测试

测试入口分两类，详细命令参考 `README.md` 与 `tests/` 目录：

- `tests/pytest/`：单元/集成测试，CI 友好，`uv run pytest tests/pytest/` 一键跑
- `tests/*.py`：交互式实操脚本（`fetch_news.py` / `push_news.py` / `run_llm_test.py` 等），针对真实 RSS 与 LLM 做端到端验证，用于调参和手测

## 相关文档

- 用户文档与配置详解：`README.md`
- 任务进度与产品决策：`docs/plan.md`
