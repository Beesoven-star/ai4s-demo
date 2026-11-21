# extra-sections-design.md — Hacker News / 行业洞察 / 问题发现 / 工作相关性 板块设计

> 本文是对现有 push job 的能力扩展设计。在保持 RSS 主流程不变的前提下，新增四个板块仅在「早报」时段输出：Hacker News 热议、跨板块行业洞察、问题发现（research gaps）、与当前01专项工作的相关性（relevance，进早报正文并单独落盘）。
>
> 配套修改的源码模块、配置字段、数据契约见各章节。落地后需要把架构层结论合并回 `docs/tech-spec.md`，运行参数变更同步 `README.md`，进度记录写入 `docs/plan.md`。
>
> created: 2026-05-16
> updated: 2026-08-13（GitHub Trending 板块下线，本文已移除相关设计；insights 输入契约同步为现状；同日新增「问题发现」gaps 板块（§5.4）与「工作相关性」relevance 板块（§5.5）；2026-08-14 起 relevance 拼进早报正文（insights 后、gaps 前）并保留单独落盘）

## 1. 目标与范围

- 在每天的早报推送中，除了现有的 RSS 精选 digest，再加入：
  - **Hacker News**：HN 首页中筛选最有讨论价值的 AI 相关热议（带评论与外链正文摘要）
  - **行业洞察**：基于 RSS/HN 板块成品 + 当日 top-N 高分原始条目做一段趋势小结
  - **问题发现（gaps）**：基于 top-N 高分原始条目 + HN 板块成品，挖掘 1-3 个潜在 research gap
  - **工作相关性（relevance）**：基于用户工作文档 + 当日 top-N 高分条目，分点归纳各工作方向的相关进展；拼进早报正文（insights 后、gaps 前），同时**单独落盘**供人工核验
- 这些内容**只在早报时段生成**（当天 `schedule.push_cron` 列表里最早那次触发），其余时段维持现有纯 RSS digest 行为
- 单板块失败 → 降级推送其他板块，整体任务仍算成功；RSS 失败 → 同现有行为，任务非 0 退出
- 不引入数据库；状态全部落到 `news-data/` 的本地文件

## 2. 架构总览

```
push_job (cron 触发)
│
├─ Step 1: 早报判定
│      └─ 否 → 走原有纯 RSS digest 流程，结束
│
├─ Step 2: 五模块编排（两阶段 gather）
│      阶段一（三路并发,relevance 只依赖当日素材,不等板块成品）:
│      ├─ run_rss_section(config, now)
│      ├─ run_hackernews_section(config, now)
│      └─ run_relevance_section(config, now)      → 进早报 + 单独落盘 relevance-*.md
│              ↓
│      阶段二（并发,输入同源互不依赖）:
│      ├─ run_insights_section(rss_md, hn_md, config, now)
│      └─ run_gaps_section(hn_md, config, now)
│
└─ Step 3: push_job 上游
       └─ sentinel 包裹四段（insights/gaps/rss/hackernews）→ 拼装 markdown → 推送 → 写 push-*.md
```

**关键设计选择**：

1. **模块自治**。每个板块封装为 `run_xxx_section(...)`，板块内部从抓取、enrich、LLM 总结全包；板块互不感知。
2. **sentinel 由 push_job 统一包**。模块返回**裸 markdown**（不含 sentinel），由上游 `assemble_with_sentinels()` 包入 `<!-- SECTION:xxx BEGIN/END -->`。这样模块不需要知道自己的板块标识，便于后续替换或加新板块。
3. **失败自吞**。模块内部捕获异常，返回错误信息；上游根据返回值决定是否在最终 push 中省略该段、是否走告警通道。
4. **RSS 是核心**。HN / insights / gaps / relevance 模块失败都是降级；RSS 模块失败仍按现有行为整体退出非 0。

**并发模型**：`asyncio.gather`，与项目通体异步风格一致。

## 3. 模块结构

```
src/
├── sections/
│   ├── __init__.py                 # 暴露各 run_xxx_section 入口
│   ├── common.py                   # 板块间公共件:load_top_entries / EMPTY_MARKER(insights/gaps/relevance 共用)
│   ├── rss/
│   │   ├── __init__.py
│   │   └── section.py              # 把现有 collect_entries_for_push + compose_digest 流程搬入
│   ├── hackernews/
│   │   ├── __init__.py
│   │   ├── frontpage_scraper.py    # HTML 抓首页 30 条
│   │   ├── item_enricher.py        # Algolia /items/{id} + 外链正文(Jina Reader,回退 html_to_markdown)
│   │   └── section.py              # run_hackernews_section 入口
│   ├── insights/
│   │   ├── __init__.py
│   │   └── section.py              # run_insights_section 入口
│   ├── gaps/
│   │   ├── __init__.py
│   │   └── section.py              # run_gaps_section 入口
│   └── relevance/
│       ├── __init__.py
│       ├── workdocs.py             # ongoing_work/ 工作文档加载(docx/md/txt,stdlib zipfile+正则解析)
│       └── section.py              # run_relevance_section 入口
├── llm.py                          # HN select / HN summarize / insights / gaps / relevance 五个 section LLM 函数
├── storage.py                      # sentinel 切片与拼装、push/relevance 文件读写
├── main.py                         # push_job:早报判定 + 五模块编排
└── push/                           # 不变,平台层无感知

prompts/
├── section_hackernews_select.md    # 30 条 frontpage 元数据 → 选 K 个 id
├── section_hackernews.md           # enriched stories → 写 markdown
├── insights.md                     # 输入板块成品 + top-N 高分条目 → 写洞察段(含 frontmatter)
├── section_gaps.md                 # top-N 高分条目 + HN 成品 → 1-3 个 research gap(含固定空态)
└── section_relevance.md            # 工作文档 + top-N 高分条目(含 link) → 单段相关进展行文(含固定空态)

news-data/
├── fetch-*.json                    # 不变
├── notify-*.md                     # 不变
├── push-*.md                       # 内容升级:含 sentinel 与 metadata
└── relevance-*.md                  # 新增:工作相关性产出,单独落盘供核验(同时进早报)
```

