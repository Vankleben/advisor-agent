"""
M5：思考批改与凝练
对照已精读论文的原文与分析结果，对用户提交的思考文字进行：
1. 事实纠错（fact_errors）—— 找出用户思考中与论文原文矛盾的事实错误，附 quote 原文与 correction
2. 偏题检测（relevance）—— 检查用户思考是否偏离论文核心贡献
3. 费曼追问（depth.probes）—— 针对用户思考中浅尝辄止的部分，提出追问
4. 凝练段落（condensed）—— 将用户思考中的正确部分凝练为一段学术化表述
5. 反幻觉校验（verification_warnings）—— 校验批改结果中引用的原文是否真实存在于论文中

申诉复核（appeal）：用户对批改不认可时，重新核对每条 quote 是否真实存在于原文，返回原文上下文

依赖：
- data/papers/{arxiv_id}_analysis.json  （M3 精读时保存的分析结果）
- data/papers/{arxiv_id}.txt            （M3 下载的论文原文）
用法：
  run_grading(client, "2401.12345v1", "用户写的思考全文")
  appeal("2401.12345v1")
"""


# --- Windows 控制台编码修复：GBK 下 print emoji 会崩溃，强制 stdout/stderr 为 UTF-8 ---
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import json
import re
import sys
import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PAPERS_DIR = DATA_DIR / "papers"
ARCHIVE_DIR = BASE_DIR / "archive"
FENCE = chr(96) * 3
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "tools"))
from config import PROVIDER   # noqa: E402

# 批改需容纳论文全文，选长上下文模型（与 main.py 的 P["long"] 同角色）
GRADING_MODEL = {"moonshot": "moonshot-v1-128k", "deepseek": "deepseek-chat"}[PROVIDER]

# 用户画像从 archive/profile.json 读取（唯一权威版本），禁止在此硬编码
from user_profile import format_profile  # noqa: E402


# ============ 加载论文原文与精读分析 ============

def _load_paper_text(arxiv_id: str) -> str:
    """从 data/papers/ 加载论文原文"""
    safe_id = arxiv_id.replace("/", "_")
    # 尝试多种文件名
    candidates = [
        PAPERS_DIR / f"{safe_id}.txt",
        PAPERS_DIR / f"{safe_id}_full.txt",
        PAPERS_DIR / f"{arxiv_id}.txt",
    ]
    for f in candidates:
        if f.exists():
            return f.read_text(encoding="utf-8")
    raise FileNotFoundError(f"找不到论文原文: {arxiv_id}，请先精读（deep_dive）")


def _load_analysis(arxiv_id: str) -> dict:
    """从 data/papers/ 加载精读分析结果"""
    safe_id = arxiv_id.replace("/", "_")
    f = PAPERS_DIR / f"{safe_id}_analysis.json"
    if not f.exists():
        raise FileNotFoundError(f"找不到精读分析: {arxiv_id}，请先调 deep_dive 精读")
    data = json.loads(f.read_text(encoding="utf-8"))
    return data


# ============ 反幻觉校验：检查 quote 是否真实存在于原文 ============

def _verify_quotes(quotes: list, paper_text: str) -> list:
    """
    校验一批引句是否真实存在于论文原文中
    返回未通过的列表：[{"quote": "xxx", "reason": "在原文中未找到此引句"}]
    """
    warnings = []
    paper_lower = paper_text.lower()
    for q in quotes:
        if not q or not isinstance(q, str):
            continue
        # 去除首尾引号和空白
        q_clean = q.strip().strip('"').strip("'").strip()
        if not q_clean:
            continue
        # 尝试精确匹配（忽略大小写）
        if q_clean.lower() in paper_lower:
            continue
        # 尝试去掉标点后匹配
        q_no_punct = re.sub(r'[^\w\s]', '', q_clean).lower()
        p_no_punct = re.sub(r'[^\w\s]', '', paper_text).lower()
        if q_no_punct and q_no_punct in p_no_punct:
            continue
        # 归一化兜底：剥掉所有非字母数字汉字字符后比对，
        # 免疫 PDF 提取的折行连字符/换行/空白差异（与 analyze_paper._norm 同方案）
        norm = lambda s: re.sub(r"[^0-9a-zA-Z一-鿿]+", "", s).lower()
        if q_clean and norm(q_clean) in norm(paper_text):
            continue
        # 省略号兜底：LLM 可能合法截断长句（尾部带省略号），剥掉后再归一化比对。
        # 不做"前N字符命中即通过"的宽松匹配——那会放过"真前缀+编造尾部"的引句
        q_ell = re.sub(r"(?:\.{3,}|…+)\s*$", "", q_clean).strip()
        if q_ell and q_ell != q_clean and norm(q_ell) in norm(paper_text):
            continue
        # 都没找到
        warnings.append({"quote": q_clean, "reason": "在论文原文中未找到此引句，可能为LLM幻觉"})
    return warnings


