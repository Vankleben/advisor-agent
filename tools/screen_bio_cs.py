"""
M6：生物×计算交叉导师筛选器

从本地卡片库（data/cards_*.json）里筛出"生物/医学 × 计算机"交叉方向的导师，
再按用户画像打两个维度的分：
  - crossover 交叉度：用户现有可交付技能能直接上手的程度
  - access    进组率：非顶尖院校大三学生发邮件申请、对方愿意收的概率

用法：
    python tools/screen_bio_cs.py --filter            # 只筛不打分（纯本地，不调 LLM）
    python tools/screen_bio_cs.py --life --filter     # 只看生命科学学院口径
    python tools/screen_bio_cs.py --life --score      # 生命科学院口径 + 两维打分
    python tools/screen_bio_cs.py --sites life,pkubio --score
    python tools/screen_bio_cs.py --score --top 30

设计说明：
- 画像唯一来源 archive/profile.json（走 user_profile），收藏清单唯一来源
  archive/target_advisors.json，排除名单唯一来源 archive/advisor_blacklist.json
  ——本文件不硬编码任何姓名。
- 筛选逻辑只认卡片自带的 research_interests 字段：方向描述里必须同时出现
  生物词与"计算/AI 是主线"的词，且不含纯湿实验标志词。summary 不参与判定，
  因为它常把"合作/交叉"写得比实际宽。
- `--life` 把范围收到"生命科学学院"：用户说过"主要还是想要跟生物交叉的老师，
  生命科学最好"，医学影像/BME/纯 AI 学院的人算交叉但不算生命科学。
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

# --- Windows 控制台编码修复：GBK 下 print emoji 会崩溃，强制 stdout/stderr 为 UTF-8 ---
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "tools"))

from store import iter_cards            # noqa: E402
from user_profile import format_profile  # noqa: E402

TARGETS_FILE = BASE_DIR / "archive" / "target_advisors.json"
BLACKLIST_FILE = BASE_DIR / "archive" / "advisor_blacklist.json"
OUT_FILE = BASE_DIR / "data" / "bio_cs_screening.json"

# 站点代号 → 院系性质。LIFE_SCIENCE 是"生命科学学院"口径：
# 用户明确说过"主要还是想要跟生物交叉的老师，生命科学最好"，
# 医学影像/BME/纯 AI 学院的人算交叉但不算生命科学，需用 --sites life 排除。
LIFE_SCIENCE = ("life", "thulife", "pkubio", "wlls", "wlsls")

# 这些站点本身就是生命科学学院/生科院（而非"全校"或"交叉院"）：学院属性已经保证了
# "与生物相关"，因此**不再要求方向描述里出现生物词**。
# 盲点记录（2026-09-23 第二次修，同类问题）：做深度学习/CV 的老师常常只写方法词
# （"超分辨荧光显微镜；深度学习计算成像"、"计算机辅助药物设计"），一个生物词都不写，
# 且"计算机辅助"不匹配"计算机算法/计算机视觉"这类完整词——于是两类人都被词表滤掉。
# 按站点判比按词判可靠：学院=生科院时，方向只要命中计算词即可。
LIFE_SCHOOL_SITES = ("life", "thulife", "pkubio", "slst", "sustech")

# 生物/医学领域词：方向里必须命中至少一个（站点在 LIFE_SCHOOL_SITES 里时可豁免）
BIO_WORDS = [
    "生物", "生命", "医学", "医", "临床", "细胞", "基因", "基因组", "组学", "神经", "脑",
    "药物", "疾病", "肿瘤", "癌", "免疫", "微生物", "生态", "动物", "植物", "育种", "农业",
    "农学", "公共卫生", "流行病", "生理", "病理", "病毒", "疫苗", "抗体", "菌", "水稻",
    "物种", "演化", "进化", "干细胞", "器官", "核酸", "RNA", "DNA", "代谢", "生物物理",
    "生物医学", "生物工程", "蛋白", "表型", "行为", "表观", "眼科", "影像",
    "显微", "成像", "荧光", "切片", "组化",
]

# "计算/AI 是主线"的词：方向里必须命中至少一个，否则算纯湿实验
COMPUTE_WORDS = [
    "机器学习", "深度学习", "人工智能", "计算机视觉", "神经网络", "大模型", "语言模型",
    "智能体", "数据挖掘", "生物信息", "信息学", "计算生物学", "计算神经", "计算方法",
    "算法", "建模", "模型", "计算机算法", "模式识别", "图像", "视觉", "检测", "识别",
    "分割", "预测模型", "模拟", "仿真", "统计", "定量", "智能化", "数字化", "大数据",
    "三维重构", "重建算法", "信号处理", "自动化分析", "挖掘", "连接组", "connectom",
    "计算机", "计算成像", "超分辨", "计算化学", "计算物理",
]

# 纯湿实验/纯化学标志词：方向里出现即剔除（这些组收 CS 学生进去也使不上劲）
WET_LAB_WORDS = [
    "有机合成", "化学生物学", "电生理学以及", "膜片钳", "晶体学及", "X-射线晶体学以及",
    "质谱鉴定", "化学合成", "探针的开发与应用", "细胞培养", "小鼠模型", "免疫组织化学",
    "分子克隆", "病毒遗传物质释放", "染色质高级结构", "原位结构生物学", "冷冻电子显微学理论",
]

# 每项技能对应的研究需求；多轴命中说明交叉面更宽
SKILL_AXES = {
    "蛋白质序列-结构计算": [
        "蛋白", "折叠", "结构预测", "氨基酸", "序列设计", "酶", "结构建模", "生物大分子",
        "RNA结构", "分子动力学", "AlphaFold", "几何深度学习", "结构基础模型",
    ],
    "图像/视频自动分析": [
        "图像", "视觉", "检测", "分割", "识别", "成像", "影像", "行为", "追踪", "跟踪",
        "视频", "重建", "超分辨", "表型", "显微", "姿态",
    ],
    "LLM/智能体": [
        "智能体", "Agent", "大模型", "语言模型", "LLM", "知识图谱", "生成式", "问答", "科学发现",
    ],
    "模型训练与微调": [
        "机器学习", "深度学习", "神经网络", "数据挖掘", "算法", "特征", "表征", "分类",
        "回归", "聚类", "监督学习", "预测",
    ],
}

# 招募原话里出现这些词 = 该组主动要计算机背景的人。
# 有些组方向写得偏湿实验、会被 WET_LAB_WORDS 滤掉，但招募原话点名要 CS 学生
# （如"欢迎…计算机科学、机器学习…背景的本科生加入"）——这类恰恰是 CS 学生最容易进的，
# 必须保住，否则筛选器会把最好的机会滤掉。
CS_WELCOME_WORDS = [
    "计算机", "机器学习", "人工智能", "计算生物学", "生物信息", "计算背景", "深度学习",
    "计算机科学", "AI", "编程", "软件", "算法", "数据科学", "计算神经",
]

PROMPT = """你是进组可行性评估员。用户在给一位大三 CS 学生筛选"寒假能进组访问/学习"的导师。