## 4. 数据契约

### 4.1 push 文件分段 sentinel

push 文件保留**完整拼接**写入磁盘和发送各平台，但用 HTML 注释 sentinel 划分板块边界。HTML 注释在 markdown 渲染中不显示，机器可解析，下游做"按段查重"时能精确切片。

拼装顺序固定为 `insights → relevance → gaps → rss → hackernews`（`storage._SECTION_ORDER`），正文以 H1 报告标题开头；自 2026-08-14 起早报落盘同样带 YAML frontmatter（metadata 供归档 Web 展示，推送内容不变）：

```markdown
# AI4S前瞻研判报告（8.13）

<!-- SECTION:insights BEGIN -->
## 📋 总览

(由高原/高峰加粗观点句组合成的简短观点摘要,2026-08-31 起;此前为按主题归并的今日全景要点)

## 🌄 "高原"最新洞察

(科学通用底座/通用 AI 方向 1-3 个深度判断;行文结构由 prompts/insights.md 决定,代码不强加格式)

## ⛰️ "高峰"最新洞察

### 高能物理与量子科技
### 化学与材料
### 生命科学与医学
### 地球科学

(AI4S 四学科各 1 个观点,H3 固定顺序;无素材学科一句话带过)
<!-- SECTION:insights END -->

<!-- SECTION:relevance BEGIN -->
## 🧭 与当前01专项工作的相关性

(分点列表,2026-08-31 起每点=加粗观点句(查缺补漏判断)+1-2 句支撑(进展带链接);此前为「进展带链接+关系分析」;H2 板块头由早报拼装时补,见 §5.5)
<!-- SECTION:relevance END -->

<!-- SECTION:gaps BEGIN -->
## 🔬 问题发现

(1-3 个潜在 research gap;素材不足时输出固定空态,由 prompts/section_gaps.md 约定)
<!-- SECTION:gaps END -->

<!-- SECTION:rss BEGIN -->
## 📰 今日Top热点

### 1️⃣ ...
<!-- SECTION:rss END -->

<!-- SECTION:hackernews BEGIN -->
## 🟧 Hacker News 热议

### 标题 (120 pts · 45 comments)
- 链接: url
- 要点:...
- HN 讨论: comments_url
<!-- SECTION:hackernews END -->
```

板块 H2 标题自 2026-08-21 起统一带符号（📋 总览 / 🧭 与当前01专项工作的相关性 / 🔬 问题发现 / 📰 今日Top热点 / 🟧 Hacker News 热议），与归档 Web 栏目图标一致；insights 段洞察 H2 自 2026-08-27 起由 💡 今日洞察 改为 🌄 "高原"最新洞察（科学通用底座+通用 AI）/ ⛰️ "高峰"最新洞察（AI4S 四学科 H3 子标题），核心是观点提炼而非事件罗列；📋 总览 内容自 2026-08-31 起改为由高原/高峰加粗观点句组合成的简短摘要；归档解析（src/web/reports.py 与公开站 parser.ts）保留 💡 今日洞察 及无符号旧标题映射以识别历史报告，但该子板块自 2026-08-31 起过滤不再展示。

某板块 markdown 为空 → 对应 sentinel 段**整段省略**（不留空标记，不留空 SECTION）。

注：relevance（工作相关性）板块自 2026-08-14 起**进入 push 文件、有 sentinel 包裹**（`SECTION:relevance`，置于 insights 后、gaps 前），同时仍单独落盘到 `news-data/relevance-*.md`，详见 §5.5。

### 4.2 分段提取函数（storage.py）

```python
def extract_section(push_md: str, section: str) -> str:
    """从 push 文件内容中切出 <!-- SECTION:{section} BEGIN/END --> 之间的 markdown。

    向后兼容:
    - 新 push 文件(带 sentinel): 按 sentinel 边界切片
    - 老 push 文件(无 sentinel) 且 section=='rss': 返回整个 body(老文件视为全 RSS)
    - 老 push 文件且 section in {gaps, hackernews, insights}: 返回空字符串
    """
```

## 5. 模块详设

### 5.1 RSS 模块（迁移既有逻辑）

`src/sections/rss/section.py::run_rss_section(config, now) -> (str, Optional[dict], Optional[str])`：

把现有 `run_push_job` 中"收集 + compose_digest"的部分原样迁过来，返回裸 markdown（不含 sentinel）+ digest metadata（title / lead / highlights，供 insights 失败时兜底）+ 错误信息。无新增功能。

### 5.2 Hacker News 模块

`src/sections/hackernews/section.py::run_hackernews_section(config, now) -> (str, Optional[str])`：

```
1. 抓首页(HTML)
   GET https://news.ycombinator.com/news
   解析 30 条 → front: [{id, title, url, site, points, comments, comments_url}]

2. 轻 LLM 初筛:select_ai_related_hn
   输入: 30 条 frontpage 元数据(无正文)
   输出: K = sections.hackernews.select_k 个 story id(默认 K=1)
   if K 个为空 → return ("", None)                    # 静默

3. 并发 enrich 选中的 K 个 story
   async for story in selected:
     - 评论树:Algolia GET /api/v1/items/{id}
         → 取前 top_comments 条 L1(默认 30,按 HN ranking)
         → 每条 L1 下挂前 top_l2_per_l1 条 L2 回复(默认 3)
         → 每条 text 过 html_to_markdown,单条截断到 comment_max_chars(默认 2000)
         → 累计达 comments_total_chars(默认 60000) 立即停止,防离群 story 撑爆 prompt
         → 输出 tree JSON: [{"l1": "...", "replies": ["...", "..."]}, ...]
     - 外链正文:
         if story.url 指向 https://news.ycombinator.com/item?id=... (Show HN/Ask HN):
             从 Algolia 同次返回的 root.text 字段取(无外部请求)
         else:
             优先走 Jina Reader (https://r.jina.ai/<url>,返回 markdown),
             失败回退直接 GET story.url → html_to_markdown,
             截断到 link_content_max_chars(默认 50000)
     - 单 story 任一失败 → 字段留空,metadata 仍传给最终 LLM

4. LLM:summarize_hackernews(enriched_stories, config)
   prompt: 对输入的 K 个 story 全部行文
   不传 recent_section_titles

5. 返回 (markdown, error)
```

