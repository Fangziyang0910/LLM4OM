# LLM4OM 官网与文档中心

面向大众的中英文宣传站，署名 EIPI 团队。第二版包括生产、排班、配送三个可操作示例，六张新采集的双语深色工作台截图、三步使用介绍和常见问题。示例支持播放、暂停、跳过、修改条件及下载 CSV。正文不展示方法清单、调用消耗或终端安装命令。

Docs 沿用官网风格，提供 46 篇文章、92 个中英文页面：快速开始与基本概念、13 篇功能指南、13 种方法、9 个建模库、求解后端、部署、CLI / Python 和故障排查。文章包含机制、输入输出、完整代码与操作案例；68 张双语 Mermaid 图在构建时生成 SVG，方法图与逐步案例联动。五类交互案例包括生产、方案对话、数据编辑、凸优化和局部搜索，另有双语工作台录屏与字幕。侧栏、页内目录、全文搜索、代码复制、手机目录和同章节语言切换沿用现有框架。

## 生成文档

先准备主项目 Python 环境与前端依赖（已有环境可直接复用）：

```bash
uv sync --all-extras
npm --prefix frontend ci
npm --prefix website ci
npm --prefix website run build
```

文档源稿位于 `content/zh/` 和 `content/en/`，文章信息位于 `docs-manifest.json`。生成器复用 React Markdown、GFM、remark-math、KaTeX 和 highlight.js，生成静态 HTML 与搜索索引；方法参数直接读取当前注册表。Mermaid 为独立构建依赖，复用 Playwright 渲染 SVG，按源码和配置哈希缓存。构建校验图源、13 个方法与 9 个库覆盖；发布文件可直接静态托管。

Markdown 中 `mermaid` 围栏生成可下载和放大的图；`walkthrough` 围栏使用 JSON 数组定义 title、nodes、body、artifact，nodes 对应 Mermaid 节点 ID。方法图完整展示主要流程，点击或播放步骤会高亮对应节点；宽屏并排呈现，窄屏上下排列。`demo` 围栏可选 production、plans、data、convex、local；`video` 的 workbench 插入对应语言录屏、片段跳转和字幕文字。普通公式由 KaTeX 在构建时排版，字体和许可一起发布。交互不自动播放，支持暂停、键盘和减少动态效果。

只编辑源稿和生成器，再重新生成；不要手动编辑 `public/docs/{zh,en}/` 或搜索索引。`public/docs/docs.css` 和 `docs.js` 是文档的共享样式与交互源文件。网站仍可直接以静态文件发布。

## 本地预览

在仓库根目录运行：

```bash
npm --prefix website run dev
```

打开 http://127.0.0.1:8831/。右上角切换语言；也可以用 `?lang=en` 直接分享英文版，或 `?lang=zh` 分享中文版。语言选择会在当前浏览器保存。

预览复用前端已安装的 Vite，支持视频片段跳转所需的 HTTP Range 请求。

文档入口为 `/docs/zh/introduction/` 与 `/docs/en/introduction/`；`/docs/` 会按链接参数或已保存偏好进入对应语言。更新内容时，先生成文档，再同步 `public/` 发布。

## 用 GitHub Pages 发布

宣传站使用同一仓库的 `gh-pages` 分支根目录发布。该分支仅保存 `website/public/` 内的静态文件，无需安装 Node.js 或运行前端构建，不包含平台运行数据、测试或设计记录。

1. 检查页面后，把 `website/public/` 的内容同步到独立的 `gh-pages` 检出目录，包含 `.nojekyll`。
2. 在该分支提交并推送。不要从当前 `main` 分支直接推送未发布的平台提交。
3. **Settings → Pages → Build and deployment** 使用 **Deploy from a branch → gh-pages → / (root)**。GitHub 会在该分支更新后重新发布。
4. 站点地址为 `https://fangziyang0910.github.io/LLM4OM/`。可以用 `?lang=en` 或 `?lang=zh` 分享指定语言。

