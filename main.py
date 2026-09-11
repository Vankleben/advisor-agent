"""
模块六+九：聊天主循环 v4.4（导师情报 + 论文拆解 + M5思考批改 + M2导师深潜 + M4进组路径 + M1.5对比视图 + M6实时监测）
v4.4 改动：新增 M6 实时情报监测（monitor / monitor_show）
v4.3 改动：新增 M1.5 对比视图（panorama 全景表 + deep_compare 深度对比）
v4.2 改动：新增 M4 进组路径分析工具 path_analysis
用法：python main.py
      然后直接用中文提问，输入 quit 退出
多行输入：/m 回车后逐行粘贴，最后单独一行输入 EOF 结束
文件输入：/f 路径（读取整个文件当一条消息）
"""


# --- Windows 控制台编码修复：GBK 下 print emoji 会崩溃，强制 stdout/stderr 为 UTF-8 ---
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
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
from paper_tools import (search_papers, search_europepmc, fetch_lab_publications,
                         merge_paper_sources, fetch_paper)
import analyze_paper as ap
import critique_thinking as ct
import advisor_deepdive as ad
import path_analysis as pa
import compare_advisors as ca
import web_fetch as wf
import knowledge_store as ks
import monitor as mon

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
    crawl = subprocess.run([sys.executable, str(BASE_DIR / "tools" / "universal_crawl.py"),
                            url, site_name],
                           capture_output=True, text=True, timeout=300, cwd=str(BASE_DIR),
                           encoding="utf-8", errors="replace")
    out = (crawl.stdout or "") + (crawl.stderr or "")

    # 名单落盘后自动补齐详情页与卡片，让 list_sites/list_teachers 立即可见
    for script in ("enrich_faculty", "batch_cards"):
        step = subprocess.run([sys.executable, str(BASE_DIR / "tools" / f"{script}.py"),
                               site_name],
                              capture_output=True, text=True, timeout=900, cwd=str(BASE_DIR),
                              encoding="utf-8", errors="replace")
        out += "\n" + ((step.stdout or "") + (step.stderr or "")).strip()
    out += f"\n提示：{site_name} 站点卡片已自动生成。如果名单不完整（如分页师资页），请把剩余分页的 URL 再调 add_school 合并。"
    return out


def tool_fetch_url(url: str) -> str:
    """抓取网页正文+链接，供 Agent 自主导航定位院系/师资页/个人主页"""
    try:
        r = wf.fetch_url(url)
    except Exception as e:
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"抓取失败：{e}", "traceback": tb}, ensure_ascii=False)
    return json.dumps(r, ensure_ascii=False)


# ============ 工具七：长期知识档案 ============

def tool_bookmark_advisor(name: str, status: str = "收藏", note: str = "") -> str:
    """收藏/更新目标老师（接触进度：收藏/已读论文/已发邮件/已回复）"""
    try:
        result = ks.bookmark(name, status=status, note=note)
    except Exception as e:
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"收藏失败：{e}", "traceback": tb}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


def tool_list_targets() -> str:
    """查看目标老师清单"""
    try:
        return ks.list_targets()
    except Exception as e:
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"读取失败：{e}", "traceback": tb}, ensure_ascii=False)


# ============ 工具八：M6 实时情报监测 ============

def tool_monitor(name: str = "") -> str:
    """对已收藏老师扫描主页变化 + 可选 arXiv 新论文，返回情报简报"""
    try:
        r = mon.scan(name)
    except Exception as e:
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"监测失败：{e}", "traceback": tb}, ensure_ascii=False)
    return json.dumps(r, ensure_ascii=False)


def tool_monitor_show() -> str:
    """查看监测历史简报"""
    try:
        return mon.show()
    except Exception as e:
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"读取监测历史失败：{e}", "traceback": tb}, ensure_ascii=False)


# ============ 工具二：论文链路 ============