**Algolia API 接口**：

```
GET https://hn.algolia.com/api/v1/items/{id}
```

返回 JSON：

```json
{
  "id": 12345678,
  "title": "...",
  "url": "...",
  "points": 120,
  "author": "...",
  "text": null,                      // Show HN/Ask HN 的正文在这里
  "children": [                       // 顶层评论数组(按 HN ranking 排序)
    {"id": ..., "text": "<HTML>", "author": "...", "children": [...]},
    ...
  ]
}
```

**优势 vs HTML 解析**：免去 HN 的 `td.ind[indent="0"]` indent-tree 解析；评论文本是干净 HTML 字符串，直接 `html_to_markdown`。

**Show HN / Ask HN 特例**：
- 首页解析时 `url` 字段就是 `https://news.ycombinator.com/item?id=X`，作为"非外链"标记
- enrich 时只调一次 Algolia（覆盖评论 + post 正文 `text` 字段），不再发外部请求

**Jina Reader 鉴权**：环境变量名通过 `sections.hackernews.jinaTokenName` 配置（默认 `JINA_API_KEY`）。配置后走 `Authorization: Bearer {token}` 调用 Jina Reader（免费额度更高）；未配置则匿名调用（额度受限）。Jina 失败时自动回退直接抓取。

**enriched story 字段（喂给最终 LLM）**：

```json
{
  "id": "12345678",
  "title": "...",
  "url": "...",
  "site": "example.com",
  "points": 120,
  "comments": 45,
  "comments_url": "https://news.ycombinator.com/item?id=12345678",
  "link_content": "(markdown, ≤link_content_max_chars; Show HN 时是 post 正文)",
  "top_comments": [
    {"l1": "(markdown, ≤comment_max_chars)", "replies": ["(markdown, ≤comment_max_chars)", "..."]},
    ...
  ]
}
```

### 5.3 Insights 模块

`src/sections/insights/section.py::run_insights_section(rss_md, hn_md, config, now) -> (str, Optional[dict], Optional[str])`：

```
1. 加载当日高分素材(src/sections/common.py::load_top_entries)
   top_entries = 今日 fetch 文件中 score ≥ filter.min_score 的条目,
                 按 score 降序取前 sections.insights.top_n 条(默认 20),
                 压缩为 {title, source, score, tags, summary(≤120 chars)} 的紧凑结构

2. LLM:generate_trend_insights
   输入: {"top_entries": ..., "rss": rss_md, "hackernews": hn_md}
   输出: insights 段 markdown(头部可带 frontmatter 元信息)
   注:行文结构、bullet 数量、风格约束等全部交给 prompts/insights.md,
      代码层不强加固定格式

3. parse_insights_with_metadata 解析 LLM 输出
   剥离 frontmatter → (insights_md, metadata)
   metadata 字段:title / excerpt / seotitle / seodescription / lead / highlights / profile / date,
   缺失字段补默认值;早报推送时 title 会被覆盖为「AI4S前沿观察报告（M.D）」（2026-09-07 前为「AI4S前瞻研判报告」）

4. 返回 (insights_md, metadata, error)
```

如果某板块返回空（失败或本日无内容），prompt 里对应键标记 `"(本次无内容)"`（`src/sections/common.py::EMPTY_MARKER`），LLM 自行适配。

### 5.4 问题发现（gaps）模块

> ⚠️ 2026-08-27 起**默认关闭**（`sections.gaps.enabled=false`，用户决策去掉该章节）；以下设计保留备查，置 `true` 即可恢复。

`src/sections/gaps/section.py::run_gaps_section(hn_md, config, now=None) -> (str, Optional[str])`：

```
1. 加载当日高分素材(src/sections/common.py::load_top_entries,与 insights 共用)
   top_entries = 今日 fetch 文件中 score ≥ filter.min_score 的条目,
                 按 score 降序取前 sections.gaps.top_n 条(默认 20)

2. 无素材短路
   if not top_entries: return ("", None)        # 当日无高分素材 → 不调 LLM,整段静默省略

3. LLM:generate_research_gaps
   输入: {"top_entries": ..., "hackernews": hn_md}
   输出: gaps 段 markdown
   注:不传 rss 成品,避免与 insights 的观察视角重复;
      素材不支撑时由 prompt 约束输出固定空态「本期无可靠 gap」

4. 返回 (markdown, error)
```

**关键设计点**：

- **输入契约**：`top_entries`（与 insights 同源的 top-N 高分原始条目）+ `hackernews`（HN 板块成品）。任一为空时对应键标记 `"(本次无内容)"`；但 `top_entries` 整体为空时直接短路，连 LLM 都不调——没有原始素材支撑的 gap 一定是硬造的。
- **无素材短路**：空态判断分两层——「完全无素材」在 code 层短路（省一次注定低质的 LLM 调用）；「有素材但不支撑可靠结论」交给 prompt 层判断，输出固定格式的空态文案，保证板块行为可预期、可单测。
- **prompt 方法论来源**：`prompts/section_gaps.md` 是 skill/research-gap-finder 方法论的压缩版。每个 gap 需包含：为什么可能成立 / 现有工作为何没覆盖 / 可切入的小问题（2026-08-13 起精简，去掉验证思路与可信度字段）。核心约束继承自该 skill：不硬造创新点、区分"真 gap"与"素材覆盖不足"、素材不足时输出固定空态。选择 research-gap-finder 而非 scientific-brainstorming 的原因见 §14——后者是对话式交互流程，不适合无人值守的定时推送。
- **不带 metadata**：返回二元组 `(md, err)`，不像 insights 那样产出 frontmatter metadata。早报 metadata（title / lead / highlights 等）由 insights 段独占产出，避免两个板块竞争同一份元信息；gaps 是纯内容段。
- **`sections.gaps.enabled` 开关**：置 false 时返回 `("", None)`，静默跳过。

