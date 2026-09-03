"""
模块六+九：聊天主循环 v4.1（导师情报 + 论文拆解 + M5思考批改 + M2导师深潜）
v1.0 改动：工具层报错附带 traceback 尾部，提升可观测性
用法：python main.py
      然后直接用中文提问，输入 quit 退出
多行输入：/m 回车后逐行粘贴，最后单独一行输入 EOF 结束
文件输入：/f D:\path\thinking.txt  （读取整个文件当一条消息）
"""
import json
import traceback
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
import critique_thinking as ct
import advisor_deepdive as ad

PROVIDERS = {
    "moonshot": {"base_url": "https://api.moonshot.cn/v1",
                 "fast": "moonshot-v1-8k", "long": "moonshot-v1-128k"},
    "deepseek": {"base_url": "https://api.deepseek.com",
                 "fast": "deepseek-chat", "long": "deepseek-chat"},
}
P = PROVIDERS[PROVIDER]
CLIENT = OpenAI(api_key=API_KEY, base_url=P["base_url"])

# ============ 输入层：单行 / 多行 / 文件 ============

def read_user_input():
    """返回用户输入的完整文本；返回 None 表示退出；返回空串表示本轮忽略"""
    first = input("你：").strip()
    if first.lower() in ("quit", "exit"):
        return None
    if first == "/m":
        print("[多行模式] 逐行输入/粘贴，最后单独一行输入 EOF 结束：")
        lines = []
        while True:
            line = input()
            if line.strip() == "EOF":
                break
            lines.append(line)
        return "\n".join(lines).strip()
    if first.startswith("/f "):
        path = first[3:].strip().strip('"')
        try:
            text = Path(path).read_text(encoding="utf-8")
            print(f"[已读取文件] {path}（{len(text)} 字符）")
            return text
        except Exception as e:
            print(f"读取失败：{e}")
            return ""
    return first

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
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"检索失败：{e}", "traceback": tb}, ensure_ascii=False)
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
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"论文下载失败：{e}", "traceback": tb}, ensure_ascii=False)
    try:
        text = txt_file.read_text(encoding="utf-8")
        card = ap.step0_decision_card(CLIENT, P["fast"], text)
    except Exception as e:
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"决策卡生成失败：{e}", "traceback": tb}, ensure_ascii=False)
    return json.dumps(card, ensure_ascii=False)


def tool_deep_dive(arxiv_id: str) -> str:
    """精读：七段框架完整拆解 + 反幻觉校验（耗时1-2分钟）"""
    try:
        txt_file, _, _ = fetch_paper(arxiv_id)
    except Exception as e:
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"论文下载失败：{e}", "traceback": tb}, ensure_ascii=False)
    try:
        text = txt_file.read_text(encoding="utf-8")
        analysis = ap.full_analysis(CLIENT, P["long"], text)
        warnings = ap.verify_quotes(analysis, text)
    except Exception as e:
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"精读失败：{e}", "traceback": tb}, ensure_ascii=False)
    out = PAPERS_DIR / f"{arxiv_id.replace('/', '_')}_analysis.json"
    out.write_text(json.dumps({"analysis": analysis, "verification_warnings": warnings},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    return json.dumps({"analysis": analysis,
                       "verification_warnings": warnings or "全部通过"},
                      ensure_ascii=False)


# ============ 工具三：M5 思考批改 ============

def tool_critique_thinking(arxiv_id: str, thinking: str) -> str:
    """M5：对照论文批改用户思考 → 纠错/偏题/追问/凝练，错误回流知识档案"""
    try:
        result = ct.run_grading(CLIENT, arxiv_id, thinking)
    except Exception as e:
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"批改失败：{e}", "traceback": tb}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


def tool_appeal_grading(arxiv_id: str) -> str:
    """申诉复核：用户不认可批改时调用，重新核对每条引用并返回原文上下文"""
    try:
        result = ct.appeal(arxiv_id)
    except Exception as e:
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"申诉复核失败：{e}", "traceback": tb}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


# ============ 工具四：M2 导师深潜 ============

