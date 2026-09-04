"""
M1 增量补丁：给已有 career_stage 的卡片补"对申请者的含义一句话简评（note）"
不重跑全量卡片（省 API），只对有 stage 无 note 的卡片调一次 LLM 生成 note。

用法：python tools/add_career_note.py
"""
import json
import sys
import glob
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "tools"))
from config import PROVIDER, API_KEY
from openai import OpenAI

PROVIDERS = {
    "moonshot": ("https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    "deepseek": ("https://api.deepseek.com", "deepseek-chat"),
}
base_url, model = PROVIDERS[PROVIDER]
client = OpenAI(api_key=API_KEY, base_url=base_url)

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