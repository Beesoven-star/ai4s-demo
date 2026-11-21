"""Retrieve and cluster a bounded IC paper sample using public metadata only.

No model API or optional Python packages are required. Original Atom responses
and the exact queries are cached so analysis can be repeated without the network.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import re
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NS = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom",
      "o": "http://a9.com/-/spec/opensearch/1.1/"}
QUERIES = [
    ("ic", 'ti:"integrated circuit" OR ti:"integrated circuits"'),
    ("design", 'ti:VLSI OR ti:"electronic design automation" OR ti:"design automation" OR ti:"logic synthesis" OR ti:"physical design"'),
    ("chip", 'ti:chiplet OR ti:CMOS OR ti:ASIC OR ti:"system-on-chip" OR ti:"chip design"'),
    ("circuit", 'ti:"circuit design" OR ti:RTL OR ti:Verilog OR ti:"hardware security" OR ti:"semiconductor manufacturing"'),
    ("architecture", '(cat:cs.AR OR cat:cs.ET) AND (abs:"integrated circuits" OR abs:"integrated circuit" OR abs:VLSI OR abs:chiplet)'),
]
STOP = set("""a an the and or of to in on for from with by at as is are was were be been being
this that these those it its their our we they them which who whose where when while
also can could may might will would should must than then into through over under
between among across without within about such both each other all more most less
many much several some any not no only however therefore thus although yet new
paper work study research propose proposed presents present introduce introduced
approach approaches method methods framework frameworks model models system systems
result results experiment experiments experimental demonstrate demonstrated shows
show showing achieve achieves achieved performance existing based using used use
enables enable enabled including include includes different various first second
compared comparison significant significantly high highly efficient efficiency
effective effectively improve improved improvement improvements novel state art
design designs designed designing circuit circuits integrated chip chips electronic
application applications task tasks problem problems solution solutions technique
techniques process processes level levels end accuracy evaluation evaluate evaluated
data provide provides given large small low higher lower best baseline baselines
number time two three four five set real world respectively available challenging
challenge challenges increasingly critical important potential promising standard
support supports multiple single prior particular general specific required need
needs optimize optimization optimized optimizing optimal advanced leveraging
leverages leverage toward towards scalable scaling scale open source robust complex
complexity comprehensive extensive quality capability capabilities simulation
simulations simulator tool tools code implementation implementations implement
implemented technology technologies learning neural network networks deep machine
""".split())
ALIASES = {"chiplets": "chiplet", "netlists": "netlist", "transistors": "transistor",
           "placements": "placement", "llms": "llm", "verilog": "rtl_verilog",
           "rtl": "rtl_verilog", "photonic": "photonics", "optical": "photonics",
           "memories": "memory", "analogues": "analog", "analogue": "analog",
           "accelerators": "accelerator", "attacks": "attack", "tokens": "token",
           "devices": "device", "wafer": "wafer", "wafers": "wafer"}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_feed(raw, query_id, observed):
    tree = ET.fromstring(raw)
    records = []
    for node in tree.findall("a:entry", NS):
        identifier = node.findtext("a:id", "", NS)
        match = re.search(r"/abs/([^/]+)$", identifier)
        if not match:
            continue
        versioned = match.group(1)
        arxiv_id = re.sub(r"v\d+$", "", versioned)
        abstract = " ".join(node.findtext("a:summary", "", NS).split())
        journal_ref = node.findtext("x:journal_ref", "", NS).strip()
        records.append({
            "id": "arxiv:" + arxiv_id, "arxiv_id": arxiv_id,
            "arxiv_version": versioned, "content_type": "paper",
            "title": " ".join(node.findtext("a:title", "", NS).split()),
            "authors": [a.findtext("a:name", "", NS) for a in node.findall("a:author", NS)],
            "url": "https://arxiv.org/abs/" + arxiv_id,
            "source": "arXiv 作者预印本", "venue_type": "preprint", "venue_name": "arXiv",
            "published_at": node.findtext("a:published", "", NS)[:10],
            "updated_at_source": node.findtext("a:updated", "", NS),
            "date_kind": "arxiv_first_submission", "collected_at": observed,
            "doi": node.findtext("x:doi", "", NS) or None,
            "journal_reference_raw": journal_ref or None,
            "publication_status": "author_preprint; journal reference unverified" if journal_ref else "preprint",
            "arxiv_categories": [c.attrib["term"] for c in node.findall("a:category", NS)],
            "abstract_text": abstract,
            "query_ids": [query_id], "domain": "集成电路",
            "verification_note": "题名、作者、摘要和日期读取自 arXiv Atom 原始记录；首次提交日不是期刊正式发表日。正式版本尚未逐一核验。",
        })
    return records, int(tree.findtext("o:totalResults", "0", NS))


def fetch_sample(out, as_of, limit):
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    observed = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    manifest = {"as_of": as_of.isoformat(), "retrieved_at": observed,
                "window_start": f"{as_of.year}-01-01", "window_end": as_of.isoformat(),
                "max_results_per_query": limit, "sort": "submittedDate descending",
                "scope": "集成电路初步探索样本，含电子与光子集成；未限定 AI 方法。仅 arXiv，非全领域或正式出版物全集。",
                "queries": []}
    all_records = {}
    for index, (query_id, expression) in enumerate(QUERIES):
        query = f'submittedDate:[{as_of.year}01010000 TO {as_of:%Y%m%d}2359] AND ({expression})'
        url = "https://export.arxiv.org/api/query?" + urlencode({"search_query": query, "start": 0,
                "max_results": limit, "sortBy": "submittedDate", "sortOrder": "descending"})
        cache = raw_dir / f"{query_id}.xml"
        if cache.exists():
            raw = cache.read_bytes()
            cached = True
        else:
            if index:
                time.sleep(3.2)
            req = Request(url, headers={"User-Agent": "ICResearchWorkbench/0.1 (bounded public metadata research)"})
            with urlopen(req, timeout=40) as response:
                raw = response.read(8_000_001)
            if len(raw) > 8_000_000:
                raise ValueError("Response exceeds metadata size limit")
            cache.write_bytes(raw)
            cached = False
        records, total = parse_feed(raw, query_id, observed)
        manifest["queries"].append({"id": query_id, "query": query, "url": url,
            "returned": len(records), "total_results": total, "truncated": len(records) < total,
            "raw_file": str(cache.relative_to(out)), "sha256": hashlib.sha256(raw).hexdigest()})
        for record in records:
            if not (f"{as_of.year}-01-01" <= record["published_at"] <= as_of.isoformat()):
                continue
            if record["id"] in all_records:
                all_records[record["id"]]["query_ids"].append(query_id)
            else:
                all_records[record["id"]] = record
        print(json.dumps({"query": query_id, "returned": len(records), "total": total,
                          "unique_so_far": len(all_records), "cached": cached}), flush=True)
    manifest["returned_before_dedup"] = sum(q["returned"] for q in manifest["queries"])
    manifest["unique_after_id_dedup"] = len(all_records)
    save(out / "search_manifest.json", manifest)
    save(out / "papers_raw.json", {"metadata": manifest, "items": sorted(all_records.values(), key=lambda r: r["id"])})


def tokenize(text):
    text = re.sub(r"\b(?:large language models?|large-language models?)\b", "llm", text.lower())
    words = re.findall(r"[a-z][a-z0-9_]{2,}", text)
    words = [ALIASES.get(w, w) for w in words if w not in STOP and len(w) < 30]
    return [w for w in words if w not in STOP]


def vectors_for(items):
    counts = []
    dfs = Counter()
    for item in items:
        title = tokenize(item["title"])
        abstract = tokenize(item["abstract_text"])
        counts_one = Counter(title * 3 + abstract)
        # Bigrams are made separately, so title/abstract boundaries never connect.
        for tokens, weight in ((title, 3), (abstract, 1)):
            for left, right in zip(tokens, tokens[1:]):
                counts_one[f"{left} {right}"] += weight * 0.7
        counts.append(counts_one)
        dfs.update(counts_one.keys())
    features = {word for word, freq in dfs.items() if 2 <= freq <= max(3, len(items) * .70)}
    vectors = []
    for counts_one in counts:
        vector = {w: (1 + math.log(c)) * (math.log((1 + len(items)) / (1 + dfs[w])) + 1)
                  for w, c in counts_one.items() if w in features}
        magnitude = math.sqrt(sum(v*v for v in vector.values())) or 1
        vectors.append({w: v / magnitude for w, v in vector.items()})
    return vectors, len(features)


def dot(left, right):
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(term, 0) for term, value in left.items())


def centroid(vectors, members):
    center = defaultdict(float)
    for index in members:
        for term, value in vectors[index].items():
            center[term] += value
    norm = math.sqrt(sum(v*v for v in center.values())) or 1
    return {term: value / norm for term, value in center.items()}


def fit_kmeans(vectors, k, seed):
    rng = random.Random(seed)
    n = len(vectors)
    chosen = [rng.randrange(n)]
    while len(chosen) < k:
        weights = [max(0., 1 - max(dot(v, vectors[i]) for i in chosen)) ** 2
                   if j not in chosen else 0. for j, v in enumerate(vectors)]
        point = rng.random() * sum(weights)
        for index, weight in enumerate(weights):
            point -= weight
            if point <= 0 and index not in chosen:
                chosen.append(index)
                break
        else:
            chosen.append(next(j for j in range(n) if j not in chosen))
    centers = [vectors[i] for i in chosen]
    previous = None
    for _ in range(60):
        labels = [max(range(k), key=lambda c: dot(vector, centers[c])) for vector in vectors]
        if labels == previous:
            break
        previous = labels[:]
        members = [[i for i, label in enumerate(labels) if label == c] for c in range(k)]
        # Empty centroids are reset to the least similar point, deterministically.
        centers = [centroid(vectors, group) if group else vectors[min(range(n), key=lambda i: dot(vectors[i], centers[labels[i]]))]
                   for group in members]
    objective = sum(dot(vector, centers[labels[i]]) for i, vector in enumerate(vectors))
    return labels, centers, objective


def silhouette(labels, distances, k):
    members = [[i for i, label in enumerate(labels) if label == c] for c in range(k)]
    scores = []
    for i, label in enumerate(labels):
        own = members[label]
        if len(own) <= 1:
            scores.append(0.)
            continue
        a = sum(distances[i][j] for j in own if j != i) / (len(own) - 1)
        b = min(sum(distances[i][j] for j in group) / len(group) for c, group in enumerate(members) if c != label and group)
        scores.append((b - a) / max(a, b) if max(a, b) else 0.)
    return sum(scores) / len(scores)


def analyze(out, selected_k=None):
    corpus = json.loads((out / "papers_raw.json").read_text(encoding="utf-8"))
    exclusions_path = out / "screening.json"
    exclusions = json.loads(exclusions_path.read_text(encoding="utf-8")) if exclusions_path.exists() else {}
    accepted = [p for p in corpus["items"] if p["id"] not in exclusions]
    rejected = [{**p, "exclusion_reason": exclusions[p["id"]]} for p in corpus["items"] if p["id"] in exclusions]
    if len(accepted) < 12:
        raise ValueError("Need at least 12 papers for exploratory clustering")
    vectors, features = vectors_for(accepted)
    distances = [[max(0., 1 - dot(a, b)) for b in vectors] for a in vectors]
    runs = []
    solutions = {}
    for k in ([selected_k] if selected_k else range(5, min(10, len(accepted)//3) + 1)):
        fits = [fit_kmeans(vectors, k, seed) for seed in (7, 19, 43, 71, 101, 137)]
        labels, centers, objective = max(fits, key=lambda fit: fit[2])
        score = silhouette(labels, distances, k)
        sizes = [labels.count(c) for c in range(k)]
        runs.append({"k": k, "cosine_silhouette": round(score, 6), "objective": round(objective, 6), "sizes": sizes})
        solutions[k] = (labels, centers)
    best = max(runs, key=lambda run: run["cosine_silhouette"])
    labels, centers = solutions[best["k"]]
    clusters = []
    for c, center in enumerate(centers):
        members = [i for i, label in enumerate(labels) if label == c]
        ordered = sorted(members, key=lambda i: dot(vectors[i], center), reverse=True)
        # Select documents closest to a spherical centroid as representative papers.
        papers = []
        for i in ordered:
            similarities = sorted([(dot(vectors[i], centers[j]), j) for j in range(len(centers))], reverse=True)
            margin = similarities[0][0] - similarities[1][0]
            p = dict(accepted[i])
            p.update(cluster_id=f"C{c+1:02d}", centroid_similarity=round(dot(vectors[i], center), 5),
                     assignment_margin=round(margin, 5), cluster_review="需人工复核" if margin < .08 else "自动初分组")
            papers.append(p)
        clusters.append({"id": f"C{c+1:02d}", "count": len(members),
                         "top_terms": [t for t, value in sorted(center.items(), key=lambda entry: entry[1], reverse=True)[:18]],
                         "papers": papers})
    result = {"metadata": corpus["metadata"], "method": {
        "algorithm": "TF-IDF (title weight 3, abstract weight 1, unigrams and bigrams) + spherical k-means",
        "dependencies": "Python standard library only; no LLM or embedding API",
        "selected_k": best["k"], "selected_cosine_silhouette": best["cosine_silhouette"],
        "k_selection": ("User-selected exploratory k; six deterministic restarts, best within-cluster cosine objective" if selected_k
                        else "Highest mean cosine silhouette among candidate k; six deterministic restarts per k, best within-cluster cosine objective"),
        "features": features, "candidates": runs,
        "caveat": "探索性词汇聚类；相似度不是可信概率；单一来源和查询截断会造成选样偏差。人工命名不代表人工逐篇确认。"},
        "screening": {"retrieved_unique": len(corpus["items"]), "included": len(accepted), "excluded": len(rejected)},
        "excluded_items": rejected, "clusters": clusters}
    save(out / "clusters_draft.json", result)
    save(out / ("clusters_fine.json" if selected_k else "clusters_coarse.json"), result)
    print(json.dumps({"screening": result["screening"], "method": result["method"]}, ensure_ascii=False), flush=True)
    for group in clusters:
        print(json.dumps({"id": group["id"], "n": group["count"], "terms": group["top_terms"],
                          "representatives": [{"id": p["id"], "title": p["title"]} for p in group["papers"][:5]]}, ensure_ascii=False), flush=True)


def export_results(out):
    coarse = json.loads((out / "clusters_coarse.json").read_text(encoding="utf-8"))
    fine = json.loads((out / "clusters_fine.json").read_text(encoding="utf-8"))
    review = json.loads((out / "topic_review.json").read_text(encoding="utf-8"))
    as_of = date.fromisoformat(coarse["metadata"]["as_of"])
    recent_start = (as_of - timedelta(days=29)).isoformat()
    paper_map = {p["arxiv_id"]: p for c in coarse["clusters"] for p in c["papers"]}
    fine_map = {p["arxiv_id"]: c["id"] for c in fine["clusters"] for p in c["papers"]}
    assigned = [paper_id for t in review["topics"] for paper_id in t["papers"]]
    if len(assigned) != len(set(assigned)) or set(assigned) != set(paper_map):
        raise ValueError("Each included paper must have exactly one reviewed primary topic")
    reviewed_abstracts = {"2609.03594", "2609.35254", "2610.03934", "2610.10858", "2610.14612",
                          "2610.41225", "2611.02304", "2611.08399", "2611.08543", "2611.10824",
                          "2611.11475", "2611.11848"}
    items = []
    topics = []
    for topic in review["topics"]:
        group = []
        for paper_id in topic["papers"]:
            p = dict(paper_map[paper_id])
            p["auto_cluster_id"] = p.pop("cluster_id")
            p["auto_fine_cluster_id"] = fine_map[paper_id]
            p.update(topic_id=topic["id"], topics=[topic["name"]], tasks=[], methods=[], views=[],
                     classification_kind="unsupervised_clustering_then_editorial_grouping",
                     relevance="abstract_reviewed" if paper_id in reviewed_abstracts else "title_screened",
                     summary_kind="source", date_group="近30天首次提交" if p["published_at"] >= recent_start else "历史补录（本年较早）")
            words = p["abstract_text"].split()
            p["abstract_truncated"] = len(words) > 140
            p["abstract_word_count_source"] = len(words)
            p["abstract_text"] = " ".join(words[:140]) + (" …" if len(words) > 140 else "")
            p["summary"] = p["abstract_text"]
            p["verification_note"] += " 主题归属为标题/题录级初步整理；" + ("摘要已抽查，" if paper_id in reviewed_abstracts else "摘要待逐篇复核，") + "未核验全文。页面摘要最多展示140个英文词，完整摘要见原始出处。"
            p["is_representative"] = paper_id in topic["representatives"]
            p["scope"] = topic["scope"]
            group.append(p)
            items.append(p)
        topic_result = {k: v for k, v in topic.items() if k != "papers"}
        topic_result.update(count=len(group), recent_count=sum(p["date_group"].startswith("近30") for p in group),
                            paper_ids=topic["papers"])
        topics.append(topic_result)
    items.sort(key=lambda p: (p["published_at"], p["arxiv_id"]), reverse=True)
    counts = {"returned_before_dedup": coarse["metadata"]["returned_before_dedup"],
              "retrieved_unique": coarse["screening"]["retrieved_unique"],
              "excluded": coarse["screening"]["excluded"], "included": len(items),
              "recent_30_days": sum(p["published_at"] >= recent_start for p in items),
              "earlier_this_year": sum(p["published_at"] < recent_start for p in items),
              "abstract_reviewed": len(reviewed_abstracts), "missing_publication_date": 0,
              "electronic_and_devices": sum(t["count"] for t in topics if t["id"] not in {"T08", "T09"}),
              "extension_topics": sum(t["count"] for t in topics if t["id"] in {"T08", "T09"})}
    result = {"schema_version": "ic-exploration-1.0", "as_of": as_of.isoformat(),
              "collected_on": as_of.isoformat(), "domain": "集成电路", "counts": counts,
              "recent_window": {"start": recent_start, "end": as_of.isoformat()},
              "scope_note": coarse["metadata"]["scope"], "classification_note": review["review_note"],
              "method": coarse["method"], "fine_method": fine["method"],
              "source_queries": coarse["metadata"]["queries"], "topics": topics, "items": items}
    save(out / "首轮论文与专题.json", result)
    # Same snapshot powers the existing workbench's new exploration page.
    save(ROOT / "web" / "public" / "ic-exploration-20261110.json", result)
    report = ["# 集成电路首轮论文检索与子方向分析", "", f"检索截止日：{as_of}。这是用于科研信息工作台的主题探索样本。", "",
        f"五组检索共返回 {counts['returned_before_dedup']} 条记录，按 arXiv 编号去重为 {counts['retrieved_unique']} 篇；排除 {counts['excluded']} 篇范围不符的记录后，保留 **{len(items)} 篇候选论文**。文本聚类后按研究任务初步归并为 **{len(topics)} 个专题**。", "",
        f"其中电子 IC 与器件方向 {counts['electronic_and_devices']} 篇，光子/声子及低温/超导拓展方向 {counts['extension_topics']} 篇。近30天（{recent_start} 至 {as_of}）首次提交 {counts['recent_30_days']} 篇，本年更早资料作为历史补录 {counts['earlier_this_year']} 篇；本次不包含新闻。", "",
        "## 检索范围与证据", "",
        "首轮使用 arXiv 作者预印本元数据与原始摘要，检索窗口为本年1月1日至截止日，每组按首次提交日倒序最多读取40条。原始 Atom、完整查询、响应校验值和排除理由保存在同目录。五组有重叠且均有截断，不能用分组数量估算研究热度或全领域占比。", "",
        "所有日期均采用 arXiv 原始 published 字段，即预印本首次提交日；版本更新时间和本次收录时间另存。作者提供的 journal reference 仅保留原文，不据此声称已核实正式录用或期刊发表。", "",
        "| 检索组 | 返回 | 接口匹配总数 | 范围 |", "| --- | ---: | ---: | --- |"]
    for q in coarse["metadata"]["queries"]:
        report.append(f"| {q['id']} | {q['returned']} | {q['total_results']} | `{q['query']}` |")
    report += ["", "## 聚类方法与解释边界", "",
        "先对题名与摘要构建 TF-IDF 单词/双词特征，题名权重为摘要的3倍，使用球面 K-means；比较 k=5至10，每个 k 用6个固定随机种子重启。该实现仅使用 Python 标准库，不调用模型服务。", "",
        f"平均余弦轮廓系数最高的粗分为 **k={coarse['method']['selected_k']}**，系数 **{coarse['method']['selected_cosine_silhouette']}**；另外保存 k=10 的细分供检查。这个系数较低，说明纯词汇分组区分度弱，不支持宣称已得到稳定领域分类。", "",
        "九个工作台专题是在观察自动粗分/细分后，按论文主要任务进行语义归并与修正得到；并非算法自动确定的九个簇。每篇均保留原始粗簇、细簇和最终专题归属。跨主题论文暂以一个主专题展示，后续可增加副标签。", "",
        f"已检查全部候选的题名与题录，重点抽查 {len(reviewed_abstracts)} 篇代表论文摘要；其他条目的摘要和相关性仍待逐篇复核，未作全文精读或独立复现。页面的分组只用于确定阅读与采集方向。", "",
        "## 初步子方向", "", "| 编号 | 子方向 | 候选篇数 | 近30天首次提交 |", "| --- | --- | ---: | ---: |"]
    for topic in topics:
        report.append(f"| {topic['id']} | {topic['name']} | {topic['count']} | {topic['recent_count']} |")
    for topic in topics:
        report += ["", f"### {topic['id']} {topic['name']}", "", f"范围：{topic['scope']}。", "", topic["focus"], "",
                   f"可展开的问题：{topic['question']}", "", "代表性材料（日期为首次提交日）：", ""]
        for identifier in topic["representatives"]:
            p = paper_map[identifier]
            report.append(f"- [{p['title']}]({p['url']})，{p['published_at']}。")
    report += ["", "## 下一步怎样展开", "",
        "优先选择 T01 RTL生成/验证、T02逻辑综合/物理设计、T03模拟/RF设计三个方向建立阅读卡：任务、输入输出、所用工具、数据集、评价指标、作者局限和原文证据。T04芯粒作为体系结构分支单独跟进，T08/T09按拓展专题保留。方向选择依据是本轮能够形成连贯论文组及具体评价问题，不代表这些方向已经被证实最前沿或最有创新空间。", "",
        "第一条完整使用示例可用 AutoC2V：按首次提交日期找到论文，查看来源，收藏、备注其生成任务与QoR评价，记录待核验问题，再变更阅读状态。当前本轮只完成论文检索、分组与探索展示；收藏、备注和阅读状态仍需后续实现。", "",
        "来源扩充应覆盖正式期刊与会议论文集，尤其补齐当前 arXiv 对制造、工艺、封装测试与工业成果的覆盖不足。新闻需要单独采集并保留新闻/论文类型，不能把论文摘要改名为新闻。", "",
        "## 文件与复现", "",
        "- `首轮论文与专题.json`：结构化题录、摘要节选、日期、自动簇与整理后的专题。",
        "- `论文索引.md`：全部保留论文的来源链接、日期和专题。",
        "- `search_manifest.json`、`raw/*.xml`：查询和原始响应证据。",
        "- `screening.json`：23篇排除记录及理由；`topic_review.json`：主专题归属。",
        "- `clusters_coarse.json`、`clusters_fine.json`：自动粗分和细分的完整结果。", "",
        "在项目目录运行：", "", "```powershell",
        ".venv\\Scripts\\python.exe scripts\\explore_ic.py fetch --as-of 2026-11-10 --max-results 40",
        ".venv\\Scripts\\python.exe scripts\\explore_ic.py cluster",
        ".venv\\Scripts\\python.exe scripts\\explore_ic.py cluster --k 10",
        ".venv\\Scripts\\python.exe scripts\\explore_ic.py export", "```", "",
        "fetch 默认复用缓存；新增检索日期应使用新目录，并重新核验排除与专题映射。"]
    (out / "检索与子方向分析.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    index = ["# 集成电路首轮论文索引", "", "日期为预印本首次提交日；全部为初筛候选，未逐篇核验正式出版状态。", "",
             "| 首次提交 | 专题 | 论文 | 时间标记 |", "| --- | --- | --- | --- |"]
    for p in items:
        index.append(f"| {p['published_at']} | {p['topics'][0]} | [{p['title'].replace('|', '／')}]({p['url']}) | {p['date_group']} |")
    (out / "论文索引.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from src import discovery
    db = ROOT / "news-data" / "discovery-ic.sqlite"
    first = discovery.upsert_items(items, origin="collected", db_path=db)
    second = discovery.upsert_items(items, origin="collected", db_path=db)
    if second["inserted"] or second["updated"] or second["total"] != len(items):
        raise ValueError(f"Repeat import failed idempotency check: {second}")
    save(out / "verification.json", {"counts": counts, "first_import": first, "repeat_import": second,
         "database": str(db), "unique_arxiv_ids": len({p["arxiv_id"] for p in items}),
         "unique_dois": len({p["doi"] for p in items if p["doi"]}),
         "single_primary_topic": True,
         "abstract_reviewed_ids": sorted(reviewed_abstracts)})
    print(json.dumps({"counts": counts, "topics": [{"name": t["name"], "count": t["count"], "recent": t["recent_count"]} for t in topics],
                      "database_import": first, "repeat_import": second}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["fetch", "cluster", "export"])
    parser.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 11, 10))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--max-results", type=int, default=40)
    parser.add_argument("--k", type=int)
    args = parser.parse_args()
    out = args.out or ROOT.parent / "研究样本" / "集成电路" / args.as_of.isoformat()
    if args.action == "fetch":
        fetch_sample(out, args.as_of, args.max_results)
    elif args.action == "cluster":
        analyze(out, args.k)
    else:
        export_results(out)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
