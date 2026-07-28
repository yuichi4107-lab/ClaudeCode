$targetDir = "g:\マイドライブ"

# 定義
$categories = @{
    "01_求人情報・企業調査" = @("求人", "調査", "ホワイト", "退職", "給与", "人事", "労働法", "収入の卑", "美建")
    "02_マンガ・動画・SNS制作" = @("マンガ", "manga", "コミクル", "comic", "リール", "Instagram", "インスタ", "Threads", "SNS", "youtube", "動画", "wav", "mp4", "avi", "台本", "ショート")
    "03_歴史・資料・学習" = @("歴史", "北条", "やぐら", "労働基準法", "FIRE", "台湾", "壬申の乱", "早良親王", "道鏡", "邪馬台国", "蘇我氏", "仏教", "物権法", "投資")
    "04_競馬・一口馬主関連" = @("競馬", "馬主", "キャロット", "SPAT4", "WIN5", "川口オート", "dokanto", "haitou", "2歳馬", "racing", "馬")
    "05_無題・コピー類" = @("無題の", "コピー", "undefined", "スクリーンショット")
}

Write-Host "Creating directories..."
foreach ($cat in $categories.Keys) {
    $path = Join-Path $targetDir $cat
    if (-not (Test-Path $path)) {
        New-Item -ItemType Directory -Force -Path $path | Out-Null
    }
}
$otherPath = Join-Path $targetDir "00_その他のファイル"
if (-not (Test-Path $otherPath)) {
    New-Item -ItemType Directory -Force -Path $otherPath | Out-Null
}

Write-Host "Moving files..."
$files = Get-ChildItem -Path $targetDir -File

$movedCount = 0
foreach ($file in $files) {
    if ($file.Name -match "^(0[0-5]_|desktop.ini)") {
        continue 
    }
    
    $moved = $false
    foreach ($cat in $categories.Keys) {
        foreach ($keyword in $categories[$cat]) {
            # 正規表現でエスケープ処理しておく
            $escaped_keyword = [regex]::Escape($keyword)
            if ($file.Name -match $escaped_keyword -or $file.Extension -match $escaped_keyword) {
                $dest = Join-Path $targetDir $cat
                Move-Item -LiteralPath $file.FullName -Destination $dest -Force -ErrorAction SilentlyContinue
                if ($?) {
                    Write-Host "Moved: $($file.Name) -> $cat"
                    $movedCount++
                } else {
                    Write-Warning "Failed to move $($file.Name) - it might be locked."
                }
                $moved = $true
                break
            }
        }
        if ($moved) { break }
    }
    
    if (-not $moved) {
        $dest = Join-Path $targetDir "00_その他のファイル"
        Move-Item -LiteralPath $file.FullName -Destination $dest -Force -ErrorAction SilentlyContinue
        if ($?) {
            Write-Host "Moved: $($file.Name) -> 00_その他のファイル"
            $movedCount++
        } else {
            Write-Warning "Failed to move $($file.Name) - it might be locked."
        }
    }
}
Write-Host "Complete! Moved $movedCount files."
