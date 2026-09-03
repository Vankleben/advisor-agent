"""
模块六+九：聊天主循环 v2（导师情报 + 论文拆解）
用法：python main.py
      然后直接用中文提问，输入 quit 退出
示例：现在收录了哪些学院？
      人工智能学院有哪些研究大模型安全的老师？
      帮我查查董胤蓬最近发了什么论文
      第3篇值不值得读？  →  精读
"""
import json
import sys
import subprocess
from pathlib import Path
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent   # main.py 在根目录
DATA_DIR = BASE_DIR / "data"
PAPERS_DIR = DATA_DIR / "papers"
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "tools"))
from config import PROVIDER, API_KEY
from paper_tools import search_papers, fetch_paper
import analyze_paper as ap

PROVIDERS = {
    "moonshot": {"base_url": "https://api.moonshot.cn/v1",
                 "fast": "moonshot-v1-8k", "long": "moonshot-v1-128k"},
    "deepseek": {"base_url": "https://api.deepseek.com",
                 "fast": "deepseek-chat", "long": "deepseek-chat"},
}
P = PROVIDERS[PROVIDER]
CLIENT = OpenAI(api_key=API_KEY, base_url=P["base_url"])

# ============ 工具一：导师情报 ============

def tool_list_sites() -> str:
    sites = []
    for f in sorted(DATA_DIR.glob("cards_*.json")):
        with open(f, encoding="utf-8") as fp:
            cards = json.load(fp)["cards"]
        sites.append({"site": f.stem.replace("cards_", ""), "人数": len(cards)})
    return json.dumps(sites or "还没有收录任何站点", ensure_ascii=False)


def tool_list_teachers(site: str, keyword: str = "", level: str = "") -> str:
    f = DATA_DIR / f"cards_{site}.json"
    if not f.exists():
        return json.dumps({"error": f"站点 {site} 未收录，可先用 add_school 收录"},
                          ensure_ascii=False)
    with open(f, encoding="utf-8") as fp:
        cards = json.load(fp)["cards"]

    result = []
    for c in cards:
        if c.get("skipped"):
            continue
        if keyword:
            blob = json.dumps(c.get("research_interests", []), ensure_ascii=False) \
                   + str((c.get("current_focus") or {}).get("text", "")) \
                   + str(c.get("summary", ""))
            if keyword not in blob:
                continue
        if level:
            if (c.get("recruitment") or {}).get("level", "") != level:
                continue
        result.append({
            "name": c.get("name"), "title": c.get("title"),
            "sections": c.get("sections"),
            "research": c.get("research_interests"),
            "招生信号": (c.get("recruitment") or {}).get("level"),
            "summary": c.get("summary"),
        })
    if len(result) > 50:
        n = len(result)
        result = result[:50] + [{"说明": f"结果过多，仅显示前50条，共筛出{n}条"}]
    return json.dumps(result or "没有符合条件的老师", ensure_ascii=False)


def tool_get_card(name: str, site: str = "") -> str:
    files = [DATA_DIR / f"cards_{site}.json"] if site else sorted(DATA_DIR.glob("cards_*.json"))
    for f in files:
        if not f.exists():
            continue
        with open(f, encoding="utf-8") as fp:
            for c in json.load(fp)["cards"]:
                if c.get("name") == name:
                    return json.dumps(c, ensure_ascii=False)
    return json.dumps({"error": f"找不到 {name}，可能未收录"}, ensure_ascii=False)


def tool_add_school(url: str, site_name: str) -> str:
    r = subprocess.run([sys.executable, str(BASE_DIR / "tools" / "universal_crawl.py"),
                        url, site_name],
                       capture_output=True, text=True, timeout=300, cwd=str(BASE_DIR))
    out = (r.stdout or "") + (r.stderr or "")
    out += (f"\n提示：名单已收录。若要生成完整卡片，请让用户在终端执行："
            f"python tools/enrich_faculty.py {site_name} 和 python tools/batch_cards.py {site_name}")
    return out


# ============ 工具二：论文链路 ============

