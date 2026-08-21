# YNFactory-cc 作業ディレクトリ恒久構成 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive 作業ツリーを維持したまま、`.git` をローカル固定・大容量バイナリを Git 管理外にし、orphan 新規履歴を GitHub private に push して、複数PC間で安全に履歴同期できる構成へ移行する。

**Architecture:** 3レイヤー責務分離 — ①作業ツリー=`G:\マイドライブ\YNFactory-cc\`（Drive配布・パス不変）/ ②大容量成果物=Git管理外（Driveのみ配布）/ ③`.git`=`C:\dev\YNFactory-git\.git`（各PCローカル）↔ GitHub private で pull/push。

**Tech Stack:** git 2.x（Git for Windows）、gh CLI 2.63.2（認証済 `yuichi4107-lab`、scope `repo`）、PowerShell / Bash、Google Drive for desktop。

**設計書:** [2026-05-30-workdir-git-architecture-design.md](../specs/2026-05-30-workdir-git-architecture-design.md)

**前提状態（2026-05-30 実測）:**
- `.git` = `C:\dev\YNFactory-git\.git`（ローカル復元済）、作業ツリー = `G:\マイドライブ\YNFactory-cc`
- 現ブランチ `codex/sagyo` HEAD=`163f6b5`、他に `codex/ebookgpt5.5` / `master`、remote 無し
- 追跡 11,847ファイル / 7.21GB。100MB超: keiba の pkl/csv/db。最大ディレクトリ: `.company/outputs/ebooks-manga` 5.35GB
- `core.longpaths=true` 設定済、`.git_drivebackup`（4.7GB）が究極のバックアップとして温存中

**安全原則（全タスク共通）:**
- `.git_drivebackup` は本移行が全工程完了し検証OKになるまで**絶対に削除しない**
- 旧ブランチ（codex/sagyo 等）の commit は**ローカルに保持**（GitHub には載せない）。orphan は別履歴なので旧履歴は失われない
- 破壊的操作（orphan・branch -m）の前にブランチ名と HEAD を記録する

---

## File Structure

このタスクで作成・変更するファイル:

- **変更**: `g:\マイドライブ\YNFactory-cc\.gitignore` — 大容量バイナリ除外ルールを追記
- **新規履歴**: orphan ブランチ `main`（GitHub の既定ブランチ・今後の作業ブランチ）
- **改訂**: `.company/engineering/docs/gdrive-git-setup.md` — 確定構成と2台目セットアップ手順に全面改訂
- **改訂**: `.claude/skills/handoff/SKILL.md` — push 対応・Drive停止依頼の見直し
- **更新**: `.company/secretary/HANDOFF.md`、`~/.claude/projects/.../memory/project_ynfactory_git_drive_setup.md` — 構成変更を記録
- **新規（GitHub）**: `yuichi4107-lab/YNFactory-cc`（private）

---

## Task 0: プリフライト（バックアップ確認・状態記録）

**Files:** なし（読み取りと記録のみ）

- [ ] **Step 1: バックアップの実在を確認**

Run:
```bash
ls -la "g:/マイドライブ/YNFactory-cc/.git_drivebackup/objects/pack/" | grep pack
```
Expected: `pack-….pack`（約4.8GB）が表示される。**無ければ STOP**（究極バックアップが無い状態で破壊的操作をしてはいけない）。

- [ ] **Step 2: 現在のブランチ・HEAD・remote を記録**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
echo "HEAD=$(git rev-parse HEAD)"; git branch; git remote -v
```
Expected: `HEAD=163f6b5…`、branches に `* codex/sagyo` `codex/ebookgpt5.5` `master`、remote 出力なし。この HEAD 値を控える（ロールバック起点）。

- [ ] **Step 3: lock 残留が無いことを確認**

Run:
```bash
ls "C:/dev/YNFactory-git/.git/"*.lock 2>/dev/null && echo "LOCK残留" || echo "lockなし(正常)"
```
Expected: `lockなし(正常)`。残っていれば `rm -f "C:/dev/YNFactory-git/.git/index.lock"`。

---

## Task 1: .gitignore に大容量バイナリ除外ルールを追記

**Files:**
- Modify: `g:\マイドライブ\YNFactory-cc\.gitignore`（末尾に追記）

