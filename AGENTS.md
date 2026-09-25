# AGENTS.md — 项目约定

本文件记录本仓库的开发与发布约定，供协作者与 AI 助手遵循。

## 提交

- 每次修改后立即提交（小步提交）；提交信息写清"改了什么、为什么"。

## 发布（Release）

- **小修复不发 Release** —— git commit 足以记录；
- 只有**成块的功能更新**才发 Release，说明保持 **3-5 行简短**；
- Release 说明只写面向用户的功能变化，**不写内部维护事项**（如数据清理、历史重写等）。

## 数据与隐私（硬规则）

- `data/` 与 `archive/` 已被 `.gitignore` 覆盖，**永不提交、永不推送**（用户数据只留本地）；
- 代码与文档中**不得出现**：真实姓名、学校/单位名、硬件具体型号、具体老师姓名与个人主页；
  - 一律用占位符：张三 / 李四 / John Smith / 某教授 A / 某实验室；
- 提交前用 `git status` 检查一遍，确认没有数据文件混入暂存区。

## 环境与验证（硬规则）

- **项目运行在 conda 环境 `advisor`（Python 3.11）**：一律用 `conda run -n advisor python ...` 调用，
  **不要硬编码某个盘符下的 python.exe 路径**（换机器/换电脑会直接失效）；
  环境不存在时先 `conda create -n advisor python=3.11 -y` 再装 README 里的依赖。
  shell 里默认的 `python` 可能是 3.14+，**不能用它验收**——3.14 起注解延迟求值（PEP 649），
  "删了 import 却留着类型注解"这类错误在 3.14 不报错、在 3.11 直接 NameError（曾导致 main.py 起不来）。
- 验证命令一律：`conda run -n advisor python tools/selftest.py`，
  必要时再实跑一次入口：`conda run -n advisor python main.py`（喂 `quit` 即可）。
- 改完共享层或工具后先跑自检（`tools/selftest.py`，不联网/不调 LLM/不改数据），全绿再提交。

## 代码结构（硬规则）

**要 LLM、要抓网页、要比引句、要读卡片/深潜报告时，一律调用共享层，禁止再抄一份。**

| 需求 | 用哪个 | 禁止 |
|---|---|---|
| 调 LLM | `tools/llm_client.py`：`make_client()` + `model_for("fast"\|"mid"\|"long")` | 自己写 `OpenAI(...)` 或模型表 |
| 抓网页 | `tools/fetch_common.py`：`get()` / `strip_html()` / `clean()` | 自己 `requests.get` + UA + 清洗正则 |
| 比对引句是否真在原文 | `tools/text_norm.py`：`flat()` / `loose()` | 自己写正则归一化 |
| 读卡片 / 深潜报告 | `tools/store.py`：`find_card()` / `iter_cards()` / `load_deepdive_report()` | 自己 glob `cards_*.json` 拼路径 |
| 用户画像 | `tools/user_profile.py`（源头 `archive/profile.json`） | 自己读 profile.json 或硬编码画像 |

- 新增/修改工具后先跑 `conda run -n advisor python tools/selftest.py`（不联网、不调 LLM、不改数据），全绿再提交；
- 跨模块传消息不要靠"字符串前缀约定"（历史事故：monitor 写"新仓库/新动态"、判定查"新仓库/新推送"，功能静默失效）——要沉淀成模块级常量或结构化字段，并由自检覆盖；
- 修 bug 时优先找同类重复实现：同一个坑往往不止一处。

## 推荐判断：Jev 自动评判（AI 助手做导师推荐时遵循）

用本项目检索出导师后，进入"推荐/排序/谁适合用户"的判断环节时，**自动调用 Jev 决策模型，不等用户点名**：

1. 逐候选调 `mcp__jev__rate`（context=卡片/深潜证据+用户画像+检索目标；question=适配度综合判断；scale=`["低","中","高"]`）；
2. 证据存疑项用 `mcp__jev__judge` 布尔处置（如"是否搁置待核"）；
3. 输出三件套：**Jev 分数+置信度 | 人工理由（他做什么/为何适合/证据出处） | 行动建议**；
4. `confidence < 0.5` 标注"证据不足，建议深潜补证"；Jev 与人工分歧时并列呈现，不擅自覆盖。
（完整规则在用户级 `~/.zcode/AGENTS.md`；本节随仓库分发，fork 后同样生效。）
