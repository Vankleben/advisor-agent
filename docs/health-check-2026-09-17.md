# tools/ 体检报告（2026-09-17）

> 范围：`main.py`、`web_server.py` 与 `tools/` 下全部 24 个脚本（含新增的 4 个共享模块 + 1 个自检脚本）。
> 本报告只记录结构性问题与实测证据，不含任何用户数据。

## 一、结论

**结构问题（重复实现 + 跨文件字符串契约）已全部归口；两个真 bug 已修复并各有回归防线。**

改造后的形状是「**星型调度 + 单一共享层**」：`main.py` 仍是唯一调度中枢（22 个工具），但"调 LLM / 抓网页 / 比对引句 / 读卡片与报告"这四件事各自**只剩一个实现**，所有工具都从共享层取。模块依赖图依旧无环（DAG）。

### 量化对比（不含自检脚本自身的检测常量）

| 指标 | 改前 | 改后 | 说明 |
|---|---|---|---|
| 模型表副本（文件数） | 10 | **1** | 只剩 `llm_client.py` |
| `OpenAI(...)` 建客户端处 | 10 | **1** | 同上，且客户端进程内复用 |
| User-Agent 字面量 | 6 | **1** | 只剩 `fetch_common.py` |
| 归一化实现处 | 5 | **1** | 只剩 `text_norm.py` |
| `requests.get(` 直连处 | 17 | **2** | 2 处均在 `fetch_common.get()` 内 |
| `sys.path.insert` 处 | 21 | **5** | 只留 main(2)/web_server(2)/llm_client(1)，策略唯一 |
| 卡片路径 `cards_*.json` 拼接处 | 7 | **5** | 归口到 `store.py`，剩余为列出站点名与历史补丁 |
| Python 文件数 / 总行数 | 22 / 4456 | 26 / 4778 | 净增 4 个共享模块（约 320 行），换来上述收敛 |

## 二、修了什么

| # | 问题（改前） | 处理 | 验证证据 |
|---|---|---|---|
| **P0** | `analyze_paper.py` 在**模块级**读 `archive/profile.json`，而 `main.py` 顶层 import 它 → `archive/` 被 gitignore，**全新克隆的仓库连 `python main.py` 都启动不了**（FileNotFoundError） | 改为函数内延迟读取，经 `user_profile` 取（不再绕过"唯一权威版本"），缺画像时打印提示并降级继续 | 子进程模拟 fresh clone（无 data/archive）：导入成功且优雅降级；已固化为自检项 |
| **P1** | `monitor` 生产者写 `"新仓库/新动态"`，消费方（`monitor` 统计 + `monitor_daily` 判定）查 `"新仓库/新推送"` → **GitHub 更新恒不计数**，简报 summary 与每日简报漏报 | 前缀沉淀为模块级常量 + 新增共享判定 `count_new()` / `has_real_changes()`，`monitor_daily` 改为调用它，同一判定不再写两份 | 同一场景差分对拍：旧版 summary 不报告仓库更新、新版正确报"1 个仓库有更新"；自检含该回归项 |
| P2 | `web_fetch.save_faculty` 全项目零调用（`data/faculty_list_*.json` 从未产生） | 删除 | 接口检查：`fetch_url`/`render_url`/`render_site` 保留 |
| P2 | `paper_tools` 里 `from web_fetch import _find_browser` 未使用 | 删除 | 编译 + 导入检查 |
| P2 | `docs/code.md` 写"18 个 function"，实际 22；目录树缺 8 个文件 | 订正为 22 并补齐 4 行工具说明；目录树补全；新增"共享基础设施"规则节 | 文档与 `TOOLS`/`DISPATCH` 实际条目对齐（自检校验 22==22） |
| P2 | `add_career_note` 是改 `cards_*.json` 的孤儿脚本，无法判断是否还需运行 | 文件头标注为**已完成的历史一次性脚本**并说明后续口径 | 干跑：退出码 0、不产生任何文件改动（325 张有 stage 的卡片均已带 note） |
| 归口 | 11 份模型表 / 10 处客户端 | 新增 `tools/llm_client.py`：`make_client()` + `model_for("fast"/"mid"/"long")`，角色按上下文长度命名 | 自检：模型表副本数必须为 1，否则失败 |
| 归口 | 6 套抓取实现、4 种 UA、策略各异的超时/SSL | 新增 `tools/fetch_common.py`：`get()`（UA/超时/SSL 降级/编码修正/4xx/5xx 抛错）、`strip_html()`、`clean()` | `clean()` 与旧 `web_fetch._clean` 输出**逐字节一致**；本地 HTTP 服务验证 GBK 页编码修正与 404 抛错；线上只读校验真实师资页解析结果与库中历史一致 |
| 归口 | 归一化比对散在 6 个文件 | 新增 `tools/text_norm.py`：`flat()` / `loose()` | 与旧实现逐用例等价（含折行连字符、省略号截断、中文括号、空值） |
| 归口 | "按姓名找卡片"3 处、深潜报告路径拼接 4 处 | 新增 `tools/store.py`：`iter_cards()` / `find_card()` / `load_deepdive_report()` / `has_deepdive()` | `panorama` 新旧输出 592 行逐字段一致；缺失老师返回 `None` 不抛异常 |
| 归口 | `paper_tools` 内 7 处直接 `requests.get`（arXiv/EuropePMC/OpenAlex/PDF 下载） | 全部改走 `fetch_common.get()`；保留其"学术接口限流退避"这一层自有策略 | 300 轮随机输入对拍 `merge_paper_sources` 与旧版完全一致；Europe PMC 线上实测 HTTP 200 正常取数 |