def _find_lab_url(name_cn: str) -> str:
    """从深潜报告/卡片里找该老师的实验室或主页 URL（供论文三源检索自动带上网址）"""
    if not name_cn:
        return ""
    rp = DATA_DIR / "deepdive" / f"{name_cn}_report.json"
    if rp.exists():
        try:
            srcs = json.loads(rp.read_text(encoding="utf-8")).get("sources") or []
            for u in srcs:   # 优先实验室/个人主页，而非学校详情页
                if any(k in u.lower() for k in ("lab", "github.io", "group", "home")):
                    return u
            if srcs:
                return srcs[0]
        except Exception:
            pass
    for f in sorted(DATA_DIR.glob("cards_*.json")):
        try:
            for c in json.loads(f.read_text(encoding="utf-8")).get("cards", []):
                if c.get("name") == name_cn:
                    for h in (c.get("homepage_candidates") or []):
                        u = h.get("url") if isinstance(h, dict) else h
                        if u:
                            return u
        except Exception:
            continue
    return ""


def tool_search_papers(author_en: str, affiliation: str = "",
                       name_cn: str = "", lab_url: str = "") -> str:
    """三源并列检索论文，跨源去重合并：
    ① arXiv（CS/物理/数学）② Europe PMC（生物医学期刊）③ 实验室官网 Publications（PI 自维护）。
    资源越多越好：任一源命中即收录，多源命中互相印证。"""
    result = {}
    arxiv_raw, epmc_raw, lab_raw = [], [], []

    # 源1：arXiv
    try:
        arxiv_raw = search_papers(author_en)
        # arXiv 结果另存，供 paper_decision/deep_dive 按序号取用
        (PAPERS_DIR / f"search_{author_en.replace(' ', '_')}.json").write_text(
            json.dumps(arxiv_raw, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        result["arXiv_错误"] = str(e)

    # 源2：Europe PMC（生物医学）
    try:
        epmc_raw = search_europepmc(author_en, affiliation)
    except Exception as e:
        result["EuropePMC_错误"] = str(e)

    # 源3：实验室官网 Publications（未给 URL 时，从卡片/深潜报告自动发现）
    if not lab_url and name_cn:
        lab_url = _find_lab_url(name_cn)
    if lab_url:
        try:
            lab_raw = fetch_lab_publications(lab_url)
            if lab_raw and lab_raw[0].get("error"):
                result["实验室官网_错误"] = lab_raw[0]["error"]
                lab_raw = []
        except Exception as e:
            result["实验室官网_错误"] = str(e)

    # 跨源合并去重
    merged = merge_paper_sources(arxiv_raw, epmc_raw, lab_raw)
    merged.sort(key=lambda p: str(p.get("published") or p.get("year") or ""), reverse=True)

    result["统计"] = {
        "arXiv": len(arxiv_raw), "EuropePMC": len(epmc_raw),
        "实验室官网": len(lab_raw), "合并去重后": len(merged),
        "实验室网址": lab_url or "（未提供/未找到）",
    }
    result["论文列表"] = [
        {"标题": p.get("title"),
         "年份": p.get("published") or p.get("year") or "",
         "期刊": p.get("journal") or p.get("venue") or "",
         "来源": p.get("sources"),
         "末位作者": p.get("is_last_author", False),
         "作者位置": p.get("author_position", ""),
         "arxiv_id": p.get("arxiv_id", ""),   # 有则可下载精读
         "链接": p.get("url", "")}
        for p in merged
    ]
    result["提示"] = ("'来源'列显示该论文命中哪些渠道，多源命中=互相印证可信度更高；"
                      "只有带 arxiv_id 的能用 paper_decision/deep_dive 精读，"
                      "官网/PMC 论文列出标题期刊年份供参考；"
                      "若全部结果的研究方向都与该老师实际方向不符，说明是同名学者，请如实告知用户")
    return json.dumps(result, ensure_ascii=False)


def tool_lab_publications(lab_url: str) -> str:
    """从实验室官网 Publications 页提取论文列表（arXiv/Europe PMC 都查不到时的兜底）"""
    try:
        papers = fetch_lab_publications(lab_url)
    except Exception as e:
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"提取失败：{e}", "traceback": tb}, ensure_ascii=False)
    if papers and papers[0].get("error"):
        return json.dumps(papers[0], ensure_ascii=False)
    return json.dumps({"来源": "实验室官网 Publications 页（PI 自己维护，最权威）",
                       "论文数": len(papers), "papers": papers}, ensure_ascii=False)


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
    """M5：对照论文批改用户思考"""
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
    """M2：抓取老师个人主页等信源，产出带逐字证据的深潜报告"""
    try:
        result = ad.run_deepdive(CLIENT, name, site, url)
    except Exception as e:
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"深潜失败：{e}", "traceback": tb}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


