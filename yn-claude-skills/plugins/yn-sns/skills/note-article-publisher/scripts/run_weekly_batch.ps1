# note 週次バッチ起動スクリプト
# Task Scheduler から呼ばれる想定。
# 5アカウント × 7日 = 35記事を下書きまで作成する。

$ErrorActionPreference = "Stop"

$ProjectRoot = "G:\マイドライブ\YNFactory-cc"
$OutputDir = Join-Path $ProjectRoot ".company\outputs\note-articles\weekly"
$LogDir = $OutputDir
$LogFile = Join-Path $LogDir "latest-batch.log"

if (-not (Test-Path $LogDir)) {
  New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"=== Weekly batch started at $Timestamp ===" | Out-File -FilePath $LogFile -Encoding UTF8

Set-Location $ProjectRoot

# Claude Code を非対話モードで起動して週次バッチを実行
# --print: 結果を標準出力に出して終了
# --permission-mode: Playwright・ファイル書き込みを許可
$Prompt = @"
note-article-publisher スキルの週次バッチモードを実行してください。
references/weekly-batch.md の手順に従い、以下を行います。

1. 今日の日付から翌週月曜-日曜の7日分を計算
2. 5アカウント分の topics/<account>.md と history.json を読み込み
3. 5アカウント × 7日 = 35記事の plan.md を生成
4. 35記事を順次生成（本文 + カバー + 挿絵 + 品質チェック）
5. アカウントごとにブラウザプロファイルで note に下書き投入
6. summary.md でオーナーへ報告

オーナー承認なしで進めて構いません（運用モード）。
ただし noteの公開ボタンは押さず、必ず下書き保存で止めてください。
"@

claude --print --permission-mode acceptEdits "$Prompt" *>> $LogFile

$Status = if ($LASTEXITCODE -eq 0) { "SUCCESS" } else { "FAILED (exit=$LASTEXITCODE)" }
"=== Weekly batch ended at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [$Status] ===" | Out-File -FilePath $LogFile -Append -Encoding UTF8

exit $LASTEXITCODE
