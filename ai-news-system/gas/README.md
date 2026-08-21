# Google Apps Script Webアプリ - セットアップ手順

AIニュース配信システムのGoogle Docsアーカイブ機能で使用するGAS Webアプリの設定手順です。

## 1. アーカイブフォルダのIDを確認

Google Drive上の `ai-news-system/archive/` フォルダをアーカイブ先として使用します。

1. Google Driveで `マイドライブ > YNFactory-cc > ai-news-system > archive` フォルダを開く
2. URLからフォルダIDを控える
   - URL例: `https://drive.google.com/drive/folders/XXXXXXXXXXXXXXX`
   - `XXXXXXXXXXXXXXX` の部分がフォルダID

## 2. Google Apps Scriptプロジェクトを作成

1. [script.google.com](https://script.google.com/) にアクセス
2. 「新しいプロジェクト」をクリック
3. プロジェクト名を設定（例: `AIニュースアーカイブ`）

## 3. スクリプトを設定

1. デフォルトの `コード.gs` の内容を全て削除
2. `code.gs` の内容をコピーして貼り付け
3. 保存（Ctrl+S）

## 4. スクリプトプロパティを設定

1. 左メニューの歯車アイコン「プロジェクトの設定」をクリック
2. 「スクリプト プロパティ」セクションで以下を追加:

| プロパティ名 | 値 |
|---|---|
| `AUTH_TOKEN` | 任意のランダムな文字列（認証用トークン） |
| `ROOT_FOLDER_ID` | 手順1で控えたフォルダID |

トークンの生成例（ターミナルで実行）:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 5. Webアプリとしてデプロイ

1. 右上の「デプロイ」→「新しいデプロイ」をクリック
2. 左の歯車アイコンで種類を「ウェブアプリ」に設定
3. 以下の設定を行う:
   - **説明**: 任意（例: `AIニュースアーカイブv1`）
   - **次のユーザーとして実行**: `自分`
   - **アクセスできるユーザー**: `全員`
4. 「デプロイ」をクリック
5. 初回はGoogleアカウントの認証許可が求められるので許可する
6. 表示される **ウェブアプリのURL** を控える

## 6. 環境変数を設定

AIニュース配信システムの `.env` に以下を追加:

```
GAS_WEBAPP_URL=https://script.google.com/macros/s/xxxxxxxxxxxx/exec
GAS_AUTH_TOKEN=手順4で設定したAUTH_TOKENと同じ値
```

## デプロイの更新

スクリプトを修正した場合は、新しいデプロイを作成する必要があります:

1. 「デプロイ」→「デプロイを管理」
2. 右上の鉛筆アイコンをクリック
3. バージョンを「新しいバージョン」に変更
4. 「デプロイ」をクリック
