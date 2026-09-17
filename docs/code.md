# 导师情报与论文伴读 Agent

## 1. 项目简介
本项目是一个基于大语言模型（LLM）与 Function Calling 的智能体系统，服务对象为寻找科研实验室的计算机大三学生。
系统通过自动化爬虫、多模态解析与严格的反幻觉校验机制，为用户提供导师情报获取、论文拆解、进组路径规划及横向对比功能。

## 2. 核心模块与现状 (MVP + v1 完成，2026-09-04 三项优化)

| 模块 | 名称 | 状态 | 描述 |
|---|---|---|---|
| **M1** | 导师画像 | ✅ 已完成 | 通用爬虫抓取学院师资页，结合LLM生成包含原文证据的结构化导师卡片。**+输入泛化：Agent 可从学校名自主导航（fetch_url 逐层找院系→师资页→收录），无需用户手动提供 URL** |
| **M1.5**| 对比视图 | ✅ 已完成 | 全景表快速全览已收录导师；深度对比支持选定2-5人，基于卡片与深潜报告打七项指标分。 |
| **M2** | 导师深潜 | ✅ 已完成 | 自动抓取导师个人/实验室主页，提取五个维度的深度信息，并附带逐字证据校验防幻觉。 |
| **M3** | 论文拆解 | ✅ 已完成 | arXiv 论文下载 -> 阅读决策卡 -> 七段法完整精读，并对所有引用句子进行反幻觉校验。 |
| **M4** | 进组路径 | ✅ 已完成 | 基于深潜报告分析导师需求侧，结合用户技能三档清单，产出带有设备算力红线的敲门砖项目。 |
| **M5** | 批改凝练 | ✅ 已完成 | 对照已精读论文，对用户的思考文字进行事实纠错、费曼追问、凝练总结，并提供申诉复核机制。**2026-09-04 代码丢失后恢复并修复5项缺陷（模型选择/全文窗口/归一化校验/schema对齐/宽松匹配漏洞），批改后凝练段落自动入已读论文库** |
| **M6** | 实时监测 | ✅ 已完成 | 对已收藏老师定时查新动态：主页快照语义 diff + arXiv 新论文检测（关键词过滤防同名作者误导），输出情报简报存档。**机会看板按用户要求砍掉** |
| **档案** | 长期知识档案 | ◐ 轻量落地 | `profile.json` 为唯一权威画像（三工具硬编码常量已删除，改经 `tools/user_profile.py` 加载）；`read_papers.json` 已读论文库（M5 自动入库+rebuild）；`target_advisors.json` 目标老师清单（收藏/已读论文/已发邮件/已回复四档进度，另支持 author_en+keywords 供 M6 arXiv 归属过滤）；`error_patterns.json` 错误回流库。待补：知识水位自动更新、技能 gap 清单、机会档案 |

## 3. 核心设计原则 (铁律)
1. **绝对反幻觉**：所有事实陈述必须基于工具抓取的真实文本，拒绝 LLM 自行脑补。工具返回结果中包含 `verification_warnings`，未通过原文校验的句子必须向用户如实标注。
2. **保留证据原文**：展示导师信息或论文拆解时，必须保留 `evidence` 原句引用，确保可溯源。
3. **算力红线限制**：在生成进组项目时，严格遵守用户本地硬件限制（设备A：仅支持≤3B量化模型；设备B：标准GPU，支持大模型微调）。
4. **诚实降级**：查不到信息的老师明确说"无数据/未收录"，不硬凑证据。

## 4. 目录结构

