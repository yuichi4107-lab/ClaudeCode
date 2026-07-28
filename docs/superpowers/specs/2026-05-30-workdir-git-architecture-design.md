---
title: YNFactory-cc 作業ディレクトリ恒久構成 設計書
date: "2026-05-30"
status: approved
author: 秘書（Claude Code / brainstorming）
supersedes: .company/engineering/docs/gdrive-git-setup.md（方法A/B/C の比較。本設計で方針確定）
related:
  - .company/engineering/debug-log/2026-05-30-git-head-recovery.md（本設計の発端となった障害）
  - メモリ project_ynfactory_git_drive_setup
---

# YNFactory-cc 作業ディレクトリ恒久構成 設計書

## 概要

### 背景（なぜこの設計が必要か）
`G:\マイドライブ\YNFactory-cc` は Google Drive for desktop 上にあり、複数PCを行き来して作業している。
これまで `.git` を Drive 同期下に置いていた（または方法Bの移設が中途半端だった）ため、Drive 同期と git の
競合で **index 破損・HEAD 消失・ハンドオフ commit ハング** が繰り返し発生してきた。

2026-05-30、`.git` の HEAD 消失で全 git コマンドが `fatal: not a git repository` となる障害が発生し、
`.git_drivebackup` からの復旧を実施した（debug-log 参照）。この復旧は「方法B（.git をローカル `C:\dev` へ）」
の構成だが、**方法B 単独は複数台運用では原理的に破綻する**（`.git` が各PCローカルに分離し、2台目では履歴が
無い／ポインタが別PCのパスを指して壊れる）。実際、今日の障害もこの構成の不備の下で起きた。

### ゴール
複数PCを行き来しても安全に履歴を同期でき、Drive 同期との競合が**原理的に再発しない**作業ディレクトリ構成を
確定し、移行する。

### 確定した方針（オーナー承認済み）
- 端末構成: **複数台を行き来する**
- 同期軸: **GitHub private リポジトリ**（このリポジトリは現在 remote 未設定。yntools では既に GitHub 運用中）
- 作業ツリー: **Drive 上に維持**（既存スキルの絶対パス前提を壊さないため）
- 大容量バイナリ: **Drive 一本化**（git 管理外にし、Drive が配布）
- 履歴: **orphan で新規履歴を開始**（旧 4.7GB 履歴はローカルバックアップに温存）

---

## 設計・方針

### アーキテクチャ（3レイヤーの役割分担）

```
┌─ 作業ツリー: G:\マイドライブ\YNFactory-cc\   ← Drive同期（スキルのパス不変・全PCへ配布）
│   ├─ コード/ドキュメント (.md/.py/.html/.pdf 等 ≈248MB)   → Git + GitHub で履歴同期
│   └─ 大容量成果物 (画像/EPUB/keibaデータ/動画 ≈7.1GB)     → Git管理外、Driveのみが配布
│
└─ .git: C:\dev\YNFactory-git\.git  ← 各PCローカル（Drive に絶対乗せない）
                                       ↕ push / pull
                              GitHub private リポジトリ（同期の軸）
```