# ============ 批改主逻辑 ============

GRADE_PROMPT = """你是论文思考批改员。用户是一名CS大三学生，刚读完一篇论文并写了自己的思考。
你需要对照论文原文和精读分析，对用户的思考进行严格批改。

铁律：
1. 所有事实判断必须基于我提供的论文原文，禁止凭你的知识编造；
2. fact_errors 中的每条 quote 必须是从论文原文中逐字复制的句子（不是你的概括），如果用户思考中有与原文矛盾的事实，附上原文 quote 和 correction；
3. 如果用户思考中没有事实错误，fact_errors 返回空数组；
4. 每条 fact_error 标注 error_type，取值：流程误解/数字记错/方法张冠李戴/概念混淆/无中生有；
5. depth.probes 是针对用户思考中浅尝辄止或未深入的部分提出的费曼式追问，以问题形式呈现，逼用户自己解释；missing_angles 列出用户没写到的可深挖角度；
6. depth.offtopic 检查用户思考是否偏离论文核心贡献，verdict 取 on_topic/partial/off_topic，reason 说明判断依据；
7. condensed 是将用户思考修正后的内容凝练为一段学术化表述（300-700字），保留用户的核心观点但提升表达精度。

【用户画像】
{profile}

【论文原文（截断）】
{paper_text}

【精读分析（七段框架）】
{analysis}

【用户提交的思考原文】
{thinking}

输出JSON：
{{
  "fact_errors": [
    {{
      "error_type": "流程误解/数字记错/方法张冠李戴/概念混淆/无中生有",
      "error": "用户思考中的错误表述（可概括其原意）",
      "quote": "论文原文中的句子（逐字复制）",
      "correction": "正确的事实说明"
    }}
  ],
  "depth": {{
    "core_contributions": [{{"point": "论文核心贡献", "quote": "支撑该贡献的论文原句（逐字复制）"}}],
    "offtopic": {{"verdict": "on_topic/partial/off_topic", "reason": "切题简要肯定；偏题说明哪里偏离了核心贡献"}},
    "missing_angles": ["用户没写到的可深挖角度"],
    "probes": ["费曼式追问1", "追问2", "追问3"]
  }},
  "condensed": "凝练后的学术化段落"
}}"""


def _strip_code_fence(text: str) -> str:
    """去掉可能的 ```json ... ``` 代码块包裹"""
    text = text.strip()
    if text.startswith(FENCE):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit(FENCE, 1)[0]
    return text.strip()


def _backfill_errors(date: str, arxiv_id: str, fact_errors: list) -> None:
    """错误模式回流：批改发现的知识性错误追加到 archive/error_patterns.json（按原文去重）"""
    f = ARCHIVE_DIR / "error_patterns.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"patterns": []}
        pats = data.setdefault("patterns", [])
        for fe in fact_errors:
            error = (fe.get("error") or "").strip()
            correction = (fe.get("correction") or "").strip()
            if not error or not correction:
                continue
            if any(p.get("arxiv_id") == arxiv_id and p.get("error") == error for p in pats):
                continue
            pats.append({"date": date, "arxiv_id": arxiv_id,
                         "error_type": fe.get("error_type") or "事实纠错",
                         "error": error, "correction": correction})
        f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[M5] 错误档案回流失败（不影响批改结果）：{e}")


