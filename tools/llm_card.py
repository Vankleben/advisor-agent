"""
工具三：LLM 导师卡片生成器 v2.2
改动：homepage_candidates 提取收紧——优先级排序 + 反幻觉校验外链来源
用法：python tools/llm_card.py 董胤蓬           （默认在 collegeai 库里找）
      python tools/llm_card.py 葛亮 life
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
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
sys.path.insert(0, str(BASE_DIR))
from config import PROVIDER, API_KEY

PROVIDERS = {
    "moonshot": {"base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k"},
    "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
}

SYSTEM_PROMPT = """你是导师情报分析员。我会给你一位高校老师的官方网页原文，你的任务是提取结构化信息。

铁律：
1. 只允许使用我提供的原文，禁止使用你自己的任何背景知识。
2. 每条结论必须在 evidence 字段附上原文中的原句作为证据：
   - evidence 必须是【原文中连续出现的完整原句】，逐字复制，禁止改写、概括、拼接；
   - 证据分散在多处的，evidence 用 JSON 数组给出多条原句，如 ["原句1", "原句2"]；
   - 找不到证据的字段填 null。
3. 招生状态（recruitment.level）三级判定：
   - "🟢"：原文明确写出欢迎本科生/实习生/访问学生（必须有原文原句）
   - "🟡"：原文有间接迹象（如列出在读本科生、提及指导本科科研）
   - "⚪"：原文没有任何相关信息
   严禁在没有任何原文支持时给出 🟢。
4. 职业阶段（career_stage）：根据教育/工作年份推断，"青年"（博士毕业8年内/助理教授/刚建组）、"中年"（副教授到教授中段）、"资深"（教授多年/院士等头衔），evidence 给出推断依据的原句；无法判断填 null。另外给一句"对申请者的实际含义"放 note（这是经验性判断，非事实，仅基于一般规律，如 青年="亲自带人概率高、机会多但资源和名声在积累期"，中年="产出与资源稳定窗口期"，资深="名头资源多但日常指导多由小导师/博后承担"）；无依据可写 null。
5. 输出必须是合法 JSON，不要输出任何 JSON 以外的内容。
6. 个人主页提取：
   - 只能从【详情页外链】里挑选，严禁凭空编造任何 URL；
   - 按可信度从高到低排序：个人主页 > 实验室主页 > Google Scholar > GitHub > 其他；
   - 每条带 type 字段标注类型（personal / lab / scholar / github / other）；
   - 找不到个人主页外链时填 []，不要编造。"""


def build_card(teacher: dict) -> dict:
    detail = teacher.get("detail") or {}
    if detail.get("error") or detail.get("no_detail_page"):
        return {"name": teacher["name"], "skipped": True,
                "reason": detail.get("error") or "无详情页"}

    user_msg = f"""老师名单页信息：{json.dumps({k: teacher.get(k) for k in ["name", "title", "sections", "research", "email"]}, ensure_ascii=False)}

详情页正文原文：
{detail.get("detail_text", "")}

详情页里的外链（label 是链接文字，url 是链接地址）：
{json.dumps(detail.get("external_links", []), ensure_ascii=False)}

请输出如下 JSON：
{{
  "name": "姓名",
  "title": "职称（原文依据）",
  "research_interests": ["研究方向1", "研究方向2"],
  "current_focus": {{"text": "近期在做什么", "evidence": ["原文原句1", "原文原句2"]}},
  "career_stage": {{"stage": "青年/中年/资深", "evidence": ["推断依据的原文原句"], "note": "对申请者的一句话含义（经验性判断，可null）"}},
  "recruitment": {{"level": "🟢/🟡/⚪", "evidence": ["原文原句"] 或 null, "note": "补充说明"}},
  "homepage_candidates": [
    {{"url": "外链地址（必须从上方外链列表里选）", "label": "外链文字", "type": "personal/lab/scholar/github/other"}}
  ],
  "summary": "一句话概括这位老师"
}}"""

    p = PROVIDERS[PROVIDER]
    client = OpenAI(api_key=API_KEY, base_url=p["base_url"])
    resp = client.chat.completions.create(
        model=p["model"],
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": user_msg}],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    return json.loads(resp.choices[0].message.content)


def verify_evidence(card: dict, teacher: dict) -> list[str]:
    """反幻觉校验：evidence 必须能在原文搜到；homepage_candidates 的 url 必须来自外链列表。"""
    detail = teacher.get("detail") or {}
    text = detail.get("detail_text", "")
    text_flat = re.sub(r"\s+", "", text)
    external_urls = {link["url"] for link in detail.get("external_links", [])
                      if isinstance(link, dict) and "url" in link}
    warnings = []

    def check(field: str, ev):
        if not ev:
            return
        quotes = ev if isinstance(ev, list) else [ev]
        for q in quotes:
            if re.sub(r"\s+", "", str(q)) not in text_flat:
                warnings.append(f"⚠️ {field} 的 evidence 在原文中找不到：{str(q)[:50]}...")

    check("current_focus", (card.get("current_focus") or {}).get("evidence")
          if isinstance(card.get("current_focus"), dict) else None)
    check("career_stage", (card.get("career_stage") or {}).get("evidence"))
    check("recruitment", (card.get("recruitment") or {}).get("evidence"))

    # 校验 homepage_candidates 的 url 必须来自外链列表
    for i, c in enumerate(card.get("homepage_candidates") or []):
        url = c.get("url") if isinstance(c, dict) else c
        if not url:
            continue
        if url not in external_urls:
            warnings.append(f"⚠️ homepage_candidates[{i}] 的 url 不在详情页外链列表中：{url[:60]}...")

    return warnings


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "董胤蓬"
    site = sys.argv[2] if len(sys.argv) > 2 else "collegeai"
    with open(DATA_DIR / f"faculty_{site}_enriched.json", encoding="utf-8") as f:
        teachers = json.load(f)["teachers"]

    teacher = next((t for t in teachers if t["name"] == name), None)
    if not teacher:
        print(f"找不到老师：{name}")
        return

    card = build_card(teacher)
    print(json.dumps(card, ensure_ascii=False, indent=2))

    warnings = verify_evidence(card, teacher)
    print("\n=== 反幻觉校验 ===")
    print("\n".join(warnings) if warnings else "✅ 所有 evidence 均可在原文中找到，homepage_candidates 的 url 均来自外链列表")


if __name__ == "__main__":
    main()
