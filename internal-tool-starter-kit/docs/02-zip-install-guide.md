# ZIP受け取り・導入手順

## 目的

研修や社内配布で受け取ったスターターキットZIPを、安全に展開し、新規社内ツールまたはCodexスキルとして利用できるようにする。

## 前提

このZIPは社内ツール開発の雛形である。

社内配布物であっても、安全確認なしに実行・コピー・上書きしない。特に、スクリプト、設定ファイル、認証情報、外部通信の有無を確認する。

## 1. ZIPを保存する

任意の作業フォルダにZIPを保存する。

```text
Downloads/
└── internal-tool-starter-kit.zip
```

## 2. 展開する

```bash
unzip internal-tool-starter-kit.zip
cd internal-tool-starter-kit
```

Windowsの場合は、右クリックから展開してもよい。

## 3. 中身を確認する

最低限、以下があることを確認する。

```text
README.md
AGENTS.md
docs/
skills/
templates/
```

配布内容によっては `templates/` がない場合もある。その場合は、READMEまたは研修講師の指示に従う。

## 4. 危険なファイルがないか確認する

以下が含まれていないことを確認する。

```text
.env
.git/
node_modules/
dist/
build/
*.log
*.key
*.pem
*.p12
*.sqlite
*.db
```

以下のような実シークレットが入っていないことも確認する。

```text
APIキー
アクセストークン
秘密鍵
本番DB接続文字列
個人情報の実データ
顧客情報の実データ
```

## 5. 利用方法を選ぶ

利用方法は2つある。

```text
A. 新しい社内ツールの雛形として使う
B. Codexのスキルとして登録して使う
```

## A. 新しい社内ツールの雛形として使う

新規プロジェクトを作成する。

```bash
mkdir my-internal-tool
cd my-internal-tool
```

スターターキットから必要なファイルをコピーする。

```bash
cp ../internal-tool-starter-kit/README.md .
cp ../internal-tool-starter-kit/AGENTS.md .
cp ../internal-tool-starter-kit/.env.example .
cp -R ../internal-tool-starter-kit/docs .
```

既存プロジェクトに導入する場合は、既存の `README.md` や `AGENTS.md` を無条件に上書きしない。既存ルールと差分を確認し、必要な部分だけ統合する。

## B. Codexのスキルとして登録して使う

Codexのスキルディレクトリを作成する。

```bash
mkdir -p ~/.codex/skills
```

必要なスキルをコピーする。

```bash
cp -R skills/internal-tool-requirements ~/.codex/skills/
cp -R skills/internal-tool-security-review ~/.codex/skills/
cp -R skills/internal-tool-quality-check ~/.codex/skills/
cp -R skills/internal-tool-handoff ~/.codex/skills/
cp -R skills/internal-tool-scaffolder ~/.codex/skills/
```

Codexを再起動する。

## 6. 動作確認する

Codexで以下のように依頼する

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

期待する結果:

- スキル名に沿った手順で回答される
- セキュリティ確認が省略されない
- 85点以上の品質判定ルールが使われる
- 秘密情報を貼り付けるよう要求されない

## 7. 更新する場合

新しいZIPを受け取った場合は、既存ファイルをいきなり上書きしない。

1. 古いスターターキットを退避する
2. 新しいZIPを別フォルダに展開する
3. `README.md` と `AGENTS.md` の差分を確認する
4. `skills/` の差分を確認する
5. 必要なものだけ更新する

## 8. 削除する場合

Codexスキルを削除する場合は、対象フォルダを削除する。

```bash
rm -rf ~/.codex/skills/internal-tool-requirements
rm -rf ~/.codex/skills/internal-tool-security-review
rm -rf ~/.codex/skills/internal-tool-quality-check
rm -rf ~/.codex/skills/internal-tool-handoff
rm -rf ~/.codex/skills/internal-tool-scaffolder
```

削除後、Codexを再起動する。

## 9. 注意事項

- 本番用の認証情報をZIPに入れない
- 実データを研修用ZIPに入れない
- 不明なスクリプトを実行しない
- 既存プロジェクトの `AGENTS.md` を無確認で置き換えない
- 社外サービスへデータを送る設定を無確認で有効化しない
- 管理者権限が必要な操作は、社内ルールに従って承認を取る

## 10. トラブルシューティング

### Codexがスキルを認識しない

- `~/.codex/skills/<skill-name>/SKILL.md` が存在するか確認する
- `SKILL.md` のfrontmatterに `name` と `description` があるか確認する
- Codexを再起動する

### スキルが意図通り使われない

- `description` が曖昧でないか確認する
- 使う場面が `SKILL.md` に明記されているか確認する
- スキル名を明示して依頼する

### 既存プロジェクトのルールと衝突する

- 既存の `AGENTS.md` を優先する
- 差分を確認する
- 研修用ルールをそのまま上書きせず、必要部分だけ取り込む
