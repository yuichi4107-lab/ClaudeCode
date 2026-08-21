---
name: note
description: note販売AIチームを単一入口で起動し、企画・構成・章別本文・X告知案・note公開・X投稿・実績分析を媒体別の人間承認つきで進める。
disable-model-invocation: true
argument-hint: "[status|style-corpus|new|resume|promote|publish-note|post-x|analyze] [theme-or-run-id]"
---

`.agents/skills/note/SKILL.md` を最初から最後まで読み、その手順を正本として実行する。役割指示が必要になったら `.agents/skills/note/references/` の該当ファイルを読む。

この呼び出しの引数は `$ARGUMENTS`。承認待ちはメイン会話に残し、各専門工程だけを `.claude/agents/note-team/` のサブエージェントへ前景委譲する。

新規runの前に、固定候補note 3本・X 20件の文体コーパスをローカル承認画面でオーナーが承認する。AIやCLIは承認を代行しない。未承認またはSHA-256不一致ならrun作成と執筆を開始しない。

note下書き、note公開、X本投稿＋1件目リプは、それぞれの工程にローカル承認画面の個別許可が記録され、直前claimに成功した場合だけ専用workerで実行する。LINE送信、予約・定期公開は行わない。
