## 新增：实验室官网 Publications 兜底

老师实验室网站里的 **Publications 板块**是 PI 自己维护的成果列表，**最权威**。
现在 Agent 会在这里兜底找论文——适用场景：新组、冷门方向、非 arXiv 领域。

### 论文检索现在是三重来源

| 顺序 | 来源 | 覆盖范围 |
|---|---|---|
| 1 | **arXiv** | CS / 物理 / 数学 |
| 2 | **Europe PMC** | 生物医学期刊（Cell / Nature / Molecular Cell…） |
| 3 | **实验室官网 Publications** ← 本次新增 | PI 自维护的完整成果列表 |

前两个都查不到时，Agent 会自动去实验室网站找 Publications 页提取。

### 实现要点

- 自动定位实验室站点里的 Publications / 论文 页面（支持 React/Vue 单页应用渲染）
- LLM 结构化提取：标题 / 作者 / 期刊 / 年份 / 链接
- 反幻觉校验：提取的标题必须在页面原文中真实存在（归一化比对）

### 实测

某实验室网站 → 提取 **14 篇论文**（含 Nature、Cell Stem Cell、Cell Research 等期刊）；
标题、作者、期刊、年份全部完整，未混入任何虚构条目。

---

## 同样包含（本轮相关修复）

- **SPA 站点多页抓取**：Agent 可点开实验室网站各子页面读全站（首页 → 研究/成员/论文/招聘，聚合 7 页 / 18000 字符）
- **Windows GBK 编码崩溃修复**：收录流程曾因 print emoji 中断
- **反幻觉校验升级**：区分「引句真实但标错页码」与「真的幻觉」

完整变更见 [v1.4](https://github.com/Vankleben/advisor-agent/releases/tag/v1.4) 与上方 commit 记录。
