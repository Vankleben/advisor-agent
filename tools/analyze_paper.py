"""
工具七：论文拆解器 v2（审计文档 M3 落地）
用法：python tools/analyze_paper.py 2605.18309v1
流程：第0步 阅读决策卡 → 确认精读 → 七段框架拆解（每处阐述附原文原句）→ 反幻觉校验
"""


# --- Windows 控制台编码修复：GBK 下 print emoji 会崩溃，强制 stdout/stderr 为 UTF-8 ---
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PAPERS_DIR = BASE_DIR / "data" / "papers"

from llm_client import make_client, model_for   # noqa: E402
from text_norm import loose                     # noqa: E402


def profile_block() -> str:
    """读者档案文本（含硬件红线），经 user_profile 从 archive/profile.json 读取。

    画像缺失不再让 import 直接崩（此前在模块级读文件，导致全新克隆仓库连 main.py 都启动不了）；
    同时改为经 user_profile 取，避免"唯一权威版本"被绕过。
    """
    try:
        from user_profile import format_profile, format_hardware
        return f"{format_profile()}\n【硬件红线】\n{format_hardware()}"
    except Exception as e:
        print(f"[M3] 用户画像读取失败（{e}），本次拆解不注入画像")
        return "（画像缺失：archive/profile.json 不可读）"


def load_paper(arxiv_id: str) -> str:
    f = PAPERS_DIR / f"{arxiv_id.replace('/', '_')}.txt"
    if not f.exists():
        raise SystemExit(f"找不到 {f}，请先运行：python tools/paper_tools.py fetch {arxiv_id}")
    return f.read_text(encoding="utf-8")


def ask_llm(client, model: str, system: str, user: str) -> dict:
    r = client.chat.completions.create(
        model=model, temperature=0.1,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        response_format={"type": "json_object"})
    return json.loads(r.choices[0].message.content)


def step0_decision_card(client, model: str, text: str) -> dict:
    """第0步：30秒判断值不值得读（只看摘要和开头，省 token）"""
    system = """你是论文阅读顾问。根据论文摘要和读者档案，判断这篇论文对该读者的价值。
只输出 JSON：{"定位": "开山作/代表作/跟进作/边缘作 及一句话理由",
"方向匹配度": "高/中/低 及一句话理由",
"建议": "精读/速读/跳过",
"预计耗时": "如 2小时",
"前置知识缺口": ["读者档案里没有、但读这篇需要的概念"]}"""
    user = f"""读者档案：{profile_block()}

论文开头（含标题摘要）：
{text[:3000]}"""
    return ask_llm(client, model, system, user)


def full_analysis(client, model: str, text: str) -> dict:
    """七段框架完整拆解。每段必须附原文原句作为证据。"""
    system = """你是论文拆解专家，读者是一名计算机大三学生。按七段框架拆解论文。

铁律：
1. 每一段的 quotes 字段必须是【原文中连续出现的完整英文原句】，逐字复制，禁止改写、概括、翻译；找不到依据的内容不许写；
2. 解释用中文，原理直述（数学定义、机制、公式），禁止使用生活化比喻；
3. concepts 字段：挑出本文涉及的关键概念，对照读者档案——档案已有的标 "known": true 并一句话带过；档案没有的标 "known": false，并用"定义+动机+数学形式"讲透；
4. reproduction 字段：对照读者硬件档案判断复现可行性，必须明确写 设备A/设备B/不可行，并给出理由；
5. 只输出合法 JSON。

输出格式：
{"goal": {"text": "解决什么问题", "quotes": ["原句"]},
 "background": {"text": "实际背景与前人不足", "quotes": ["原句"]},
 "setup": {"text": "数据集/基线/指标/算力", "quotes": ["原句"]},
 "method": {"text": "方法流程逐步拆解", "quotes": ["原句"]},
 "concepts": [{"term": "概念名", "known": true或false, "explanation": "解释"}],
 "results_limits": {"text": "结果含义与局限", "quotes": ["原句"]},
 "reproduction": {"text": "复现可行性与设备建议", "quotes": ["原句"]}}"""
    user = f"""读者档案：{profile_block()}

论文全文：
{text[:90000]}"""
    return ask_llm(client, model, system, user)


def _norm(s: str) -> str:
    """归一化比对（唯一实现见 text_norm.loose）：免疫 PDF 提取的折行连字符、空格、标点差异。"""
    return loose(s)


def verify_quotes(analysis: dict, text: str) -> list[str]:
    """反幻觉校验：所有 quotes 必须能在论文原文中原样找到（归一化后比对）。"""
    text_flat = _norm(text)
    warnings = []
    for section, content in analysis.items():
        if isinstance(content, dict):
            for q in content.get("quotes") or []:
                if _norm(str(q)) not in text_flat:
                    warnings.append(f"⚠️ [{section}] 引句在原文找不到：{str(q)[:60]}...")
    return warnings


def print_card(card: dict):
    print("\n===== 第0步：阅读决策卡 =====")
    for k, v in card.items():
        if isinstance(v, list):
            v = "、".join(v) if v else "无"
        print(f"  {k}：{v}")


def print_analysis(a: dict):
    names = {"goal": "① 解决目标", "background": "② 实际背景", "setup": "③ 实验设置",
             "method": "④ 方法流程", "results_limits": "⑥ 结果与局限",
             "reproduction": "⑦ 复现可行性"}
    for key, title in names.items():
        c = a.get(key) or {}
        print(f"\n===== {title} =====")
        print(c.get("text", "无"))
        for q in c.get("quotes") or []:
            print(f'  📎 原文："{q}"')
    print("\n===== ⑤ 概念解释 =====")
    for c in a.get("concepts", []):
        tag = "【已掌握】只需回顾" if c.get("known") else "【新概念】重点学习"
        print(f"\n  ◆ {c.get('term')} {tag}")
        print(f"    {c.get('explanation')}")


def main():
    arxiv_id = sys.argv[1]
    text = load_paper(arxiv_id)
    client = make_client()

    card = step0_decision_card(client, model_for("fast"), text)
    print_card(card)

    if input("\n进入精读拆解？(y/n)：").strip().lower() != "y":
        print("已跳过。时间省下来了。")
        return

    print("\n精读拆解中（全文较长，需要 1-2 分钟）...")
    analysis = full_analysis(client, model_for("long"), text)
    print_analysis(analysis)

    print("\n===== 反幻觉校验 =====")
    warnings = verify_quotes(analysis, text)
    print("\n".join(warnings) if warnings else "✅ 所有引句均可在原文中找到")

    out = PAPERS_DIR / f"{arxiv_id.replace('/', '_')}_analysis.json"
    out.write_text(json.dumps({"decision_card": card, "analysis": analysis,
                               "verification_warnings": warnings},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n拆解结果已存档：{out}")


if __name__ == "__main__":
    main()