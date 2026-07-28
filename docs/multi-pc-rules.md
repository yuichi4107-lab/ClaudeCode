---
title: マルチPC共有ルール
status: active
last_updated: "2026-06-15"
applies_to: "YNFactory-cc を複数PCと ClaudeCode / Codex で共有する全作業"
---

# マルチPC共有ルール

## 0. 結論

`YNFactory-cc` は、Google Drive、GitHub、ZSlimバックアップの3層で運用する。

| レイヤー | 役割 | 置き場 |
|---|---|---|
| Google Drive | 日常作業場、制作物、入力、生活ログ、ClaudeCode / Codex 共有作業場 | Drive側 `YNFactory-cc` |
| GitHub | コード、ルール、スキル、手順書の履歴 | `yuichi4107-lab/YNFactory-cc` |
| ZSlim | Drive削除・上書き・破損から戻す世代バックアップ | `/Volumes/ZSlim/YNFactory-backups/restic` |

Drive側ではGit操作しない。Git操作は各PCのローカルGit作業ディレクトリで行う。

## 1. 作業場所

### Drive側

日常作業はDrive側で行う。

Macの例:

```text
/Users/yuichi/Library/CloudStorage/GoogleDrive-yuichi4107@gmail.com/マイドライブ/YNFactory-cc
```

Windowsの例:

```text
G:\マイドライブ\YNFactory-cc
```

### ローカルGit側

GitHubへ送る変更はローカルGit側で扱う。

Mac:

```text
/Users/yuichi/YNFactory-cc
```

Windows:

```text
C:\YNFactory-cc
```

## 2. Gitに入れるもの

原則として、履歴を残したいコード・ルール・手順だけをGitHubへ送る。

- `AGENTS.md`
- `CLAUDE.md`
- `.agents/`
- `.codex/`
- `.company/scripts/`
- `.company/requirements/`
- `docs/`
- 主要コード
- 設定テンプレート

## 3. Gitに入れないもの

以下はDrive側に残し、GitHubへ送らない。

- `.company/outputs/`
- `.company/codex/`
- `.company/inputs/` の生成・取込状態
- 画像、動画、音声、EPUB、PDF、ZIP
- `.company/.venvs/`
- `node_modules`
- `.env`、APIキー、トークン、認証情報
- ブラウザプロファイル、Playwrightスナップショット、キャッシュ

必要な小さなテキスト成果物だけをGitへ送る場合は、対象パスを明示して個別に扱う。

## 4. Drive側からGitHubへ送る

ローカルGit側で実行する。

```bash
cd /Users/yuichi/YNFactory-cc
python3 .company/scripts/sync_drive_git.py commit-push -m "変更内容" <相対パス...>
```

Windowsでは `cd C:\YNFactory-cc` に読み替える。

重要:

- パスはリポジトリルートからの相対パスで指定する。
- `git add -A` のような広いステージングは避ける。
- 秘密情報・大容量ファイル・生成物が混ざっていないか確認する。

## 5. GitHubからDrive側へ反映する

ローカルGit側で実行する。

```bash
cd /Users/yuichi/YNFactory-cc
python3 .company/scripts/sync_drive_git.py pull-sync
```

これにより、GitHubから取得したコード・ルール・手順書がDrive側へ戻る。

## 6. 同時編集ルール

- 同じファイルを複数PCから同時に編集しない。
- `.company/secretary/HANDOFF.md` と当日TODOは、その日の主担当PCだけが書く。
- 自動化は1つのPCまたはVPSだけで動かす。同じタスクを複数PCに登録しない。
- Drive競合コピーを見つけたら、片方を即削除せず、本体へ内容を統合してから削除する。

## 7. バックアップ

Google Drive同期はバックアップではない。削除や破損も同期される。

このPCでは、ZSlimへ世代バックアップする。

```bash
cd /Users/yuichi/YNFactory-cc
python3 .company/scripts/backup_zslim_restic.py run
```

保持期間:

- 日次7世代
- 週次8世代
- 月次12世代

詳細は `docs/backup-zslim.md` を読む。

## 8. 実行直前に承認が必要な操作

以下は、方針が決まっていても直前承認を取る。

- `.git_drivebackup` の削除
- Drive競合ファイルの削除
- 大規模な `git rm --cached`
- 外部サービスへの投稿、送信、公開
- 本番環境への不可逆反映

## 9. 禁止事項

- Drive側で `git commit` / `git pull` / `git push` しない。
- Drive側に `.git` 本体を置かない。
- `.env` や実トークンをGitに入れない。
- 大容量成果物をGitに入れない。
- `git push --force` を使わない。
- 手作業でDrive側とローカルGit側を丸ごと上書き同期しない。

## 10. 迷ったとき

- 制作物か、履歴管理したいコードかを先に分ける。
- 制作物ならDrive側に置く。
- コード・ルール・手順ならGitHubへ送る。
- 復元性が必要ならZSlimバックアップを見る。
