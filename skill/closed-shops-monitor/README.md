# NEWoMan高輪 閉店店舗監視

毎週 月・金 21:00 JST に NEWoMan高輪 公式サイトの「クローズショップ」を監視し、
新たに閉店した店舗の情報が FAQ ナレッジベースに残存していないかをチェックして
Lark に通知します。

## 動作概要

```
1. https://www.newoman.jp/takanawa/newshop/ をスクレイピング
2. notified-shops.json と差分比較 → 新規閉店店舗のみ抽出
3. GBase API で FAQ 全件取得
4. 店舗名 + 別名(shop-aliases.yaml)で question + answer を文字列マッチ
5. Lark Webhook へ結果通知
6. notified-shops.json を更新してコミット
```

## ディレクトリ構成

```
skill/closed-shops-monitor/
├── README.md
├── scripts/
│   └── monitor.py
└── data/
    ├── shop-aliases.yaml      # 店舗名表記揺れ辞書
    └── notified-shops.json    # 通知済み状態(ワークフローが自動更新)
```

## ローカル実行(テスト)

```bash
export GBASE_DATASET_ID=...
export GBASE_API_TOKEN=...
export LARK_WEBHOOK_URL=...

# Dry run(Lark 送信せず JSON プレビュー)
python skill/closed-shops-monitor/scripts/monitor.py --dry-run

# 全件強制通知(初回テスト用、状態ファイル無視)
python skill/closed-shops-monitor/scripts/monitor.py --force-notify-all --dry-run
```

## GitHub Actions

`.github/workflows/closed-shops-monitor.yml` が以下のスケジュールで起動:

- **毎週月曜 21:00 JST**(`0 12 * * 1` UTC)
- **毎週金曜 21:00 JST**(`0 12 * * 5` UTC)
- **手動実行**: workflow_dispatch + 任意で `force_notify_all: true`

## 必要な GitHub Secrets

| Secret 名 | 用途 |
|-----------|------|
| `GBASE_DATASET_ID` | NEWoMan高輪 dataset の UUID |
| `GBASE_API_TOKEN` | GBase API token (`ak-...`) |
| `LARK_WEBHOOK_URL` | Lark カスタム Bot Webhook URL |

## 通知パターン

| ケース | カラー | 件名 |
|--------|--------|------|
| 新規閉店あり + FAQ ヒットあり | 🔴 赤 | 新規閉店店舗の FAQ ヒット通知 |
| 新規閉店あり + FAQ 全件ヒットなし | 🟡 黄 | 新規閉店店舗あり(FAQ ヒットなし) |
| 新規閉店なし | 🟢 緑 | 閉店店舗監視 - 異常なし(稼働確認) |
| エラー | 🔴 赤 | 閉店店舗監視 - エラー |

## 別名辞書 (shop-aliases.yaml) の更新

通知に「ヒット 0 件」が出た場合は、FAQ にカナ表記しか登録されていない可能性があります。
人手で確認のうえ、`shop-aliases.yaml` に別名を追加してコミットしてください。
次回実行時から自動で拾います。