- [ ] **Step 1: 追記前の追跡サイズを記録（before値）**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git ls-tree -r --long HEAD | awk -F'\t' '{split($1,m," ");s+=m[4];c++} END{printf "before: %d files %.0f MB\n",c,s/1048576}'
```
Expected: `before: 11847 files 7385 MB`（概ね）。

- [ ] **Step 2: .gitignore 末尾に除外ルールを追記**

`.gitignore` の末尾（`.git_drivebackup/` の次）に以下を追加する:

```gitignore

# ─── 大容量バイナリは Git 管理外（Drive が配布）2026-05-30 GitHub軸移行 ───
# 画像
*.png
*.jpg
*.jpeg
*.webp
*.gif
# 動画・音声の大物
*.mp4
*.mov
# keiba 大容量データ（本番はVPS、ローカルは非稼働の古いコピー）
keiba-unified/jra/data/
# 各種データダンプ・モデル
*.pkl
*.parquet
*.sqlite
*.sqlite3
# 注: *.db は keiba 等のDBダンプ。Git管理したい小さなDBがあれば個別に !path で除外解除する
*.db
```

- [ ] **Step 3: ルールが意図通り効くか確認（追跡解除されるファイル数）**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git ls-files -ci --exclude-standard | wc -l
```
Expected: 数千件（画像中心。概ね 5,000〜6,500 件）。`0` なら追記ミス → Step 2 を見直す。

- [ ] **Step 4: 100MB超の追跡ファイルが除外対象に入ったか確認**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git ls-tree -r --long HEAD | awk -F'\t' '{split($1,m," "); if(m[4]+0>104857600) print m[4]/1048576" MB "$2}'
for f in keiba-unified/jra/data/features_all.pkl keiba-unified/jra/data/features.csv keiba-unified/jra/data/keiba.db; do
  git check-ignore "$f" >/dev/null && echo "IGNORE OK: $f" || echo "!!! 未ignore: $f"
done
```
Expected: 3ファイルすべて `IGNORE OK`。`!!! 未ignore` が出たら Step 2 のパターンを修正。

- [ ] **Step 5: .gitignore 変更を codex/sagyo にコミット（旧ブランチ側の記録として）**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git add .gitignore
git commit -m "chore(repo): 大容量バイナリ(画像/動画/keibaデータ)をgitignore除外（GitHub軸移行の前処理）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git rev-parse --short HEAD
```
Expected: 新しい短縮ハッシュが表示され `1 file changed`。

---

## Task 2: orphan ブランチ `main` を作成し、スリム状態で再ステージ

**Files:** なし（git 操作。working tree は無変更、index のみ再構築）

- [ ] **Step 1: orphan ブランチ main を作成**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git checkout --orphan main
```
Expected: `Switched to a new branch 'main'`。この時点で index は旧ブランチの内容（全追跡ファイル）を引き継いでいる。

- [ ] **Step 2: index を完全クリア（working tree のファイルは消さない）**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git rm -r --cached . >/dev/null 2>&1; echo "index cleared (exit=$?)"
git status --short | head -1
```
Expected: `index cleared (exit=0)`。`--cached` なので Drive 上の実ファイルは一切削除されない（重要）。

> ⚠️ **2026-05-30 実績の落とし穴**: `exit=1` になり index が空にならない場合、**埋め込みgitリポジトリ（gitlink, mode 160000）**が
> 原因のことがある（本リポジトリでは `yn-tools` が該当）。`git rm -r --cached .` は gitlink で停止し全体を中断する。
> その場合は `git rm -r --cached --force .` を使うか、`git ls-files -s | awk '$1==160000{print $4}'` で gitlink を特定して
> `git rm --cached -f <path>` で先に外してから再実行する。`--cached` なので実体は消えない。

- [ ] **Step 3: .gitignore を尊重して再ステージ**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git add -A
git diff --cached --name-only | wc -l
```
Expected: 約 6,000〜7,000 件（11,847 から画像等が抜けた数）。

- [ ] **Step 4: ステージ済み合計サイズを確認（after値・目標248MB前後）**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git diff --cached --numstat >/dev/null 2>&1
git ls-files -s | awk '{print $2}' | git cat-file --batch-check 2>/dev/null | awk '{s+=$3} END{printf "staged blobs: %.0f MB\n", s/1048576}'
```
Expected: `staged blobs: 約 240〜300 MB`。500MB を超えるなら除外漏れ → Task 1 のパターンを追加して Step 2 からやり直す。

---

