---
name: closed-shops-faq-lookup
description: |
  ニュウマン高輪チャットボットの「閉店店舗関連 FAQ」検索 + 監視ツール。
  LUMINE から「◯◯店が閉店予定」と事前通知が来た際、店舗名から全 10 言語の関連 FAQ を
  一括検索し、Lark に通知。日本語版は Q+A 詳細、他言語は件数のみ表示。
  併せて、公式サイトの「クローズショップ」一覧を月・金 21:00 JST に自動巡回し、
  新規閉店店舗が出た時に FAQ 残存をチェックする監視機能も提供。

  使うとき:
  (1) LUMINE から店舗閉店の事前通知が来た → 関連 FAQ を即座に調査したい
  (2) 担当者が「あの店舗の FAQ 探して」と言った
  (3) 特定 FAQ ID の検出可否を診断したい(検出漏れ調査)
  (4) 公式サイトの新規閉店店舗を週次でチェックしたい

  触发词:閉店 FAQ、店舗 FAQ 検索、店舗名 FAQ、shop FAQ、lookup faq、
  闭店 FAQ、店铺 FAQ 查找、ニュウマン FAQ、NEWoMan 閉店、
  クローズショップ、closed shop monitor、FAQ 検出漏れ、inspect FAQ
---

# 閉店店舗関連 FAQ 検索 + 監視 Skill

NEWoMan高輪のチャットボット FAQ ナレッジベースを店舗名から検索・監視するためのツール群。
LUMINE 様との運用合意「**月 1 次基準・隔週定例で確認**」に基づく事前/事後の二段構え。

---

## 利用シナリオ別ガイド

### シナリオ A:LUMINE から閉店事前通知 → 関連 FAQ 調査(主要用途)

担当者が「LUMINE から ◯◯店が 6/30 閉店と連絡来たので FAQ 調べて」と言ったら、
このシナリオです。

**手順**:
```bash
cd ~/2025_AI/Tina0529/newoman-reports
python skill/closed-shops-monitor/scripts/lookup-faq.py "店舗名"
```

**出力**:
- 全 10 言語の関連 FAQ をローカル文字列マッチで検出
- 日本語版を詳細表示(Q + A 抜粋 200 字、matched キーワード明示)
- 他言語は件数のみグルーピング表示
- Lark Webhook へカード形式で自動投稿

**オプション**:
- `--csv /tmp/result.csv` — 全文(切り詰めなし)CSV エクスポート(Excel 確認用)
- `--no-lark` — Lark 送信せずコンソール表示のみ
- `--language ja|all` — デフォルト ja、`all` で全言語対象

**典型的な担当者フロー**:
1. 店舗名を Claude に渡して lookup-faq.py を実行
2. Lark に届いたカードを確認
3. CSV エクスポートして LUMINE と「これ削除/これ修正」を確認
4. GBase 管理画面で該当 FAQ を順次処理

### シナリオ B:公式サイトを定期巡回(自動運用)

`monitor.py` が GitHub Actions で **毎週月・金 21:00 JST** に自動起動。
担当者の操作不要(初回 setup 後は完全自動)。

**動作**:
1. https://www.newoman.jp/takanawa/newshop/ をスクレイピング
2. `notified-shops.json` と差分比較 → 新規閉店店舗のみ抽出
3. GBase API で `language=ja` の FAQ 全件取得
4. 店舗名 + 別名(`shop-aliases.yaml`)でローカル文字列マッチ
5. Lark に通知(3 パターン: ヒットあり / ヒット 0 件 / 新規なし heartbeat)
6. `notified-shops.json` を更新してコミット

**手動トリガー**(GitHub Actions UI):
```
gh workflow run closed-shops-monitor.yml --repo Tina0529/newoman-reports
```

オプション:
- `dry_run=true` — Lark 送信せず log 確認のみ
- `force_notify_all=true` — 既通知済みも含めて再通知

### シナリオ C:特定 FAQ の検出漏れ原因診断

「このFAQ ID `xxx` が検出されなかったけど何で?」と聞かれたら、
このシナリオです。