【用户画像】
{profile}

【用户手里真正能交付的东西（打分时以此为准）】
1. YOLO 目标检测+迁移学习：在高校课题组做过动物行为识别的 CV 部分，mAP50 0.716→0.803，
   模型已交付课题组试运行——这是他最硬、最可复述的成果；
2. HuggingFace 微调全流程、LoRA/QLoRA、知识蒸馏、Transformer/注意力、RLHF 基本流程；
3. LLM Agent + Function Calling：独立设计并开源 22 工具的科研助手 Agent（含引句证据校验）；
4. jev-arm-lab（已开源）：独立设计"判断交给模型、否决权留在代码"的机器人决策实验，
   三轮 55 场景/571 轮决策，能讲清自己测出来的失败模式与局限；
5. ⚠️ ESM-IF1 逆向折叠：只是 vibe coding 跑通流程、会用 ESM 工具，**模型机制与折叠物理原理
   没学过、讲不清**——不要按"能承担蛋白质设计科研"给它打高分。
【用户当前想去的方向（打分时对齐）】
生命科学学院里做深度学习/计算机视觉/机器学习的老师：图像与视频自动分析（显微成像、行为追踪、
表型、分割检测）、模型训练与微调、生命科学大模型。**纯湿实验组不算对口**。
【用户的硬约束】
- 学校是民航类院校（非985/211），学术光环弱；
- 算力只有 RTX3060 12GB + 核显笔记本：能 QLoRA 微调 ≤8B 模型，不能做预训练/多卡；
- 没有湿实验经验，生物/医学领域知识薄。

【待评估老师】（每位含卡片数据，全部来自其院系官网抓取）
{teachers}

