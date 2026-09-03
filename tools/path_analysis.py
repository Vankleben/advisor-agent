"""
M4：进组路径分析
输入老师名 → 读取其 M2 深潜报告 + 用户画像 → 产出需求侧/供给侧/行动方案
反幻觉规则：需求侧必须引用深潜报告里的 evidence 原文，无证据的判断不输出
用法（独立测试）：python tools/path_analysis.py 俞立
"""
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEEPDIVE_DIR = BASE_DIR / "data" / "deepdive"

FENCE = chr(96) * 3   # markdown 代码围栏字符，动态构造避免显示问题

# 用户画像（来自设计文档第2节，改动画像时直接改这里）
USER_PROFILE = """【知识储备-已掌握】
- ML/DL理论：Transformer/RNN/CNN框架
- 工程：HuggingFace Transformers全流程（微调/loss/benchmark）；跑通过水印、越狱、R-Judge、Agent构建、CoT、RLHF、PoT（停留于"知道+跑过"层面）
- 系统：Shell/集群训练脚本、Git、Vim
- 推理系统入门：kernel核函数、KV cache、首token生成、CPU/GPU分工
- 多模态入门：Qwen2.5-VL看图问答、CLIP余弦相似度

【项目经历】
- 熊类行为识别（川农课题组）：YOLO11迁移学习，mAP50 0.716→0.803，已交付
- ESM-IF1蛋白质逆向折叠：完整流水线，序列恢复率45.8%，代码开源

【兴趣方向】ML / LLM / CV / 具身智能 / AI4Science"""

# 双硬件红线（M4行动方案必须过这个检查）
HARDWARE = """设备A（核显笔记本）：仅≤3B量化推理、数据处理、评测脚本、prompt工程、API调用；
设备B（RTX3060 12GB）：7-8B量化推理流畅、QLoRA/LoRA微调7-8B、全参微调≤1.5B、YOLO级CV训练；
不可行：13B以上微调、预训练、多卡分布式。项目建议必须标注设备A或B，超红线的方案直接不许出现。"""

PROMPT = """你是进组路径分析员。用户是一名想进实验室的CS大三学生，我给他选定了目标老师。

铁律：
1. 需求侧（老师缺什么人）必须基于我提供的深潜报告原文，每条判断附 evidence 原句引用；
   报告里没有支撑的判断不要写；
2. 供给侧只对照用户画像列"已具备/可快速补齐/短期补不了"三档，不做无据评价；
3. 行动方案给1-2个敲门砖项目，必须过算力检查并标注设备A/B，超红线方案禁止出现；
   项目方向要能从需求侧判断里找到依据；
4. 输出用简洁中文。

【用户画像】
{profile}

【算力红线】
{hardware}

【目标老师的深潜报告】
{report}

输出JSON：
{{"demand": [{{"need": "老师缺什么样的人/技能", "evidence": "深潜报告原文", "note": ""}}],
  "supply": {{"ready": ["已具备"], "quick": ["可快速补齐"], "gap": ["短期补不了"]}},
  "actions": [{{"project": "敲门砖项目描述", "device": "A或B", "basis": "依据demand哪条", "steps": ["步骤"]}}],
  "summary": "一句话结论：值不值得主攻，从哪切入"}}"""


def strip_code_fence(text: str) -> str:
    """剥掉 LLM 输出可能带的 markdown 代码围栏"""
    if text.startswith(FENCE):
        text = text.split("\n", 1)[1]
        text = text.rsplit(FENCE, 1)[0]
    return text.strip()


def run_path_analysis(client, model, name: str, site: str = "") -> dict:
    # 1. 找深潜报告
    report_file = DEEPDIVE_DIR / f"{name}_report.json"
    if not report_file.exists():
        return {"error": f"没有 {name} 的深潜报告，请先对该老师执行 M2 深潜（advisor_deepdive）"}
    report = json.loads(report_file.read_text(encoding="utf-8"))

    # 2. 组 prompt 调 LLM
    prompt = PROMPT.format(profile=USER_PROFILE, hardware=HARDWARE,
                           report=json.dumps(report.get("report", report),
                                             ensure_ascii=False))
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3)
    text = strip_code_fence(resp.choices[0].message.content.strip())
    result = json.loads(text)

    # 3. 落盘
    out = DEEPDIVE_DIR / f"{name}_path.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"name": name, "path": result, "saved": str(out)}


if __name__ == "__main__":
    # 独立测试模式
    sys.path.insert(0, str(BASE_DIR))
    from config import PROVIDER, API_KEY
    from openai import OpenAI
    P = {"moonshot": ("https://api.moonshot.cn/v1", "moonshot-v1-8k"),
         "deepseek": ("https://api.deepseek.com", "deepseek-chat")}[PROVIDER]
    client = OpenAI(api_key=API_KEY, base_url=P[0])
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if not name:
        print("用法：python tools/path_analysis.py 老师中文名")
        sys.exit(1)
    r = run_path_analysis(client, P[1], name)
    print(json.dumps(r, ensure_ascii=False, indent=2))