def tool_advisor_deepdive(name: str, site: str = "", url: str = "") -> str:
    """M2：抓取老师个人主页等信源，产出带逐字证据的深潜报告（近期研究/组内风格/招生/去向/动态）"""
    try:
        result = ad.run_deepdive(CLIENT, name, site, url)
    except Exception as e:
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"深潜失败：{e}", "traceback": tb}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


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
    {"type": "function", "function": {
        "name": "critique_thinking",
        "description": "M5思考批改：用户读完一篇【已精读过】的论文后提交了自己写的思考文字时调用。做事实纠错/偏题检测/费曼追问/凝练段落。thinking 必须原样传入用户写的思考全文，禁止改写删减",
        "parameters": {"type": "object", "properties": {
            "arxiv_id": {"type": "string", "description": "该论文的 arXiv id，须是用户已精读过的"},
            "thinking": {"type": "string", "description": "用户提交的思考全文"}},
            "required": ["arxiv_id", "thinking"]}}},
    {"type": "function", "function": {
        "name": "appeal_grading",
        "description": "申诉复核：用户对批改结果有异议时调用，重新核对批改中每条原文引用是否真实存在",
        "parameters": {"type": "object", "properties": {
            "arxiv_id": {"type": "string", "description": "该论文的 arXiv id"}},
            "required": ["arxiv_id"]}}},
    {"type": "function", "function": {
        "name": "advisor_deepdive",
        "description": "M2导师深潜：用户想深入了解某位【已收录】老师时调用。抓取其个人主页/实验室页，产出带逐字证据的深潜报告（近期研究/组内风格/招生意向/学生去向/近期动态/该问的问题）",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "老师中文名，须已在卡片库中"},
            "site": {"type": "string", "description": "站点代号，可省略，省略时全库搜索", "default": ""},
            "url": {"type": "string", "description": "手动指定的个人主页网址，可省略；卡片里没有外链时请用户提供", "default": ""}},
            "required": ["name"]}}},
]

DISPATCH = {"list_sites": tool_list_sites, "list_teachers": tool_list_teachers,
            "get_card": tool_get_card, "add_school": tool_add_school,
            "search_papers": tool_search_papers, "paper_decision": tool_paper_decision,
            "deep_dive": tool_deep_dive,
            "critique_thinking": tool_critique_thinking,
            "appeal_grading": tool_appeal_grading,
            "advisor_deepdive": tool_advisor_deepdive}

SYSTEM = """你是导师情报与论文伴读助手，服务对象是一名想找实验室的计算机大三学生。

铁律：
1. 你只能通过调用工具获取信息，禁止凭自己的知识回答任何关于具体老师或论文的事实；
2. 工具返回什么就说什么，查不到就如实说"未收录/无数据"；如果工具返回了 traceback 字段，请截取最后几行关键报错（包含文件名和行号）告诉用户，不要只说"内部错误"；
3. 展示老师信息时保留招生信号标记（🟢🟡⚪）和 evidence 原文引用；
4. 用户问未收录的学校时，主动说明并请他提供该校师资页网址；
5. 论文流程：用户给中文老师名 → 你转成拼音调 search_papers → 展示结果（重点推荐"末位作者"的论文，那是他主导的）→ 用户选定后先调 paper_decision 出决策卡 → 用户明确说"精读/拆解"才调 deep_dive；
6. deep_dive 返回的 analysis 要完整展示给用户，逐段呈现并保留原文引用；verification_warnings 非空时要如实告知哪些引句未通过校验；
7. M5批改流程：用户对已精读的论文提交思考后，原样传入 critique_thinking（禁止替用户改写思考）；返回结果分四块呈现——fact_errors 逐条列出并保留 quote 原文引用与 correction；verification_warnings 非空时如实告知"以下批改未通过原文校验，可申诉"；depth.probes 以提问形式抛给用户；condensed 作为凝练段落完整展示；用户对批改不认可时调 appeal_grading，不要自行辩护；
8. M2深潜流程：用户说"深挖/深入了解某位老师"时调 advisor_deepdive（name 传老师中文名）；返回的 report 按五个维度分块展示并保留每条 evidence 与来源编号；verification_warnings 非空时如实告知；fit_questions 以提问清单形式呈现给用户；如果返回 error 说没有外链，请用户提供该老师个人主页网址后带 url 参数重试；
9. 回答用简洁中文，列表用表格。"""


def main():
    messages = [{"role": "system", "content": SYSTEM}]
    print("导师情报 Agent（论文拆解 + 思考批改 + 导师深潜）已启动，输入 quit 退出")
    print("长文本技巧：/m 进入多行模式（EOF 结束）；/f 文件路径 读取整个文件\n")

    while True:
        user = read_user_input()
        if user is None:
            break
        if not user:
            continue
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
                    print(f"  [调用工具] {call.function.name}({str(args)[:200]})")
                    result = DISPATCH[call.function.name](**args)
                    messages.append({"role": "tool", "tool_call_id": call.id,
                                     "content": result})
            else:
                print(f"\nAgent：{msg.content}\n")
                messages.append(msg)
                break


if __name__ == "__main__":
    main()
