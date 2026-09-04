"""
长期知识档案维护（设计文档第6节轻量落地）
- 已读论文库 archive/read_papers.json：M5 批改后自动入库（凝练段落=申请素材库），可 rebuild 全量重建
- 目标老师清单 archive/target_advisors.json：收藏/接触进度（后续 M6 监测的触发依据）
用法：
  python tools/knowledge_store.py rebuild                     # 从所有批改产物重建已读论文库
  python tools/knowledge_store.py show                        # 查看两个档案
  python tools/knowledge_store.py bookmark 俞立 --note 备注    # 收藏/更新目标老师
"""
import json
import sys
import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PAPERS_DIR = BASE_DIR / "data" / "papers"
ARCHIVE_DIR = BASE_DIR / "archive"
READ_PAPERS_FILE = ARCHIVE_DIR / "read_papers.json"
TARGETS_FILE = ARCHIVE_DIR / "target_advisors.json"


def _load(path: Path, default: dict) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _save(path: Path, db: dict) -> None:
    path.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")


# ============ 已读论文库 ============

def update_read_papers(arxiv_id: str) -> dict:
    """把某篇论文的 M5 批改结果入库（凝练段落沉淀为申请素材）"""
    grading_file = PAPERS_DIR / f"{arxiv_id.replace('/', '_')}_grading.json"
    if not grading_file.exists():
        return {"error": f"找不到 {arxiv_id} 的批改结果，精读并批改后才会入库"}
    g = json.loads(grading_file.read_text(encoding="utf-8"))
    entry = {
        "arxiv_id": g.get("arxiv_id", arxiv_id),
        "date": g.get("date", ""),
        "condensed": g.get("condensed", ""),
        "n_fact_errors": len(g.get("fact_errors") or []),
        "error_types": sorted({fe.get("error_type", "") for fe in g.get("fact_errors", [])
                               if fe.get("error_type")}),
    }
    db = _load(READ_PAPERS_FILE, {"papers": []})
    db["papers"] = [p for p in db.get("papers", []) if p.get("arxiv_id") != entry["arxiv_id"]]
    db["papers"].append(entry)
    db["updated"] = datetime.date.today().isoformat()
    _save(READ_PAPERS_FILE, db)
    return {"added": entry["arxiv_id"], "total": len(db["papers"])}


def rebuild() -> dict:
    """扫描 data/papers 下全部批改产物，重建已读论文库"""
    rebuilt = []
    for f in sorted(PAPERS_DIR.glob("*_grading.json")):
        r = update_read_papers(f.name.replace("_grading.json", ""))
        if "added" in r:
            rebuilt.append(r["added"])
    return {"rebuilt": rebuilt, "count": len(rebuilt)}


def show_read_papers() -> str:
    db = _load(READ_PAPERS_FILE, {"papers": []})
    return json.dumps(db.get("papers", []), ensure_ascii=False)


# ============ 目标老师清单 ============

def bookmark(name: str, site: str = "", status: str = "收藏", note: str = "") -> dict:
    """收藏或更新目标老师（同名即更新；status 记录接触进度：收藏/已读论文/已发邮件/已回复）"""
    db = _load(TARGETS_FILE, {"targets": []})
    ts = db.setdefault("targets", [])
    today = datetime.date.today().isoformat()
    for t in ts:
        if t.get("name") == name:
            if status:
                t["status"] = status
            if note:
                t["note"] = note
            if site:
                t["site"] = site
            t["updated"] = today
            _save(TARGETS_FILE, db)
            return {"updated": t}
    ts.append({"name": name, "site": site, "status": status, "note": note,
               "added": today})
    _save(TARGETS_FILE, db)
    return {"added": ts[-1], "total": len(ts)}


def list_targets() -> str:
    db = _load(TARGETS_FILE, {"targets": []})
    return json.dumps(db.get("targets", []), ensure_ascii=False)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "rebuild":
        print(json.dumps(rebuild(), ensure_ascii=False, indent=2))
    elif cmd == "show":
        print("=== 已读论文库 ===")
        print(show_read_papers())
        print("=== 目标老师清单 ===")
        print(list_targets())
    elif cmd == "bookmark":
        name = sys.argv[2]
        note = sys.argv[sys.argv.index("--note") + 1] if "--note" in sys.argv else ""
        status = sys.argv[sys.argv.index("--status") + 1] if "--status" in sys.argv else "收藏"
        print(json.dumps(bookmark(name, status=status, note=note), ensure_ascii=False, indent=2))
    else:
        print(f"未知命令：{cmd}")
        sys.exit(1)