### 5.5 工作相关性（relevance）模块

`src/sections/relevance/section.py::run_relevance_section(config, now) -> (str, Optional[str])`：

```
1. 加载工作文档(src/sections/relevance/workdocs.py::load_work_docs)
   读取 sections.relevance.work_dir(默认 ongoing_work/)下全部 docx/md/txt:
   - docx:stdlib zipfile + 正则解析 word/document.xml,按 </w:p> 分段
   - md/txt:直接读取
   - 不支持的扩展名跳过;单文档截断到 work_doc_max_chars(默认 20000)
   - sections.relevance.include_docs 非空时只保留指定文件名的文档
     (2026-08-27 起默认 ["以往研究内容.docx"],用户决策:相关性只锚定该文档;
     指定文档全部缺失时按无工作文档短路)

2. 加载当日高分素材(src/sections/common.py::load_top_entries, include_link=True)
   top_entries = 今日 fetch 文件中 score ≥ filter.min_score 的条目,
                 按 score 降序取前 sections.relevance.top_n 条(默认 30)
   注:relevance 用 include_link=True 变体,产出供人工核验,需要原文链接

3. 无输入短路
   if 无工作文档 or 无高分素材: return ("", None)   # 不调 LLM,静默省略

4. LLM:generate_work_relevance
   输入: {"work_docs": 按文件名分块的工作文档, "top_entries": 含 link 的高分条目}
   输出: relevance markdown(无 frontmatter 解析)

5. 返回 (markdown, error)
```

**关键设计点**：

- **进早报 + 单独落盘（2026-08-14 调整，覆盖 2026-08-13「单独落盘不进报告」决策）**：`rel_md` 非空时由早报拼装补 `## 与当前01专项工作的相关性` H2 板块头，以 `SECTION:relevance` sentinel 置于 insights 后、gaps 前；同时仍写入 `news-data/relevance-YYYY-MM-DD.md`（`storage.get_relevance_file()`，H1「# 与当前01专项工作的相关性（M.D）」+ 正文）供人工核验。`cleanup_old_files` 同步支持 `relevance-*.md` 过期清理。
- **与 insights/gaps 的差异**：不拼装、无 sentinel、无 metadata（早报 metadata 仍由 insights 独占）；编排上挂在阶段一与 RSS/HN 三路并发，因为只依赖当日素材，不需要等任何板块成品。
- **输入契约**：`work_docs`（按文件名分块）+ `top_entries`（含 link，`top_n` 默认 30，比 insights/gaps 的 20 宽——相关性匹配需要更大候选面）。任一为空直接短路不调 LLM。
- **prompt 设计要点**（`prompts/section_relevance.md`）：角色「AI4S 科研情报分析师」；输出为**分点列表**（`- ` 开头，2-4 点；2026-08-27 起由单段行文改为分点，同日板块改名「01 专项」并只用《以往研究内容.docx》；2026-08-31 起改为**查缺补漏观点形态**——任务定位为「结合今日消息与已有研究内容，指出 01 专项还需要查缺补漏的部分」，每点 = 1-2 句支撑（进展行内带链接+暴露的缺口）+ **结尾整句加粗的我方结论**（查缺补漏动作，落到具体环节，不写开头话题概括句），总长 150-300 字，均为用户决策；此前为「进展带链接 + 一句关系分析」200-400 字）；约束：不硬拉关系（弱相关整条舍弃）、锚定素材、链接用行内 markdown、结论句禁空话、全部无相关时输出固定文案「今日消息与当前 01 专项工作无显著相关」。
- **`sections.relevance.enabled` 开关**：置 false 时返回 `("", None)`，静默跳过。

## 6. LLM 调用与 Prompt 策略

### 6.1 Section LLM 函数（src/llm.py）

```python
async def select_ai_related_hn(
    candidates: list[dict],     # 首页 30 条元数据(无正文)
    k: int,                      # 期望返回数量,默认 1
    config: dict,
) -> tuple[list[str], Optional[str]]:
    """轻量 LLM:从 HN 首页候选中挑出 k 个 AI 相关的 story id,只读 title/site/points/comments。
    返回 ([id1, ...], error)。"""

async def summarize_hackernews(
    enriched_stories: list[dict], # 已 enrich(含 link_content 与 top_comments)
    config: dict,
) -> tuple[str, Optional[str]]:
    """对输入的 K 个 enriched stories 全部行文。K 由配置 select_k 决定。
    不传历史上下文。"""

async def generate_trend_insights(
    sections: dict[str, str],   # {"top_entries": json, "rss": md, "hackernews": md}
    config: dict,
) -> tuple[str, Optional[str]]:
    """输入板块成品 + top-N 高分条目,返回洞察段 markdown(可含 frontmatter)。"""

async def generate_research_gaps(
    sections: dict[str, str],   # {"top_entries": json, "hackernews": md}
    config: dict,
) -> tuple[str, Optional[str]]:
    """与 generate_trend_insights 同构。输入 top-N 高分条目 + HN 成品(不传 rss),
    返回 gaps 段 markdown;无 frontmatter 解析。"""

async def generate_work_relevance(
    sections: dict[str, str],   # {"work_docs": 按文件名分块, "top_entries": json(含 link)}
    config: dict,
) -> tuple[str, Optional[str]]:
    """与 generate_research_gaps 同构。输入工作文档 + top-N 高分条目,
    返回 relevance markdown;无 frontmatter 解析。"""
```

返回风格沿用 `generate_immediate_push`：成功返回 `(content, None)`，失败返回 `("", error_msg)`。

**单次早报推送的 LLM 调用预算**：