| レイヤー | 置き場 | 役割 | 同期方法 |
|---|---|---|---|
| **作業ツリー**（オーナーが触る場所） | `G:\マイドライブ\YNFactory-cc\`（現状維持） | 全ファイルの実体 | Drive（全PCに自動配布） |
| **大容量成果物**（画像/EPUB/keiba/動画） | 作業ツリー内（同上） | 生成物 | Drive のみが配布 |
| **`.git`（履歴）** | `C:\dev\YNFactory-git\.git`（各PCローカル） | コード+ドキュメントの履歴 | GitHub private 経由で pull/push |

**作業ディレクトリは `G:\マイドライブ\YNFactory-cc\` のまま変わらない。** 変わるのは裏方（`.git` の置き場＝
ローカル、同期軸＝GitHub）だけ。

### なぜ競合が再発しないか
Drive は「大容量ファイルの配布」、GitHub は「履歴の同期」と**責務が完全に分離**される。
Drive が `.git` の中身（index/HEAD/objects）に触れることが二度と無くなるため、今日の HEAD 消失・
index 破損・ハンドオフハングが原理的に発生しなくなる。方法B の弱点（履歴がローカル分離して 2台目で
壊れる）は、GitHub を介した pull/push が埋める。

### 採用しなかった案とその理由
- **方法A（Drive維持・ストリーミングで.git除外）**: 複数台で履歴が同期されない。かつ今日の障害はこの系統の
  構成下で実際に発生しており、信頼性が不足。
- **純粋GitHub軸（クローンをDrive外に）**: 最もクリーンだが、既存スキルが Drive 絶対パス（`g:\マイドライブ\…`）
  前提で大量に書かれており、全書き換えが必要で改修コストが過大。
- **方法C（ハイブリッド・成果物だけsymlink）**: 理想形だが構造大改修＋symlink運用で最も重い。YAGNI。

---

## 詳細

### 現状の実測値（2026-05-30 時点）
- 追跡ファイル: **11,847 / 7.21GB**（`.git` は圧縮後 4.7GB）
- GitHub 100MB/ファイル制限を**超過しているファイルが既に存在**（そのままでは push 不可）:
  - `keiba-unified/jra/data/features_all.pkl` 117.3 MB
  - `keiba-unified/jra/data/features.csv` 106.5 MB
  - `keiba-unified/jra/data/keiba.db` 102.3 MB
  - `keiba-unified/jra/data/keiba_live.db` 54.5 MB（警告ライン超）
- 拡張子別サイズ（除外候補）: png 5,622.9MB / jpg 1,074.9MB / db 157.3MB / csv 125.8MB / pkl 120.1MB / mp4 36.2MB
- 容量の本体: `.company/outputs/ebooks-manga/` = 5.35GB（マンガ画像）

### スリム化の対象（git 管理外にする＝Drive 一本化）
拡張子ベースで除外:
- 画像: `*.png` `*.jpg` `*.jpeg` `*.webp`
- 動画: `*.mp4`
- keiba データ: `keiba-unified/jra/data/`（`*.pkl` `*.csv` `*.db` 等）

**残すもの**: `.md` / `.py` / `.html` / `.css` / `.js` / `.pdf` / フォント / 設定ファイル等のテキスト・コード主体。
→ **スリム化後の Git 追跡サイズ ≈ 248MB**、100MB超ファイルはゼロになり GitHub push が現実的になる。

> 注: `.gitignore` には既に `*.epub` `*.mobi` が登録済み（EPUB は元々 Drive 保全）。
> 本設計では画像・動画・keibaデータを追加する。

### 履歴の扱い（orphan 新規履歴）
GitHub は「push する履歴のどこかに 100MB 超ファイルがあれば丸ごと拒否」する。現履歴には keiba の
117MB ファイル等が埋まっているため、過去履歴をそのままは push できない。

→ **orphan ブランチで新規履歴を開始**:
1. 現在のスリム状態を「初期コミット1つ」として新しい履歴を作る
2. 旧履歴（4.7GB・全コミット）は `C:\dev` 上の `.git_drivebackup` 相当にアーカイブ温存（参照可能）
3. GitHub には軽量な新規履歴のみを push

**トレードオフ（承知の上で採用）**:
- 旧コミットの細かい変更履歴は GitHub には載らない（ローカルアーカイブ参照になる）
- 画像/EPUB 等は Git で版管理されない（Drive の版管理に依存）

### 機密情報の保護
- `.env` `*.pem` `*.key` `secrets/` `credentials.json` は既に `.gitignore` 済み
- **push 前に最終スキャンを実施**（追跡ファイルに API キー・トークン・VPS 認証が混入していないか）
- GitHub は必ず **private**

### 移行ステップ（実装計画で詳細化）
1. **スリム化**: `.gitignore` 追記 → `git rm --cached -r` で大容量を追跡解除（実ファイルは残す）
2. **orphan 新規履歴**: 現スリム状態を初期コミット化。旧 `.git` はアーカイブ温存
3. **GitHub private 作成 + 初回 push**（≈248MB）
4. **2台目以降の手順書**: 各PCで `.git` ローカル配置 + gitdir ポインタ + remote 設定（gdrive-git-setup.md を改訂）
5. **運用ルール更新**: 作業開始時 `git pull`、終了時 `/handoff`→`git push`。handoff スキルを更新
6. **検証**: push/pull 往復、別PC想定の clone 再現、100MB超ファイル混入ゼロ、機密混入ゼロを確認

### 運用ルール（移行後）
- **作業開始時**: `git pull`（最新履歴を取得）
- **作業終了時**: `/handoff` → `git commit` → `git push`
- **大容量ファイル**: Git に追加しない（Drive が自動配布）。新種の大容量拡張子が出たら `.gitignore` に追記
- **`.git` は各PCローカル固定**。Drive 側 `.git` はポインタファイルのみ（今日の構成を踏襲）

---

## 再発防止
- `.git` を Drive 同期下に置かない（ローカル `C:\dev\YNFactory-git\.git` 固定、Drive 側はポインタ）
- 大容量バイナリを Git に入れない（`.gitignore` で除外、Drive 配布に一本化）
- ハンドオフ時の git 操作はローカル `.git` に対してのみ走るため、Drive 同期一時停止が不要になる
- 複数台の履歴整合は GitHub が担保（手動 Drive 同期に依存しない）

## 未解決・実装計画で詰める点
- orphan 切り替えの正確なコマンド手順（現ブランチ `codex/sagyo` をどう扱うか）
- GitHub リポジトリ名・可視性（private 確定）・既存 yntools リポジトリとの分離
- 2台目セットアップ手順書の具体化（gitdir ポインタは端末固有パスを含む）
- handoff スキルの push 対応改修範囲
