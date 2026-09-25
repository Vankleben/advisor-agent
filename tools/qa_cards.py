"""工具六：卡片数据质检（离线、只读、不调 LLM）

用法：python tools/qa_cards.py          # 检查 data/ 下全部站点
      python tools/qa_cards.py sjtu_life   # 只查一个站点

背景：2026-09 大采集曾出现"抓了个壳"的事故——上交 208 人的 detail_url
全指向同一个栏目页、上科大目录漏采（静态抓到 JS 空壳）。本工具把当时的
人工质检表固化下来，新克隆/新收录后跑一遍即可发现同类问题。

检查项与判定：
  FAIL（退出码 1）
    - 卡片存在重复姓名（同站内）
    - faculty 里 ≥50% 条目带 detail_url，但唯一率 <90%（典型：全指向列表页）
  WARN（仅提示，不改退出码）
    - 卡片数 < 名单人数（批量建卡可能中断过）
    - 研究方向非空率 <50%（可能只抓到了名单壳）
  INFO
    - 各站人数/卡片数/研究非空率/🟢 数、跨站同名（兼聘属正常）
"""

# --- Windows 控制台编码修复：GBK 下 print emoji 会崩溃，强制 stdout 为 UTF-8 ---
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import json
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ⚠️ 读取失败 {path.name}: {e}")
        return None


def check_site(site: str) -> tuple[list[str], list[str]]:
    """返回 (fails, warns)。"""
    fails, warns = [], []
    cards_f = DATA_DIR / f"cards_{site}.json"
    fac_f = DATA_DIR / f"faculty_{site}.json"

    cards = (_load(cards_f) or {}).get("cards") or []
    faculty = (_load(fac_f) or {}).get("teachers") or []

    if not cards:
        fails.append("没有任何卡片")
        return fails, warns

    # 1) 同站重名
    names = [(c.get("name") or "").strip() for c in cards]
    names = [n for n in names if n]
    dups = [n for n, k in Counter(names).items() if k > 1]
    if dups:
        fails.append(f"卡片重名 {len(dups)} 个：{dups[:5]}")

    # 2) 卡片数 vs 名单数
    if faculty and len(cards) < len(faculty):
        warns.append(f"卡片 {len(cards)} < 名单 {len(faculty)}（建卡可能中断过）")

    # 3) detail_url 唯一率（抓壳事故的核心指标）
    urls = [(t.get("detail_url") or "").strip() for t in faculty]
    urls = [u for u in urls if u]
    if faculty and len(urls) >= max(1, len(faculty) // 2):
        uniq = len(set(urls))
        ratio = uniq / len(urls)
        if ratio < 0.9:
            fails.append(f"detail_url 唯一率仅 {ratio:.0%}（{uniq}/{len(urls)}）——疑似全指向列表页")

    # 4) 研究方向非空率
    n_res = sum(1 for c in cards if c.get("research_interests"))
    rate = n_res / len(cards)
    if rate < 0.5:
        warns.append(f"研究方向非空率仅 {rate:.0%}（{n_res}/{len(cards)}）——可能只抓到名单壳")

    return fails, warns


def main() -> int:
    sites = sorted(p.stem.replace("cards_", "")
                   for p in DATA_DIR.glob("cards_*.json"))
    if len(_sys.argv) > 1:
        sites = [s for s in _sys.argv[1:] if s in sites] or sites
    if not sites:
        print("data/ 下没有卡片文件")
        return 1

    any_fail = False
    print(f"=== 卡片质检（{len(sites)} 个站点）===")
    print(f"{'站点':16s} {'卡片':>5} {'名单':>5} {'研究方向':>8} {'🟢':>3}  判定")
    all_names = {}
    for site in sites:
        cards = (_load(DATA_DIR / f"cards_{site}.json") or {}).get("cards") or []
        faculty = (_load(DATA_DIR / f"faculty_{site}.json") or {}).get("teachers") or []
        n_res = sum(1 for c in cards if c.get("research_interests"))
        n_g = sum(1 for c in cards
                  if (c.get("recruitment") or {}).get("level") == "🟢")
        for c in cards:
            n = (c.get("name") or "").strip()
            if n:
                all_names.setdefault(n, set()).add(site)

        fails, warns = check_site(site)
        verdict = "✅" if not fails and not warns else ("❌ " + "; ".join(fails) if fails
                                                       else "⚠️ " + "; ".join(warns))
        if fails:
            any_fail = True
        print(f"{site:16s} {len(cards):>5} {len(faculty):>5} "
              f"{n_res:>4}({n_res / max(len(cards), 1):>3.0%}) {n_g:>3}  {verdict}")

    cross = {n: s for n, s in all_names.items() if len(s) > 1}
    if cross:
        sample = list(cross.items())[:5]
        print(f"\nINFO 跨站同名 {len(cross)} 人（兼聘/多栏目属正常）："
              + "、".join(f"{n}({'/'.join(s)})" for n, s in sample))

    print("\n结论：", "存在 FAIL，需修复后重跑" if any_fail else "全部通过")
    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