```
advisor_agent/
├── main.py                  # Agent 主程序：聊天循环 + function calling 派发（22 个工具）
├── web_server.py            # 本地 Web 聊天页后端（复用 main 的 CLIENT/TOOLS/DISPATCH）
├── config.py                # LLM 提供商与 API_KEY（已被 .gitignore 排除，不入库）
├── tools/
│   ├── llm_client.py        # ★共享层：模型表与 LLM 客户端的唯一来源（fast/mid/long 三档角色）
│   ├── fetch_common.py      # ★共享层：抓取（UA/超时/SSL 降级/编码修正/HTML 清洗）
│   ├── text_norm.py         # ★共享层：引句归一化比对（反幻觉校验的唯一实现）
│   ├── store.py             # ★共享层：卡片与深潜报告读取归口
│   ├── selftest.py          # 离线自检：跑一遍确认共享层与关键契约没退化
│   ├── crawl_faculty.py     # 工具一：师资名单抓取器（通用层 fetch/合并/落盘 + 站点适配器）
│   ├── enrich_faculty.py    # 工具二：详情页追踪器 v2.2（抓教师详情页正文 + 外链列表）
│   ├── llm_card.py          # 工具三：LLM 导师卡片生成器 v2.2（含 verify_evidence 反幻觉校验）
│   ├── batch_cards.py       # 工具四：批量卡片生成器 v2.1
│   ├── universal_crawl.py   # 工具五：通用师资抓取器（LLM 驱动，适配任意学校的师资页）
│   ├── paper_tools.py       # 工具六：论文检索与全文获取（arXiv/EuropePMC/OpenAlex/官网PDF）
│   ├── analyze_paper.py     # 工具七：论文拆解器 v2（决策卡 + 七段精读 + verify_quotes）
│   ├── critique_thinking.py # 工具八：M5 思考批改（run_grading 批改 + appeal 申诉复核）
│   ├── advisor_deepdive.py  # 工具九：M2 导师深潜（多信源抓取 + 逐字证据校验）
│   ├── path_analysis.py     # M4 进组路径分析（需求侧/供给侧/敲门砖项目 + 双硬件红线检查）
│   ├── compare_advisors.py  # M1.5 对比视图（panorama 全景表纯本地 / deep_compare 调LLM打分）
│   ├── monitor.py           # M6 实时情报监测（主页快照 diff + arXiv + GitHub）
│   ├── monitor_daily.py     # M6 定时任务入口（Windows 计划任务调用）
│   ├── knowledge_store.py   # 长期档案：已读论文库 + 目标老师清单
│   ├── memory.py            # 动态记忆：画像自动生长 + 事件时间线
│   ├── chat_history.py      # 会话历史落盘与回看（/history）
│   ├── user_profile.py      # 用户画像唯一权威读取口（archive/profile.json）
│   ├── web_fetch.py         # 网页抓取（给 Agent 的 fetch_url + 无头浏览器渲染）
│   └── add_career_note.py   # 历史一次性补丁（已完成，保留备查，勿再依赖）
├── prompts/                 # 预留目录（暂空）
├── archive/                 # 长期知识档案
│   ├── profile.json         # 用户画像：兴趣方向 / 已掌握 / 学习中 / 双硬件红线
│   └── error_patterns.json  # M5 错误模式回流库（日期 + 论文 + 错误类型 + 原话 + 纠正）
└── data/
    ├── faculty_{site}.json          # 师资名单（crawl_faculty / universal_crawl 产物）
    ├── faculty_{site}_enriched.json # 追踪详情页后的名单（含 detail_text + external_links）
    ├── cards_{site}.json            # 导师卡片库（Agent 检索的主要数据源）
    ├── papers/                      # 论文全文(.txt)、检索结果(search_*.json)、拆解与批改产物
    ├── deepdive/                    # M2 深潜报告、信源缓存、M4 路径报告、M1.5 对比结果
    └── monitor/                     # M6 主页快照、arXiv/GitHub 已见记录、情报简报
```

### 4.1 共享基础设施（新增工具前必读）

**规则：需要 LLM / 抓网页 / 比对引句 / 读卡片与报告时，一律调用共享层，禁止再抄一份。**

| 共享模块 | 提供 | 曾经的问题 |
|---|---|---|
| `llm_client` | `make_client()` / `model_for("fast"\|"mid"\|"long")` | 曾 11 份模型表副本、10 处各自新建客户端，同类任务在不同入口用了不同模型 |
| `fetch_common` | `get()` / `strip_html()` / `clean()` / `UA` | 曾 6 套独立抓取、4 种 UA、4 种超时与 SSL 策略 |
| `text_norm` | `flat()`（去空白）/ `loose()`（去标点并小写） | 曾 6 个文件各写一份归一化，反幻觉校验标准不一致 |
| `store` | `find_card()` / `iter_cards()` / `load_deepdive_report()` / `has_deepdive()` | 曾"按姓名找卡片"在 3 处、报告路径拼接在 4 处各写一遍 |