| 调用 | 输入规模 | 用途 |
|---|---|---|
| `compose_digest` | 当日符合条件的 RSS 条目 | 现有，RSS digest 主体 |
| `select_ai_related_hn` | 30 条 HN 首页元数据 | 轻量；只读 title/site/points/comments |
| `summarize_hackernews` | `K = select_k` 个 enriched stories | 行文 K 条 |
| `generate_trend_insights` | RSS/HN 成品 markdown + top-N 高分条目 | 一段洞察 |
| `generate_research_gaps` | HN 成品 markdown + top-N 高分条目 | 1-3 个 research gap |
| `generate_work_relevance` | 工作文档 + top-N 高分条目（含 link） | 单段相关进展行文 |

合计 6 次 / 早报。晚报维持现有 1 次。

### 6.2 关注领域（HN 板块用）

为避免领域定义在多个 prompt 里漂移，统一在此沉淀；各 prompt 在自身骨架里直接引用本节，不做重新发明。

**正面关注**：

- **AI Agent**：智能体架构、工具链、多智能体、自主规划、Agent 框架
- **AI 模型**：训练、推理、微调、量化部署、模型服务、语音 / 多模态 / 视觉模型
- **AI 基础设施**：GPU 调度、芯片硬件、数据中心、推理优化、分布式训练、向量数据库、RAG 框架
- **大厂 / 前沿动态**：Apple、Google、Meta、OpenAI、Anthropic、Microsoft、xAI 等公司的官方动作与战略
- **AI 集成的开发者工具**：API 网关、自动化脚本、低代码平台等明确与 AI 协同的工具

**负面排除（一律剔除）**：

- 嵌入式开发（Arduino、ESP32、树莓派、单片机）
- 底层系统编程（内存分配器、编译器、链接器，与 AI 工作负载无明显关联时）
- 通用开发工具（命名规范、代码风格、纯前端模板、UI 组件库、管理后台模板、静态网站主题）
- 学习资源（纯教程仓库、面试题合集、Roadmap，除非是含实用代码的深度技术指南）
- 配置文件集合（Dotfiles、配置模板）
- 与 AI / 科技无关的内容（电子书、资源搬运、刷榜项目、明星项目搬运）
- 纯娱乐 / 高风险误用（deepfake 等无明确基础设施价值的项目）

### 6.3 Prompt 文件

#### prompts/section_hackernews_select.md（骨架）

- 角色定位（"HN 早间选题人"）
- 输入：JSON 数组（30 条 frontpage 元数据：id / title / site / points / comments）
- 关注领域：引用 §6.2
- 任务：挑 `k` 个最符合关注领域的 story id
- 决策原则：title + site 不足以判定 AI 相关时，**宁可漏选不可错选**（错选会让最终 LLM 写出与 AI4S Daily 调性无关的内容）
- 输出：纯 JSON id 数组，如 `["12345"]` 或 `[]`（无任何匹配时返回空数组）
- 严禁输出任何解释性文字

#### prompts/section_hackernews.md（骨架）

- 角色定位（"HN 早间编辑"）
- 输入 schema 说明（K 个 enriched story，含 `link_content` 与 `top_comments`）
- 关注领域：引用 §6.2（通常无需二次筛选，仅作为行文背景参考）
- 任务：对输入的 `K` 个 enriched stories 全部行文（不再二次挑选）
- 内容要求（每条 story）：
  - 提炼原文核心（背景 / 要点 / 结论）
  - 汇总 HN 评论区的有价值观点（支持 / 反对 / 补充），不是简单复述
  - 若评论中出现明显反驳原文的观点，必须保留并标注
- 输出格式建议（最终以 prompt 实测为准）：
  ```
  ### 标题 (N pts · M comments)
  - 链接: url
  - 内容总结: 2-3 条核心要点
  - 💬 HN 讨论: 1-2 条最有价值的观点（含反对意见）
  - 🔗 HN 讨论页: comments_url
  ```
- 风格约束：客观、犀利、克制；避免与 RSS digest 句式雷同；不做宏大叙事

#### prompts/insights.md（骨架）

- 角色定位（"AI 行业观察员"）
- 输入：top-N 高分条目 JSON + RSS/HN 板块成品 markdown
- 任务：基于输入做趋势总览与观点小结；frontmatter 元信息（title / excerpt / lead / highlights 等）也由 LLM 一并产出
- 风格约束：避免与 RSS digest 句式雷同；避免简单复述已经在其他板块出现过的具体新闻
- 结构与 bullet 数量交由 prompt 内部约定，code 层不限制

#### prompts/section_gaps.md（骨架）

- 角色定位（"研究问题发现者"，方法论源自 skill/research-gap-finder 的压缩版）
- 输入：top-N 高分条目 JSON + HN 板块成品 markdown
- 任务：挖掘 1-3 个潜在 research gap，每个含：
  - 为什么可能成立（基于素材中的信号）
  - 现有工作为何没覆盖
  - 可切入的小问题
- 核心约束（继承自 research-gap-finder skill）：
  - **不硬造创新点**：素材中没有信号支撑的方向宁可不写
  - **区分真 gap 与素材覆盖不足**：找不到不等于不存在，评测缺口/工程机会需在标题标注性质；依据薄弱时降级为"待进一步核实的潜在切入点"
  - **素材不足时输出固定空态**：固定格式「本期无可靠 gap」文案，不自由发挥
- 风格约束：克制、可证伪；每个 gap 必须能追溯到具体素材条目，不做宏大叙事

#### prompts/section_relevance.md（骨架）

- 角色定位（"AI4S 科研情报分析师"）
- 输入：工作文档（`{work_docs}`，按文件名分块）+ top-N 高分条目 JSON（`{top_entries}`，含 link）
- 任务：按工作文档自身结构归纳工作方向，每个方向给 1-3 条：
  - 今日进展（带原文链接，供人工核验）
  - 相关点（与该方向的具体关系）
  - 可关注角度
- 核心约束：
  - **不硬拉关系**：弱相关宁可不写
  - **锚定素材**：每条相关进展必须能追溯到具体条目
  - **全部无相关时输出固定文案**：「今日消息与当前工作无显著相关」，不自由发挥
- 篇幅约束：总长 300-600 字
- 产出单独落盘（§5.5），不进报告、无 sentinel

### 6.4 调用顺序与并发

