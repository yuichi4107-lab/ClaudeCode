# スキル作成手順

## 目的

社内ツール開発で繰り返し使う作業手順を、CodexのSkillとして整理する。

Skillは人間向けの説明書ではなく、AIエージェントに「いつ、何を、どの順番で確認するか」を渡すための短い手順書として作る。

## 基本構成

1つのスキルは1つのフォルダで管理する。

```text
skills/
└── internal-tool-security-review/
    └── SKILL.md
```

必要に応じて以下を追加する。

```text
skills/
└── internal-tool-security-review/
    ├── SKILL.md
    ├── references/
    │   └── checklist.md
    ├── scripts/
    │   └── check_secrets.sh
    └── assets/
        └── report-template.md
```

## 役割分担

```text
SKILL.md
  AIが最初に読む中核手順。

references/
  必要なときだけ読む詳細資料。長いチェックリストや規程を置く。

scripts/
  毎回同じ処理を確実に行うための補助スクリプトを置く。

assets/
  出力物の雛形やコピーして使うテンプレートを置く。
```

## SKILL.mdの基本形

```md
---
name: internal-tool-security-review
description: Use this skill when reviewing internal business tools for security risks such as secrets, personal data, logs, permissions, external communication, destructive operations, and production safety.
---

# Internal Tool Security Review

## 使う場面

社内ツールのリリース前、認証・権限・個人情報・ログに関わる変更時に使う。

## 手順

1. 扱うデータを確認する。
2. 秘密情報の混入を確認する。
3. 認証・権限を確認する。
4. ログ・外部通信を確認する。
5. リリース可否を判定する。

## 出力形式

- Critical
- High
- Medium
- Low
- リリース可否
```

## 作成手順

1. スキル名を決める。
   - 小文字
   - ハイフン区切り
   - 1スキル1目的

2. `description` を書く。
   - いつ使うスキルかを明確にする
   - 対象作業を具体的に書く
   - トリガーになりそうな単語を含める

3. 本文を書く。
   - 最初に「使う場面」を書く
   - 次に「基本方針」を書く
   - その後に「手順」を番号付きで書く
   - 最後に「出力形式」と「禁止事項」を書く

4. 必要なら `references/` に分ける。
   - 長い規程
   - 詳細チェックリスト
   - 社内固有の判断基準
   - API仕様やDB仕様

5. 必要なら `scripts/` に分ける。
   - 秘密情報パターン検出
   - 雛形生成
   - 定型フォーマット変換
   - 機械的な検証

6. 動作確認する。
   - 想定プロンプトでスキルが使いやすいか確認する
   - 出力が実務で使えるか確認する
   - 長すぎないか確認する

## 命名例

```text
internal-tool-requirements
internal-tool-security-review
internal-tool-quality-check
internal-tool-handoff
internal-tool-scaffolder
```

## 書いてよいもの

- 作業手順
- 判断基準
- チェックリスト
- 出力フォーマット
- 参照すべきファイル名
- 安全上の禁止事項
- 研修用のダミー値

## 書いてはいけないもの

- 実際のパスワード
- APIキー
- トークン
- 秘密鍵
- 本番DB接続文字列
- 個人情報や顧客情報の実データ
- 社内限定の詳細URL
- 長すぎる社内規程の全文
- READMEのような人間向け説明だけの文章

## 品質チェック

作成後、以下を確認する。

- `SKILL.md` が存在する
- frontmatterに `name` がある
- frontmatterに `description` がある
- `description` だけで使う場面が分かる
- 1スキル1目的になっている
- 手順が具体的である
- 出力形式がある
- 禁止事項がある
- 秘密情報が含まれていない
- 長すぎない

## 動作確認プロンプト例

```text
internal-tool-requirements を使って、この社内ツールの要件定義をしてください。
```

```text
internal-tool-security-review を使って、この変更のセキュリティレビューをしてください。
```

```text
internal-tool-quality-check を使って、実装後の品質チェックをしてください。
```

```text
internal-tool-handoff を使って、この作業の引き継ぎを作成してください。
```

```text
internal-tool-scaffolder を使って、新しい社内ツールの雛形を作成してください。
```

## 配布前チェック

ZIP化する前に以下を確認する。

- `.env` が入っていない
- 秘密情報が入っていない
- `node_modules` が入っていない
- 巨大ログが入っていない
- `.git` が入っていない
- 不要な一時ファイルが入っていない
- 受講者が読む導入手順が入っている
