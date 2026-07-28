# X API 開通手順（2026年版・完全ガイド）

> ⚠️ **このセットアップは最初の難関です。**
> X（旧Twitter）の Developer Portal は画面遷移が分かりにくく、設定を1つでも間違えると投稿できません。
> このドキュメントの手順を**飛ばさず**、**順番通り**に進めてください。

---

## 取得するもの（最終ゴール）

以下の **5つのキー** を取得して、GAS スクリプトプロパティ または `.env` に設定します。

| キー名 | 用途 | 表示される画面 |
|---|---|---|
| **API Key** | アプリ識別子 | Keys and Tokens タブ |
| **API Key Secret** | アプリ秘密鍵 | Keys and Tokens タブ |
| **Bearer Token** | 読み取り用トークン | Keys and Tokens タブ |
| **Access Token** | ユーザー認証トークン | Keys and Tokens タブ |
| **Access Token Secret** | ユーザー認証秘密鍵 | Keys and Tokens タブ |

> 💡 これらは **1度しか表示されない** ので、必ずメモアプリ等にコピー保存してください。
> 紛失した場合は再生成（Regenerate）が必要です。

---

## 公式ドキュメント（一次情報）

つまずいたとき、画面の見え方が違うときはまず公式を確認してください。

| ドキュメント | URL | 内容 |
|---|---|---|
| Developer Platform トップ | https://developer.x.com | アカウント登録の入口 |
| Getting Started | https://docs.x.com/x-api/getting-started/getting-access | アクセス取得の公式手順 |
| About X API | https://docs.x.com/x-api/getting-started/about-x-api | プラン・料金体系 |
| Authentication | https://docs.x.com/resources/fundamentals/authentication | 認証の仕組み |
| OAuth 1.0a (API Key & Secret) | https://docs.x.com/resources/fundamentals/authentication/oauth-1-0a/api-key-and-secret | 今回使う認証方式 |
| Apps overview | https://docs.x.com/resources/fundamentals/developer-apps | アプリ作成の解説 |
| Manage Tokens | https://docs.x.com/resources/fundamentals/authentication/guides/v2-authentication-mapping | トークン再生成 |

---

## Step 1: X Developer Portal にログイン

1. https://developer.x.com を開く
2. 右上の **「Sign in」** をクリック
3. 投稿に使いたい **Xアカウント** でログイン
   - ⚠️ **投稿したい本垢でログインしてください**。別アカウントで作成すると、そのアカウントから投稿されてしまいます

---

## Step 2: 有料プランへの登録

> ⚠️ **2026年現在、Free プランでは投稿API（POST /2/tweets）は使えません。**
> 必ず以下のいずれかに登録してください。

### プラン比較

| プラン | 月額 | 投稿上限 | こんな人向け |
|---|---|---|---|
| **Free** | $0 | 投稿API利用不可 | ❌ このツールでは使えません |
| **Basic** | $200/月 | 月3,000投稿 | 大量投稿する人 |
| **Pay Per Use**（従量課金） | $0 + 従量 | 投稿1件あたり数円 | **個人ユーザー推奨** |
| Pro | $5,000/月 | 月100万投稿 | 企業・大規模運用 |

> 💡 **個人で月数十〜数百投稿なら Pay Per Use がおすすめ**です。

### 登録手順

1. ログイン後、ダッシュボード https://developer.x.com/en/portal/dashboard に移動
2. 左メニュー **「Products」→「X API v2」** を開く
3. 画面上部のプラン選択画面で **「Pay Per Use」** または **「Basic」** を選択
4. **「Subscribe」** または **「Get started」** をクリック
5. 支払い情報（クレジットカード）を登録
6. ユースケース選択画面で **「Making a bot」** または **「Building tools for X users」** を選択
7. プロジェクト名・説明を入力（例: `MyXPostBot`）
8. 利用規約に同意して登録完了

> 📖 公式ガイド: https://docs.x.com/x-api/getting-started/getting-access

---

## Step 3: プロジェクト・アプリを作成

ダッシュボード https://developer.x.com/en/portal/dashboard に戻る。

### 3-1. プロジェクト作成

1. 左メニュー **「Projects & Apps」** をクリック
2. **「+ Add Project」** または **「Create Project」** をクリック
   - すでに登録時に作られていればスキップしてOK
3. 以下を入力:
   - **Project name**: 任意（例: `XPostProject`）
   - **Use case**: `Making a bot`
   - **Description**: 簡単な説明（例: `Auto-posting X via Google Apps Script`）

### 3-2. アプリ作成

1. プロジェクト内で **「+ Add App」** または **「Create App」** をクリック
2. 環境を選択（通常 **「Production」**）
3. **App name**: 全世界でユニークな名前（例: `xskill-yourname-2026`）
   - すでに使われている名前はNG。`yourname` 部分を自分のIDに変える
4. **「Next」** または **「Complete」** をクリック

### 3-3. キーを保存（重要・1回限り）

アプリ作成直後に **以下の3つが画面表示されます。必ずコピーして保存**:

- ✅ **API Key**
- ✅ **API Key Secret**
- ✅ **Bearer Token**

> ⚠️ この画面を閉じると **二度と表示されません**。
> 紛失したらこの後の Step 5 で **Regenerate** が必要です。

---

## Step 4: OAuth 権限設定（最重要・ここを間違えると 403 エラー）