**手順**:
```
gh workflow run inspect-faq.yml \
  --repo Tina0529/newoman-reports \
  -f faq_id=<UUID> \
  -f shop_name="<期待した店舗名>"
```

**出力**(GitHub Actions log):
- FAQ の question/answer 全文 + language タグ + 全フィールド
- 期待した店舗名のキーワード展開と matching 診断
- 検出可否の判定結果と原因(別名不足 / 文字種兜底フィルタで除外 等)

---

## ファイル構成

```
skill/closed-shops-monitor/
├── SKILL.md                    ← この説明書
├── README.md                   ← repo 内向け技術文書
├── scripts/
│   ├── monitor.py              ← 公式サイト自動巡回(シナリオ B)
│   ├── lookup-faq.py           ← 店舗名 → FAQ 検索(シナリオ A)
│   └── inspect-faq.py          ← FAQ 個別診断(シナリオ C)
└── data/
    ├── shop-aliases.yaml       ← 店舗名表記揺れ辞書(編集可、要 commit)
    └── notified-shops.json     ← 通知済み state(自動更新、手動編集不可)

.github/workflows/
├── closed-shops-monitor.yml    ← 月・金 21:00 JST 自動 + workflow_dispatch
└── inspect-faq.yml             ← workflow_dispatch のみ(診断用)
```

---

## 必要な環境変数 / GitHub Secrets

| 名前 | 用途 | 取得元 |
|------|------|--------|
| `GBASE_DATASET_ID` | NEWoMan高輪 dataset の UUID | GBase 管理画面 |
| `GBASE_API_TOKEN` | GBase API token (`ak-...`) | GBase 管理画面 |
| `LARK_WEBHOOK_URL` | 通知先 Lark カスタム Bot Webhook | Lark グループ設定 |

GitHub Actions では Secrets 経由で自動注入。ローカル実行時は `export` してください。

---

## 検索ロジック詳細(技術仕様)

### 1. 店舗名キーワード展開
- 入力店舗名 + `shop-aliases.yaml` の別名を組合せ
- 自動展開: 大文字/小文字、`THE` プレフィックス除去、全角→半角(＆→&)
- 3 文字未満のキーワードは誤マッチ防止のため除外

### 2. 言語フィルタ(monitor.py のみ、Plan B)
- API レスポンスの `language` タグを 100% 信頼
- タグが無い FAQ のみ、文字種(ひらがな/カタカナ/漢字)で兜底判定
- これにより「タグは ja、中身は英語」の自動学習 FAQ も漏らさず検出

### 3. マッチング
- Q + A を改行連結 → lower-case 化 → substring search
- いずれかのキーワードが含まれていればヒット
- 重複 ID は除外

### 4. 重複通知防止(monitor.py のみ)
- `notified-shops.json` で「first_notified_at」を記録
- 公式サイトに既出の店舗は再通知しない
- 新規閉店ゼロ時は緑色 heartbeat 通知(稼働確認)

---

## アンチパターン

❌ **shop-aliases.yaml に追加せず lookup-faq.py を実行** → 別名が拾えず漏れる可能性
   → 担当者は「このカナ表記もある」と気づいたら必ず `shop-aliases.yaml` に追記

❌ **notified-shops.json を手動編集** → 自動コミットと衝突
   → state リセット必要時は `monitor.py` 経由で(または明示的に PR で)

❌ **dry_run=true なのに Lark 来ないと焦る** → 仕様
   → 動作確認時は `dry_run=true`、本番時は `dry_run=false`

❌ **GBase deep link を SKILL.md にハードコード** → URL 変更で陳腐化
   → 担当者は管理画面 TOP からたどる

---

## 関連 issue / 経緯

- 2026-04 月次レポートで「言語混在」検出機能を追加
- 2026-05-13 LUMINE 5 月定例で「月 1 次基準・隔週定例で確認」運用合意
- 2026-05-13 closed-shops-monitor 初回稼働、5 件検出 → THE MATCHA TOKYO 0 件確認
- 2026-05-15 Plan B 修正(API language タグ信頼)→ Johnny Depp +1 件追加検出
