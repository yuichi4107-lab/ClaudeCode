# Task Scheduler 週次バッチ起動設定（Windows）

毎週日曜 23:00 などに自動で週次バッチを起動する手順。

## 前提

- Claude Code CLI がインストール済み（`claude` コマンドがPATHに通っている）
- `g:\マイドライブ\YNFactory-cc` で Claude Code が動く
- ブラウザプロファイル `note-ai` / `note-money` / `note-career` / `note-spiritual` / `note-love` がそれぞれログイン済み
- 既存の `YNFactory-MorningBriefing` タスクと同じパターンを踏襲

## タスク登録（PowerShell管理者で実行）

```powershell
$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument '-NoProfile -ExecutionPolicy Bypass -File "G:\マイドライブ\YNFactory-cc\.agents\skills\note-article-publisher\scripts\run_weekly_batch.ps1"'

# 毎週日曜 23:00 起動
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 23:00

$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -ExecutionTimeLimit (New-TimeSpan -Hours 6)

Register-ScheduledTask `
  -TaskName "YNFactory-NoteWeeklyBatch" `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description "5アカウントの note 記事を週次で35件下書き生成"
```

## 動作確認

```powershell
# 手動実行（テスト用）
Start-ScheduledTask -TaskName "YNFactory-NoteWeeklyBatch"

# 状態確認
Get-ScheduledTask -TaskName "YNFactory-NoteWeeklyBatch" | Get-ScheduledTaskInfo

# ログ確認
Get-Content "G:\マイドライブ\YNFactory-cc\.company\outputs\note-articles\weekly\latest-batch.log" -Tail 50
```

## 注意

- ブラウザ操作を伴うため、PCがスリープしていると動かない。
  - 電源オプションで「コンピューターをスリープ状態にする」を「なし」に設定するか、
  - 起動時刻の数分前に「スリープ解除」する。
- 2段階認証が走った場合は、その記事はスキップして人間対応に回すため、
  monthly でnoteのセッションが切れていないか確認する。
- バッチ実行中は note 画面が見えるので、PC前で他作業をしている時間は避ける（深夜推奨）。

## 停止・削除

```powershell
# 一時停止
Disable-ScheduledTask -TaskName "YNFactory-NoteWeeklyBatch"

# 削除
Unregister-ScheduledTask -TaskName "YNFactory-NoteWeeklyBatch" -Confirm:$false
```
