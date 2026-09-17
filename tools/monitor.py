"""
M6：实时情报监测
对已收藏老师（archive/target_advisors.json）做主页快照差异监测 + 可选 arXiv 新论文检测，
输出情报简报（存档 history）。

设计（对准设计审计文档 M6，砍掉机会看板，仅保留监测）：
- 监测源：老师深潜报告 sources 里的主页 URL（无深潜报告或 no 主页则标注"无监测源"）。
- 主页快照：抓取正文 → 清洗（去 script/style/导航噪音）→ 与上次快照对比找出实质性变化行，
  忽略时间戳/页码/纯链接等噪音；首次建立基线不报变化。
- arXiv：若该老师在 target_advisors 里填了 author_en，则用 paper_tools 检索并对比"已见论文 id"，
  报告新增。未填 author_en 的老师跳过 arXiv 检测。
- GitHub：若该老师在 target_advisors 里填了 github（GitHub 用户名，如 tsinghua-mars-lab），
  则拉取该账号最近 push 的仓库，报告新增仓库/活跃度。未填 github 的老师跳过。
  归属需人工确认——同名账号很常见，务必填该老师真实的 GitHub 账号（从主页/论文脚注核对）。

要启用某位老师的主页/arXiv/GitHub 监测，在 archive/target_advisors.json 的该老师条目加：
  "urls": [...可选覆盖监测来源...]  （默认取深潜报告 sources）
  "author_en": "英文名拼音，如 John Smith",
  "keywords": ["研究主题词1", "主题词2"],   （用于 arXiv 归属过滤）
  "github": "GitHub用户名"
- 输出：情报简报（按老师分组的 change list），存档到 data/monitor/{name}_briefing.json 与快照。

用法：
  python tools/monitor.py scan              # 扫描全部收藏老师
                      scan --name 张三      # 只扫某人
                      show                   # 看历史简报
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

from fetch_common import get, strip_html
from store import load_deepdive_report

BASE_DIR = Path(__file__).resolve().parent.parent
ARCHIVE = BASE_DIR / "archive"
TARGETS_FILE = ARCHIVE / "target_advisors.json"
MONITOR_DIR = BASE_DIR / "data" / "monitor"
MONITOR_DIR.mkdir(parents=True, exist_ok=True)

# 简报条目的前缀标记：生产者与消费者必须共用同一常量。
# （此前 monitor 写"新仓库/新动态"、monitor 与 monitor_daily 却判断"新仓库/新推送"，
#   导致 GitHub 更新永远不计入简报统计。）
SRC_NEW_PREFIX = "[有新增内容]"
GH_NEW_PREFIX = "新仓库/新动态"

# 噪音行判定：时间戳、版权、计数器、纯空格/标点/链接
NOISE_RE = re.compile(
    r"^(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|(?:第|共)?\d+(?:页|条)?|"
    r"更新时间[：:]?[\s\S]*|Copyright.*|©.*|Powered by.*)$",
    re.I)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _fetch_text(url: str) -> str:
    return strip_html(get(url, timeout=20).text)


def _semantic_diff(old: str, new: str) -> list:
    """找 new 里新增的实质性内容行（相对 old 而言），剔除噪声。"""
    old_lines = {_flat(l) for l in old.split("\n") if l.strip()}
    additions = []
    for line in new.split("\n"):
        line = _flat(line)
        if not line or line in old_lines:
            continue
        if len(line) < 8:          # 太短忽略（可能是菜单/碎片）
            continue
        if NOISE_RE.match(line):
            continue
        additions.append(line)
    # 去重并限长
    seen, out = set(), []
    for a in additions:
        if a[:60] not in seen:
            seen.add(a[:60])
            out.append(a[:200])
        if len(out) >= 20:
            break
    return out


def _github_trail(github_id: str) -> dict:
    """GitHub 轨迹：拉该账号最近 push 的仓库，返回 {"repos": [(repo, pushed_at, html_url)]}，最多8个。"""
    r = get(f"https://api.github.com/users/{github_id}/repos",
            params={"sort": "pushed", "per_page": 8, "type": "owner"},
            headers={"Accept": "application/vnd.github+json", "User-Agent": "advisor-agent"},
            timeout=15)
    out = []
    for repo in r.json():
        out.append({
            "repo": repo.get("full_name", ""),
            "pushed_at": (repo.get("pushed_at") or "")[:10],
            "url": repo.get("html_url", ""),
            "desc": (repo.get("description") or "")[:80],
        })
    return {"repos": out}


def _nice_name(name: str) -> str:
    return str(name).replace("/", "_").replace("\\", "_")


def _monitor_sources(name: str) -> list:
    """从深潜报告的 sources 里取监测 URL（优先个人主页 cs）。"""
    rep = load_deepdive_report(name) or {}
    return rep.get("sources", [])


def _load_targets() -> list:
    if not TARGETS_FILE.exists():
        return []
    return json.loads(TARGETS_FILE.read_text(encoding="utf-8")).get("targets", [])


def count_new(entry: dict) -> tuple:
    """单个老师的新增计数：(主页源新增, 新论文, 新仓库)。判定依据与生产者共用前缀常量。"""
    n_src = sum(1 for c in entry.get("changes") or [] if str(c).startswith(SRC_NEW_PREFIX))
    n_arxiv = sum(1 for a in entry.get("arxiv") or [] if isinstance(a, dict))
    n_gh = sum(1 for g in entry.get("github") or [] if str(g).startswith(GH_NEW_PREFIX))
    return n_src, n_arxiv, n_gh


def has_real_changes(briefing: dict) -> tuple:
    """简报里是否存在真实新增：(新增总数, 有新增的老师数)。

    供 scan 的 summary 与 monitor_daily 的"今日是否有变化"共用，避免同一判定写两份而漂移。
    """
    total = teachers = 0
    for t in briefing.get("per_teacher") or []:
        n = sum(count_new(t))
        if n:
            total += n
            teachers += 1
    return total, teachers


def scan(name: str = "") -> dict:
    """扫描收藏老师，返回情报简报（含变化与建议）。"""

    targets = _load_targets()
    if name:
        targets = [t for t in targets if t.get("name") == name]
    if not targets:
        return {"error": "目标老师清单为空，请先收藏某位老师（bookmark_advisor）"}

    today = datetime.date.today().isoformat()
    briefings = {"date": today, "per_teacher": [], "summary": []}

    for t in targets:
        tname = t.get("name")
        author_en = t.get("author_en", "")      # 可填空，默认不做 arXiv 检测
        github_id = t.get("github", "")          # 可填空，默认不做 GitHub 检测
        urls = _monitor_sources(tname)
        entry = {"name": tname, "urls": urls, "changes": [], "arxiv": [], "github": [], "note": ""}
        if not urls:
            entry["note"] = "无深潜报告主页源，跳过页面监测（可在深潜时指定主页URL）"

        # 1) 主页快照 diff
        for i, url in enumerate(urls, 1):
            snap = MONITOR_DIR / f"{_nice_name(tname)}_src{i}.snap.txt"
            try:
                text = _flat(_fetch_text(url))
            except Exception as e:
                entry["changes"].append(f"[抓取失败] {url}：{e}")
                continue
            if not snap.exists():
                snap.write_text(text, encoding="utf-8")
                entry["changes"].append(f"[首次监测] {url} 已建立基线（后续开始跟踪变化）")
            else:
                old = snap.read_text(encoding="utf-8")
                if _flat(old) == text:
                    entry["changes"].append(f"[无变化] {url}")
                else:
                    snap.write_text(text, encoding="utf-8")
                    adds = _semantic_diff(old, text)
                    if adds:
                        entry["changes"].append(f"{SRC_NEW_PREFIX} {url}")
                        entry["changes"].extend(f"  · {a}" for a in adds)
                    else:
                        entry["changes"].append(f"[变化] {url}（仅剩格式/时间戳，无实质）")

        # 2) arXiv 新论文（可选，且做过归属过滤，避免同名作者误导）
        if author_en:
            try:
                from paper_tools import search_papers
                papers = search_papers(author_en, max_results=10)
                kws = t.get("keywords") or []
                # 过滤：标题命中至少一个研究关键词才算疑似归属；无关键词则不采用
                # （arXiv 检索同名作者极常见，直接在标题层面粗筛，宁少勿滥）
                def _match(p):
                    tt = (p.get("title") or "").lower()
                    return any(k.lower() in tt for k in kws) if kws else False
                kept = [p for p in papers if _match(p)]
                seen_file = MONITOR_DIR / f"{_nice_name(tname)}_arxiv_seen.json"
                seen = set()
                if seen_file.exists():
                    seen = set(json.loads(seen_file.read_text(encoding="utf-8")))
                new_ids = [p["arxiv_id"] for p in kept if p["arxiv_id"] not in seen]
                if new_ids:
                    entry["arxiv"] = [
                        {"id": p["arxiv_id"], "title": p["title"],
                         "published": p.get("published", "")}
                        for p in kept if p["arxiv_id"] in new_ids]
                elif kept:
                    entry["arxiv"] = [f"无新增（已见 {len(kept)} 篇本主题论文）"]
                elif kws:
                    entry["arxiv"] = [f"近期未检索到符合 {tname} 主题的 arXiv 新论文（关键词：{', '.join(kws[:3])}）"]
                seen.update(p["arxiv_id"] for p in kept)
                seen_file.write_text(json.dumps(sorted(seen), ensure_ascii=False),
                                     encoding="utf-8")
            except Exception as e:
                entry["arxiv"].append(str(e))

        # 3) GitHub 轨迹（可选）
        if github_id:
            try:
                g = _github_trail(github_id)
                seen_file = MONITOR_DIR / f"{_nice_name(tname)}_github_seen.json"
                seen = {}
                if seen_file.exists():
                    seen = json.loads(seen_file.read_text(encoding="utf-8"))
                new_repos = [r for r in g["repos"] if r["repo"] not in seen]
                # 记录本次全部仓库 + 最近 push 时间供下次对比
                seen = {r["repo"]: r["pushed_at"] for r in g["repos"]}
                seen_file.write_text(json.dumps(seen, ensure_ascii=False),
                                     encoding="utf-8")
                if new_repos:
                    entry["github"] = [
                        f"{GH_NEW_PREFIX}: {r['repo']}（最近更新 {r['pushed_at']}）{r['desc']}"
                        for r in new_repos]
                elif g["repos"]:
                    entry["github"] = [f"{len(g['repos'])} 个仓库，最近无新增（最新：{g['repos'][0]['pushed_at']} {g['repos'][0]['repo']}）"]
                else:
                    entry["github"] = ["GitHub 无仓库"]
            except Exception as e:
                entry["github"].append(f"[GitHub 抓取失败] {e}")

        briefings["per_teacher"].append(entry)
        n_new_src, n_new_arxiv, n_new_gh = count_new(entry)
        if n_new_src or n_new_arxiv or n_new_gh:
            briefings["summary"].append(
                f"{tname}：{n_new_src} 个主页源有新增 / {n_new_arxiv} 篇新论文 / {n_new_gh} 个仓库有更新")

    # 存历史
    hist = MONITOR_DIR / "history.json"
    hist_list = []
    if hist.exists():
        hist_list = json.loads(hist.read_text(encoding="utf-8"))
    hist_list.append(briefings)
    hist.write_text(json.dumps(hist_list[-30:], ensure_ascii=False, indent=2),
                    encoding="utf-8")

    return briefings


def show() -> str:
    hist = MONITOR_DIR / "history.json"
    if not hist.exists():
        return "无历史简报"
    return json.dumps(json.loads(hist.read_text(encoding="utf-8")),
                      ensure_ascii=False, indent=2)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    if sys.argv[1] == "scan":
        n = sys.argv[2] if len(sys.argv) > 2 else ""
        print(json.dumps(scan(n), ensure_ascii=False, indent=2))
    elif sys.argv[1] == "show":
        print(show())
    else:
        print(f"未知命令 {sys.argv[1]}")
        sys.exit(1)