## Task 3: ステージ内容の安全検証（100MB超ゼロ・機密ゼロ）

**Files:** なし（検証のみ。**このタスクが gate。1件でも問題があれば commit に進まない**）

- [ ] **Step 1: 50MB超の巨大ファイルがステージに無いことを確認**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git ls-files -s | awk '{print $2"\t"$4}' | while IFS=$'\t' read sha path; do
  sz=$(git cat-file -s "$sha" 2>/dev/null); if [ "${sz:-0}" -gt 52428800 ]; then printf "%.1f MB\t%s\n" "$(echo "$sz/1048576"|bc -l)" "$path"; fi
done
echo "--- 上に何も出なければ50MB超ゼロ ✓ ---"
```
Expected: 出力なし（`---` 行のみ）。50MB超が出たら該当を `.gitignore` に追加し Task 2 Step2 からやり直す。

- [ ] **Step 2: 機密ファイルがステージに無いことを確認**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git ls-files | grep -Ei '(^|/)\.env|\.env\.|\.pem$|\.key$|credentials|secret|token|id_rsa|\.pfx$' | grep -vi 'example\|sample\|template\|\.md$' | head -20
echo "--- 上に何も出なければ機密ファイルなし ✓ ---"
```
Expected: 出力なし。1件でも出たら `.gitignore` に追加 → `git rm --cached <該当>` → 再検証。

- [ ] **Step 3: ファイル内容に生の機密が埋まっていないか全種スキャン（最重要ゲート）**

> ⚠️ **2026-05-30 インシデント教訓**: 初回実行時、このゲートで `AIzaSy: 2 / Telegram: 6` の検出が
> 出ていたのに処理をバッチ化して止まらず、機密入りコミットを GitHub に push してしまった。
> **このスキャンで1件でも検出が出たら、commit にも push にも絶対に進まないこと。** 値を除去し
> 再スキャンで全項目0になるまで繰り返す。下記は実際に本リポジトリで検出された全パターンを網羅する。

Run（venv/site-packages 等は誤検知のため除外）:
```bash
cd "g:/マイドライブ/YNFactory-cc"
EXCL='\.venvs/|/site-packages/|Trust Tokens|chrome-cover-profile|chrome_profiles|node_modules/'
echo "Telegram     : $(git grep -lI --cached -E '[0-9]{8,12}:AA[A-Za-z0-9_-]{30,}' 2>/dev/null | grep -vE "$EXCL" | wc -l)"
echo "Gemini       : $(git grep -lI --cached -E 'AIzaSy[A-Za-z0-9_-]{20,}' 2>/dev/null | grep -vE "$EXCL" | wc -l)"
echo "OpenAI/汎用sk: $(git grep -lI --cached -E 'sk-[A-Za-z0-9]{20,}' 2>/dev/null | grep -vE "$EXCL" | wc -l)"
echo "Stripe sk/wh : $(git grep -lI --cached -E 'whsec_[A-Za-z0-9]{20,}|sk_(live|test)_[A-Za-z0-9]{20,}' 2>/dev/null | grep -vE "$EXCL" | wc -l)"
echo "Google GOCSPX: $(git grep -lI --cached -E 'GOCSPX-[A-Za-z0-9_-]{10,}' 2>/dev/null | grep -vE "$EXCL" | wc -l)"
echo "GitHub/Slack : $(git grep -lI --cached -E 'gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}' 2>/dev/null | grep -vE "$EXCL" | wc -l)"
echo "PEM秘密鍵    : $(git grep -lI --cached -E '\-\-\-\-\-BEGIN [A-Z ]*PRIVATE KEY' 2>/dev/null | grep -vE "$EXCL" | wc -l)"
echo "VPSパスワード: $(git grep -lI --cached -E 'sshpass -p|VPS_PASS\s*=\s*\"[^\"]|PASSWORD\s*=\s*.[A-Za-z0-9@]{6,}' 2>/dev/null | grep -vE "$EXCL" | wc -l)  # 旧root PWの平文/ sshpass直書きを検出"
echo "env形式実値  : $(git grep -lI --cached -E '^(SECRET_KEY|DB_PASSWORD|ENCRYPTION_KEY|GOOGLE_CLIENT_SECRET)=[A-Za-z0-9_+/=-]{16,}' 2>/dev/null | grep -vE "$EXCL" | grep -viE 'replace-with|your[_-]|placeholder|example|dummy|change[_-]?me' | wc -l)"
```
Expected: **全項目 0**。1件でも非ゼロなら：①コード→`os.environ.get(...)` 化、②記録/手順書→プレースホルダに伏字化、
③マシン固有設定→`.gitignore` 追加＋`git rm --cached`。除去後に `git add -A && git commit --amend --no-edit` し、再度このスキャンで全0を確認してから次へ。

