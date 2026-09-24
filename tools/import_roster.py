"""
把"官网名单页实抓"的教师名册转成标准卡片，供筛选器/深潜等工具统一使用。

与 batch_cards 的区别：**不调 LLM**，所有字段逐字取自名册，因此不存在"LLM 编造、
再回头验证引句"的环节——名册本身就是证据。代价是卡片比 LLM 版薄（没有 summary 提炼、
没有招募等级判定），适合那些"名单页一次给全 姓名/职称/研究方向/邮箱"的学院站点。

用法：
    python tools/import_roster.py slst data/roster_slst.json --dept "某某大学生命科学与技术学院"
    python tools/import_roster.py sustech data/roster_sustech.json --dept "某某大学生命科学学院"

名册 JSON 格式（列表，字段缺省用空串/None 均可）：
    [{"name": "张三", "title": "助理教授", "field": "超分辨成像；深度学习",
      "url": "https://...", "email": "zhangsan@x.edu.cn", "dept": "生物系", "join": false}, ...]
其中 field/研究方向 会用 ；、; 拆成 research_interests；url 进 homepage_candidates。
"""
import argparse
import json
import re
import sys
from pathlib import Path

# --- Windows 控制台编码修复：GBK 下 print emoji 会崩溃，强制 stdout/stderr 为 UTF-8 ---
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# 职称 → 学术阶段。"特聘研究员"在新型研究机构里常是青年 PI 序列，故归"青年"。
JUNIOR_WORDS = ("助理教授", "副教授", "助理研究员", "副研究员", "研究副教授",
                "特聘研究员", "青年", "讲师")
SENIOR_WORDS = ("讲席教授", "教授", "研究员", "院士", "院长", "主任")


def infer_stage(title: str) -> str:
    t = title or ""
    if any(w in t for w in JUNIOR_WORDS):
        return "青年"
    if any(w in t for w in SENIOR_WORDS):
        return "资深"
    return "未知"


def split_field(field: str) -> list:
    parts = re.split(r"[；;、|/]", field or "")
    return [p.strip() for p in parts if p.strip()]


def card_from(row: dict, dept: str, source_note: str) -> dict:
    name = (row.get("name") or "").strip()
    title = (row.get("title") or "").strip()
    field = (row.get("field") or "").strip()
    row_dept = (row.get("dept") or "").strip()
    org = "·".join(x for x in (dept, row_dept) if x)
    rec_note = (f"本次为官网名单页实抓（{source_note}），未逐页核实招生信息"
                + ("；名单页该条目挂了 JOIN US 招募链接" if row.get("join") else ""))
    return {
        "name": name,
        "title": f"{org}{title}" if org else title,
        "research_interests": split_field(field),
        "current_focus": {"text": field, "evidence": [field] if field else []},
        "career_stage": {"stage": infer_stage(title),
                         "evidence": [title] if title else [],
                         "note": "阶段由职称字符串推断"},
        "recruitment": {"level": "⚪", "evidence": None, "note": rec_note},
        "homepage_candidates": [row["url"]] if row.get("url") else [],
        "email": row.get("email") or None,
        "summary": f"{name}是{org}{title}，研究方向：{field}。" if field else f"{name}是{org}{title}。",
        "_verification": [],
    }


def main():
    ap = argparse.ArgumentParser(description="官网名册 → 标准卡片（不调 LLM）")
    ap.add_argument("site", help="站点代号（如 slst / sustech）")
    ap.add_argument("roster", help="名册 JSON 路径")
    ap.add_argument("--dept", default="", help="院系全名，写进 title 与 summary")
    args = ap.parse_args()

    rows = json.loads(Path(args.roster).read_text(encoding="utf-8"))
    source_note = Path(args.roster).name
    cards, seen = [], set()
    for r in rows:
        name = (r.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        cards.append(card_from(r, args.dept, source_note))
    out = DATA_DIR / f"cards_{args.site}.json"
    out.write_text(json.dumps({"count": len(cards),
                               "note": f"由 tools/import_roster.py 从 {source_note} 导入，"
                                       f"字段逐字来自官网名单页，未调 LLM",
                               "cards": cards},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    with_email = sum(1 for c in cards if c["email"])
    with_field = sum(1 for c in cards if c["research_interests"])
    print(f"{args.site}: {len(cards)} 张卡片 -> {out}")
    print(f"  其中有研究方向 {with_field} 张，有邮箱 {with_email} 张")


if __name__ == "__main__":
    main()
