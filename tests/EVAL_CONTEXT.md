# NEWoMan高輪 Bot 对比测试 - 背景说明

> 本文档为 AI agent 提供本次对比测试的完整背景上下文。

---

## 1. 项目背景

### NEWoMan高輪 (ニュウマン高輪)

NEWoMan高輪是 JR東日本グループ旗下的商業施設（位于高輪ゲートウェイ駅），需要一个面向顾客的 AI チャットボット，用于回答营業時間、店舗情報、アクセス、イベント、施設案内等常见问题。

### GBase 平台

GBase（https://api.gbase.ai）是一个 AI chatbot 平台，提供以下核心能力：

- **RAG (Retrieval-Augmented Generation)**：基于检索增强生成，从知识库中检索相关文档片段后生成回答
- **FAQ**：基于预设问答对的精确匹配回答
- **Streaming API**：通过 SSE 流式返回响应内容

NEWoMan高輪的 AI チャットボット部署在 GBase 平台上。

### 为什么要做这次对比测试

本番環境使用 Gemini 2.5 Flash 模型，在实际运行中存在以下问题：

- 部分问题返回空响应（empty）或仅返回定型句（filler_only），RAG pipeline 未能正常完成
- 需要验证切换到 Claude Sonnet 4.5 后，RAG 执行的稳定性是否有显著改善

---

## 2. 测试目的

**核心目标**：验证将模型从 Gemini 2.5 Flash 切换到 Claude Sonnet 4.5 后，RAG 执行的稳定性是否有显著提高。

具体验证项：

- RAG pipeline 正常完成率（answered + not_found）是否提升
- empty / filler_only 等异常响应是否减少
- 各カテゴリ的回答品質是否保持或改善
- 响应时间是否在可接受范围内

---

## 3. 测试环境

| 项目 | Bot 1（検証環境） | Bot 2（本番環境） |
|------|-------------------|-------------------|
| 环境名称 | NEWoMan高輪 検証環境 | NEWoMan高輪 本番環境 |
| 模型 | Claude Sonnet 4.5 | Gemini 2.5 Flash |
| Bot ID | `fa228b57-59e1-447b-87e2-02c494195961` | `b50d5b21-262a-4802-a8c4-512af224c72f` |
| GBase API | https://api.gbase.ai | https://api.gbase.ai |
| 测试日期 | 2026-02-20 | 2026-02-20 |
| 评测完成时间 | 2026-02-20T19:31:35 | 2026-02-20T22:22:57 |

---

## 4. 测试方法

### 4.1 测试用例

- 共 300 题，定义在 `newoman-takanawa.yaml`
- 覆盖カテゴリ：general(132), location(52), shop(46), food(37), facility(14), hours(6), access(4), product(4), service(3), event(2)

### 4.2 执行流程

1. 通过 `bot_eval.py` 脚本，向 GBase streaming API 逐题发送问题
2. 每题使用独立 session_id，通过 POST `/questions/{bot_id}` 端点发送
3. 解析 streaming 响应，收集：响应内容、响应时间、回答来源（RAG/FAQ）
4. 对每个响应执行分类判定

### 4.3 回答分类判定逻辑

判定按优先级从高到低执行：

1. **empty**：响应为空或仅包含空白字符
2. **error**：匹配系统错误模式（エラーが発生、システムエラー等）
3. **not_found**：匹配"未找到"模式（見つかりませんでした、該当する情報がありません等）
4. **filler_only**：去除定型句（お調べいたします、お探しいたします等）、店名引用、标点后，剩余内容少于 5 字符
5. **answered**：以上均不匹配，判定为已回答（不评估内容正确性）

### 4.4 RAG 稳定性判定

- **RAG 正常处理** = `answered` + `not_found`（RAG pipeline 正常完成，无论是否找到匹配信息）
- **RAG 处理失败** = `empty` + `filler_only` + `error`（pipeline 异常，未能正常返回结果）

---

## 5. 测试结果摘要

### 5.1 总体结果

| 指标 | Bot 1 (Sonnet 4.5) | Bot 2 (Gemini 2.5 Flash) |
|------|---------------------|--------------------------|
| 总题数 | 300 | 300 |
| answered（正常回答） | 288 (96.0%) | 273 (91.0%) |
| unanswered（未回答） | 12 (4.0%) | 27 (9.0%) |

### 5.2 未回答原因分布

| 原因 | Bot 1 (Sonnet 4.5) | Bot 2 (Gemini 2.5 Flash) |
|------|---------------------|--------------------------|
| empty | 0 | 0 |
| error | 0 | 0 |
| not_found | 12 | 25 |
| filler_only | 0 | 2 |

### 5.3 RAG 稳定性分析

| 指标 | Bot 1 (Sonnet 4.5) | Bot 2 (Gemini 2.5 Flash) |
|------|---------------------|--------------------------|
| RAG 正常处理 (answered + not_found) | 300 (100.0%) | 298 (99.3%) |
| RAG 处理失败 (empty + filler_only + error) | 0 (0.0%) | 2 (0.7%) |

### 5.4 回答来源分布

| 来源 | Bot 1 (Sonnet 4.5) | Bot 2 (Gemini 2.5 Flash) |
|------|---------------------|--------------------------|
| RAG | 235 | 234 |
| FAQ | 65 | 66 |

### 5.5 カテゴリ別結果