> 注: `SECRET_KEY=replace-with-...` のようなプレースホルダは誤検知。値が実在のキーか説明文字列かを目視で判別する。
> 機密値そのものは画面に出さず、退避は `[Environment]::SetEnvironmentVariable('NAME',$val,'User')`（PowerShell）で行う。

- [ ] **Step 4: 機密ファイル名・gitlink の確認**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
echo "## settings.local.json（全階層・マシン固有設定）##"
git ls-files | grep 'settings.local.json' || echo "なし ✓"
echo "## gitlink（mode 160000・埋め込みリポジトリ）##"
git ls-files -s | awk '$1==160000{print $4}' || echo "なし"
```
Expected: `settings.local.json` は 0件（`**/.claude/settings.local.json` でignore済みのはず）。gitlink が出たら
（例: `yn-tools` が埋め込みgitだと `git rm -r --cached .` がそこで停止する）→ `git rm --cached -f <path>` で個別解除してから Task 2 Step2 を続行。

---

## Task 4: orphan 初期コミット

**Files:** なし（コミット作成）

- [ ] **Step 1: 初期コミットを作成**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git commit -m "chore(repo): GitHub軸へ移行 — スリム化した新規履歴の初期コミット

- 作業ツリーはDrive維持、.gitはローカル(C:\\dev\\YNFactory-git)、同期軸をGitHub privateへ
- 大容量バイナリ(画像/動画/keibaデータ)はgitignore除外しDrive配布に一本化
- 旧履歴(4.7GB)はローカルのcodex/sagyo他ブランチと.git_drivebackupに温存

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
Expected: `[main (root-commit) ……]` と表示され（**root-commit** が重要＝orphan成功の証拠）、数千 files changed。

- [ ] **Step 2: コミット結果を検証**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
echo "branch=$(git branch --show-current) HEAD=$(git rev-parse --short HEAD)"
git log --oneline -1
git rev-list --count HEAD
```
Expected: `branch=main`、`git rev-list --count HEAD` = `1`（新規履歴なのでコミット1個）。

- [ ] **Step 3: 大容量ファイルが未追跡・無視状態で working tree に残っていることを確認**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
ls -la ".company/outputs/ebooks-manga/" | head -3
git status --short | grep -E '\.(png|jpg|mp4)$' | head -3
echo "--- statusに画像が出なければignore正常・実ファイルはDriveに健在 ✓ ---"
```
Expected: ディレクトリに実ファイルが存在し、かつ `git status` には画像が出ない（ignore されている）。

---

## Task 5: 旧ブランチをアーカイブ名にリネーム（ローカル保持）

**Files:** なし（ローカルブランチのリネーム。push しない＝GitHubには出さない）

- [ ] **Step 1: codex/sagyo をアーカイブ名にリネーム**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git branch -m codex/sagyo archive/pre-github-2026-05-30
git branch
```
Expected: `* main` / `archive/pre-github-2026-05-30` / `codex/ebookgpt5.5` / `master`。旧 commit は archive ブランチが参照し続けるため失われない。

- [ ] **Step 2: 旧履歴がローカルに健在なことを確認**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git log --oneline -3 archive/pre-github-2026-05-30
```
Expected: `163f6b5` 系の旧コミット（設計書・在庫コミット等）が表示される。

---

## Task 6: GitHub private リポジトリ作成 + remote 設定

**Files:** なし（GitHub 側リソース作成 + ローカル remote 設定）

- [ ] **Step 1: gh の git 認証連携を有効化（https push 用）**

Run:
```bash
gh auth setup-git
gh auth status 2>&1 | grep -E 'Logged in|scopes'
```
Expected: `Logged in to github.com account yuichi4107-lab`、scopes に `repo` を含む。

- [ ] **Step 2: private リポジトリを作成（push はまだしない）**

Run:
```bash
gh repo create yuichi4107-lab/YNFactory-cc --private --description "YN Factory 会社運営リポジトリ（作業ツリーはDrive、本リポジトリは履歴同期軸）"
```
Expected: `✓ Created repository yuichi4107-lab/YNFactory-cc on GitHub`。

> 万一「name already exists」が出たら別名（例 `YNFactory-company`）を使い、以降のURLを読み替える。

- [ ] **Step 3: remote origin を設定**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git remote add origin https://github.com/yuichi4107-lab/YNFactory-cc.git
git remote -v
```
Expected: `origin  https://github.com/yuichi4107-lab/YNFactory-cc.git (fetch/push)`。

