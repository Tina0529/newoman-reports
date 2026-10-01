# 月次レポート自動生成の初期設定

`auto-monthly-report.yml` は **毎月1日 10:00 JST** に**前月分**のレポートを自動生成する（2026-10-01 変更）。
初回のみ、GitHub Secrets に以下の値を登録する必要がある。

## 必要な Secrets

| Secret 名 | 用途 | 必須 |
|----------|------|------|
| `GBASE_DATASET_ID` | GBase の Dataset ID | ✅ |
| `GBASE_API_TOKEN` | GBase API Bearer Token | ✅ |
| `ANTHROPIC_API_KEY` | 現在は未使用（未回答判定はルールベースに統一。2026-10-01〜） | - |

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
3. `target_month` を空欄のまま実行すれば前月分、`YYYY-MM` を入れればその月（当月なら途中経過）を生成
4. 成功すれば、`docs/clients/newoman-takanawa/` にレポートが生成される

## スケジュール仕様

- **発火**: 毎月 1 日の **10:00 JST** (= 01:00 UTC)
- **対象月**: 前月（JST 基準）
- **対象期間**: 前月 1 日 ~ 前月末日
- **未回答判定**: ルールベース（キーワード判定）。7・8月の再集計と同じ基準
- **変更理由**: 以前は月末 22:00 に当月分を生成していたが、GitHub の schedule が数時間遅れ、月末当日の未明に走って最終日が欠けたり（8月・9月）、本来の回が翌月にずれて「月末ではない」とスキップされたりした。前月分を1日に集計すれば遅延しても欠けない

## トラブルシューティング

| 症状 | 原因 | 対処 |
|------|------|------|
| ❌ Secrets が未設定 | Secret 名のスペルミス | 上記表の通り(英数字大文字 + アンダースコア)で登録 |
| ❌ API Token 期限切れ | GBase の token 有効期限超過 | 新しい token を Secret に上書き |
| ❌ Dataset ID 不正 | dataset 削除・移動 | GBase 管理画面で正しい ID を取得して上書き |
| 前月分が生成されない | GitHub Actions の schedule が実行されなかった | `Actions` タブで手動 `Run workflow`（target_month 空欄） |

## 既存の手動 workflow との関係

- `update-report.yml` (既存): 任意月を手動指定して再生成。今後も保持。
- `auto-monthly-report.yml`: 毎月1日に前月分を自動生成。
- 過去月分の再生成や CSV モードは引き続き `update-report.yml` で対応。
