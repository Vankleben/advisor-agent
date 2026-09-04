"""
用户画像单一来源（唯一权威版本：archive/profile.json）
所有需要画像的模块（M3拆解/M4路径/M1.5对比/M5批改）都从这里读，
禁止在各工具里再硬编码画像常量——改画像只改 archive/profile.json 一个文件。
用法：
    from user_profile import format_profile, format_hardware
    prompt.format(profile=format_profile(), hardware=format_hardware())
"""
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROFILE_FILE = BASE_DIR / "archive" / "profile.json"


def load_profile() -> dict:
    """读取画像 JSON；文件缺失/损坏时抛异常，由上层处理"""
    return json.loads(PROFILE_FILE.read_text(encoding="utf-8"))


def format_profile(p: dict = None) -> str:
    """把画像格式化为 prompt 用的文本块（知识储备/学习中/项目经历/兴趣方向）"""
    p = p or load_profile()
    lines = ["【知识储备-已掌握】"]
    lines += [f"- {k}" for k in p.get("known", [])]
    if p.get("learning"):
        lines.append("【学习中】")
        lines += [f"- {k}" for k in p["learning"]]
    if p.get("projects"):
        lines.append("【项目经历】")
        lines += [f"- {pr['name']}：{pr['detail']}" for pr in p["projects"]]
    lines.append("【兴趣方向】" + " / ".join(p.get("interests", [])))
    return "\n".join(lines)


def format_hardware(p: dict = None) -> str:
    """把双硬件红线格式化为 prompt 用的文本块（设备A/B 分可行/勉强/不可行三档）"""
    p = p or load_profile()
    lines = []
    for dev, spec in p.get("hardware", {}).items():
        if isinstance(spec, dict):
            lines.append(f"{dev}（{spec.get('summary', '')}）")
            for lvl in ("可行", "勉强", "不可行"):
                if spec.get(lvl):
                    lines.append(f"  {lvl}：{spec[lvl]}")
        else:  # 兼容旧的字符串格式
            lines.append(f"{dev}：{spec}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(format_profile())
    print()
    print(format_hardware())