【打分要求】
对每位老师打两个分（1-5 的整数）：

A. crossover 交叉度——这位老师组里的活儿，用户现有技能能直接上手的程度。
   5 = 有能立刻接手的任务（如蛋白序列-结构计算、图像检测分割、行为视频分析、模型微调）
   4 = 主要任务对口但需补一块领域知识
   3 = 计算成分真实存在但只是辅助手段
   2 = 用户只能打下手或做数据工程
   1 = 基本是湿实验或纯理论，用户进去使不上劲

B. access 进组率——一名非985大三 CS 学生发邮件申请，"愿意收他寒假来学"的概率。
   5 = 页面明写欢迎本科生/实习生/访问学生，或青年 PI 正在建组缺人
   4 = 青年 PI + 组里明显缺计算人手
   3 = 信息不明但方向对口，值得一试
   2 = 资深大牛、组大，本科生进去大概率被扔给博后带或直接不回
   1 = 院士/讲席教授且页面无任何招生信息

C. cross_reason / access_reason 各一句话理由，**必须引用卡片里的具体方向词**，
   不要泛泛而谈。
D. entry_task 如果用户真的进去了，最可能被派去做的第一件事是什么
   （要具体，且必须能在他 RTX3060 上跑）。

铁律：只能依据上面给的卡片数据，卡片里没有的信息不要推测；分数必须是 1-5 的整数。
输出 JSON：{{"scores":[{{"name":"","crossover":0,"access":0,"cross_reason":"",
"access_reason":"","entry_task":""}}]}}"""


def load_target_names() -> set:
    """读收藏清单姓名（唯一权威版本：archive/target_advisors.json）。"""
    try:
        data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return set()
    return {t.get("name") for t in (data.get("targets") or []) if t.get("name")}


def load_blacklist() -> dict:
    """读用户明确不要的老师（archive/advisor_blacklist.json）→ {姓名: 原因}。

    用户拒掉某个人往往是出于我看不到的理由（听过传闻、方向不合口味等），
    这里只负责"记住并尊重"，不追问他为什么。
    """
    try:
        data = json.loads(BLACKLIST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for item in (data.get("blocked") or []):
        if isinstance(item, dict) and item.get("name"):
            out[item["name"]] = item.get("reason") or ""
    return out


def build_pool(sites: tuple = ()) -> list:
    """从卡片库筛出生物×计算交叉候选人；同名只保留信息最全的那张卡。

    sites 非空时只保留这些站点代号下的卡片（用于"只看生命科学学院"口径）。
    用户明确排除的人（archive/advisor_blacklist.json）在这里就滤掉，不进入候选。
    """
    blocked = load_blacklist()
    best = {}
    for site, c in iter_cards():
        if c.get("skipped"):
            continue
        if sites and site not in sites:
            continue
        ri = c.get("research_interests")
        ri_txt = " ".join(str(x) for x in ri) if isinstance(ri, list) else str(ri or "")
        if not ri_txt:
            continue
        # 生命科学学院站点：学院属性已保证与生物相关，不再要求方向里出现生物词
        if site not in LIFE_SCHOOL_SITES and not any(k in ri_txt for k in BIO_WORDS):
            continue
        rec = c.get("recruitment") or {}
        ev = rec.get("evidence") or []
        ev_txt = " ".join(str(x) for x in (ev if isinstance(ev, list) else [ev]))
        # 招募原话点名要计算机背景的人 → 即便方向偏湿实验也保留（这类组 CS 学生最容易进）
        cs_welcome = any(w in ev_txt for w in CS_WELCOME_WORDS)
        if not cs_welcome:
            if not any(k in ri_txt for k in COMPUTE_WORDS):
                continue
            if any(k in ri_txt for k in WET_LAB_WORDS):
                continue
        name = c.get("name")
        if not name or name in blocked:
            continue
        cf = c.get("current_focus") or {}
        axes = [ax for ax, kws in SKILL_AXES.items() if any(k in ri_txt for k in kws)]
        item = {
            "name": name,
            "site": site,
            "title": c.get("title"),
            "stage": (c.get("career_stage") or {}).get("stage"),
            "recruit": rec.get("level"),
            "recruit_evidence": rec.get("evidence"),
            "cs_welcome": cs_welcome,
            "interests": [str(x) for x in (ri if isinstance(ri, list) else [ri])],
            "focus": (cf.get("text") if isinstance(cf, dict) else None),
            "email": c.get("email"),
            "homepage": [(h.get("url") if isinstance(h, dict) else str(h))
                         for h in (c.get("homepage_candidates") or [])],
            "axes": axes,
        }
        weight = len(json.dumps(item, ensure_ascii=False))
        if name not in best or weight > best[name][0]:
            best[name] = (weight, item)
    return [v[1] for v in best.values()]


def filter_only(pool: list) -> None:
    """只打印筛选结果，不调 LLM。"""
    pool.sort(key=lambda r: (-len(r["axes"]), 0 if r["recruit"] == "🟢" else 1))
    print(f"筛出 {len(pool)} 人（生物×计算交叉，已排除纯湿实验与排除名单）\n")
    for r in pool:
        print(f'{r["site"]:11s}|{r["name"]:7s}|{str(r["title"])[:14]:16s}|招{str(r["recruit"]):3s}'
              f'|{"+".join(a[:3] for a in r["axes"]):22s}|{" / ".join(r["interests"])[:90]}')


def score(pool: list, top: int = 0) -> dict:
    """调 LLM 打分；按 profile 与卡片内容，不引入任何外部信息。"""
    from llm_client import make_client, model_for  # 延迟导入：--filter 模式不依赖 LLM 配置

    client = make_client()
    model = model_for("mid")
    profile = format_profile()
    targets = load_target_names()
    out, batch_size = [], 12
    for i in range(0, len(pool), batch_size):
        batch = pool[i:i + batch_size]
        resp = client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[{"role": "user",
                       "content": PROMPT.format(profile=profile,
                                                teachers=json.dumps(batch, ensure_ascii=False,
                                                                    indent=1))}])
        got = json.loads(resp.choices[0].message.content).get("scores", [])
        returned = {g.get("name") for g in got}
        for g in got:
            src = next((p for p in batch if p["name"] == g.get("name")), {})
            g.update({"site": src.get("site"), "title": src.get("title"),
                      "stage": src.get("stage"), "recruit": src.get("recruit"),
                      "recruit_evidence": src.get("recruit_evidence"),
                      "interests": src.get("interests"), "email": src.get("email"),
                      "axes": src.get("axes"),
                      "already_target": g.get("name") in targets})
            out.append(g)
        missing = [p["name"] for p in batch if p["name"] not in returned]
        if missing:
            print(f"  ⚠️ 本批漏评（模型未返回）: {missing}")
        print(f"  批次 {i // batch_size + 1}/{-(-len(pool) // batch_size)}：{len(got)} 条")
    out.sort(key=lambda x: (-(x.get("crossover") or 0) - (x.get("access") or 0)))
    if top:
        out = out[:top]
    result = {"generated": date.today().isoformat(), "count": len(out), "scores": out}
    OUT_FILE.parent.mkdir(exist_ok=True)
    OUT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已写出 {OUT_FILE}")
    for x in out[:30]:
        flag = " ★已收藏" if x.get("already_target") else ""
        print(f'[{x["crossover"]}/{x["access"]}] {x.get("name")} | '
              f'{str(x.get("title"))[:14]} | {x.get("site")}{flag}')
        print(f'    交叉: {x.get("cross_reason", "")}')
        print(f'    进组: {x.get("access_reason", "")}')
        print(f'    进门任务: {x.get("entry_task", "")}')
    return result


def main():
    ap = argparse.ArgumentParser(description="生物×计算交叉导师筛选器")
    ap.add_argument("--filter", action="store_true", help="只筛不打分（不调 LLM）")
    ap.add_argument("--score", action="store_true", help="筛 + 两维打分（调 LLM）")
    ap.add_argument("--top", type=int, default=0, help="只保留总分前 N 名")
    ap.add_argument("--life", action="store_true",
                    help="只看生命科学学院口径（清华生命/北大生科/西湖生命）")
    ap.add_argument("--sites", default="",
                    help="只保留指定站点代号，逗号分隔（如 life,pkubio,wlls）")
    args = ap.parse_args()

    sites = LIFE_SCIENCE if args.life else ()
    if args.sites:
        sites = tuple(s.strip() for s in args.sites.split(",") if s.strip())
    pool = build_pool(sites)
    if args.score:
        score(pool, top=args.top)
    else:
        filter_only(pool)


if __name__ == "__main__":
    main()