```python
async def _run_morning_push(config):
    # 阶段一:RSS/HN/relevance 三路并发(relevance 只依赖当日素材,不等板块成品)
    rss_result, hn_result, rel_result = await asyncio.gather(
        run_rss_section(config, now),
        run_hackernews_section(config, now),
        run_relevance_section(config, now),
    )
    rss_md, digest_meta, rss_err = rss_result
    hn_md, hn_err = hn_result
    rel_md, rel_err = rel_result

    if rss_err and not rss_md:
        raise RuntimeError(...)               # RSS 失败整体抛错

    # relevance 进早报(insights 后、gaps 前,拼装时补 H2 板块头),同时单独落盘
    if rel_md:
        save_relevance_file(get_relevance_file(), rel_md, ...)

    # 阶段二:insights/gaps 并发(输入同源,互不依赖)
    insights_result, gaps_result = await asyncio.gather(
        run_insights_section(rss_md, hn_md, config, now),
        run_gaps_section(hn_md, config, now),
    )
    insights_md, metadata, insights_err = insights_result
    gaps_md, gaps_err = gaps_result
    # insights 失败时用 digest_meta 兜底 metadata;gaps 失败只省略该段

    final = assemble_with_sentinels({
        "insights": insights_md,
        "gaps": gaps_md,
        "rss": rss_md,
        "hackernews": hn_md,
    })

    await send_to_platforms(final, config["push"], ...)
    save_push_file(get_push_file(), final, profile="morning", metadata=metadata)
```

`assemble_with_sentinels(sections: dict[str, str]) -> str` 的契约：

- 按固定顺序拼装 `insights → gaps → rss → hackernews`（`storage._SECTION_ORDER`）
- 空 markdown 段整段省略（连同 sentinel）
- 段间留一个空行

## 7. 行业洞察板块设计

按用户决策，本节**不在 code 层规定 insights 的格式**：

- bullet 数量、子标题、字数限制、固定栏目等都属于 prompt 工程范畴
- 调整方法：编辑 `prompts/insights.md` 而非改代码
- 输入合同（code 层保证）：
  - `sections["top_entries"]`：当日 fetch 文件中 score ≥ `filter.min_score` 的 top-N 高分条目 JSON（N = `sections.insights.top_n`，默认 20）
  - `sections["rss" | "hackernews"]` 两个键的板块成品 markdown
  - 任一来源为空时该键值为 `"(本次无内容)"`
- 输出合同：LLM 输出可带 frontmatter（title / excerpt / seotitle / seodescription / lead / highlights / profile），由 `parse_insights_with_metadata` 剥离为 metadata，正文直接作为 markdown 段插入，code 层不校验结构

## 8. 配置 schema

```json
{
  "filter": {
    "min_score": 60,
    "hot_threshold": 90,
    "context_days": 2,
    "keep_days": 7,
    "push_context_days": 5,
    "no_content_marker": "[NO_NEW_CONTENT]"
  },
  "schedule": {
    "fetch_interval_minutes": 60,
    "fetch_lookback_minutes": 360,
    "push_cron": ["0 8 * * *", "0 17 * * *"],
    "timezone_hours": 8
  },
  "sections": {
    "hackernews": {
      "enabled": true,
      "select_k": 3,
      "top_comments": 50,
      "top_l2_per_l1": 3,
      "comment_max_chars": 2000,
      "comments_total_chars": 80000,
      "link_content_max_chars": 50000,
      "request_timeout": 10,
      "algolia_base": "https://hn.algolia.com/api/v1",
      "jinaTokenName": "JINA_API_KEY"
    },
    "insights": {
      "enabled": true,
      "top_n": 20
    },
    "gaps": {
      "enabled": true,
      "top_n": 20
    },
    "relevance": {
      "enabled": true,
      "work_dir": "ongoing_work",
      "top_n": 30,
      "work_doc_max_chars": 20000,
      "include_docs": ["以往研究内容.docx"]
    }
  },
  "llm": {
    "prompts": {
      "score_batch": "prompts/score_batch.md",
      "immediate_push": "prompts/immediate_push.md",
      "digest": "prompts/digest.md",
      "section_hackernews_select": "prompts/section_hackernews_select.md",
      "section_hackernews": "prompts/section_hackernews.md",
      "insights": "prompts/insights.md",
      "section_gaps": "prompts/section_gaps.md",
      "section_relevance": "prompts/section_relevance.md"
    }
  }
}
```

向后兼容：

- `sections` 整段缺失 → 等价于全部 `enabled=false` → push_job 走原有纯 RSS 路径
- `push_cron` 为空 → 无早报触发,不生成新板块
- 旧 push 文件没有 sentinel → `extract_section("rss", ...)` 返回整个 body，其他 section 返回空字符串
- `JINA_API_KEY` 未设 → HN 外链正文走 Jina 匿名调用，失败再回退直接抓取

## 9. 失败隔离与降级策略

| 失败位置 | 行为 |
|---|---|
| `run_rss_section` 失败 | 整个 push_job 退出非 0（核心承诺不变） |
| HN 首页抓取失败 | `run_hackernews_section` 返回 `("", error)` → 板块整段省略 → 告警 |
| HN 轻 LLM 初筛失败或返回空 | 板块整段省略，告警（初筛失败）或静默（结果为空） |
| HN 单 story enrich 失败 | 字段留空，metadata 仍传给最终 LLM |
| HN summarize LLM 失败 | 板块整段省略，告警 `notify_llm_errors("section_hackernews", ...)` |
| insights LLM 失败 | 洞察段省略，其他板块照常推送，告警；metadata 用 digest 的兜底 |
| gaps 当日无高分素材 | 不调 LLM，板块整段静默省略（code 层短路） |
| gaps LLM 失败 | 板块整段省略，告警 `notify_llm_errors("gaps", ...)` |
| relevance 无工作文档或无高分素材 | 不调 LLM，静默省略（code 层短路） |
| relevance LLM 失败 | 不写 relevance-*.md，告警 `notify_llm_errors("relevance", ...)`；报告不受影响 |
| 早报判定为否 | 完全跳过 HN/insights/gaps/relevance，不消耗任何额外 API |
| `sections.xxx.enabled=false` | 对应模块直接返回空，静默跳过 |

