"""本地数据读取归口：卡片库（data/cards_*.json）与深潜报告（data/deepdive/*_report.json）。

此前"按姓名找卡片"在 3 个文件各写一遍、深潜报告路径拼接在 4 个文件各写一遍，
文件格式一变就要改多处。所有读取一律走这里。

用法：
    from store import iter_cards, find_card, load_deepdive_report, has_deepdive
    card = find_card("张三")                    # 全库找；找不到返回 None
    rep  = load_deepdive_report("张三")         # 深潜报告（内含 report/sources 字段）
"""
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DEEPDIVE_DIR = DATA_DIR / "deepdive"


def _load(path: Path):
    """读 JSON；文件不存在或损坏时返回 None（调用方无需各自 try/except）。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe(name: str) -> str:
    return str(name).replace("/", "_").replace("\\", "_")


def iter_cards():
    """遍历所有卡片，产出 (site, card)；跳过读不动的文件与 skipped 卡片之外的原始条目。"""
    for f in sorted(DATA_DIR.glob("cards_*.json")):
        data = _load(f)
        if not isinstance(data, dict):
            continue
        site = f.stem.replace("cards_", "")
        for c in data.get("cards") or []:
            if isinstance(c, dict):
                yield site, c


def find_card(name: str, site: str = ""):
    """按姓名找卡片；site 省略时全库搜索。找不到返回 None。"""
    files = ([DATA_DIR / f"cards_{site}.json"] if site
             else sorted(DATA_DIR.glob("cards_*.json")))
    for f in files:
        data = _load(f)
        if not isinstance(data, dict):
            continue
        for c in data.get("cards") or []:
            if c.get("name") == name:
                return c
    return None


def deepdive_path(name: str) -> Path:
    return DEEPDIVE_DIR / f"{_safe(name)}_report.json"


def load_deepdive_report(name: str):
    """读某老师的深潜报告（含 name/date/sources/report/verification_warnings）；无则 None。"""
    return _load(deepdive_path(name))


def has_deepdive(name: str) -> bool:
    return deepdive_path(name).exists()
