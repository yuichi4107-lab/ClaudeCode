---
name: internal-tool-scaffolder
description: Use this skill when creating a new internal business tool project scaffold from the starter kit, including README, AGENTS, environment examples, docs, templates, safe gitignore rules, initial directories, and security-conscious setup without real secrets.
---

# Internal Tool Scaffolder

## 使う場面

新しい社内ツールのプロジェクト雛形を作るときに使う。

既存プロジェクトに導入する場合も使えるが、既存ファイルを無条件に上書くない。

## 基本方針

最初から安全な構成にする。秘密情報を入れず、`.env.example` と `.gitignore` を用意し、READMEとAGENTSで人間向け説明とAI向けルールを分ける。

## 手順

1. 作成先を確認する。
   - プロジェクト名
   - 作成先ディレクトリ
   - 既存ディレクトリか新規ディレクトリか
   - 使用技術が決まっているか

2. 既存ファイルを確認する。
   - `README.md`
   - `AGENTS.md`
   - `.env`
   - `.env.example`
   - `.gitignore`
   - `src/`
   - `tests/`

3. 上書きリスクを判定する。
   - 既存ファイルがある場合は、勝手に上書くない
   - 統合が必要な場合は差分を説明する
   - `.env` は作成・上書きしない

4. 最小構成を作る。

```text
.
├── README.md
├── AGENTS.md
├── .env.example
├── .gitignore
├── docs/
├── src/
├── tests/
├── scripts/
└── templates/
```

5. スターターキットからコピーする。
   - `README.md`
   - `AGENTS.md`
   - `.env.example`
   - `docs/`
   - `templates/`

6. `.gitignore` を用意する。
   - `.env`
   - 秘密鍵
   - ログ
   - DBファイル
   - 依存パッケージ
   - ビルド成果物

7. 技術スタックが指定されている場合だけ、その構成を追加する。
   - Node.js
   - Python
   - Rails
   - Laravel
   - その他

8. 最後に品質確認する。
   - 実シークレットが入っていない
   - `.env` 本体が入っていない
   - 既存ファイルを勝手に上書くていない
   - 起動・テスト扉順の空欄が残っている場合は明記する

## 出力形式

```md
# スキャフォールド結果

## 作成先

## 作成ファイル

## コピーしたテンプレート

## 上書きしなかったファイル

## 追加で必要な設定

## セキュリティ確認

## 次アクション
```

## 禁止事項

- `.env` を作る
- 実際の秘密情報を入れる
- 既存の `README.md` や `AGENTS.md` を無確認で上書きする
- 不要な外部依存を追加する
- 本番DB接続情報を雛形に入れる
- 社外送信設定をデフォルト有効にする
