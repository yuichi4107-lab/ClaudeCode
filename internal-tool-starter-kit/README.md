# 社内ツール開発スターターキット

## 概要

このパッケージは、企業内ネットワークで使う社内ツールを安全に作るためのスターターキットです。

`README.md` は人間向け、`AGENTS.md` はAIエージェントや開発担当者向け、`skills/` はCodexに登録して使う手順書です。

## 内容

```text
.
├── README.md
├── AGENTS.md
├── .env.example
├── docs/
│   ├── 01-skill-creation-guide.md
│   └── 02-zip-install-guide.md
├── skills/
│   ├── internal-tool-requirements/
│   ├── internal-tool-security-review/
│   ├── internal-tool-quality-check/
│   ├── internal-tool-handoff/
│   └── internal-tool-scaffolder/
└── templates/
    ├── project-plan.template.md
    ├── handoff-report.template.md
    └── gitignore.template
```

## 使い方

新しい社内ツールの雛形として使う場合は、対象プロジェクトに以下をコピーします。

```text
README.md
AGENTS.md
.env.example
docs/
```

Codexスキルとして使う場合は、`skills/` 配下を `~/.codex/skills/` カピーします。

```bash
mkdir -p ~/.codex/skills
cp -R skills/internal-tool-requirements ~/.codex/skills/
cp -R skills/internal-tool-security-review ~/.codex/skills/
cp -R skills/internal-tool-quality-check ~/.codex/skills/
cp -R skills/internal-tool-handoff ~/.codex/skills/
cp -R skills/internal-tool-scaffolder ~/.codex/skills/
```

## 含まれるスキル

```text
internal-tool-requirements
  要件定義、スコープ、完了条件、権限、データ分類を整理する。

internal-tool-security-review
  秘密情報、個人情報、ログ、権限、外部通信、破壊的操作を確認する。

internal-tool-quality-check
  実装後に100点満点で品質を確認し、85点以上を合格にする。

internal-tool-handoff
  作業終了時に変更内容、確認結果、残リスク、次アクションを残す。

internal-tool-scaffolder
  新しい社内ツールの安全な雛形を作る　
```

## 注意事項

- 実際の秘密情報をこのパッケージに入れない
- `.env` を配布しない
- 個人情報や顧客情報の実データを入れない
- 既存プロジェクトの `AGENTS.md` を無確認で上書きしない
- 社内ツールであっても認証・権限・ログ・外部通信を確認する

## 詳細手順

- スキル作成: `docs/01-skill-creation-guide.md`
- ZIP導入: `docs/02-zip-install-guide.md`
