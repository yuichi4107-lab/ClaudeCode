---
name: sales-briefing
description: 毎朝の営業オペレーション承認UI。軸C（法人アウトバウンド）の pending DM をオーナーに提示し、承認・却下を受け付けてVPSに送信指示を出す。Phase 1 では軸Cのみ対応、Phase 2で軸A・Bを統合する。平日朝の営業DM承認や「今日のDM承認」「営業ブリーフィング」を求められたとき、または `/sales-briefing` と入力されたときに使う。
---

# Sales Briefing — 朝の営業承認ワークフロー

## 起動タイミング
- Windows Task Scheduler が平日07:30 に Claude Code を起動しこのスキルを呼び出す
- オーナーが手動で `/sales-briefing` と打っても実行できる

## ステップ

### 1. VPS から最新の approval_queue を取得

```bash
ssh yn-vps "cd /opt/sales-ops && python -c 'import sys; sys.path.insert(0, \"src\"); from core.db import Database; from core.approval_queue import ApprovalQueue; import os, json; from dotenv import load_dotenv; load_dotenv(); db = Database(os.environ[\"SALES_OPS_DB_PATH\"]); q = ApprovalQueue(db); print(json.dumps(q.list_pending(track=\"c\")))'"
```

（実運用では `ssh yn-vps "/opt/sales-ops/venv/bin/python /opt/sales-ops/scripts/list_pending.py --track c --json"` のような薄いCLIラッパーを使う。初期はSSHで直接Python叩く形でOK）

### 2. ペンディング件数をオーナーに提示

```
おはようございます！朝の営業承認です。

軸C（法人アウトバウンド）pending: 47件
  - 税理士事務所: 18件
  - 社労士事務所: 12件
  - 制作会社: 10件
  - その他: 7件

トップ10件を表示して一括承認しますか？
[1] トップ10を一括プレビュー→承認
[2] 業種を絞って選ぶ（税理士だけ、等）
[3] 個別に1件ずつレビュー
[4] 全部skip（今日は送らない）
```

AskUserQuestion でこの4択を提示する。

### 3. 承認UI

- トップN件について、件名+本文冒頭100字+企業名を並べて表示
- オーナーが「全承認」「個別却下」「文面修正」を選べる
- 文面修正時は、該当項目をその場で上書き編集して再度pending化

### 4. 承認アクションをVPSに通知

```bash
ssh yn-vps "cd /opt/sales-ops && ./venv/bin/python -c 'from core.db import Database; from core.approval_queue import ApprovalQueue; import os; from dotenv import load_dotenv; load_dotenv(); db = Database(os.environ[\"SALES_OPS_DB_PATH\"]); q = ApprovalQueue(db); [q.approve(i) for i in [ID1, ID2, ...]]'"
```

### 5. 送信トリガー

```bash
ssh yn-vps "cd /opt/sales-ops && ./venv/bin/python scripts/run_send_approved.py"
```

### 6. 結果サマリーをTelegramに通知

Telegram tool の reply で完了報告:
```
🌅 朝の営業承認 完了 (軸C)
  承認: 10件 / 却下: 3件 / 保留: 34件
  送信結果: 成功 10 / 失敗 0
  返信が来たら15分以内にこのチャットで通知します。
```

### 7. DASHBOARD_SALES.md 更新

今日の送信数を `.company/projects/AI導入支援営業/DASHBOARD_SALES.md` の §1「現状スナップショット」に追記する。

- DM送信数 累計: [前日値] → [前日値 + 今日の承認送信数]
- 今週送信数: [今週累計 + 今日の承認送信数]
- 最終更新日: [今日の日付]
- 返信対応待ちが新着あれば §6「返信対応待ち」に追加

### 8. 月曜のみ — 週次レビュー起動の確認

**本日が月曜日の場合のみ**以下を表示してオーナーに確認する:

```
---
今日は月曜日です。週次営業レビューを実施しますか？
  [Y] はい → /weekly-sales-review を起動します
  [N] いいえ → このまま終了します
```

オーナーが「Y」を選択した場合は `/weekly-sales-review` スキルのステップ1から実行する。
月曜以外の日は、このステップ8はスキップして終了する。

## VPS 接続エイリアス

`~/.ssh/config` に以下を設定済み前提:
```
Host yn-vps
  HostName 163.44.101.31
  User root
  IdentityFile ~/.ssh/conoha_yn_factory
```

## Phase 2 以降の拡張

Phase 2 で軸A（フリーランス応募）・軸B（コンテンツ投稿）の承認も同じフローに統合する。その際 `track` パラメータを `c` から `a, b, c` すべてに拡張するだけで対応可能。

## 参考
- `references/approval-ui.md` — 承認UIのフロー詳細・エッジケース対応