---

## Task 7: push -u origin main + 検証

**Files:** なし（初回 push）

- [ ] **Step 1: main を push（upstream 設定）**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git push -u origin main
```
Expected: `Writing objects: 100%` → `branch 'main' set up to track 'origin/main'`。途中で 100MB 超エラー（GH001）が出たら push は中断される → Task 3 Step1 に戻り該当ファイルを除外。

> GitHub のプッシュ保護（secret scanning）が機密を検出すると push がブロックされる。ブロックされたら表示された該当箇所を除去して再 push（Task 3 をやり直す）。

- [ ] **Step 2: リモートの状態を検証**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git ls-remote --heads origin
gh repo view yuichi4107-lab/YNFactory-cc --json name,visibility,defaultBranchRef -q '.name+" "+.visibility+" default="+.defaultBranchRef.name'
```
Expected: `refs/heads/main` が表示され、`YNFactory-cc PRIVATE default=main`。

- [ ] **Step 3: GitHub 上のリポジトリサイズが軽量であることを確認**

Run:
```bash
gh api repos/yuichi4107-lab/YNFactory-cc --jq '"size="+(.size|tostring)+" KB  private="+(.private|tostring)'
```
Expected: `size` が概ね 300,000 KB（≒300MB）以下、`private=true`。極端に大きければ大容量混入を疑い Task 3 を再確認。

---

## Task 7.5: 漏洩シークレットのローテーション（2026-05-30 インシデント対応・オーナー実行）

**Files:** 参照のみ — [.company/engineering/debug-log/2026-05-31-secret-rotation-after-github-leak.md](../../../.company/engineering/debug-log/2026-05-31-secret-rotation-after-github-leak.md)

> 背景: 移行作業中に機密入りコミットを private リポジトリへ誤 push（同日削除済み・実被害リスク低）。
> 念のため露出した認証情報をローテーションする。コードからの機密除去自体は完了済み（コミット `e760dc2`）。
> 本Taskは**オーナーが手動で実施**する外部サービス側の作業。

- [ ] **Step 1: 優先度[高] をローテーション**
  - Stripe ライブ secret key（`sk_live_`）+ Webhook secret（`whsec_`）→ VPS `/opt/yn-tools/.env` 更新 → `docker compose up -d`
  - Google OAuth クライアントシークレット（`GOCSPX-`）→ `.env` 更新 → ログイン確認
  - DB パスワード / `SECRET_KEY`（`ENCRYPTION_KEY` は既存暗号化データ確認後）→ `.env` 更新
  - VPS root パスワード（ConoHa パネル or `passwd root`）→ ローカル環境変数 `VPS_ROOT_PW` 更新
  - 手順詳細は上記ローテーション手順書を参照

- [ ] **Step 2: 優先度[低] は判断（private・短時間のため様子見可）**
  - Telegram bot トークン4種 / Gemini キー2種（Gemini は失効済みの可能性大）

- [ ] **Step 3: 完了チェック**
  - 各サービスが新シークレットで正常動作することを確認（手順書のチェックリスト）
  - 旧値が VPS `.env`・ローカル・GitHub のどこにも残っていないこと

---

## Task 8: 2台目セットアップ手順書を改訂

**Files:**
- Modify: `g:\マイドライブ\YNFactory-cc\.company\engineering\docs\gdrive-git-setup.md`（全面改訂）

- [ ] **Step 1: 手順書を確定構成に全面改訂**

`gdrive-git-setup.md` を以下の骨子で書き換える（旧 方法A/B/C 比較は「経緯」として末尾に残す）。frontmatter の `last_updated` を `2026-05-30`、`status: 確定` にする。本文に必須で含める内容:

1. **確定構成の図**（設計書と同じ3レイヤー図）
2. **既存PC（YN_FACTORY）の現状**: `.git`=`C:\dev\YNFactory-git\.git`、remote=GitHub、ブランチ=`main`
3. **2台目以降のセットアップ手順**（コマンド付き・端末固有パスに注意）:
```bash
# 前提: その端末でも作業ツリーは G:\マイドライブ\YNFactory-cc（Drive同期済）
# 1. Drive 側の .git ポインタが他PCのパスを指していると壊れるので、まずローカルに clone
mkdir -p /c/dev
git clone https://github.com/yuichi4107-lab/YNFactory-cc.git /c/dev/YNFactory-cc-clone
# 2. clone した .git だけをローカル保管場所へ移動
mv /c/dev/YNFactory-cc-clone/.git /c/dev/YNFactory-git/.git
# 3. Drive 作業ツリーの .git をこの端末用ポインタに（パスは各端末固有）
echo "gitdir: C:/dev/YNFactory-git/.git" > "/g/マイドライブ/YNFactory-cc/.git"
# 4. clone の残骸を削除し、作業ツリーで認識確認
rm -rf /c/dev/YNFactory-cc-clone
cd "/g/マイドライブ/YNFactory-cc"
git config core.longpaths true
git status   # 正常に動けばOK（大容量はDrive側に既にある）
```
4. **日常運用ルール**: 開始時 `git pull`、終了時 `/handoff`→`git push`
5. **やってはいけないこと**: `.git` 本体を Drive に置く / 大容量を `git add` する
6. **端末別セットアップ状況表**を更新（YN_FACTORY=完了 2026-05-30）

- [ ] **Step 2: コミット**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git add .company/engineering/docs/gdrive-git-setup.md
git commit -m "docs(infra): gdrive-git-setup を確定構成(GitHub軸)に改訂 + 2台目セットアップ手順

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
Expected: `1 file changed`。

---

## Task 9: handoff スキルを push 対応に更新

**Files:**
- Modify: `g:\マイドライブ\YNFactory-cc\.claude\skills\handoff\SKILL.md`

- [ ] **Step 1: 現行の handoff スキルを読んで差分箇所を特定**

Run:
```bash
sed -n '1,40p' "g:/マイドライブ/YNFactory-cc/.claude/skills/handoff/SKILL.md" | grep -n "Drive\|commit\|push\|同期" | head
```
Expected: Step3「Google Drive同期 一時停止 必須」周辺の行が見つかる。

- [ ] **Step 2: Step3 を新構成向けに改訂**

`SKILL.md` の Step3 を以下の方針で書き換える:
1. **Drive 同期一時停止は「任意」に格下げ**（`.git` はローカルになったため commit 競合は原理的に解消。ただし HANDOFF/TODO 等 Drive 上ファイル書き込み中の重複(1)防止に停止は依然有効、と注記）
2. **commit 後に `git push origin main` を追加**（最大3回リトライ）:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git add -A
git commit -m "handoff: [作業サマリーを1行で]

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
for i in 1 2 3; do
  if git push origin main; then echo "[OK] push 成功 (試行 $i)"; break; fi
  echo "[WARN] push 失敗 (試行 $i) → pull --rebase して再試行"; git pull --rebase origin main; sleep 3
done
```
3. **lock パスをローカルに修正**: `.git/index.lock` → `C:/dev/YNFactory-git/.git/index.lock`
4. ブランチ名 `codex/sagyo` の記述を `main` に更新

- [ ] **Step 3: コミット**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git add .claude/skills/handoff/SKILL.md
git commit -m "feat(skill): handoff を GitHub軸対応に更新（push追加・Drive停止を任意化・lockパス修正）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
Expected: `1 file changed`。

---

## Task 10: メモリ・HANDOFF を更新（構成変更の記録）

**Files:**
- Modify: `C:\Users\fcmdt\.claude\projects\g---------YNFactory-cc\memory\project_ynfactory_git_drive_setup.md`
- Modify: `g:\マイドライブ\YNFactory-cc\.company\secretary\HANDOFF.md`

- [ ] **Step 1: メモリを新構成に更新**

`project_ynfactory_git_drive_setup.md` の本文を更新し、以下を反映する（既存の復旧記録は残しつつ追記）:
- 同期軸は **GitHub private `yuichi4107-lab/YNFactory-cc`**、既定/作業ブランチは **`main`**（旧 `codex/sagyo` は `archive/pre-github-2026-05-30` にリネームしローカル保持）
- 大容量バイナリ（画像/動画/keibaデータ）は **Git管理外・Drive配布**
- 日常運用: 開始時 `git pull` / 終了時 `git push`
- 2台目手順は `gdrive-git-setup.md` 参照

- [ ] **Step 2: MEMORY.md のポインタ行を確認（変更不要なら触らない）**

Run:
```bash
grep -n "ynfactory_git_drive_setup" "C:/Users/fcmdt/.claude/projects/g---------YNFactory-cc/memory/MEMORY.md"
```
Expected: 既存の1行が見つかる。説明文が古ければ「GitHub軸・main」へ1行更新。

- [ ] **Step 3: HANDOFF.md に移行完了サマリを追記してコミット**

`HANDOFF.md` frontmatter に `last_session_summary_v2026_05_30_github_migration` を追記（移行完了・GitHub URL・branch=main・残=旧バックアップ削除のみ）。その後:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git add .company/secretary/HANDOFF.md
git commit -m "handoff: 作業ディレクトリGitHub軸移行の記録（branch=main / 大容量Drive一本化）

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git push origin main
```
Expected: push 成功。（メモリファイルはローカル `~/.claude` 配下で git 管理外のため commit 対象外）

