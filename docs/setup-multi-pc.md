---
title: YNFactory-cc 複数PCセットアップ手順
date: "2026-06-15"
status: active
---

# YNFactory-cc 複数PCセットアップ手順

## 基本方針

`YNFactory-cc` は、2つの作業場所を役割で分ける。

| 場所 | 役割 |
|---|---|
| Google Drive側 `YNFactory-cc` | 日常作業、制作物、入力、生活ログ、ClaudeCode / Codex の共有作業場 |
| ローカルGit側 `YNFactory-cc` | GitHubへ送るコード、ルール、スキル、手順書の履歴管理 |

Drive側では `git commit` / `git pull` / `git push` を実行しない。Git操作は必ずローカルGit側で行う。

## Mac

### 1. Google Drive側を確認

Google Drive for desktop を有効にし、Drive側の `YNFactory-cc` を確認する。

```bash
ls "$HOME/Library/CloudStorage"
```

このPCの現在のDrive側パス:

```text
/Users/yuichi/Library/CloudStorage/GoogleDrive-yuichi4107@gmail.com/マイドライブ/YNFactory-cc
```

ClaudeCode / Codex で日常作業をする場合は、このDrive側フォルダを開く。

### 2. ローカルGit側を確認

GitHubへ送る作業用に、ローカルGit作業ディレクトリを用意する。

```bash
cd ~
git clone https://github.com/yuichi4107-lab/YNFactory-cc.git ~/YNFactory-cc
cd ~/YNFactory-cc
git pull --ff-only origin main
git status --short --branch
```

このPCの標準ローカルGit側パス:

```text
/Users/yuichi/YNFactory-cc
```

### 3. 環境変数

通常のスクリプトや説明では相対パスを使う。PC固有パスが必要な場合だけ環境変数に閉じ込める。

```bash
export YNFACTORY_DRIVE_ROOT="$HOME/Library/CloudStorage/GoogleDrive-yuichi4107@gmail.com/マイドライブ/YNFactory-cc"
export YNFACTORY_ROOT="$HOME/YNFactory-cc"
```

## Windows

### 1. Google Drive側を確認

Google Drive for desktop を有効にし、Drive側の `YNFactory-cc` を確認する。

例:

```text
G:\マイドライブ\YNFactory-cc
```

ClaudeCode / Codex で日常作業をする場合は、このDrive側フォルダを開く。

### 2. ローカルGit側を確認

GitHubへ送る作業用に、ローカルGit作業ディレクトリを用意する。

```powershell
cd C:\
git clone https://github.com/yuichi4107-lab/YNFactory-cc.git C:\YNFactory-cc
cd C:\YNFactory-cc
git pull --ff-only origin main
git status --short --branch
```

Windowsの標準ローカルGit側パス:

```text
C:\YNFactory-cc
```

## 日常作業

### Drive側で作業するもの

- 電子書籍、マンガ、絵本、SNS素材などの成果物
- `.company/outputs/`
- `.company/codex/`
- `.company/inputs/`
- 生活ログ、音声入力、画像、動画、EPUB、PDF、ZIP

### GitHubへ送るもの

- `AGENTS.md`
- `CLAUDE.md`
- `.agents/`
- `.codex/`
- `.company/scripts/`
- `.company/requirements/`
- `docs/`
- 主要コード、設定テンプレート、運用ルール

### Drive側からGitHubへ送る

ローカルGit側で実行する。

```bash
cd ~/YNFactory-cc
python3 .company/scripts/sync_drive_git.py commit-push -m "変更内容" docs AGENTS.md CLAUDE.md
```

Windowsでは `cd C:\YNFactory-cc` に読み替える。

### GitHubからDrive側へ反映する

ローカルGit側で実行する。

```bash
cd ~/YNFactory-cc
python3 .company/scripts/sync_drive_git.py pull-sync
```

## 禁止事項

- Drive側でGit操作しない。
- Drive側に `.git` 本体を置かない。
- 大容量成果物をGitに入れない。
- `.env`、APIキー、トークン、パスワードをGitに入れない。
- 同じファイルを複数PCから同時編集しない。
- 同じ自動化を複数PCで同時起動しない。

## 新しいPCを追加したら最初に読むもの

```text
AGENTS.md
CLAUDE.md
docs/multi-pc-rules.md
docs/backup-zslim.md
.company/secretary/HANDOFF.md
.company/secretary/todos/
```

## 完了チェック

- [ ] Drive側 `YNFactory-cc` が見える
- [ ] ローカルGit側 `YNFactory-cc` が見える
- [ ] ローカルGit側で `git pull --ff-only origin main` が成功する
- [ ] ClaudeCode / Codex でDrive側を開ける
- [ ] GitHubへ送る変更は `sync_drive_git.py` で反映できる
- [ ] ZSlimバックアップ方針を確認した