> ❌ デフォルト設定のままでは投稿できません。必ずこの手順を実行してください。

### 4-1. User authentication settings を開く

1. ダッシュボード → 作成したアプリをクリック
2. **「Settings」タブ** を開く
3. 「User authentication settings」セクションの **「Set up」** をクリック

### 4-2. 設定内容

以下の通りに設定:

| 項目 | 設定値 |
|---|---|
| **App permissions** | ⭐ **`Read and Write`** ← デフォルトの `Read` のままだと投稿できません |
| **Type of App** | `Web App, Automated App or Bot` |
| **Callback URI / Redirect URL** | `http://localhost:8080/callback` |
| **Website URL** | 任意のURL（例: 自分のXプロフィールURL） |

4. **「Save」** をクリック

> ⚠️ Direct Message 権限まで欲しい場合は `Read and Write and Direct Message` を選択。今回は不要。

---

## Step 5: Access Token を生成（または再生成）

> ⚠️ **Step 4 で Permissions を変更した後は、Access Token を必ず再生成してください。**
> 古いトークンは Read 権限のままなので、投稿時に 403 エラーになります。

1. アプリ画面 → **「Keys and Tokens」タブ**
2. **「Access Token and Secret」** セクションを探す
3. **「Generate」** または **「Regenerate」** をクリック
4. 表示される以下を **コピー保存**:
   - ✅ **Access Token**
   - ✅ **Access Token Secret**

> ⚠️ こちらも **1度しか表示されません**。

---

## Step 6: GAS スクリプトプロパティに登録（メイン用途）

GAS（Google Apps Script）の自動投稿機能を使う場合:

1. Google スプレッドシートを開く → **「拡張機能」→「Apps Script」**
2. 左メニューの **歯車アイコン（プロジェクトの設定）** をクリック
3. 下部の **「スクリプト プロパティ」** で **「スクリプト プロパティを追加」**
4. 以下4つを登録:

| プロパティ名 | 値 |
|---|---|
| `X_API_KEY` | Step 3-3 でコピーした API Key |
| `X_API_SECRET` | Step 3-3 でコピーした API Key Secret |
| `X_ACCESS_TOKEN` | Step 5 でコピーした Access Token |
| `X_ACCESS_TOKEN_SECRET` | Step 5 でコピーした Access Token Secret |

5. **「スクリプト プロパティを保存」** をクリック

詳しくは [`skills/gas-x-post/SETUP.md`](../skills/gas-x-post/SETUP.md) を参照。

---

## Step 7（補助）: ローカル Python から投稿テストする場合

GAS ではなく、PCから直接投稿テストしたい場合のみ実施。

```bash
cp .env.example .env
```

`.env` を開いて入力:

```
API_KEY=取得したAPI Key
API_KEY_SECRET=取得したAPI Key Secret
BEARER_TOKEN=取得したBearer Token
ACCESS_TOKEN=取得したAccess Token
ACCESS_TOKEN_SECRET=取得したAccess Token Secret
```

```bash
pip install -r requirements.txt

# 確認のみ（投稿しない）
python skills/note-to-x/scripts/post_to_x.py --dry-run

# 実際に投稿
python skills/note-to-x/scripts/post_to_x.py
```

✅ 成功すると以下のように表示されます:
```
投稿成功!
   ID  : 1234567890
   URL : https://x.com/i/web/status/1234567890
   本文: X-skill 開通テスト ✅
```

---

## よくあるエラーと対処法

| エラー | 原因 | 対処法 |
|--------|------|--------|
| `503 Service Unavailable` | プラン未登録 / Free プランのまま | Step 2 の有料プラン登録を完了する |
| `403 Forbidden` | App Permissions が「Read」のまま | Step 4 で `Read and Write` に変更 → Step 5 でトークン再生成 |
| `401 Unauthorized` | APIキーが間違っている | コピーミス確認。`.env` / GAS プロパティを再確認 |
| `401 Unauthorized`（権限変更後） | Permission変更後にトークンを再生成していない | Step 5 を再実行 |
| `429 Too Many Requests` | レート制限超過 | しばらく待つ（自動リトライあり） |
| `400 Bad Request` | 投稿文が長すぎ / 重複投稿 | 280文字以内・直前と同じ本文でないか確認 |

---

## トラブルシューティング: 画面が違う・ボタンが見つからない

X Developer Portal のUIは頻繁に変わります。

1. **公式ドキュメント** https://docs.x.com/x-api/getting-started/getting-access を確認
2. それでも分からなければ Claude / Cursor に **「X Developer Portalで〇〇のボタンが見つからない」** と画面のスクショを貼って質問
3. X コミュニティフォーラム https://devcommunity.x.com/ で同じ症状の投稿を検索

---

## チェックリスト

```
□ Step 1: developer.x.com に投稿用アカウントでログインした
□ Step 2: Pay Per Use または Basic プランに登録した
□ Step 3: プロジェクト・アプリを作成し、API Key / Secret / Bearer Token を保存した
□ Step 4: App Permissions を「Read and Write」に変更した
□ Step 5: Access Token / Secret を（再）生成して保存した
□ Step 6: GAS スクリプトプロパティに4つのキーを登録した（GAS利用時）
□ Step 7: dry-run / GAS の dryRun() でテスト投稿が成功した
```

すべてチェックがついたら、X投稿くんが使える状態です 🎉
