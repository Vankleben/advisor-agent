"""
工具七：论文拆解器 v2（审计文档 M3 落地）
用法：python tools/analyze_paper.py 2605.18309v1
流程：第0步 阅读决策卡 → 确认精读 → 七段框架拆解（每处阐述附原文原句）→ 反幻觉校验
"""
import json
import re
import sys
from pathlib import Path
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent.parent
PAPERS_DIR = BASE_DIR / "data" / "papers"
sys.path.insert(0, str(BASE_DIR))
from config import PROVIDER, API_KEY

PROVIDERS = {
    "moonshot": {"base_url": "https://api.moonshot.cn/v1",
                 "fast": "moonshot-v1-8k", "long": "moonshot-v1-128k"},
    "deepseek": {"base_url": "https://api.deepseek.com",
                 "fast": "deepseek-chat", "long": "deepseek-chat"},
}

PROFILE = json.loads((BASE_DIR / "archive" / "profile.json").read_text(encoding="utf-8"))


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
    user = f"""读者档案：{json.dumps(PROFILE, ensure_ascii=False)}

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
    user = f"""读者档案：{json.dumps(PROFILE, ensure_ascii=False)}

论文全文：
{text[:90000]}"""
    return ask_llm(client, model, system, user)


def _norm(s: str) -> str:
    """归一化：剥掉所有非字母数字汉字字符。
    免疫 PDF 提取的折行连字符(Re-bound\\nForce)、空格、标点差异。"""
    return re.sub(r"[^0-9a-zA-Z一-鿿]+", "", s).lower()


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
    p = PROVIDERS[PROVIDER]
    client = OpenAI(api_key=API_KEY, base_url=p["base_url"])

    card = step0_decision_card(client, p["fast"], text)
    print_card(card)

    if input("\n进入精读拆解？(y/n)：").strip().lower() != "y":
        print("已跳过。时间省下来了。")
        return

    print("\n精读拆解中（全文较长，需要 1-2 分钟）...")
    analysis = full_analysis(client, p["long"], text)
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