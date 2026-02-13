---
name: chatbot-message-analyzer
description: |
  GBaseSupport消息履历分析报告生成工具。分析客服chatbot的对话记录CSV文件，
  生成包含KPI概览、时间维度分析、问题分类、用户行为洞察、错误模式分析、
  分析总结、改善建议的可视化HTML报告（日/中双语切换，ECharts图表）。
  当用户需要：(1)分析chatbot消息履历、(2)生成对话分析报告、
  (3)评估bot回答质量、(4)挖掘用户问题趋势、(5)分析未回答原因时使用此skill。
  触发词：消息履历、メッセージ履歴、对话分析、bot分析、チャット分析、
  message history、conversation analysis、履历分析、回答分析
---

# GBaseSupport Message Analyzer

分析chatbot的消息履历CSV，生成交互式HTML分析报告。

## 资源文件位置

本skill的所有资源文件位于 `~/.claude/skills/chatbot-message-analyzer/`:

- `assets/report-template.html` — 主报告HTML模板
- `assets/unanswered-template.html` — 未回答一览子页面HTML模板
- `references/industry-categories.md` — 行业问题分类参考
- `scripts/analyze.py` — Python分析脚本（可选，也可由Claude直接生成报告）

## 设计系统（UI UX Pro Max）

本skill的报告模板采用 **UI UX Pro Max** 设计智能系统，遵循以下设计规范：

### 设计风格
- **Style**: Minimalism & Swiss Style（简约瑞士风格）
- **Palette**: Analytics Dashboard（分析仪表板配色）
- **Typography**: Inter + Noto Sans JP（专业现代字体组合）

### 核心配色（CSS变量）
```css
:root {
    --primary: #3B82F6;      /* 主色-信任蓝 */
    --secondary: #60A5FA;    /* 次色 */
    --cta: #F97316;          /* 行动按钮-橙色 */
    --background: #F8FAFC;   /* 背景色 */
    --text: #1E293B;         /* 文本色 */
    --border: #E2E8F0;       /* 边框色 */
    --success: #10B981;      /* 成功-绿色 */
    --warning: #F59E0B;      /* 警告-黄色 */
    --danger: #EF4444;       /* 危险-红色 */
}
```

### 设计原则（必须遵守）
1. **No Emoji Icons**: 使用SVG图标（Lucide Icons），绝不使用emoji作为UI图标
2. **Cursor Pointer**: 所有可点击元素添加 `cursor-pointer`
3. **Hover Feedback**: 提供hover视觉反馈（颜色/阴影/边框变化）
4. **Smooth Transitions**: 使用200-250ms的平滑过渡动画
5. **High Contrast**: 确保WCAG AA级别对比度（文本至少4.5:1）
6. **8px Grid**: 使用8px网格系统的间距
7. **Consistent Radius**: 统一使用圆角（6px-16px）
8. **Subtle Shadows**: 使用柔和阴影增加层次感

### 组件样式规范

**KPI卡片**
- 使用顶部3px色条指示状态
- hover时轻微上移并增加阴影
- 数值使用大字号（1.875rem）加粗

**图表**
- 使用ECharts
- 统一tooltip样式（白色背景、边框、阴影）
- 柱状图圆角4px、折线图平滑曲线

**表格**
- 表头使用大写字母、小字号
- hover行高亮
- 数字右对齐使用等宽字体

**徽章（Badge）**
- 使用药丸形状（9999px圆角）
- 背景使用10%透明度的对应颜色

### 无障碍支持
- 支持 `prefers-reduced-motion` 减少动画
- 打印样式优化（隐藏语言切换、移除阴影）
- 键盘导航支持（focus状态可见）

## 工作流程

### Phase 1: 上下文收集

在开始分析前，向用户确认以下信息：

**必须确认：**
1. **CSV文件路径** — 在当前工作目录中查找 `チャット履歴_*.csv` 文件
2. **客户名称**（用于报告标题，如 NEWoMan高輪）
3. **报告周期**（如 2025年12月）

**可选确认：**
4. **行业类型**（默认：零售/商業施設）
5. **特别关注点**（如有）

**自动推断**：如果当前目录下存在CSV文件且文件名/路径包含客户名称和期间信息，可自动推断，无需每次都问用户。

### Phase 2: 数据解析