模型角色按**上下文长度**而非功能命名：`fast`=短任务（决策卡/卡片/深潜/路径/对比）、`mid`=中等长文（名单与官网论文提取）、`long`=长文（精读拆解、M5 批改）。换模型只改 `llm_client.py` 一处。

改动共享层或工具后，先跑离线自检确认没退化：

```bash
python tools/selftest.py      # 不联网、不调 LLM、不改动 data/archive
```


## 5. 数据产物（data/ 目录）

| 文件 | 生成者 | 内容 |
|---|---|---|
| `faculty_{site}.json` | crawl_faculty / universal_crawl | 师资名单原始抓取结果，带抓取日期 |
| `faculty_{site}_enriched.json` | enrich_faculty | 每位教师补充 `detail_text`（详情页正文）与 `external_links`（外链列表） |
| `cards_{site}.json` | batch_cards | `{count, cards[]}`；卡片字段：`name / title / research_interests / current_focus{ text, evidence } / career_stage / recruitment{ level 🟢🟡⚪, evidence, note } / homepage_candidates[ {url, label, type} ] / summary / _verification` |
| `papers/search_{author}.json` | paper_tools | arXiv 检索结果（含作者位置、是否末位作者） |
| `papers/{arxiv_id}.txt` | paper_tools | 论文全文（PDF 解析为纯文本） |
| `papers/{arxiv_id}_analysis.json` | analyze_paper | `{decision_card, analysis, verification_warnings}`（M3 精读产物） |
| `papers/{arxiv_id}_grading.json` | critique_thinking | `{arxiv_id, date, fact_errors, verification_warnings, depth, condensed}`（M5 批改产物） |
| `deepdive/{name}_report.json` | advisor_deepdive | `{name, date, sources, report, verification_warnings, fetch_failures, used_fallback}`（M2 深潜报告，五个维度） |
| `deepdive/{name}_src{i}.txt` | advisor_deepdive | 信源原文缓存（校验与溯源用） |
| `deepdive/{name}_path.json` | path_analysis | `{demand, supply, actions, summary}`（M4 进组路径） |
| `deepdive/compare_result.json` | compare_advisors | `{matrix, summary}`（M1.5 深度对比打分矩阵） |

## 6. 运行方式

### 6.1 启动主程序
```bash
python main.py
```
- 直接用中文对话，输入 `quit` 退出；
- `/m` 回车进入多行模式（逐行粘贴，单独一行 `EOF` 结束）；
- `/f 路径` 读取整个文本文件当一条消息（如提交 M5 思考）。

LLM 配置在 `config.py`：`PROVIDER` 支持 `moonshot`（fast=8k / long=128k 双模型分工）与 `deepseek`（单模型），该文件已被 .gitignore 排除。

### 6.2 收录一所新学校（三步）
1. 在对话中提供师资名单页网址 → Agent 调 `add_school(url, site_name)`（内部运行 universal_crawl.py，LLM 驱动提取名单）；
2. `python tools/enrich_faculty.py {site}` —— 逐人追踪详情页，抓正文与外链；
3. `python tools/batch_cards.py {site}` —— LLM 批量生成结构化卡片并逐条反幻觉校验。

### 6.3 各模块触发话术（对话内自然语言即可）
| 模块 | 示例话术 |
|---|---|
| M1 检索 | "collegeai 站有哪些做 LLM 的老师？" / "看看某位老师的卡片" |
| M1.5 全景 | "已收录的老师全览一下" |
| M1.5 深度对比 | "对比一下几位老师"（2-5 人） |
| M2 深潜 | "深挖一下某位老师"（无个人主页时 Agent 会请用户提供主页 URL 重试） |
| M3 论文 | "查一下某位老师近期的论文" → 选定 → "先出决策卡" → "精读这篇" |
| M5 批改 | 精读后 `/f thinking.txt` 提交思考；不认可结果就说"我要申诉" |
| M4 进组 | "我想进某位老师的组，帮我规划一下该做什么项目" |

## 7. Agent 工具清单（main.py 注册的 22 个 function）

