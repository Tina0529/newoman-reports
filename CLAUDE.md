# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GBaseSupport Message Analyzer — chatbot 消息履历分析工具，从 GBase API 或 CSV 文件读取客服对话数据，生成交互式 HTML 分析报告，并通过 GitHub Pages 托管多客户仪表板。

## Commands

```bash
# 运行分析（CSV 模式）
python3 skill/chatbot-message-analyzer/scripts/analyze.py --csv <path.csv> --client "NEWoMan高輪" --period "2025年12月" --output /tmp

# 运行分析（API 模式）
python3 skill/chatbot-message-analyzer/scripts/analyze.py \
  --dataset-id <uuid> --token <bearer_token> \
  --start-date 2025-12-01 --end-date 2025-12-31 \
  --client "NEWoMan高輪" --period "2025年12月" \
  --output /tmp --site-dir docs --client-slug newoman-takanawa

# 安装依赖
pip install pandas requests
```

GitHub Actions 工作流 `update-report.yml` 通过 workflow_dispatch 手动触发，输入 dataset_id、api_token、month 即可自动生成报告并提交。

## Architecture

### 数据流

```
GBase API / CSV → analyze.py → HTML报告 + dashboard-data.json → docs/ → GitHub Pages
```

### 核心组件

- **`skill/chatbot-message-analyzer/scripts/analyze.py`** — 分析引擎。两种模式（CSV/API），处理：未回答判定（3层检测）、问题分类（7个固定类别）、会话深度统计、语言检测、媒体类型识别。输出主报告 HTML 和可选的未回答一览子页面（>10条时生成）。
- **`skill/chatbot-message-analyzer/assets/report-template.html`** — 主报告模板（Jinja2 风格占位符），ECharts 图表，日/中双语切换。
- **`skill/chatbot-message-analyzer/assets/unanswered-template.html`** — 未回答一览子页面模板。
- **`docs/`** — GitHub Pages 静态站点根目录。
- **`docs/assets/js/`** — 仪表板前端：`auth.js`（SHA-256 密码验证）、`dashboard.js`（客户切换、图表渲染、管理面板）、`i18n.js`（JA/ZH 切换）。
- **`docs/clients/clients.json`** — 客户注册表，每个客户含 `slug`、`name`、可选 `hidden`。
- **`docs/clients/{slug}/dashboard-data.json`** — 各客户的月度统计汇总，被 dashboard.js 动态加载。

### 多客户机制

客户通过 `clients.json` 注册，每个客户有独立的 `docs/clients/{slug}/` 目录存放报告和 dashboard-data.json。隐藏客户有双层控制：JSON 中 `hidden: true` + localStorage 持久化。

## Key Conventions

- **设计系统**：Minimalism & Swiss Style。颜色用 CSS 变量（`--primary: #3B82F6` 等）。图标只用 Lucide SVG，禁止 emoji 作 UI 图标。
- **字体**：Inter（英文/数字）+ Noto Sans JP（CJK），通过 Google Fonts CDN 加载。
- **图表**：统一使用 ECharts 5（CDN）。
- **双语**：报告模板和仪表板使用 `data-ja` / `data-zh` 属性实现日/中切换，由 i18n.js 控制。
- **时区**：API 数据从 UTC 转换为 JST（+9小时）。
- **CSV 编码**：自动检测 UTF-8、UTF-8-BOM、Shift-JIS、CP932。
- **未回答判定**：空内容 → 关键词匹配 → 去除垫语后<20字符。
- **General Agent 轨迹剥离**（2026-09-09 起）：General Agent（2026-08-20 切换）的 API `answer` 字段内含执行轨迹 `[TOOL_CALL] … [TOOL_RESPONSE] <检索到的FAQ原文> … [ANSWER] <最终回答>`。检索结果里混入「見つかりませんでした」型 FAQ 会让关键词判定误报，因此 `strip_agent_traces()` 在加载数据后立即把 `回答` 替换为 `[ANSWER]` 之后的最终回答（原文保留在 `回答_raw`）。所有判定/展示只看最终回答。
- **检证账号排除**（2026-09-09 定例合意）：`docs/clients/<slug>/exclude_users.json` 里的 `user_id` 会在加载数据后从统计中排除（也可用 `--exclude-users` 追加）。NEWoMan高輪 现在排除我方 Sparticle検証 和ルミネ様検証各 1 个账号。
- **FAQ 固定回答不算未回答**（2026-09-09 定例合意）：`回答来源` 为 `faq`/`agent_faq` 的消息即使命中「見つかりません」等关键词也不计入未回答。另外 `<NO_ANSWER>`、「確認できておりません」已加入未回答关键词。
- **FAQ 一览 API 分页**：`/datasets/{id}/faqs` 默认排序分页会漏/重复记录，`link_faq_audit._load_all_faqs` 固定用 `size=1000&order_by=id` 并核对 total，件数不一致时打印警告。
- **问题分类**：7 个固定类别（位置/店铺/设施/营业时间/活动/投诉/其他），基于关键词匹配。
- **报告命名**：`{client}_{period}_分析レポート.html`，未回答一览为 `{client}_{period}_未回答一覧.html`。
- **analyze.py 输出到 site-dir 时**，会自动更新对应客户的 dashboard-data.json（追加或更新月份数据）并复制报告文件。