整体准则：**RSS 是核心，其余是增强**。除 RSS 外的任何失败都不阻塞推送，但都通过现有 `notify_llm_errors` 通道发简单告警，方便事后排查。

## 10. 早报判定逻辑

```python
def is_morning_push(now: datetime, config: Dict) -> bool:
    cron_list = config.get("schedule", {}).get("push_cron", [])
    if not cron_list:
        return False
    if len(cron_list) == 1:
        return True  # 唯一定时即"最早",任何触发都视为早报

    base = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_fires = [croniter(c, base).get_next(datetime) for c in cron_list]
    closest = min(today_fires, key=lambda f: abs(now - f))
    return closest == min(today_fires)
```

规则:`push_cron` 中 now 离哪条 cron 最近就归为那条;最近的那条若是当天最早的 cron,则视为早报。

为什么不再用单独的 `morning_cron` + 容差:
- 复用 `push_cron`,少一个配置项,加 cron 自动延展
- 「最近匹配」自动等价于容差 = 到次近 cron 距离的一半,systemd timer 漂移更稳健
- 单条 cron 部署自然变成"每次推送都是早报",与用户预期一致

## 11. 与现有模块的集成点

- `src/main.py::run_push_job` 改造：
  1. 开头加 `is_morning = is_morning_push(now, config)`
  2. `is_morning=False` 时走原路径（`run_rss_section` only）
  3. `is_morning=True` 时进入 `_run_morning_push` 编排（RSS/HN/relevance 并发 → insights/gaps 并发 → sentinel 拼装；relevance 进早报并单独落盘）
- `src/storage.py`：
  - `extract_section(content, section)` 分段切片
  - `assemble_with_sentinels(sections)` 按 `_SECTION_ORDER = ("insights", "relevance", "gaps", "rss", "hackernews")` 拼装
  - `get_relevance_file()` 生成 `news-data/relevance-YYYY-MM-DD.md` 路径；`cleanup_old_files` 支持 `relevance-*.md` 过期清理
- `save_push_file`：frontmatter 带上 `profile: "morning"|"default"` 与 insights metadata，方便后续按 profile 分析
- `src/push/` **不动**，平台层无感知
- `src/llm.py`：`select_ai_related_hn / summarize_hackernews / generate_trend_insights / generate_research_gaps / generate_work_relevance / parse_insights_with_metadata`
- `src/sections/` 模块树（rss / hackernews / insights / gaps / relevance 五个子包 + common.py 公共件）

## 12. 测试策略

单元测试：

- `tests/pytest/test_sections_hackernews_scraper.py`：HN 首页 fixture → 测试 30 条解析
- `tests/pytest/test_sections_hackernews_enricher.py`：mock Algolia → 测试评论 top_comments 截断、Show HN 特例
- `tests/pytest/test_storage_sections.py`：sentinel 切片（含老文件 fallback）
- `tests/pytest/test_morning_detection.py`：cron 边界、容差、跨时区

交互式脚本（与现有 `tests/*.py` 风格一致）：

- `tests/run_morning_push.py`：模拟一次完整早报，强制 `is_morning=True`
- `tests/fetch_hackernews.py`：单独跑 HN 抓取 + enrich

## 13. 实施步骤建议（历史归档）

> 本节为 2026-05 初版落地时的实施顺序，已全部完成。GitHub 相关步骤随 2026-08-13 板块下线一并移除/废弃。

按依赖顺序实施，每步可独立 PR / commit：

1. **storage 层**：sentinel 切片与拼装、`save_push_file` profile 字段 + 单测
2. **RSS 模块迁移**：把现有 `run_push_job` 中的 RSS 流程提取为 `run_rss_section`，验证行为不变
3. **Hacker News 模块**：frontpage scraper → Algolia enricher → section 入口 + 单测 + fixture
4. **LLM 函数 + Prompt 文件**：section LLM 函数 + prompt
5. **Insights 模块**：依赖 §5.3，相对简单
6. **push_job 升级**：早报判定 + 模块编排 + sentinel 拼装 + 失败隔离
7. **配置 schema 升级**：`config.json.example` 与 `config.json` 同步；README 配置详解章节补全
8. **文档同步**：`docs/tech-spec.md` 把架构升级合并；`docs/plan.md` 写进度

## 14. 关键决策记录