| 工具 | 模块 | 说明 |
|---|---|---|
| `list_sites` | M1 | 列出已收录站点及人数 |
| `list_teachers` | M1 | 按站点/方向关键词/招生信号筛选老师 |
| `get_card` | M1 | 查看完整卡片（含全部 evidence） |
| `add_school` | M1 | 收录新学校师资页（universal_crawl），收录后自动跑 enrich+batch 生成卡片 |
| `fetch_url` | M1 | 抓网页正文+链接，Agent 自主导航定位院系/师资页/个人主页 |
| `bookmark_advisor` | 档案 | 收藏/更新目标老师（接触进度四档 + author_en + keywords） |
| `list_targets` | 档案 | 查看目标老师清单 |
| `monitor` | M6 | 扫描收藏老师主页 + arXiv 新论文，输出情报简报 |
| `monitor_show` | M6 | 查看监测历史简报 |
| `remember` | 记忆 | 用户口述新信息写入长期画像（技能/在学/项目/兴趣/备注） |
| `show_profile` | 记忆 | 展示当前画像与近期记忆 |
| `search_papers` | M3 | 按作者英文名查 arXiv 近期论文 |
| `fetch_fulltext` | M3 | 多级获取论文全文（DOI/PDF直链/PMCID/本地PDF），返回 paper_id |
| `lab_publications` | M3 | 单独提取实验室官网 Publications 页论文列表 |
| `paper_decision` | M3 | 第0步阅读决策卡（定位/匹配度/建议/前置缺口） |
| `deep_dive` | M3 | 七段框架精读 + 反幻觉校验 |
| `critique_thinking` | M5 | 事实纠错/偏题检测/费曼追问/凝练段落 |
| `appeal_grading` | M5 | 申诉复核：重新核对批改中的每条引用 |
| `advisor_deepdive` | M2 | 深潜报告（五维度 + 逐字证据） |
| `path_analysis` | M4 | 进组路径（需先有 M2 报告） |
| `panorama` | M1.5 | 全景表（纯本地，不调 LLM） |
| `deep_compare` | M1.5 | 深度对比（2-5 人，七项指标打分矩阵） |

System Prompt 中固化了 11 条行为规则：工具返回什么就说什么、traceback 摘要告知用户、`verification_warnings` 非空必须如实转述、M5 批改时思考原文原样传入禁止改写、申诉时不自行辩护等。

## 8. 反幻觉校验机制（三层，全部落盘可溯源）

| 层 | 实现位置 | 规则 |
|---|---|---|
| 卡片层 | `llm_card.verify_evidence` | 每条 evidence（去空白归一化后）必须逐字出现在详情页原文中；`homepage_candidates` 的 URL 必须来自详情页外链列表——**防止 LLM 凭记忆编造个人主页**。结果写入卡片的 `_verification` 字段 |
| 论文层 | `analyze_paper.verify_quotes` | 拆解中所有 quotes 归一化（剥掉非字母数字汉字字符，免疫 PDF 提取的折行连字符/空格/标点差异）后必须在论文全文中找到 |
| 深潜层 | `advisor_deepdive.verify_report` | 每条 point 的 evidence 必须能在其标注的 `source` 编号对应信源原文中找到；source 编号越界同样报警 |

所有校验结果统一以 `verification_warnings` 列表返回，非空时 System Prompt 强制 Agent 向用户如实转述，M5 还提供 `appeal_grading` 申诉复核通道（批改者自己也可能幻觉）。

## 9. 长期知识档案（archive/，对应设计文档第 6 节）

- **`profile.json`**：用户画像活版本——`interests`（ML/LLM/CV/具身/AI4Science）、`known`（已掌握概念，前置解释的判定依据）、`learning`（在学中）、`hardware`（设备 A/B 算力红线摘要）。M3 拆解器启动时加载。
- **`error_patterns.json`**：M5 批改发现的知识性错误按条回流（日期 + arxiv_id + 错误类型 + 用户原话 + 纠正），已收录真实条目（如"预训练/微调数据顺序说反""准确率数字记错"）。
- **现状**：2026-09-04 画像合一完成——`archive/profile.json` 是唯一权威版本（含项目经历、双硬件红线三档明细），M4/M1.5/M5 一律经 `tools/user_profile.py` 实时加载，各工具里的硬编码常量已删除。改画像只改这一个 JSON 文件。
- **已落地**：`read_papers.json` 已读论文库（M5 批改后自动入库，凝练段落=申请素材库；`python tools/knowledge_store.py rebuild` 可全量重建）；`target_advisors.json` 目标老师清单（bookmark_advisor 工具，收藏/已读论文/已发邮件/已回复四档接触进度，是 M6 监测的触发依据）。
- **待补**：知识水位自动更新（拆解后更新 known 列表）、技能 gap 清单（M4 历次汇总）、机会档案（历年活动开放时间）。

