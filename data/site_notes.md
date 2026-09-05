# 目标院校站点可达性记录（2026-09-04 探测）

| 站点 | 状态 | 说明 |
|---|---|---|
| 清华 collegeai | ✅ 已收录 | 静态师资页，93人卡片 |
| 清华 life | ✅ 已收录 | 126人卡片 |
| 北大 sai(pkusai) | ✅ 已收录 | 分页合并36人，卡片已建 |
| 上交 sjtuai | ◐ 已填名单未建卡 | faculty_sjtuai.json 16人，待 enrich+batch |
| 复旦 计算与智能创新学院 | ✅ 已收录 | render_url(Chrome headless) 解决 JS 名单页，190 人卡片 |
| 浙大 zju | ❌ 网络不可达 | www.cs.zju.edu.cn SSL EOF/ERR_CONNECTION_CLOSED，Chrome 也连不上，属网络层拦截，非代码可解 |
| 西湖大学 | ❌ 间歇性断连 | 首页偶可达，深层约/faculty/ 页 ERR_CONNECTION_CLOSED；需换网络环境 |

结论：浙大/西湖/复旦三校官网师资名单均为 JS 动态渲染，基于 requests 的抓取拿不到名单。
要自动收录需引入 headless 浏览器（playwright/puppeteer）。在引入前，如实标注"未收录"，不伪造名单（反幻觉铁律）。
