# NEWoMan Bot 応答評価 (newoman-eval)

NEWoMan高輪 GBase Bot の応答品質を評価するスキル。
300問のテストケースを使って複数のBotを比較テストし、
RAG実行率・応答時間・カテゴリ別分析を含むHTML比較レポートを生成する。

## ディレクトリ構成

```
skill/newoman-eval/
├── SKILL.md              # このファイル
├── cases/
│   └── newoman-takanawa.yaml   # 300問テストケース（NEWoMan高輪向け）
├── scripts/
│   ├── bot_eval.py       # Bot評価スクリプト（GBase APIにストリーミング送信）
│   └── gen_report.py     # 比較HTMLレポート生成スクリプト
└── templates/
    └── comparison.html   # 比較レポートHTMLテンプレート
```

## ワークフロー

### Step 1: Bot評価を実行

各Botに対して `bot_eval.py` を実行し、JSON結果ファイルを生成する。

```bash
# 検証環境Bot (Sonnet 4.5)
python3 skill/newoman-eval/scripts/bot_eval.py \
  --bot-id fa228b57-59e1-447b-87e2-02c494195961 \
  --cases skill/newoman-eval/cases/newoman-takanawa.yaml \
  --output tests/results/eval-fa228b57-YYYYMMDD-HHMMSS.json

# 正式環境Bot (Gemini 2.5 Flash)
python3 skill/newoman-eval/scripts/bot_eval.py \
  --bot-id b50d5b21-262a-4802-a8c4-512af224c72f \
  --cases skill/newoman-eval/cases/newoman-takanawa.yaml \
  --output tests/results/eval-b50d5b21-YYYYMMDD-HHMMSS.json
```

**bot_eval.py オプション:**
| オプション | デフォルト | 説明 |
|-----------|----------|------|
| `--bot-id` | (必須) | GBase Bot ID (UUID) |
| `--token` | 環境変数 or 内蔵値 | GBase APIトークン |
| `--cases` | 同ディレクトリの cases.yaml | テストケースファイル |
| `--output` | results/eval-{id}-{timestamp}.json | 出力先 |
| `--limit` | 0 (全件) | テスト件数制限 |
| `--delay` | 1.0 | リクエスト間隔（秒） |
| `--timeout` | 60.0 | タイムアウト（秒） |

### Step 2: 比較レポートを生成

2つのeval JSONから比較HTMLレポートを生成する。

```bash
python3 skill/newoman-eval/scripts/gen_report.py \
  --bot1-json tests/results/eval-fa228b57-YYYYMMDD-HHMMSS.json \
  --bot2-json tests/results/eval-b50d5b21-YYYYMMDD-HHMMSS.json \
  --bot1-name "NEWoMan高輪 検証環境" \
  --bot1-model "Claude Sonnet 4.5" \
  --bot1-short "検証環境" \
  --bot2-name "NEWoMan高輪 正式環境" \
  --bot2-model "Gemini 2.5 Flash" \
  --bot2-short "正式環境" \
  --output docs/bot-eval/index.html
```

生成されたHTMLは自己完結型（JSONデータ埋め込み）で、
GitHub Pages経由で直接アクセスできる。

### Step 3: GitHub Pagesにデプロイ

```bash
git add docs/bot-eval/index.html tests/results/eval-*.json
git commit -m "Add bot eval report: YYYY-MM-DD"
git push
```

GitHub Pages URL: `https://tina0529.github.io/newoman-reports/bot-eval/`

## 判定基準

### RAG実行分類
- **正常実行**: `answered`（回答あり）+ `not_found`（情報なし = RAG実行はしたが該当なし）
- **実行失敗**: `empty`（空応答）+ `filler_only`（定型句のみ）+ `error`（エラー）

### 未回答判定ロジック（bot_eval.py）
1. 空出力 / システムエラー → `empty` / `error`
2. 「見つかりませんでした」系 → `not_found`
3. 定型句のみ（お調べします等）→ `filler_only`
4. 上記以外 → `answered`（内容の正確性は問わない）

## 依存ライブラリ

```bash
pip install httpx pyyaml
```

## テストケース形式 (cases.yaml)

```yaml
- description: "case-001"
  vars:
    user_input: "営業時間を教えてください"
  metadata:
    category: "営業時間"
```

## レポート機能

- Bot情報カード（名前・モデル・ID）
- RAG実行分析（実行率KPI、成功/失敗内訳、失敗理由詳細）
- カテゴリ別RAG実行率（横棒グラフ）
- 回答ソース分布（RAG/FAQドーナツ）
- 応答時間分析（全体平均KPI + カテゴリ別棒グラフ）
- 全質問一覧テーブル（フィルタ・検索・回答プレビュー展開）
