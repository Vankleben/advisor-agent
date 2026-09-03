"""
工具四：批量卡片生成器 v2.1
输入：data/faculty_{site}_enriched.json
输出：data/cards_{site}.json
用法：python tools/batch_cards.py collegeai
      python tools/batch_cards.py life
"""
import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
sys.path.insert(0, str(BASE_DIR / "tools"))
from llm_card import build_card, verify_evidence


def main():
    site = sys.argv[1] if len(sys.argv) > 1 else "collegeai"
    in_file = DATA_DIR / f"faculty_{site}_enriched.json"
    out_file = DATA_DIR / f"cards_{site}.json"

    if not in_file.exists():
        print(f"找不到 {in_file}，请先运行 enrich_faculty.py {site}")
        return

    with open(in_file, encoding="utf-8") as f:
        teachers = json.load(f)["teachers"]

    cards = []
    done = set()
    if out_file.exists():
        with open(out_file, encoding="utf-8") as f:
            cards = json.load(f)["cards"]
            done = {c["name"] for c in cards}
        print(f"续传：已有 {len(done)} 张卡片，跳过")

    total = len(teachers)
    for i, t in enumerate(teachers):
        if t["name"] in done:
            continue

        card = build_card(t)
        card["_verification"] = ([] if card.get("skipped")
                                 else verify_evidence(card, t))
        cards.append(card)

        with open(out_file, "w", encoding="utf-8") as f:
            json.dump({"count": len(cards), "cards": cards},
                      f, ensure_ascii=False, indent=2)

        if (i + 1) % 10 == 0:
            print(f"进度 {i + 1}/{total}，已生成 {len(cards)} 张卡片")
        time.sleep(0.3)

    levels = {"🟢": 0, "🟡": 0, "⚪": 0}
    warn_n = skip_n = 0
    for c in cards:
        if c.get("skipped"):
            skip_n += 1
            continue
        lv = (c.get("recruitment") or {}).get("level")
        if lv in levels:
            levels[lv] += 1
        warn_n += len(c.get("_verification") or [])

    print(f"\n完成：{len(cards)} 张卡片（{skip_n} 张因无数据跳过 LLM）")
    print(f"招生信号分布：🟢 {levels['🟢']} / 🟡 {levels['🟡']} / ⚪ {levels['⚪']}")
    print(f"反幻觉校验警告共 {warn_n} 条")


if __name__ == "__main__":
    main()