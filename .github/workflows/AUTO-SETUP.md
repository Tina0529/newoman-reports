# 月次レポート自動生成の初期設定

`auto-monthly-report.yml` は **月末日 22:00 JST** に当月分のレポートを自動生成する。
初回のみ、GitHub Secrets に以下の値を登録する必要がある。

## 必要な Secrets

| Secret 名 | 用途 | 必須 |
|----------|------|------|
| `GBASE_DATASET_ID` | GBase の Dataset ID | ✅ |
| `GBASE_API_TOKEN` | GBase API Bearer Token | ✅ |
| `ANTHROPIC_API_KEY` | LLM 判定用(未設定でもルールベースで動作) | △ |

## 設定手順

1. ブラウザで以下を開く:
   `https://github.com/Tina0529/newoman-reports/settings/secrets/actions`
2. **New repository secret** をクリック
3. Name と Value を入力して **Add secret**
4. 上記の必須 Secret を全て登録(`GBASE_DATASET_ID`, `GBASE_API_TOKEN`)

## 動作確認(オプション)

設定後すぐに動作確認するには:

1. `Actions` タブ → `Auto Monthly Report` ワークフローを選択
2. **Run workflow** をクリック
3. `force` を `true` にして実行(日付チェックをスキップ)
4. 成功すれば、`docs/clients/newoman-takanawa/` に当月分レポートが生成される

## スケジュール仕様

- **発火**: 毎月 28-31 日の **22:00 JST** (= 13:00 UTC)
- **判定**: スクリプト内で「明日は翌月か?」をチェックし、月末日のみ実行
- **対象月**: 実行日の当月(JST)
- **対象期間**: 当月 1 日 ~ 実行日(=月末日)

## トラブルシューティング

| 症状 | 原因 | 対処 |
|------|------|------|
| ❌ Secrets が未設定 | Secret 名のスペルミス | 上記表の通り(英数字大文字 + アンダースコア)で登録 |
| ❌ API Token 期限切れ | GBase の token 有効期限超過 | 新しい token を Secret に上書き |
| ❌ Dataset ID 不正 | dataset 削除・移動 | GBase 管理画面で正しい ID を取得して上書き |
| 当月分が生成されない | cron の発火時刻に GitHub Actions が遅延した | `Actions` タブで手動 `Run workflow` |

## 既存の手動 workflow との関係

- `update-report.yml` (既存): 任意月を手動指定して再生成。今後も保持。
- `auto-monthly-report.yml` (新規): 月末日に当月分のみ自動生成。
- 過去月分の再生成や CSV モードは引き続き `update-report.yml` で対応。