仓库已公开，发布分支为 `gh-pages`。[中文官网](https://fangziyang0910.github.io/LLM4OM/?lang=zh)、[英文官网](https://fangziyang0910.github.io/LLM4OM/?lang=en)、[中文Docs](https://fangziyang0910.github.io/LLM4OM/docs/zh/introduction/)和[英文Docs](https://fangziyang0910.github.io/LLM4OM/docs/en/introduction/)可公开访问。每次更新先通过本地检查，再推送发布分支并在线复测。

GitHub Pages 承载官网与文档。完整建模服务仍需 Python、Docker 求解环境和模型服务配置，不能直接运行在 Pages 中。

官方说明：[GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)、[发布来源](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)。

## 检查

复用仓库现有的 Playwright，不添加依赖。先启动预览服务器，再运行：

```bash
node website/check.cjs http://127.0.0.1:8831/
```

检查三个示例的实际计算、条件变化、无解、CSV 下载、完整语言切换与记忆、对应语言的深色素材、键盘页签、大图对话框、FAQ，以及 1440、1280、768、390、360、320 六种屏幕宽度。另在正常动效设置下检查播放、暂停、继续、播放中切语言和排班位置动画。截图保存到忽略提交的 `artifacts/website/v2/`。

文档检查：

```bash
node website/check-docs.cjs http://127.0.0.1:8831/
node website/check-learning.cjs http://127.0.0.1:8831/
```

遍历全部 92 个页面，检查项目子路径下的内部链接与锚点、唯一 ID、双语章节对应、英文正文、全部方法／库覆盖；浏览器检查全文搜索、无结果与失败恢复、键盘操作、代码复制、语言记忆、同章节切换、手机目录、六种宽度和禁用 JavaScript 后的文章阅读。截图保存在 `artifacts/website/docs/`。把地址换成 GitHub Pages 地址可复测线上部署。

学习材料检查另外覆盖全部方法各阶段的节点联动、完整图与字体大小、整数枚举与连续顶点解、凸投影和梯度下降、场景选择、数据保存后单独建模、取消与输入校验、CSV、视频片段跳转与字幕语言、流程图放大、播放暂停和无 JavaScript 内容。九个建模库文章中的首个完整 Python 示例已在本地 Worker 实际求解并核对目标值。

这组检查验证宣传站，不调用真实 LLM 或平台后端。三个示例枚举各自的小型可行集合，显示实际最优解；它们用于介绍操作，不代表完整平台的运行性能。

## 重新采集工作台素材

```bash
node website/capture.cjs
```

复用已有前端、Python 环境、Playwright、ffmpeg 和 Pyomo / HiGHS。脚本启动隔离的本地平台与固定回复适配器，实际求解生产问题与两个变更场景，采集中文、英文深色截图，录制 MP4 并生成 WebVTT 字幕。截图位于 `public/assets/screens/{zh,en}/`，录屏位于 `public/assets/demos/`；日志、原始视频和隔离数据位于忽略提交的 `artifacts/website/`。完成后关闭脚本启动的服务。

## 维护

- 页面结构与中文原文：`public/index.html`。
- 双语文案：`public/translations.js`，每项按 `[中文, English]` 保存。
- 语言、截图、播放与示例交互：`public/site.js`。
- 三个有限示例的计算：`public/examples.mjs`。
- 响应式视觉：`public/styles.css`。
- 文档源稿与目录：`content/{zh,en}/`、`docs-manifest.json`；生成器：`build-docs.mjs`。
- 文档框架与搜索：`public/docs/docs.css`、`docs.js`。
- 学习材料渲染：`doc-components.mjs`、`render-diagrams.mjs`；客户端：`public/docs/learning.mjs`；纯数值计算：`learning-models.mjs`。
- 截图由 `capture.cjs` 新采集；团队标识来自 EIPI 现有官网。Inter 字体的 OFL 许可随站点保留。
- 功能变化时核对主项目 README 和用户指南。不要添加未经核实的效果指标或在线平台地址。
