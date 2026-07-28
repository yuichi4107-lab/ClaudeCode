# 音声録音アプリ

インストール不要のブラウザ完結型音声録音Webアプリです。
外部ライブラリ・フレームワーク不使用のバニラJavaScript実装です。

## 機能概要

- マイクからの音声録音（開始 / 停止 / 一時停止 / 再開）
- 録音中のリアルタイム波形表示（Web Audio API AnalyserNode + Canvas）
- 経過時間タイマー（mm:ss 形式）
- 録音完了後のインライン再生
- 録音リスト管理（再生 / ダウンロード / リネーム / 削除）
- IndexedDB による録音データの永続保存（ページ再読み込み後も復元）
- WebM ダウンロード / WAV 変換ダウンロード
- マイクデバイス選択（複数デバイス対応）
- 日本語 UI・レスポンシブレイアウト・ダークモード対応
- 日本語エラーメッセージ（権限拒否・デバイス未接続・非対応ブラウザ）

---

## ローカル起動手順

> 重要: マイクへのアクセスにはセキュアコンテキスト（`https://` または `http://localhost`）が必要です。
> ファイルを直接ブラウザで開く（`file://` URL）と、マイクが使用できません。**必ず下記の方法で起動してください。**

### ★ かんたん起動（Windows・推奨）

1. このフォルダ内の **`start.bat`** を**ダブルクリック**します
2. 小さな黒いウィンドウが開き、数秒で**ブラウザが自動的に開きます**（`http://localhost:8765/`）
3. 録音を終えたら、その黒いウィンドウを閉じるとアプリが停止します

> `start.bat` は Python / Node.js を自動検出してローカルサーバを起動します。
> どちらも入っていない場合はインストール案内が表示されます。

---

### 手動で起動する場合（Mac / Linux / 上級者向け）

#### Python（推奨・インストール済みの場合）

```bash
# voice-recorder ディレクトリに移動
cd voice-recorder

# Python 3 でローカルサーバーを起動
python -m http.server 8000

# ブラウザで以下を開く
# http://localhost:8000
```

### Node.js がある場合

```bash
cd voice-recorder
npx serve .

# ブラウザで表示された URL を開く（通常 http://localhost:3000）
```

### VS Code を使っている場合

- 拡張機能「Live Server」をインストール
- `index.html` を右クリック → 「Open with Live Server」

---

## 使い方

### 録音する

1. ブラウザで `http://localhost:8000` を開く
2. 「マイクデバイス」のドロップダウンで使用するマイクを選択（任意）
3. 「録音開始」ボタンをクリック
4. マイク使用の許可を求めるダイアログが表示されたら「許可」をクリック
5. 録音中は波形がリアルタイムで表示され、タイマーがカウントされます
6. 「一時停止」で録音を中断、再度クリックで再開いても、デバイス名が「マイク 1」のように表示される場合があります（権限取得後に「更新」ボタンで正式名称が表示されます）。

---

## ファイル構成

```
voice-recorder/
├── start.bat    # かんたん起動ツール（Windows・ダブルクリック）
├── index.html   # メインHTML
├── style.css    # スタイルシート（ライトモード / ダークモード対応）
├── app.js       # アプリロジック（MediaRecorder / Web Audio API / IndexedDB）
└── README.md    # このファイル
```

---

## 技術仕様

- **MediaRecorder API**: 録音の開始・停止・一時停止・再開
- **Web Audio API AnalyserNode**: リアルタイム波形描画
- **IndexedDB**: 録音 Blob + メタデータの永続保存
- **AudioContext.decodeAudioData**: WAV 変換（RIFF PCM 16bit エンコード）
- **MediaDevices.enumerateDevices**: マイクデバイス一覧取得
- 外部ライブラリ・CDN・ビルドツール: なし（バニラJS）
