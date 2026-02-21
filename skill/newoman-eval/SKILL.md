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

# 本番環境Bot (Gemini 2.5 Flash)
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

2つのeval JSONから比較HTMLレポートを生成する。単回と複数回の2つのモードがある。

#### 単回モード（1回分のテスト結果）

```bash
python3 skill/newoman-eval/scripts/gen_report.py \
  --bot1-json tests/results/eval-fa228b57-YYYYMMDD-HHMMSS.json \
  --bot2-json tests/results/eval-b50d5b21-YYYYMMDD-HHMMSS.json \
  --output docs/bot-eval/index.html
```

#### 複数回モード（複数回のテスト結果を1レポートに統合）

`--round` オプションを繰り返し指定する。形式: `ラベル:日付:bot1json:bot2json`

```bash
python3 skill/newoman-eval/scripts/gen_report.py \
  --round "第1回:2026-02-20:tests/results/eval-fa228b57-R1.json:tests/results/eval-b50d5b21-R1.json" \
  --round "第2回:2026-02-28:tests/results/eval-fa228b57-R2.json:tests/results/eval-b50d5b21-R2.json" \
  --round "第3回:2026-03-07:tests/results/eval-fa228b57-R3.json:tests/results/eval-b50d5b21-R3.json" \
  --output docs/bot-eval/index.html
```

複数回モードでは、タブ切り替えで各回の詳細と「総合」タブ（全回トレンド）を確認できる。

#### 共通オプション

| オプション | デフォルト | 説明 |
|-----------|----------|------|
| `--round` | (なし) | 複数回指定: `ラベル:日付:bot1json:bot2json` |
| `--bot1-json` | (なし) | Bot 1 eval JSON（単回モード用） |
| `--bot2-json` | (なし) | Bot 2 eval JSON（単回モード用） |
| `--bot1-name` | NEWoMan高輪 検証環境 | Bot 1 表示名 |
| `--bot1-model` | Claude Sonnet 4.5 | Bot 1 モデル名 |
| `--bot1-short` | 検証環境 | Bot 1 略称 |
| `--bot2-name` | NEWoMan高輪 本番環境 | Bot 2 表示名 |
| `--bot2-model` | Gemini 2.5 Flash | Bot 2 モデル名 |
| `--bot2-short` | 本番環境 | Bot 2 略称 |
| `--output` | stdout | 出力先HTMLパス |

生成されたHTMLは自己完結型（JSONデータ埋め込み）で、
GitHub Pages経由で直接アクセスできる。

#### 増分ワークフロー（テスト追加時）

新しいテスト回が完了したら、全回分のJSONを `--round` で指定して再生成するだけでよい。

```bash
# 第2回テスト完了後
python3 skill/newoman-eval/scripts/gen_report.py \
  --round "第1回:2026-02-20:tests/results/eval-fa228b57-R1.json:tests/results/eval-b50d5b21-R1.json" \
  --round "第2回:2026-02-28:tests/results/eval-fa228b57-R2.json:tests/results/eval-b50d5b21-R2.json" \
  --output docs/bot-eval/index.html
```

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

### 各回の詳細
- Bot情報カード（名前・モデル・ID）
- テスト結果の概要（目的駆動型の分析サマリー）
- RAG実行分析（実行率KPI、成功/失敗内訳、失敗理由詳細）
- カテゴリ別RAG実行率（横棒グラフ）
- 回答ソース分布（RAG/FAQドーナツ）
- 応答時間分析（全体平均KPI + カテゴリ別棒グラフ）
- 全質問一覧テーブル（フィルタ・検索・回答プレビュー展開）

### 総合タブ（複数回モードのみ）
- 全回テスト総合サマリー（各回の結果概要と変化量）
- 正常回答率の推移（折れ線グラフ）
- 平均応答時間の推移（面グラフ付き折れ線）
- カテゴリ別全回比較（グループ棒グラフ）
- 回答ステータスの変化テーブル（改善/悪化した質問の一覧）