## 10. 与设计审计文档 v0.4 的差距（v2 待办）

| # | 事项 | 现状 |
|---|---|---|
| 1 | ~~M6 实时情报监测~~ | ✅ 2026-09-04 完成：主页快照 diff + arXiv 新论文（关键词归属过滤防同名误导）+ 情报简报存档。GitHub/Scholar 源暂未接，可后续扩 |
| 2 | ~~院校机会监测与倒计时~~ | 按用户要求砍掉，不做 |
| 3 | ~~M1 输入泛化~~ | ✅ 2026-09-04 完成：fetch_url 接入 main.py，实测导航上交找到 AI学院/计算机/电院 三个师资页并成功收录 |
| 4 | **深度对比七项指标口径对齐** | 现实现为：方向匹配/招生信号/计算相关度/信息透明度/进组可行性/组内活跃度/竞争门槛；设计文档 v0.4 为：方向匹配度/科研活跃度/本科生友好度/培养产出/资源与开放度/竞争烈度/可达性。需决定以哪版为准 |
| 5 | 全景表按列排序、勾选交互 | 目前为固定精简列表 |
| 6 | ~~档案自动化回流 + 双轨画像合一~~ | ◐ 2026-09-04 完成画像合一（profile.json 唯一权威）；已读论文库/目标老师清单/错误库已落；仍缺：知识水位自动更新、技能 gap 清单、机会档案 |
| 7 | M2 深潜的"合作网络/工程足迹"维度（GitHub 数据） | 深潜五维度中未单列，依赖个人主页内容 |
| 8 | ~~M1 卡片增强：职业阶段简评（对申请者的实际含义）~~ | ✅ 已完成：`career_stage.note` 已回填（`add_career_note.py` 一次性补丁，325 张有 stage 的卡片均带简评）；无主页标注、官网/主页冲突标注仍未做 |
| 9 | ~~收录流程自动化：enrich+batch 目前需用户在终端手动跑两步~~ | ✅ 已完成：`add_school` 内部串行调用 universal_crawl → enrich_faculty → batch_cards，Agent 无需用户敲命令 |

## 11. 已知问题

- **arXiv 接口不稳定（环境相关）**：`export.arxiv.org` 的 http 会 301 到 https，而该域名 https 从本机常年偏慢（实测 14s 成功与 >30s 超时交替出现），高峰时返回 429 限流。`search_papers` 已把接口超时放宽到 45s 并带 3 次退避重试（6→12→24s），失败时会明确报错而非静默返回空。Europe PMC 与国内站点访问正常。
- **已读论文库 / 错误模式库没有 Agent 读取入口**：`archive/read_papers.json`、`archive/error_patterns.json` 目前只写不读（写入由 M5 批改触发），只能用 `python tools/knowledge_store.py show` 在终端查看；若要让 Agent 引用（如"我读过哪些论文"），需要新增工具。
- **若干产物只写不读**：`data/deepdive/{name}_path.json`（M4）、`data/deepdive/compare_result.json`（M1.5）、`data/monitor/每日简报_*.txt`（M6 定时任务）落盘后没有消费方，属于留痕而非数据源。
- arXiv 版本 ≠ 发表版本，引用时未做版本标注（设计文档数据源表中的注意事项）。

## 12. 明确不做（划界，来自设计审计文档）

不自动发邮件、不替用户做申请决策、不抓取需要登录的平台数据、不输出无来源断言、不维护两套 Agent 代码、不用生活比喻解释概念。

## 13. 本地 Web 聊天界面（2026-09-04 新增）

零依赖，复用 main.py 的 function calling 链路。启动：
```bash
conda activate advisor
python web_server.py          # 浏览器打开 http://127.0.0.1:8080
```
- 单页聊天，前端渲染 markdown 表格/证据折叠/工具调用痕迹；支持多轮历史（messages 整段回传）。
- 后端 `web_server.py`：http.server + POST /chat，agent.SYSTEM/TOOLS/DISPATCH 复用；ChatCompletionMessage 转 JSON 安全 dict。
- 与 CLI `python main.py` 功能完全一致，只是多了可读性更好的页面。