# ============ 工具五：M4 进组路径分析 ============

def tool_path_analysis(name: str) -> str:
    """M4：进组路径分析——基于深潜报告+用户画像，产出需求侧/供给侧/敲门砖方案"""
    try:
        result = pa.run_path_analysis(CLIENT, P["fast"], name)
    except Exception as e:
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"路径分析失败：{e}", "traceback": tb}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


# ============ 工具六：M1.5 对比视图 ============

def tool_panorama() -> str:
    """档一：全景表——列出所有已收录老师的精简信息"""
    try:
        result = ca.panorama()
    except Exception as e:
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"全景表生成失败：{e}", "traceback": tb}, ensure_ascii=False)
    return result


def tool_deep_compare(names) -> str:
    """档二：深度对比——选2-5位老师，读卡片+深潜报告，调LLM打七项指标分"""
    # names 可能从 function calling 传来 list 或字符串
    if isinstance(names, str):
        names = [n.strip() for n in names.split(",") if n.strip()]
    try:
        result = ca.deep_compare(CLIENT, P["fast"], names)
    except Exception as e:
        tb = traceback.format_exc()[-500:]
        return json.dumps({"error": f"深度对比失败：{e}", "traceback": tb}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


# ============ 工具注册与派发 ============

TOOLS = [
    {"type": "function", "function": {
        "name": "list_sites", "description": "列出已收录的所有学院/站点及人数",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "list_teachers",
        "description": "列出某站点的老师，可按研究方向关键词、招生信号筛选",
        "parameters": {"type": "object", "properties": {
            "site": {"type": "string", "description": "站点代号，如 collegeai / life"},
            "keyword": {"type": "string", "description": "研究方向关键词，可省略", "default": ""},
            "level": {"type": "string", "description": "招生信号，可省略", "default": ""}},
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
        "description": "收录一个新学校的师资名单页（通过 fetch_url 自主导航找到师资页网址后调用）",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "师资名单页的完整网址"},
            "site_name": {"type": "string", "description": "给站点起个英文代号"}},
            "required": ["url", "site_name"]}}},
    {"type": "function", "function": {
        "name": "fetch_url",
        "description": "抓取网页，返回清洗后的正文和可点击链接列表。用于自主导航：从学校主页沿'院系/机构/师资队伍'链接逐层找到目标学院的师资名单页，也可用于查看老师个人主页内容。多次调用即可像浏览器一样逐层深入",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "完整网址"}},
            "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "bookmark_advisor",
        "description": "收藏/更新目标老师到长期档案（用户说收藏某老师、想盯某老师、或汇报接触进展如已发邮件/已回复时调用）",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "老师中文名"},
            "status": {"type": "string", "description": "接触进度：收藏/已读论文/已发邮件/已回复，默认收藏"},
            "note": {"type": "string", "description": "备注，可省略", "default": ""}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "list_targets",
        "description": "查看目标老师清单（用户问'我收藏了哪些老师/目标清单/盯哪些组'时调用）",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "monitor",
        "description": "M6实时情报监测：扫描已收藏老师的主页是否有新增内容、arXiv是否有新论文，输出情报简报；可只扫某人（传 name）",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "老师中文名，可省略；省略则扫全部收藏老师", "default": ""}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "monitor_show",
        "description": "查看 M6 监测的历史简报（过去几轮扫描结果）",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "search_papers",
        "description": "查某老师近期发表的论文——三源并列检索并跨源去重：arXiv（CS/物理/数学）+ Europe PMC（生物医学期刊如 Cell/Nature）+ 实验室官网 Publications（PI 自维护）。中文名转拼音填入；建议同时传 affiliation（机构，过滤同名学者）和 name_cn（中文名，用于自动发现实验室网址）；也可直接传 lab_url 指定实验室网站。任一源命中即返回，多源命中互相印证",
        "parameters": {"type": "object", "properties": {
            "author_en": {"type": "string", "description": "作者英文名，如 Yinpeng Dong / Xiaohua Shen"},
            "affiliation": {"type": "string", "description": "机构英文名（如 Tsinghua），过滤同名学者，建议填", "default": ""},
            "name_cn": {"type": "string", "description": "老师中文名（如 沈晓骅），用于自动查找其实验室网址以检索官网论文", "default": ""},
            "lab_url": {"type": "string", "description": "实验室网站 URL，直接指定则跳过自动查找", "default": ""}},
            "required": ["author_en"]}}},
    {"type": "function", "function": {
        "name": "lab_publications",
        "description": "单独提取某个实验室官网 Publications 页的完整论文列表（PI 自己维护）。适用：想看某实验室全部成果、或该老师论文不在学术数据库时。注：search_papers 已并列包含此源；此工具用于单独查看官网完整列表",
        "parameters": {"type": "object", "properties": {
            "lab_url": {"type": "string", "description": "实验室网站 URL（如 https://www.xshenlab.com）；会自动定位其中的 Publications/论文 页面"}},
            "required": ["lab_url"]}}},
    {"type": "function", "function": {
        "name": "paper_decision",
        "description": "对某篇论文出阅读决策卡：定位/匹配度/建议/前置缺口。用户选定一篇论文后先调这个",
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
        "description": "M5思考批改：用户读完一篇已精读过的论文后提交了自己写的思考文字时调用。做事实纠错/偏题检测/费曼追问/凝练段落。thinking 必须原样传入用户写的思考全文，禁止改写删减",
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
        "description": "M2导师深潜：用户想深入了解某位已收录老师时调用。抓取其个人主页/实验室页，产出带逐字证据的深潜报告",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "老师中文名，须已在卡片库中"},
            "site": {"type": "string", "description": "站点代号，可省略，省略时全库搜索", "default": ""},
            "url": {"type": "string", "description": "手动指定的个人主页网址，可省略", "default": ""}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "path_analysis",
        "description": "M4进组路径分析：用户想为某位老师制定进组计划（怎么进组/该做什么项目/帮我规划进组）时调用。需该老师已有M2深潜报告，否则提示先深潜。输出老师缺什么人/用户技能三档清单/带设备标注的敲门砖项目",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "老师中文名，须已有深潜报告"}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "panorama",
        "description": "M1.5全景表：用户想看所有已收录老师的总览/全览/有哪些老师/一览表时调用。无需参数，返回所有老师的精简列表（姓名/职称/方向/招生信号/有无深潜报告）",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "deep_compare",
        "description": "M1.5深度对比：用户想对比/比较几位老师时调用。传入2-5位老师中文名列表，读取卡片+深潜报告打七项指标分（方向匹配/招生信号/计算相关度/信息透明度/进组可行性/组内活跃度/竞争门槛），输出打分矩阵+推荐建议",
        "parameters": {"type": "object", "properties": {
            "names": {"type": "array", "items": {"type": "string"},
                       "description": "2-5位老师中文名列表"}},
            "required": ["names"]}}},
]

