"""
动态记忆：让用户画像（archive/profile.json）随使用自动生长

设计原则：
- 只增不减（学习记录不删旧的），但自动去重；
- 每次写入都留痕（archive/memory_log.json 时间线），可追溯可手动清理；
- 自动沉淀路径：M3 精读→新概念进 learning；M4 进组→可快速补齐的技能进 learning；
  M5 批改→事件留痕（错误本来就会进 error_patterns）；
- 用户显式入口：remember()（Agent 工具，用户说"记住…"时调用）。

用法：
    from memory import add_learning, remember, recent_digest, log_event
"""
import json
import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ARCHIVE = BASE_DIR / "archive"
PROFILE_FILE = ARCHIVE / "profile.json"
LOG_FILE = ARCHIVE / "memory_log.json"

VALID_CATEGORIES = ("interest", "skill_known", "skill_learning", "project", "note")


def _today() -> str:
    return datetime.date.today().isoformat()


def _load_profile() -> dict:
    return json.loads(PROFILE_FILE.read_text(encoding="utf-8"))


def _save_profile(p: dict) -> None:
    p["updated"] = _today()
    PROFILE_FILE.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_log() -> list:
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def log_event(kind: str, detail: str, source: str = "") -> None:
    """记录一条记忆事件（时间线，供 recent_digest 展示 + 审计）"""
    log = _load_log()
    log.append({"date": _today(), "kind": kind, "detail": detail, "source": source})
    LOG_FILE.write_text(json.dumps(log[-500:], ensure_ascii=False, indent=2),
                        encoding="utf-8")


def _norm(s) -> str:
    return str(s or "").strip().lower()


def _dedup_add(lst: list, terms: list) -> list:
    """向列表追加去重后的条目，返回实际新增的"""
    have = {_norm(x) for x in lst}
    added = []
    for t in terms:
        t = str(t or "").strip()
        if not t or _norm(t) in have:
            continue
        lst.append(t)
        have.add(_norm(t))
        added.append(t)
    return added


def add_learning(terms: list, source: str = "") -> list:
    """新增"在学"概念/技能：已在 known 或 learning 里的会跳过"""
    terms = [t for t in (terms or []) if t]
    if not terms:
        return []
    p = _load_profile()
    known = {_norm(x) for x in p.get("known", [])}
    terms = [t for t in terms if _norm(t) not in known]
    learning = p.setdefault("learning", [])
    added = _dedup_add(learning, terms)
    if added:
        _save_profile(p)
        log_event("知识增长", f"新增待学：{'、'.join(added[:6])}", source)
    return added


def add_known(terms: list, source: str = "") -> list:
    """标记为已掌握：加入 known，并从 learning 中移除"""
    terms = [t for t in (terms or []) if t]
    if not terms:
        return []
    p = _load_profile()
    known = p.setdefault("known", [])
    added = _dedup_add(known, terms)
    if added:
        # 从 learning 移除已掌握的
        added_norm = {_norm(x) for x in added}
        p["learning"] = [x for x in p.get("learning", []) if _norm(x) not in added_norm]
        _save_profile(p)
        log_event("掌握升级", f"标记已掌握：{'、'.join(added[:6])}", source)
    return added


def add_interest(items: list, source: str = "") -> list:
    p = _load_profile()
    added = _dedup_add(p.setdefault("interests", []), items or [])
    if added:
        _save_profile(p)
        log_event("兴趣更新", f"新增兴趣：{'、'.join(added)}", source)
    return added


def add_project(name: str, detail: str = "", source: str = "") -> bool:
    name = str(name or "").strip()
    if not name:
        return False
    p = _load_profile()
    projects = p.setdefault("projects", [])
    if any(_norm(x.get("name")) == _norm(name) for x in projects):
        return False
    projects.append({"name": name, "detail": str(detail or "").strip()})
    _save_profile(p)
    log_event("项目更新", f"新增项目：{name}", source)
    return True


def remember(text: str, category: str = "note", source: str = "用户口述") -> dict:
    """
    用户显式记忆入口（Agent 工具调用）。
    category: interest(兴趣) / skill_known(已掌握) / skill_learning(在学) /
              project(项目，文本用"名称：说明"格式) / note(其他备注)
    任何一条都会写入 memory_log 留痕。
    """
    text = str(text or "").strip()
    if not text:
        return {"error": "内容为空"}
    cat = category if category in VALID_CATEGORIES else "note"
    result = {"category": cat, "text": text}

    if cat == "interest":
        result["added"] = add_interest([text], source)
    elif cat == "skill_known":
        result["added"] = add_known([text], source)
    elif cat == "skill_learning":
        result["added"] = add_learning([text], source)
    elif cat == "project":
        name, _, detail = text.partition("：")
        result["added"] = add_project(name or text, detail, source)
    else:  # note
        p = _load_profile()
        added = _dedup_add(p.setdefault("notes", []), [text])
        if added:
            _save_profile(p)
        log_event("备注", text, source)
        result["added"] = added

    # 统一留痕（如果是 note 已在上面留过，避免重复）
    if cat != "note":
        log_event("手动记忆", f"[{cat}] {text}", source)
    return result


def recent_digest(n: int = 10) -> str:
    """近期记忆摘要（供系统提示注入），倒序展示"""
    log = _load_log()[-n:]
    if not log:
        return ""
    lines = [f"- {e.get('date', '')} [{e.get('kind', '')}] {e.get('detail', '')}"
             for e in reversed(log)]
    return "\n".join(lines)


if __name__ == "__main__":
    print("=== 近期记忆 ===")
    print(recent_digest(20) or "(空)")
    p = _load_profile()
    print("\n=== 画像概览 ===")
    print("已知:", len(p.get("known", [])), "| 在学:", p.get("learning", []))
    print("项目:", [x.get("name") for x in p.get("projects", [])])