def run_grading(client, arxiv_id: str, thinking: str) -> dict:
    """
    M5 批改主入口
    :param client: OpenAI client
    :param arxiv_id: 论文 arXiv id
    :param thinking: 用户提交的思考全文（原样传入，禁止改写）
    :return: {
        "fact_errors": [...],
        "relevance": {...},
        "depth": {"probes": [...]},
        "condensed": "...",
        "verification_warnings": [...]
    }
    """
    # 1. 加载论文原文和精读分析
    paper_text = _load_paper_text(arxiv_id)
    analysis_data = _load_analysis(arxiv_id)
    analysis = analysis_data.get("analysis", analysis_data)

    # 2. 构造 prompt
    # 截断上限 160000 字符：常规论文全文进入批改窗口
    # （此前 15000 截断会致盲——实测论文 153k 字符，finetune 等关键内容全落在窗口外）
    PAPER_CAP = 160000
    paper_truncated = paper_text[:PAPER_CAP]
    if len(paper_text) > PAPER_CAP:
        paper_truncated += f"\n...[原文共{len(paper_text)}字符，已截断]"

    prompt = GRADE_PROMPT.format(
        profile=format_profile(),
        paper_text=paper_truncated,
        analysis=json.dumps(analysis, ensure_ascii=False, indent=2)[:8000],
        thinking=thinking,
    )

    # 3. 调 LLM 批改（模型由 config.PROVIDER 决定；勿用 models.list()——返回顺序由服务端决定）
    resp = client.chat.completions.create(
        model=GRADING_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    # 兼容不同 client 的调用方式
    raw = resp.choices[0].message.content.strip()
    raw = _strip_code_fence(raw)

    result = json.loads(raw)

    # 4. 反幻觉校验：批改结果中所有引向论文的 quote 都必须真实存在于原文
    all_quotes = []
    for fe in result.get("fact_errors", []):
        q = fe.get("quote", "")
        if q:
            all_quotes.append(q)
    # depth.core_contributions 里支撑核心贡献的原句同样校验
    for cc in (result.get("depth", {}) or {}).get("core_contributions", []) or []:
        q = cc.get("quote", "") if isinstance(cc, dict) else ""
        if q:
            all_quotes.append(q)
    # condensed 中如果有引号包裹的内容也校验
    condensed = result.get("condensed", "")
    for m in re.finditer(r'"([^"]{20,})"', condensed):
        all_quotes.append(m.group(1))

    warnings = _verify_quotes(all_quotes, paper_text)

    result["verification_warnings"] = warnings

    # 5. 保存批改结果（扁平格式，与既有产物 schema 一致：arxiv_id/date/fact_errors/...）
    result["arxiv_id"] = arxiv_id
    result["date"] = datetime.date.today().isoformat()
    safe_id = arxiv_id.replace("/", "_")
    out = PAPERS_DIR / f"{safe_id}_grading.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # 6. 错误记录回流长期知识档案（设计文档 M5：错误模式库）
    _backfill_errors(result["date"], arxiv_id, result.get("fact_errors") or [])

    # 7. 已读论文库入库（凝练段落沉淀为申请素材）
    try:
        import knowledge_store
        knowledge_store.update_read_papers(arxiv_id)
    except Exception as e:
        print(f"[M5] 已读论文库入库失败（不影响批改结果）：{e}")

    return result


# ============ 申诉复核 ============

def appeal(arxiv_id: str) -> dict:
    """
    申诉复核：用户对批改结果有异议时调用
    重新核对批改中每条 quote 是否真实存在于论文原文，返回原文上下文
    """
    safe_id = arxiv_id.replace("/", "_")

    # 1. 加载批改结果
    grading_file = PAPERS_DIR / f"{safe_id}_grading.json"
    if not grading_file.exists():
        return {"error": f"找不到 {arxiv_id} 的批改结果，无法申诉"}
    grading_data = json.loads(grading_file.read_text(encoding="utf-8"))
    # 兼容两种落盘格式：新版扁平 / 旧版嵌套 {"grading": ...}
    grading = grading_data.get("grading", grading_data)

    # 2. 加载论文原文
    try:
        paper_text = _load_paper_text(arxiv_id)
    except FileNotFoundError as e:
        return {"error": str(e)}

    # 3. 逐条核对 fact_errors 中的 quote
    fact_errors = grading.get("fact_errors", [])
    review = []
    for i, fe in enumerate(fact_errors):
        quote = fe.get("quote", "").strip().strip('"').strip("'")
        if not quote:
            continue
        # 在原文中搜索（精确）
        idx = paper_text.lower().find(quote.lower())
        if idx >= 0:
            # 找到了，提取上下文（前后各 200 字符）
            start = max(0, idx - 200)
            end = min(len(paper_text), idx + len(quote) + 200)
            context = paper_text[start:end]
            review.append({
                "index": i,
                "quote": quote,
                "found": True,
                "context": context,
                "verdict": "引句逐字存在于论文原文中",
            })
        else:
            # 归一化兜底：免疫 PDF 折行/空白/连字差异（与 _verify_quotes 同方案）
            norm = lambda s: re.sub(r"[^0-9a-zA-Z一-鿿]+", "", s).lower()
            if quote and norm(quote) in norm(paper_text):
                review.append({
                    "index": i,
                    "quote": quote,
                    "found": True,
                    "context": "",
                    "verdict": "归一化比对确认存在于原文（原文存在换行/空白差异，无法截取原样上下文）",
                })
            else:
                # 省略号兜底：LLM 合法截断的长句，剥掉省略号后再比对
                q_ell = re.sub(r"(?:\.{3,}|…+)\s*$", "", quote).strip()
                if q_ell and q_ell != quote and norm(q_ell) in norm(paper_text):
                    review.append({
                        "index": i,
                        "quote": quote,
                        "found": True,
                        "context": "",
                        "verdict": "引句以省略号截断，截断前部分归一化后确认存在于原文",
                    })
                else:
                    review.append({
                        "index": i,
                        "quote": quote,
                        "found": False,
                        "context": "",
                        "verdict": "引句在论文原文中未找到，批改中的此条 quote 可能为LLM幻觉，建议撤销该条纠错",
                    })

    # 4. 统计
    total = len(review)
    confirmed = sum(1 for r in review if r["found"])
    hallucinated = total - confirmed

    return {
        "arxiv_id": arxiv_id,
        "review": review,
        "summary": f"共核查 {total} 条引句：{confirmed} 条确认存在于原文，{hallucinated} 条未找到（可能为幻觉）",
        "recommendation": "如有引句未找到，建议撤销对应的 fact_error 条目" if hallucinated > 0 else "所有引句均确认存在于原文，批改结果有效",
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from config import PROVIDER, API_KEY
    from openai import OpenAI

    PROVIDERS = {
        "moonshot": ("https://api.moonshot.cn/v1", "moonshot-v1-8k"),
        "deepseek": ("https://api.deepseek.com", "deepseek-chat"),
    }
    base_url, model = PROVIDERS[PROVIDER]
    client = OpenAI(api_key=API_KEY, base_url=base_url)

    if len(sys.argv) < 2:
        print("用法：")
        print("  python tools/critique_thinking.py <arxiv_id> '思考文字'   # 批改")
        print("  python tools/critique_thinking.py --appeal <arxiv_id>     # 申诉")
        sys.exit(1)

    if sys.argv[1] == "--appeal":
        r = appeal(sys.argv[2])
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        arxiv_id = sys.argv[1]
        thinking = sys.argv[2] if len(sys.argv) > 2 else input("请输入思考全文：\n")
        r = run_grading(client, arxiv_id, thinking)
        print(json.dumps(r, ensure_ascii=False, indent=2))