def tool_search_papers(author_en: str) -> str:
    """按作者英文名查 arXiv 近期论文"""
    try:
        papers = search_papers(author_en)
    except Exception as e:
        return json.dumps({"error": f"检索失败：{e}"}, ensure_ascii=False)
    out = PAPERS_DIR / f"search_{author_en.replace(' ', '_')}.json"
    out.write_text(json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8")
    brief = [{"序号": i, "id": p["arxiv_id"], "发表": p["published"],
              "标题": p["title"], "作者位置": p["author_position"],
              "末位作者": p["is_last_author"]} for i, p in enumerate(papers)]
    return json.dumps(brief or "未找到该作者的论文（检查英文名拼写）", ensure_ascii=False)


def tool_paper_decision(arxiv_id: str) -> str:
    """第0步：下载论文并出阅读决策卡"""
    try:
        txt_file, _, _ = fetch_paper(arxiv_id)
    except Exception as e:
        return json.dumps({"error": f"论文下载失败：{e}"}, ensure_ascii=False)
    text = txt_file.read_text(encoding="utf-8")
    card = ap.step0_decision_card(CLIENT, P["fast"], text)
    return json.dumps(card, ensure_ascii=False)


def tool_deep_dive(arxiv_id: str) -> str:
    """精读：七段框架完整拆解 + 反幻觉校验（耗时1-2分钟）"""
    try:
        txt_file, _, _ = fetch_paper(arxiv_id)
    except Exception as e:
        return json.dumps({"error": f"论文下载失败：{e}"}, ensure_ascii=False)
    text = txt_file.read_text(encoding="utf-8")
    analysis = ap.full_analysis(CLIENT, P["long"], text)
    warnings = ap.verify_quotes(analysis, text)
    out = PAPERS_DIR / f"{arxiv_id.replace('/', '_')}_analysis.json"
    out.write_text(json.dumps({"analysis": analysis, "verification_warnings": warnings},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    return json.dumps({"analysis": analysis,
                       "verification_warnings": warnings or "全部通过"},
                      ensure_ascii=False)


# ============ 工具注册与派发 ============

TOOLS = [
    {"type": "function", "function": {
        "name": "list_sites", "description": "列出已收录的所有学院/站点及人数",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "list_teachers",
        "description": "列出某站点的老师，可按研究方向关键词、招生信号（🟢/🟡/⚪）筛选",
        "parameters": {"type": "object", "properties": {
            "site": {"type": "string", "description": "站点代号，如 collegeai / life"},
            "keyword": {"type": "string", "description": "研究方向关键词，可省略", "default": ""},
            "level": {"type": "string", "description": "招生信号 🟢/🟡/⚪，可省略", "default": ""}},
            "required": ["site"]}}},
    {"type": "function", "function": {
        "name": "get_card",
        "description": "查看某位老师的完整卡片，含所有 evidence 原文引用",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "site": {"type": "string", "description": "可省略，省略时全库搜索", "default": ""}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "add_school",
        "description": "收录一个新学校的师资名单页（用户提供师资页网址时调用）",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "师资名单页的完整网址"},
            "site_name": {"type": "string", "description": "给站点起个英文代号"}},
            "required": ["url", "site_name"]}}},
    {"type": "function", "function": {
        "name": "search_papers",
        "description": "查某老师近期发表的论文。参数是作者英文名（拼音），中文名由你负责转成拼音",
        "parameters": {"type": "object", "properties": {
            "author_en": {"type": "string", "description": "作者英文名，如 Yinpeng Dong"}},
            "required": ["author_en"]}}},
    {"type": "function", "function": {
        "name": "paper_decision",
        "description": "对某篇论文出【阅读决策卡】：定位/匹配度/建议/前置缺口。用户选定一篇论文后先调这个",
        "parameters": {"type": "object", "properties": {
            "arxiv_id": {"type": "string", "description": "arXiv id，如 2605.18309v1"}},
            "required": ["arxiv_id"]}}},
    {"type": "function", "function": {
        "name": "deep_dive",
        "description": "对论文做七段框架完整拆解（目标/背景/实验/方法/概念/结果/复现）。仅当用户明确说要精读/拆解时才调用",
        "parameters": {"type": "object", "properties": {
            "arxiv_id": {"type": "string", "description": "arXiv id，如 2605.18309v1"}},
            "required": ["arxiv_id"]}}},
]

DISPATCH = {"list_sites": tool_list_sites, "list_teachers": tool_list_teachers,
            "get_card": tool_get_card, "add_school": tool_add_school,
            "search_papers": tool_search_papers, "paper_decision": tool_paper_decision,
            "deep_dive": tool_deep_dive}

SYSTEM = """你是导师情报与论文伴读助手，服务对象是一名想找实验室的计算机大三学生。

铁律：
1. 你只能通过调用工具获取信息，禁止凭自己的知识回答任何关于具体老师或论文的事实；
2. 工具返回什么就说什么，查不到就如实说"未收录/无数据"；
3. 展示老师信息时保留招生信号标记（🟢🟡⚪）和 evidence 原文引用；
4. 用户问未收录的学校时，主动说明并请他提供该校师资页网址；
5. 论文流程：用户给中文老师名 → 你转成拼音调 search_papers → 展示结果（重点推荐"末位作者"的论文，那是他主导的）→ 用户选定后先调 paper_decision 出决策卡 → 用户明确说"精读/拆解"才调 deep_dive；
6. deep_dive 返回的 analysis 要完整展示给用户，逐段呈现并保留原文引用；verification_warnings 非空时要如实告知哪些引句未通过校验；
7. 回答用简洁中文，列表用表格。"""


def main():
    messages = [{"role": "system", "content": SYSTEM}]
    print("导师情报 Agent（含论文拆解）已启动，输入 quit 退出\n")

    while True:
        user = input("你：").strip()
        if user.lower() in ("quit", "exit"):
            break
        messages.append({"role": "user", "content": user})

        # function calling 循环：LLM 可能连续调用多个工具才给出回答
        for _ in range(10):
            resp = CLIENT.chat.completions.create(
                model=P["fast"], messages=messages, tools=TOOLS, temperature=0.3)
            msg = resp.choices[0].message

            if msg.tool_calls:
                messages.append(msg)
                for call in msg.tool_calls:
                    args = json.loads(call.function.arguments or "{}")
                    print(f"  [调用工具] {call.function.name}({args})")
                    result = DISPATCH[call.function.name](**args)
                    messages.append({"role": "tool", "tool_call_id": call.id,
                                     "content": result})
            else:
                print(f"\nAgent：{msg.content}\n")
                messages.append(msg)
                break


if __name__ == "__main__":
    main()