## 三、验证方式（可复现）

1. **差分对拍（最硬的证据）**：把旧版文件从 git 取出、以相同随机输入同时跑新旧实现并逐字段比对 —— `merge_paper_sources` 300 轮一致、`_verify_quotes` 8 类边界用例一致、`panorama` 592 行一致、`clean()` 逐字节一致。**没有靠"看起来对"来验收。**
2. **线上只读校验**（各 1 次 GET，不写任何文件）：真实师资名单页解析 98 条 → 合并 93 人，与库中历史抓取一致；Europe PMC 接口正常返回。
3. **端到端 M6**（临时副本内进行，不碰真实 `data/`）：`monitor.scan()` + `monitor_daily.main()` 全流程跑通；注入 GitHub 账号后确认新增仓库被正确计数并触发简报落盘。
4. **离线自检**：`python tools/selftest.py` —— 9 项全绿（23 模块导入、共享层唯一性、抓取/归一化行为、store 接口、P1 契约、工具表一致、P0 fresh-clone、数据文件只读）。已**反向验证**：故意植入一份模型表副本时，自检会报失败。
5. **数据零改动**：自检前后比对 `data/`+`archive/` 全部 89 个文件的 mtime，无变化；所有端到端测试都在临时副本里做。

## 四、没改的 / 剩余风险

- **arXiv 接口不稳定（环境问题，非代码问题）**：`export.arxiv.org` 的 http 会 301 到 https，而该接口主机从本机常年偏慢——实测同一台机器上 14s 成功与 >30s 超时交替出现，多次请求后返回 429 限流；同时 `arxiv.org`（网站主机，非接口）1.1s 即可达。已把接口超时 30s→45s 并保留 3 次退避重试；失败时 `tool_search_papers` 会记入 `arXiv_错误` 并继续用其余三源（Europe PMC / 官网 / 种子策略），不会静默返回空。**建议换个时段再验证论文检索；若长期如此，可考虑换用其他论文元数据源。**
- **M6 的 GitHub 监测实际未启用**：当前 7 位收藏老师都没填 `github` 字段（`author_en` 同理），所以 P1 修复的是"潜伏 bug"。填上账号后即可生效（归属需人工确认）。
- **两个档案库只写不读**：`archive/read_papers.json`、`archive/error_patterns.json` 由 M5 批改写入，但 Agent 没有读取入口（只能 `python tools/knowledge_store.py show`）。若希望 Agent 回答"我读过哪些论文/我常犯哪类错"，需要新增工具。
- **只写不读的产物**：`data/deepdive/{name}_path.json`、`data/deepdive/compare_result.json`、`data/monitor/每日简报_*.txt` 落盘后无消费方（留痕性质）。
- **M3→M5 仍靠"文件存在性"传递依赖**（有 `_analysis.json` 才能批改），报错信息友好，未改。
- **M1.5 七项指标口径**与设计审计文档 v0.4 不一致，属产品决策，未动。
- `llm_client.make_client()` 在进程内缓存单例：运行中切换 `config.PROVIDER` 不会重建客户端（正常使用不会遇到）。

## 五、日常怎么用

```bash
python tools/selftest.py     # 改完代码先跑这个（不联网/不调 LLM/不改数据）
python main.py               # CLI
python web_server.py         # 本地 Web 界面
```

约定已写入 `AGENTS.md`（"代码结构（硬规则）"）与 `docs/code.md`（4.1 共享基础设施）：**要 LLM、要抓网页、要比引句、要读卡片/报告，一律调共享层，禁止再抄一份；跨模块传消息不得用字符串前缀。**

## 六、本次改动提交（17 个）

4 个共享模块 → P0 → P1 → main/web_server → 6 组工具改造 → paper_tools 传输层 → 自检 → 文档 → 约定。
按项目约定**未发 Release**：本次为内部结构治理，用户可见变化只有 M6 的 GitHub 计数修复，不构成"成块的功能更新"。

## 七、补记（同日事后发现的一处启动崩溃）

报告发布后，实际启动 `python main.py` 报错退出：

```
File "tools/advisor_deepdive.py", line 150, in <module>
    def run_deepdive(client: OpenAI, ...)
NameError: name 'OpenAI' is not defined
```

- **根因**：改造中删掉了 `from openai import OpenAI`，但函数签名里的 `client: OpenAI` 注解留着。
  **验证环境与运行环境不一致**——验证跑在本机默认的 Python 3.14（PEP 649 起注解延迟求值，不报错），
  而项目实际运行在 conda `advisor` 的 Python 3.11（注解立即求值）→ 导入即崩，整个 Agent 起不来。
- **处理**：去掉该注解；自检新增「注解引用的名字都有定义（版本无关）」静态检查（AST 扫描，
  不依赖解释器版本），并做了反向验证（把错误注解还原回去，自检会精确报出文件名与行号）；
  `AGENTS.md` 增加硬规则：**验收必须用项目解释器 `D:\conda\envs\advisor\python.exe`（3.11）**。
- **复验**：3.11 下 24 个模块全部导入、自检 11 项全绿、入口实跑正常；
  本次新增的抓取/解析路径（西湖适配器、SMART 适配器、西湖详情抽取、curl 兜底、卡片外链校验）也全部在 3.11 下重跑通过。
- **教训**：凡是"只在 3.14 下过了一遍"的验证都不算数——这也是把自检写成版本无关静态检查的原因。