| 决策 | 方案 | 原因 |
|---|---|---|
| 新板块时机 | 仅早报（当天最早一次 `push_cron` 触发） | 板块价值更适合一日一报；晚报维持原有 RSS 节奏；复用 push_cron 不引入新配置 |
| 模块边界 | `src/sections/<board>/` 各自封装抓取+LLM+总结 | 模块自治便于扩展、替换、单测；上游编排极简 |
| sentinel 归属 | push_job 上游统一包 | 模块不感知自己的板块标识；新增板块零修改成本 |
| ~~GH trending 数据源~~（已废弃，2026-08-13 板块下线） | 单页 HTML `https://github.com/trending`，无语言/since 过滤 | 用户决策：最简、最稳；语言过滤靠 topics + readme 在 LLM 层判 |
| ~~GH deep-dive 内容~~（已废弃） | REST API 拿 metadata + topics + README | topics 是 AI 相关性最强信号；metadata 补 license/pushed_at；README 给内容深度 |
| ~~GH 鉴权~~（已废弃） | GITHUB_TOKEN 可选 | 日 ~20 calls 远低于匿名 60 req/hr 上限；零配置即可跑 |
| ~~GH 筛选策略~~（已废弃） | history 过滤 → 全部 deep-dive → 一次 LLM 选 1-3 | 候选量小（5-15）；单次 LLM 比两阶段简单且选择质量高 |
| ~~GH 候选护栏~~（已废弃） | `max_deep_dive=10` | 极端日（trending 大改）限制 HTTP 与 token 消耗 |
| GitHub Trending 板块下线（2026-08-13） | 删除 `src/sections/github/`、`prompts/section_github.md`、`sections.github_trending` 配置、`summarize_github_trending`、`trending-history.json` 及 `github` CLI 子命令 | 板块下线；同日新增 gaps 板块（见下行），早报现为 insights + gaps + RSS + HackerNews 四段 |
| 问题发现（gaps）板块（2026-08-13） | 方法论选自 skill/research-gap-finder 压缩版；输入 top-N 高分条目 + HN 成品（不传 RSS 成品）；无素材 code 层短路不调 LLM；素材不支撑时 prompt 约束固定空态；不带 metadata | 对比 scientific-brainstorming：后者是对话式交互流程，不适合无人值守定时推送；research-gap-finder 可一次性产出。不传 RSS 成品避免与 insights 视角重复；metadata 由 insights 独占避免两段竞争；空态分 code/prompt 两层保证可预期 |
| 工作相关性（relevance）板块（2026-08-13） | 单独落盘 `news-data/relevance-*.md`，**暂不入报告**、无 sentinel、无 metadata；输入工作文档（ongoing_work/，docx 用 stdlib zipfile+正则解析）+ top-30 高分条目（include_link=True）；阶段一与 RSS/HN 三路并发；无输入 code 层短路 | 用户决策：调优期需反复重跑本板块，入报告则每次调整都要重生成整份早报、消耗全套 LLM；单独落盘可用 CLI 独立迭代。只依赖当日素材故无需等板块成品；产出供人工核验故素材带原文链接 |
| HN 数据源 | 首页 HTML + 评论/正文 Algolia | 首页要"现场感"走 HTML；Algolia 评论 JSON 结构清晰，免去 indent-tree 解析 |
| HN 外链正文 | 优先 Jina Reader，失败回退直接 GET + html_to_markdown | Jina 直接返回干净 markdown，省一次本地转换；回退保证可用性 |
| HN 筛选策略 | 30 条 → 轻 LLM 选 K → enrich → 最终 LLM 行文 | 用户决策：把 enrich 工作量压到 K 个 story；轻 LLM 用 title 已足够判 AI 相关 |
| HN 评论结构 | L1 + 每个 L1 下挂 N 条 L2 回复,tree JSON 喂 LLM | 真实数据:L2 信息量与 L1 持平(24 条/8k chars vs 18/6k);拍平丢失父子关系,LLM 无法识别"回复反驳了顶层"。Tree 结构让 LLM 看清论辩链 |
| HN 评论上限 | `top_comments`(L1)+ `top_l2_per_l1=3` + `comments_total_chars`(总预算) | 真实平均:L1 18 条/6k chars,L2 24 条/8k。给足余量但平均只跑 ~14k。总预算硬上限拦住离群 story(309 评论那种) |
| 无历史上下文 | HN 板块不传 recent_section_titles | 用户决策：避免不必要的上下文污染；HN 风格与 RSS digest 差异已足够大 |
| insights 素材 | top-N 高分原始条目 + RSS/HN 板块成品 | 原始条目给趋势总览提供覆盖面，板块成品给深加工结论 |
| insights 输出结构 | 由 prompt 决定，code 不强加；frontmatter metadata 由 LLM 产出、code 解析 | 用户决策：bullet 数量与栏目属于 prompt 工程，便于迭代 |
| 关注领域沉淀 | 在 §6.2 集中定义正面列表 + 负面排除，HN 相关 prompt 引用 | 避免领域定义在 prompt 间漂移；用户已明确兴趣边界（AI Agent / 模型 / 基础设施 / 大厂动态），排除嵌入式、底层系统、纯前端模板、学习资源等 |
| 板块 sentinel 用 HTML 注释 | `<!-- SECTION:xxx BEGIN/END -->` | markdown 渲染不显示；机器易解析；老 push 文件零冲突 |
| 失败降级粒度 | 单板块失败省略本段；RSS 失败整体退出 | RSS 是核心承诺，其他是增强 |
| 早报判定 | cron + 容差，而非"今天第一次" | 早报失败时晚报不会错误升级为长版本 |
| 截断参数初始值（2026-05-17 合入） | `top_comments=20` / `comment_max_chars=500` / `link_content_max_chars=3000` | 凭直觉给出的保守默认；上线后通过真实数据校准 |
| 截断参数校准（2026-05-17 合入后,激进路径） | `top_comments: 20→50` / `link_content_max_chars: 6000→50000` / `comment_max_chars: 800→2000` / `comments_total_chars: 80000` / `max_prompt_chars: 64000→150000` | 用户决策:把 LLM 上下文用到 DeepSeek v4 flash 128k tokens 限的合理水平,优先内容深度而非 API 成本。中英混合 100k chars ≈ 30-50k tokens,远低于 128k 模型限 |
| 单板块 CLI（2026-05-17 合入后） | `python -m src.main rss` / `hackernews` / `gaps` / `relevance` | 便于 prompt 调优期反复跑单板块而不消耗全套 LLM 调用；relevance 子命令单跑时打印 + 落盘 |


hacker news 评论统计

┌─────────────┬──────────┬──────────────┬────────────────┬──────────┐
│    层级     │ 平均条数 │ 平均 md 字符 │ 平均单条 chars │ 最大单条 │
├─────────────┼──────────┼──────────────┼────────────────┼──────────┤
│ L1 顶层评论 │ 18       │ 5,952        │ ~330           │ 1,755    │
├─────────────┼──────────┼──────────────┼────────────────┼──────────┤
│ L2 一级回复 │ 24       │ 8,166        │ ~340           │ 2,381    │
├─────────────┼──────────┼──────────────┼────────────────┼──────────┤
│ L3+ 更深层  │ 41       │ 13,048       │ ~315           │ 2,291    │
├─────────────┼──────────┼──────────────┼────────────────┼──────────┤
│ ALL 全部    │ 83       │ 27,166       │ ~330           │ 2,381    │
└─────────────┴──────────┴──────────────┴────────────────┴──────────┘