1. 读取CSV，自动尝试编码（UTF-8 → UTF-8-BOM → Shift-JIS → CP932）
2. 识别字段映射（参考下方字段映射表）
3. 数据清洗与预处理

```python
import pandas as pd

# 编码自动检测
for encoding in ['utf-8', 'utf-8-sig', 'shift-jis', 'cp932']:
    try:
        df = pd.read_csv(filepath, encoding=encoding)
        break
    except:
        continue
```

**字段映射参考：**

| 标准字段 | 可能的列名 |
|---------|-----------|
| timestamp | 質問時間, 日時, created_at, timestamp |
| question | 質問, ユーザー入力, user_message, query |
| answer | 回答, ボット回答, bot_response, response |
| feedback | ユーザーフィードバック, 評価, rating, feedback |
| feedback_reason | 評価理由, feedback_reason |
| session_id | チャットID, session_id, conversation_id |
| user_id | ユーザー, user_id, user |
| escalated | 担当者に接続済み, escalated |

### Phase 3: 分析逻辑

#### 3.1 未回答判定规则

满足以下任一条件即判定为「未回答」：

1. 回答字段为空或仅空白字符
2. 回答包含未找到类关键词：
   - 見つかりませんでした
   - 情報が見つかりません
   - お答えできません
   - 一致する情報は見つかりませんでした
3. 回答仅为垫语无实质内容（自动识别垫语模式）：
   - 常见垫语：「○○をお調べいたします。」「少々お待ちください」「確認いたします」
   - 判定方式：去除垫语后，剩余内容少于20字符

#### 3.2 问题分类（两层结构）

**第一层：通用大类（固定7类）**
- 店舗・商品照会
- 施設・サービス
- 位置・ナビゲーション
- 営業時間
- イベント・キャンペーン
- クレーム・フィードバック
- 雑談・その他

**第二层：行业细分**
根据Phase 1确认的行业类型，参考 `references/industry-categories.md` 生成二级分类。

#### 3.3 语言检测

根据用户提问内容自动检测语言：
- 日本語：平假名/片假名/日文汉字
- English：拉丁字母为主
- 中文：简体/繁体汉字
- 한국어：韩文字符
- その他

#### 3.4 会话深度计算

按会话ID（チャットID）分组，统计每个会话的消息轮数。

#### 3.5 错误模式分析

对未回答/回答错误的内容进行深入分析，根据实际数据自动归纳错误类型，常见模式包括：
- **情報なしエラー**：数据库中不存在相关信息
- **検索失敗**：关键词匹配问题、意图理解失败
- **再確認依頼**：问题表述模糊、仅为问候语
- **その他**：其他无法分类的错误

每个错误需分析具体原因，用于生成改善建议。

#### 3.6 KPI计算公式

| KPI | 计算公式 |
|-----|---------|
| 総メッセージ数 | COUNT(*) |
| 正常回答率 | (总数 - 未回答数) / 总数 |
| 未回答率 | 未回答数 / 总数 |
| 好評価率 | 良い評価数 / (良い評価数 + 悪い評価数) |
| フィードバック率 | 有评价数 / 总数 |

**注意**：好評価率的分母只包含有评价的记录，未评价("-")不计入。

### Phase 4: 报告生成

使用 `assets/report-template.html` 作为主报告模板，`assets/unanswered-template.html` 作为未回答子页面模板，填充分析数据生成HTML报告。

#### 报告结构

1. **报告概要**：分析对象、期间、类型、生成日期
2. **サマリー**：5个KPI卡片
3. **時間別分析**：
   - 每日平均件数统计卡片（日平均、最多日、最少日）
   - 日别推移图表、曜日分布、时段分布
4. **質問分類分析**：分类占比、分类详情、高频问题TOP10
5. **ユーザー行動分析**：会话深度、语言分布
6. **Bot性能分析**：
   - 未回答问题数量卡片（链接到子页面）
   - 富媒体使用情况
7. **エラーパターン別分析**：错误类型卡片、错误详情表格
8. **分析サマリー**：主要洞见（5-7条关键发现）
9. **改善提案**：按优先级排序的建议列表

#### 子页面生成

当未回答数量超过10条时，生成独立的未回答问题子页面：
- 文件名：`{客户名}_{期间}_未回答一覧.html`
- 包含完整的未回答问题列表
- 支持按错误类型筛选（情報なし/検索失敗/再確認）
- 主报告中显示链接按钮跳转到子页面