DISPATCH = {"list_sites": tool_list_sites, "list_teachers": tool_list_teachers,
            "get_card": tool_get_card, "add_school": tool_add_school,
            "fetch_url": tool_fetch_url,
            "bookmark_advisor": tool_bookmark_advisor,
            "list_targets": tool_list_targets,
            "monitor": tool_monitor,
            "monitor_show": tool_monitor_show,
            "search_papers": tool_search_papers, "paper_decision": tool_paper_decision,
            "lab_publications": tool_lab_publications,
            "deep_dive": tool_deep_dive,
            "critique_thinking": tool_critique_thinking,
            "appeal_grading": tool_appeal_grading,
            "advisor_deepdive": tool_advisor_deepdive,
            "path_analysis": tool_path_analysis,
            "panorama": tool_panorama,
            "deep_compare": tool_deep_compare}

SYSTEM = """你是导师情报与论文伴读助手，服务对象是一名想找实验室的计算机大三学生。

铁律：
1. 你只能通过调用工具获取信息，禁止凭自己的知识回答任何关于具体老师或论文的事实；
2. 工具返回什么就说什么，查不到就如实说"未收录/无数据"；如果工具返回了 traceback 字段，请截取最后几行关键报错（包含文件名和行号）告诉用户，不要只说"内部错误"；
3. 展示老师信息时保留招生信号标记和 evidence 原文引用；
4. M1收录流程：用户问到未收录的学校/学院时，不要直接要网址——先调 fetch_url 自主导航：从学校主页（知名高校域名你通常知道，如清华大学 https://www.tsinghua.edu.cn）出发，沿"院系设置/机构设置/师资队伍/教师名单/教职工"等链接逐层找与用户兴趣相关的学院（计算机/人工智能/交叉信息等优先）；找到师资名单页调 add_school(url, 站点代号)；add_school 内部会**自动跑 enrich_faculty 和 batch_cards 生成卡片**，跑完后 list_sites/list_teachers 就能直接查到该站点，不要再让用户去终端敲命令；一个学院有分页师资页时（第2页/第3页...），把每个分页都调一次 add_school 用**同一站点代号**合并，add_school 会按姓名去重累加；导航失败（页面打不开/找不到入口）再请用户提供师资页网址，不要瞎猜编造 URL；收录后若用户继续问该学院老师，直接用 list_teachers/get_card。
5. 论文流程：用户给中文老师名 -> 转成拼音调 search_papers（一次调用即三源并列检索：arXiv + Europe PMC + 实验室官网Publications，自动去重合并；务必传 affiliation 过滤同名，传 name_cn 以自动查找实验室网址）-> 展示合并后的论文列表（'来源'列标明命中渠道，多源命中可信度更高；重点推荐末位作者的论文，那是他主导的）+ 统计信息（各源命中数）-> **若全部结果的研究方向都与该老师实际方向不符，说明是重名学者，必须如实告知"未检索到本人论文"，绝不可把同名者的论文当成他的** -> 带 arxiv_id 的可用 paper_decision 出决策卡并精读；官网/PMC 论文列出标题/期刊/年份供参考（无法下载精读）-> 用户明确说精读/拆解才调 deep_dive；
6. deep_dive 返回的 analysis 要完整展示给用户，逐段呈现并保留原文引用；verification_warnings 非空时要如实告知哪些引句未通过校验；
7. M5批改流程：用户对已精读的论文提交思考后，原样传入 critique_thinking（禁止替用户改写思考）；返回结果分四块呈现——fact_errors 逐条列出并保留 quote 原文引用与 correction；verification_warnings 非空时如实告知可申诉；depth.probes 以提问形式抛给用户；condensed 作为凝练段落完整展示；用户对批改不认可时调 appeal_grading，不要自行辩护；
8. M2深潜流程：用户说深挖/深入了解某位老师时调 advisor_deepdive（name 传老师中文名）；返回的 report 按五个维度分块展示并保留每条 evidence 与来源编号；verification_warnings 非空时如实告知；fit_questions 以提问清单形式呈现给用户；如果返回 error 说没有外链，请用户提供该老师个人主页网址后带 url 参数重试；
9. M4路径分析流程：用户说怎么进某老师的组/该做什么项目/帮我规划进组时调 path_analysis（name 传老师中文名）；返回的 path 中 demand 每条保留 evidence 原句，supply 三档分列展示，actions 逐个展示并标注设备A/B；如果返回 error 说没有深潜报告，引导用户先做深潜；
10. M1.5对比视图流程：用户说全览/有哪些老师/一览时调 panorama（无参数），结果展示为表格（姓名/职称/方向/招生信号/有无深潜）；用户说对比/比较几位老师时调 deep_compare（names 传中文名列表，2-5人），结果展示为七项打分矩阵表格 + 总结建议；无深潜报告的老师如实标注；用户只选了1人时提示至少选2人才能对比；
11. 长期档案流程：用户说收藏某老师/想盯某老师时调 bookmark_advisor；用户汇报接触进展（读完论文了/发邮件了/老师回复了）时调 bookmark_advisor 更新 status（已读论文/已发邮件/已回复）；用户问收藏清单时调 list_targets；
12. M6监测流程：用户说看看收藏的老师有什么新动态/情报/监测下他们时调 monitor（无参数扫全部，或传名字扫某人）；返回的 per_teacher 里 changes（主页新增内容）、arxiv（新论文）、github（GitHub 新仓库/活跃）分老师展示，[首次监测]说明该老师刚建立基线下次才有变化对比；"未监测"提示可深潜补主页URL以便开始监测；若要监测 arXiv/GitHub，需在收藏档案里为该老师填 author_en+keywords / github（让用户确认归属）；
12. 回答用简洁中文，列表用表格。"""


def main():
    messages = [{"role": "system", "content": SYSTEM}]
    print("导师情报 Agent（论文拆解 + 思考批改 + 导师深潜 + 进组路径分析 + 对比视图）已启动，输入 quit 退出")
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
