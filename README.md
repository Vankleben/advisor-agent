# 导师情报与论文伴读 Agent

给找科研实验室的 CS 大三学生用的本地智能体：导师情报、论文精读、思考批改、进组路径规划、目标老师监测，一套对话完成。

> 反幻觉铁律贯穿始终：每条事实都挂原文证据，查不到就明说"无数据"，绝不编造。

---

## 快速开始

需要：Python 3.11+（建议 conda `advisor` 环境）、一个 API key（当前用 deepseek）。

```bash
# 1. 装依赖（首次）
pip install openai requests beautifulsoup4 pymupdf

# 2. 配置 key
# 编辑 config.py（已被 .gitignore 排除，不会提交）
PROVIDER = "deepseek"
API_KEY   = "sk-xxx"

# 3. 启动 —— 二选一
python main.py                     # 终端对话
python web_server.py              # 浏览器 http://127.0.0.1:8080 （更易读的界面）
```

---

## 七个模块（都能用）

| 模块 | 功能 | 对话里怎么说 |
|---|---|---|
| M1 导师情报 | 从学校名导航到师资页→自动收录→出卡片（含🟢招生信号/职业阶段简评）；查/筛/看卡片 | “看看清华有哪些做 LLM 的老师”“朱松纯的卡片” |
| M1.5 对比 | 全景表全览；选 2-5 人七项打分 | “全览一下”“对比俞立和王童” |
| M2 深潜 | 抓主页→7 维度报告（研究轨迹时间线/GitHub 足迹/招生意向/学生去向…） | “深挖俞立” |
| M3 论文拆解 | arXiv 检索→阅读决策卡→七段精读（原文佐证+反幻觉校验） | “查 Dong 的论文”→“先出决策卡”→“精读这篇” |
| M4 进组路径 | 需求侧/供给侧/敲门砖项目（设备A/B算力红线） | “怎么进俞立的组” |
| M5 思考批改 | 纠错+偏题+费曼追问+凝练+申诉复核 | 精读后提交思考；不服可说“申诉” |
| M6 实时监测 | 收藏老师主页diff+arXiv+GitHub 情报简报；**已配每日 9 点自动跑** | “看看收藏的老师有什么新动态” |

**数据现状**（2026-09-04）：清华 collegeai(93) + 清华 life(126) + 北大智能学院(36) + 复旦计算与智能创新学院(190) + 上交 AI(16) = **461 张卡片**。

---

## 核心设计（铁律）

1. **绝对反幻觉**：所有事实基于工具抓取的原文；`verification_warnings` 非空必须如实告知。
2. **保留证据原文**：卡片/深潜/精读都带 evidence 原句，可溯源。
3. **算力红线**：M4 敲句砖项目区分设备 A（≤3B 量化）/设备 B（RTX3060，可 LoRA 微调），超红线方案不出现。
4. **诚实降级**：查不到就说无数据，绝不硬凑；无个人主页/无招生信息如实标注。

---

## 目录结构

```
advisor_agent/
├── main.py / web_server.py / web/index.html   # 终端 + Web 双入口
├── tools/
│   ├── crawl_faculty.py       # 特定高校师资页适配抓取
│   ├── universal_crawl.py     # LLM 驱动通用师资抓取（分页合并）
│   ├── enrich_faculty.py      # 抓每位老师详情页
│   ├── llm_card.py            # LLM 生成导师卡片（含反幻觉校验）
│   ├── add_career_note.py     # 给卡片补职业阶段简评
│   ├── paper_tools.py         # arXiv 检索/下载
│   ├── analyze_paper.py       # 论文精读（决策卡+七段）
│   ├── critique_thinking.py   # M5 思考批改+申诉
│   ├── advisor_deepdive.py    # M2 深潜（7 维度）
│   ├── path_analysis.py       # M4 进组路径
│   ├── compare_advisors.py    # M1.5 对比
│   ├── web_fetch.py           # 网页抓取（render_url 支持 JS 页面）
│   ├── monitor.py / monitor_daily.py  # M6 监测
│   ├── knowledge_store.py     # 档案（已读论文/目标清单）
│   └── user_profile.py        # 画像加载
├── archive/                   # 用户画像/错误回流/已读论文/目标清单
├── data/                      # 卡片/论文/深潜/监测数据
└── docs/code.md               # 详细进度文档
```

---

## 手动工具用法（终端）

```bash
# 学校收录（分页自动合并）
python tools/universal_crawl.py <师资页URL> <站点代号>
python tools/enrich_faculty.py <站> && python tools/batch_cards.py <站>

# 论文
python tools/paper_tools.py search "Yinpeng Dong"
python tools/paper_tools.py fetch <arxiv_id_or_num>

# 监测
python tools/monitor.py scan | python tools/monitor_daily.py

# 档案
python tools/knowledge_store.py rebuild | show | bookmark 姓名 --note 备注

# 每日定时（已注册 / 重装）
setup_monitor_task.bat
```

---

## Web 界面说明
- 启动：`python web_server.py` → 浏览器打开 `http://127.0.0.1:8080`
- 单页聊天，渲染 markdown 表格/证据折叠/工具调用痕迹；多轮历史自动保持
- 功能与终端完全一致，只是更好读

---

## 已知限制 / 缺口

- **浙大、西湖**官网在你当前网络下无法访问（SSL/连接被掐，非代码问题）；需换网络环境再收。
- **复旦/浙大/西湖**师资页是 JS 动态页，复旦已用 Chrome headless 解决；其余待网络通后同法。
- 论文检索目前只 arXiv；对比七指标口径与设计文档 v0.4 不完全一致（文档在 docs/）。

---

## 开发规范（重要）

- **每次修改文件后立即 git 提交**（用户永久规则，存于 D:\zcode_memory\AGENTS.md）。
- 反幻觉：任何工具返回带 verification_warnings / traceback 时，如实转述，不掩盖。
- 永久档案都存 `archive/`，不发散。