**子页面模板占位符说明**（使用 `assets/unanswered-template.html`）：

| 占位符 | 说明 | 示例 |
|--------|------|------|
| `{{CLIENT_NAME}}` | 客户名称 | NEWoMan高輪 |
| `{{PERIOD}}` | 分析期间 | 2025年12月 |
| `{{MAIN_REPORT_FILENAME}}` | 主报告文件名 | NEWoMan高輪_2025年12月_分析レポート.html |
| `{{TOTAL_UNANSWERED}}` | 未回答总数 | 104 |
| `{{INFO_NASHI_COUNT}}` | 情報なし件数 | 83 |
| `{{INFO_NASHI_PERCENT}}` | 情報なし占比 | 80 |
| `{{SEARCH_FAIL_COUNT}}` | 検索失敗件数 | 20 |
| `{{SEARCH_FAIL_PERCENT}}` | 検索失敗占比 | 19 |
| `{{RECONFIRM_COUNT}}` | 再確認件数 | 1 |
| `{{RECONFIRM_PERCENT}}` | 再確認占比 | 1 |
| `{{TABLE_ROWS}}` | 表格行HTML | 见下方格式 |

**TABLE_ROWS 行格式**：

```html
<tr>
    <td class="number">1</td>
    <td class="timestamp">2025-12-31 14:42:45</td>
    <td><span class="badge badge-red" data-ja="情報なし" data-zh="信息缺失">情報なし</span></td>
    <td class="question-cell">和菓子屋ある？</td>
    <td class="answer-cell">申し訳ございませんが...</td>
</tr>
```

**Badge样式对应**：
- `情報なし` → `badge-red`
- `検索失敗` → `badge-yellow`
- `再確認` → `badge-gray`

#### 技术要点

- 使用ECharts绑定图表数据
- 双语切换：所有文本使用 `data-ja` 和 `data-zh` 属性
- 图表语言也需随切换更新

### Phase 5: 输出

**输出到CSV文件所在的同一目录**（而非固定路径），确保报告和数据在一起。

**必须同时生成两个文件**（当未回答数>10时）：

1. **主报告**：`{客户名}_{期间}_分析レポート.html`
2. **子页面**：`{客户名}_{期间}_未回答一覧.html`

```python
import os

# 输出到CSV所在目录
output_dir = os.path.dirname(csv_filepath)

# 1. 生成主报告
main_filename = f"{output_dir}/{client_name}_{period}_分析レポート.html"

# 2. 生成子页面（未回答数>10时）
if unanswered_count > 10:
    sub_filename = f"{output_dir}/{client_name}_{period}_未回答一覧.html"
```

**重要提醒**：
- 两个文件必须放在同一目录下，链接才能正常工作
- 主报告中的CTA按钮链接到子页面文件名（相对路径）
- 子页面的返回链接也使用相对路径指向主报告

## 分析总结撰写指南

「分析サマリー」部分应包含以下维度的洞见：

1. **回答品質**：正常回答率、好评情况
2. **用户构成**：语言分布、国际化需求
3. **时间特征**：高峰时段、使用规律
4. **主要需求**：TOP问题类型、热门话题
5. **问题点**：未回答原因分析、改善空间

使用 `<span class='highlight-text'>关键数据</span>` 高亮重要数据。

## 改善建议生成规则

按优先级分类：

| 优先级 | 条件 | badge样式 |
|-------|------|-----------|
| 高 | 直接影响用户体验的问题（FAQ缺失、回答错误） | badge-red |
| 中 | 可优化但不紧急的问题（问候语应答、多语言） | badge-yellow |
| 低 | 锦上添花的改进（回答细节优化） | badge-blue |

每条建议需包含：
- 具体问题描述
- 改善方向/解决方案

## 使用方法（Claude Code）

在Claude Code中使用此skill：

```
# 方法1: 直接在包含CSV的目录下运行
cd /path/to/month-data/
# 然后告诉Claude: "分析这个月的聊天履历"

# 方法2: 指定CSV文件
# 告诉Claude: "用 chatbot-message-analyzer 分析 チャット履歴_2025.12.01_2025.12.31.csv"

# 方法3: 运行脚本
python3 ~/.claude/skills/chatbot-message-analyzer/scripts/analyze.py \
  --csv "チャット履歴_2025.12.01_2025.12.31.csv" \
  --client "NEWoMan高輪" \
  --period "2025年12月"
```