---

## Task 11: 最終検証（往復・clone 再現・ロールバック確認）

**Files:** なし（検証のみ）

- [ ] **Step 1: push/pull 往復が成立することを確認**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git fetch origin && git status -sb | head -1
```
Expected: `## main...origin/main`（ローカルとリモートが一致、ahead/behind なし）。

- [ ] **Step 2: 別PCを想定した clone 再現テスト（一時ディレクトリ）**

Run:
```bash
rm -rf /c/dev/_ynfc_clonetest
git clone https://github.com/yuichi4107-lab/YNFactory-cc.git /c/dev/_ynfc_clonetest 2>&1 | tail -3
du -sh /c/dev/_ynfc_clonetest/.git 2>/dev/null
ls /c/dev/_ynfc_clonetest/.company/secretary/HANDOFF.md && echo "ドキュメント取得OK ✓"
ls /c/dev/_ynfc_clonetest/.company/outputs/ebooks-manga/*/*.png 2>/dev/null | head -1 || echo "画像は含まれない(設計通り)✓"
rm -rf /c/dev/_ynfc_clonetest
```
Expected: clone 成功、`.git` が数百MB以下、HANDOFF.md は取得でき、画像は含まれない。

- [ ] **Step 3: ロールバック可能性の確認（旧履歴の生存）**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc"
git log --oneline -1 archive/pre-github-2026-05-30
ls -la "g:/マイドライブ/YNFactory-cc/.git_drivebackup/objects/pack/" | grep pack
```
Expected: 旧 HEAD（`163f6b5` 系）が archive ブランチに健在、`.git_drivebackup` も健在。**この2つが揃っている限り、いつでも旧構成に戻せる。**

- [ ] **Step 4: 完了報告とクリーンアップ案内**

オーナーに以下を報告する:
- GitHub private `YNFactory-cc` へ移行完了、branch=`main`、サイズ ◯◯MB
- 旧履歴は `archive/pre-github-2026-05-30`（ローカル）+ `.git_drivebackup`（4.7GB）に温存
- **数日 運用して問題なければ** `.git_drivebackup` 削除 + Drive ゴミ箱の旧worktree(12.69GB) 削除で約17.5GB解放（このクリーンアップは別途オーナー判断で実施）

---

## Self-Review 結果（計画作成者による確認）

- **Spec 網羅**: 設計書「移行ステップ」1〜6 = Task1〜2/4/6-7/8-9/11 に対応。スリム化(Task1-2)・orphan(Task2-5)・GitHub作成push(Task6-7)・2台目手順書(Task8)・運用ルール=handoff(Task9)・検証(Task11)。spec「未解決」の4点（orphanコマンド／リポ名可視性／2台目手順／handoff改修）も各 Task で確定済。
- **プレースホルダ**: 全 Step に実コマンドと期待出力を記載。Task8/9/10 の文書改訂は骨子＋必須内容を列挙（文章生成タスクのため逐語コードは不要だが含有必須項目を明示）。
- **整合性**: ブランチ名は全 Task で `main`（新規）/`archive/pre-github-2026-05-30`（旧）に統一。remote 名 `origin`、GitHub URL `yuichi4107-lab/YNFactory-cc` を一貫使用。lock パスはローカル `C:/dev/YNFactory-git/.git` に統一。