| カテゴリ | 题数 | Bot 1 回答数 | Bot 1 回答率 | Bot 2 回答数 | Bot 2 回答率 |
|----------|------|-------------|-------------|-------------|-------------|
| general | 132 | 126 | 95.5% | 123 | 93.2% |
| location | 52 | 52 | 100.0% | 46 | 88.5% |
| shop | 46 | 43 | 93.5% | 42 | 91.3% |
| food | 37 | 36 | 97.3% | 35 | 94.6% |
| facility | 14 | 13 | 92.9% | 12 | 85.7% |
| hours | 6 | 6 | 100.0% | 4 | 66.7% |
| access | 4 | 4 | 100.0% | 3 | 75.0% |
| product | 4 | 3 | 75.0% | 4 | 100.0% |
| service | 3 | 3 | 100.0% | 2 | 66.7% |
| event | 2 | 2 | 100.0% | 2 | 100.0% |

### 5.6 关键发现

- Sonnet 4.5 的 RAG 稳定性显著优于 Gemini 2.5 Flash：RAG 正常处理率 100.0% vs 99.3%
- Sonnet 4.5 的回答率高出 5 个百分点：96.0% vs 91.0%
- Sonnet 4.5 产生 0 个 filler_only 响应，Gemini 2.5 Flash 产生 2 个
- Sonnet 4.5 产生 0 个 empty 响应（两者均为 0）
- Sonnet 4.5 的 not_found 数量显著更少：12 vs 25，说明其 RAG 检索匹配能力更强
- location 和 hours カテゴリ差异最大：Sonnet 4.5 分别为 100.0% 和 100.0%，Gemini 为 88.5% 和 66.7%

---

## 6. 多轮测试计划

| 轮次 | 计划日期 | 状态 | 说明 |
|------|---------|------|------|
| 第1回 | 2026-02-20 | 已完成 | 初始基线测试 |
| 第2回 | 2026-02-28 | 待执行 | 第二轮验证 |
| 第3回 | 2026-03-07 | 待执行 | 最终验证 |

每轮使用相同的 300 题测试用例，相同的两个 Bot 环境。

报告支持多轮模式：使用 `gen_report.py --round` 参数将多轮结果合并为单一 HTML 报告。多轮报告提供：
- **总合タブ**: 各轮正常回答率/响应时间的趋势折线图、分类全回比较、ステータス变化表
- **各回タブ**: 完整的单轮报告内容（Summary、图表、问题表格）

---

## 8. 关键文件路径

| 文件 | 路径 | 用途 |
|------|------|------|
| 技能说明 | `skill/newoman-eval/SKILL.md` | 评测技能的完整说明文档 |
| 评测脚本 | `skill/newoman-eval/scripts/bot_eval.py` | 向 GBase API 发送问题并收集评测结果 |
| 报告生成脚本 | `skill/newoman-eval/scripts/gen_report.py` | 从两个 eval JSON 生成 HTML 比较报告 |
| 测试用例 | `skill/newoman-eval/cases/newoman-takanawa.yaml` | 300 题测试用例定义 |
| HTML 模板 | `skill/newoman-eval/templates/comparison.html` | 比较报告的 HTML 模板 |
| Bot 1 结果 | `tests/results/eval-fa228b57-20260220-182201.json` | Sonnet 4.5（検証環境）评测结果 |
| Bot 2 结果 | `tests/results/eval-b50d5b21-20260220-212710.json` | Gemini 2.5 Flash（本番環境）评测结果 |
| 生成的报告 | `docs/bot-eval/index.html` | 自己完結型 HTML 比较报告（可通过 GitHub Pages 访问） |

> 注：以上路径均为仓库根目录的相对路径。仓库根目录为 `/Users/agent2025/Desktop/2025_AI/Tina0529/newoman-reports/`。

---

## 9. 技术术语表

| 术语 | 说明 |
|------|------|
| **RAG** | Retrieval-Augmented Generation。检索增强生成，先从知识库检索相关文档片段，再基于检索结果生成回答 |
| **FAQ** | Frequently Asked Questions。基于预设问答对的精确匹配回答，不经过 RAG pipeline |
| **answered** | 回答分类：Bot 返回了实质性内容的回答（不评估正确性） |
| **not_found** | 回答分类：RAG pipeline 正常执行完成，但未检索到匹配信息，Bot 回复"見つかりませんでした"等 |
| **empty** | 回答分类：Bot 返回空响应，RAG pipeline 未能正常完成 |
| **filler_only** | 回答分类：Bot 仅返回定型句（如"お調べいたします"），无实质内容，RAG pipeline 未正常完成 |
| **error** | 回答分类：响应包含系统错误信息（エラーが発生、システムエラー等） |
| **RAG 正常処理** | answered + not_found 的合计。表示 RAG pipeline 正常完成（无论是否找到信息） |
| **RAG 処理失敗** | empty + filler_only + error 的合计。表示 RAG pipeline 异常，未能正常返回结果 |
| **GBase** | AI chatbot 平台（api.gbase.ai），提供 RAG + FAQ 能力和 streaming API |
| **検証環境** | 验证环境，用于测试新配置（本次为 Sonnet 4.5） |
| **本番環境** | 生产环境，当前运行的正式配置（本次为 Gemini 2.5 Flash） |
| **streaming API** | 通过 SSE (Server-Sent Events) 流式返回响应内容的 API 接口 |
| **session_id** | 每次问答的唯一会话标识，评测时每题使用独立 session_id 以避免上下文干扰 |
