"""
M1 增量补丁（历史一次性脚本，使命已完成，保留备查）。

执行状态：全部卡片的 career_stage 均已带 note，本脚本再跑不会改动任何文件
（无 stage 或已有 note 的卡片会被跳过）。新增卡片请直接改 llm_card.py 的提示词回填，
不要再依赖本脚本。

原本用途：给已有 career_stage 的卡片补"对申请者的含义一句话简评（note）"，
不重跑全量卡片（省 API），只对有 stage 无 note 的卡片调一次 LLM 生成 note。

用法：python tools/add_career_note.py
"""


# --- Windows 控制台编码修复：GBK 下 print emoji 会崩溃，强制 stdout/stderr 为 UTF-8 ---
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import json
import glob
from pathlib import Path

from llm_client import make_client, model_for

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

client = make_client()
model = model_for("fast")

SYSTEM = """你是科研申请顾问。我给你一位老师的职业阶段，请用一句话给出"对打算申请他实验室的学生"的实际含义。
要求：基于一般规律的经验性判断，务实、不夸大、不贬低，80字以内，纯中文，不要 JSON 包裹。
【职业阶段】青年（博士毕业8年/助理教授/刚建组）
【实际含义示例】亲自带人概率高、冲劲足，本科生机会相对多，但组的名声、设备和资源可能还在积累期
【职业阶段】中年（副教授到教授中段）
【实际含义示例】产出与资源相对稳定的窗口期，适合求稳深钻
【职业阶段】资深（教授多年/院士等头衔）
【实际含义示例】名头响、资源多，但日常指导可能由小导师/博后承担，需留意组内是否有本科生一作先例"""


def main():
    for f in glob.glob(str(DATA_DIR / "cards_*.json")):
        if "life_old" in f:
            continue  # 跳过备份
        path = Path(f)
        d = json.loads(path.read_text(encoding="utf-8"))
        n_added = 0
        for c in d["cards"]:
            if c.get("skipped"):
                continue
            cs = c.get("career_stage") or {}
            if cs.get("stage") and not cs.get("note"):
                r = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": SYSTEM},
                              {"role": "user", "content": f"该老师职业阶段：{cs['stage']}；依据：{'；'.join(cs.get('evidence') or [])[:150]}"}],
                    temperature=0.3)
                note = (r.choices[0].message.content or "").strip().strip('"')
                if note:
                    cs["note"] = note
                    n_added += 1
        if n_added:
            path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{path.name}: 补 {n_added} 条 note")


if __name__ == "__main__":
    main()