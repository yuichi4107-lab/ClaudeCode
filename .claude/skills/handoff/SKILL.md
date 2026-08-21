---
name: handoff
description: セッション終了時のハンドオフ処理。HANDOFF.md更新、TODO更新、Drive↔ローカルGit同期スクリプトの実行までを一括で行い、次回セッションへの引き継ぎを完了する。
---

# ハンドオフスキル (/handoff)

## 概要

セッションの作業内容を記録し、次回セッション（別端末含む）で確実に引き継げるようにする。
「おわり」「また明日」と言わなくても、このスキルを呼ぶだけでハンドオフが完了する。

## 前提: マルチPC作業ディレクトリ構成

- 論理上の作業場所はリポジトリルート（`YNFactory-cc`）。相対パスで統一する
- **Drive側**（このスキルが動く場所。例: `.../GoogleDrive-.../マイドライブ/YNFactory-cc`）には `.git` を置かない。Drive側で `git commit` / `git push` / `git pull` は実行しない
- **ローカルGit作業ディレクトリ**が別途存在する: Mac = `/Users/yuichi/YNFactory-cc`、Windows = `C:\YNFactory-cc`。git操作は必ずこちら側で行う
- Drive側とローカルGit側の反映は `.company/scripts/sync_drive_git.py`（ローカルGit作業ディレクトリから実行）を使う
- 毎日午前3時（Asia/Tokyo）に `.company/scripts/daily_git_sync.py` による自動コミット→push→pullルーティンが動く前提（commit→push→pullの順、機密パターン検知・50MB超ファイル検知つき）。このスキルの手動実行と役割が重複するので、直前に自動同期が走っていないか意識する
- **Macでは `/Users/yuichi/YNFactory-cc` の存在と `.git` の有無を必ず実行時に確認すること。** 存在しない、または `.git` が無い場合は Mac 側で `git commit` は実行できない。その場合は HANDOFF.md / TODO の更新のみ行い、「Drive側のドキュメント更新のみ完了。commit は Windows 側（`C:\YNFactory-cc`）で実施してください」と明記して終える
- Windows側でローカルGit作業ディレクトリが確認できる場合は、そちらから `sync_drive_git.py commit-push` を実行する

## 実行手順

### Step 1: HANDOFF.md 更新

`.company/secretary/HANDOFF.md` を以下のように更新する:

1. **frontmatter を更新**:
   - `last_updated`: 今日の日付 (YYYY-MM-DD)
   - `last_device`: わかれば端末名
   - `last_session_summary`: このセッションで行った作業の要約（1-3行）

2. **「現在進行中の作業」セクションを更新**:
   - 各プロジェクトの状態を最新化
   - 完了した項目はチェック
   - 新たに発覚した問題・ブロッカーを追記
   - 「次のアクション」を更新

3. **技術的なメモ**:
   - VPS の状態変更があれば記録
   - 環境変数やAPI設定の変更があれば記録
   - 既知のバグや回避策を記録

### Step 2: TODO 更新

`.company/secretary/todos/YYYY-MM-DD.md` (今日の日付) を更新:
- ファイルが存在しなければ、前日のTODOから未完了タスクを引き継いで新規作成
- 完了したタスクにチェックを入れる
- 新たに発生したタスクを追加

### Step 3: Drive↔ローカルGit同期・commit・push

Drive側そのものでは git コマンドを実行しない。**ローカルGit作業ディレクトリが存在し `.git` があるか**をまず確認する。

#### 3-1. ローカルGit作業ディレクトリの確認

```bash
# Mac の場合
ls -la /Users/yuichi/YNFactory-cc/.git 2>&1 | head -3
```

- 存在しない／`.git` が無い場合 → **Step 3-2 以降はスキップ**し、Step 4 で「Drive側の更新のみ完了。commit は Windows 側（`C:\YNFactory-cc`）で実施してください」と案内して終える
- 存在する場合 → 3-2 へ進む

#### 3-2. Drive側の変更をローカルGit側へ反映してcommit・push

ローカルGit作業ディレクトリ（例 `/Users/yuichi/YNFactory-cc`、Windowsは `C:\YNFactory-cc`）で実行する:

```bash
cd /Users/yuichi/YNFactory-cc   # Windowsは C:\YNFactory-cc
python3 .company/scripts/sync_drive_git.py commit-push \
  -m "handoff: [作業サマリーを1行で]" \
  .company/secretary/HANDOFF.md .company/secretary/todos/YYYY-MM-DD.md [その他更新した相対パス...]
```

- `commit-push` は「Drive側の指定パスをローカルGit側へコピー → `git add` → `git commit` → `git push`」までを一括実行する
- 引数はリポジトリルートからの**相対パス**のみ（絶対パス不可）。今回のセッションでDrive側で更新した相対パスをすべて列挙する
- コミットメッセージのプレフィックスは必ず `handoff:` にする
- push が失敗する場合は `.company/scripts/sync_drive_git.py pull-sync` で最新化してから再実行する

#### 3-3. 失敗時

- リモートと乖離している場合は先に `python3 .company/scripts/sync_drive_git.py pull-sync` を実行し、GitHub側の最新をpullしてDriveへ反映してから 3-2 を再試行する
- それでも失敗する場合はユーザーに状況報告する（エラーメッセージを添える）

### Step 4: 完了報告

ユーザーに以下を一言で報告:
- 「ハンドオフ完了しました。」
- 更新した内容の要点（1-2行）
- commit/push を実施できなかった場合はその旨と「Windows側でのcommitが必要」であることを明記

## 使い方

- `/handoff` — セッション終了時に手動で呼ぶ
- 会話の最後に自動で実行されることもある（CLAUDE.md のルールに基づく）

## 注意事項

- HANDOFF.md は全端末で共有される最重要ファイル。正確に記述すること
- Drive側では `git` コマンドを一切実行しない（`sync_drive_git.py` はローカルGit作業ディレクトリから実行する）
- 毎日午前3時の自動同期（`daily_git_sync.py`）と手動ハンドオフの内容が競合しないよう、pushが失敗したら必ず `pull-sync` してから再試行する
- 機密情報（APIキー等）は HANDOFF.md に直接書かず、「.env参照」と記述する。コード／設定ファイルにもトークン・パスワードを直書きしない。**2026-05-30に機密混入ファイルをGitHubへ誤pushする事故が実際に発生している**ため、commit-push 前に対象ファイルへの機密混入スキャン（APIキー・トークン・パスワードのパターン確認）を必ず行うこと
- 詳細な同期構成の経緯は [.company/engineering/docs/gdrive-git-setup.md](.company/engineering/docs/gdrive-git-setup.md) を参照（内容が古い場合は本SKILL.mdとプロジェクトルート CLAUDE.md の記述を優先する）
