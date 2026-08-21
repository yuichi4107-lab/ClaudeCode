# voice-journal

PC起動中に常時録音し、1時間ごとのセグメントを自動で文字起こしして `inbox` に蓄積するサービスです。
マイク音声とPC再生音(WASAPIループバック)を同時録音し、ローカルのfaster-whisper（small/int8）で日本語文字起こしを行います。音声データは外部に送信せず、ローカル完結です。

---

## セットアップ

### 1. 依存ライブラリのインストール

```
py -m pip install -r requirements.txt
```

> **注意**: `faster-whisper` は `ctranslate2` 等を伴い数百MB程度になります。初回起動時にWhisper smallモデルが自動ダウンロードされます（~500MB）。

### 2. `config.json` の確認・編集

| キー | 既定値 | 説明 |
|------|--------|------|
| `temp_dir` | `C:\voice-journal-temp` | 録音FLACの一時保存場所（Drive外推奨） |
| `inbox_dir` | `.company/secretary/inbox` | 文字起こしテキストの保存先 |
| `segment_seconds` | `3600` | セグメント長（秒） |
| `align_to_clock_hour` | `true` | 正時でセグメントを区切る |
| `mic_device` | `null` | マイクデバイスindex。nullで既定 |
| `loopback_device` | `null` | ループバックデバイスindex。nullで自動検出 |
| `capture_system_audio` | `true` | PC再生音を録音する |
| `whisper_model` | `"small"` | Whisperモデルサイズ |
| `whisper_device` | `"auto"` | `auto`=CUDA優先→CPU fallback |
| `language` | `"ja"` | 文字起こし言語 |
| `max_transcribe_retries` | `3` | 文字起こし失敗時のリトライ上限 |

### 3. デバイスの確認

利用可能なオーディオデバイスを確認するには:

```python
import sounddevice as sd
print(sd.query_devices())
```

`mic_device` や `loopback_device` に整数indexを指定して特定デバイスを選択できます。`null` の場合は既定デバイスを使用します。

---

## 起動方法

### 手動起動（テスト・動作確認）

```
start.bat
```

または:

```
py service.py
```

### 自動起動の登録（ログオン時）

2通りあります。**通常は方法A（管理者不要）で十分です。**

#### 方法A：スタートアップ方式（管理者不要・推奨）

`voice-journal` フォルダで PowerShell を開き（管理者でなくてOK）:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_autostart_startupfolder.ps1
```

ユーザーのスタートアップフォルダに `VoiceJournal.lnk` を作成し、次回ログオン時から
`pythonw`（画面なし）で自動起動します。解除は:

```powershell
powershell -ExecutionPolicy Bypass -File .\remove_autostart_startupfolder.ps1
```

#### 方法B：タスクスケジューラ方式（自動再起動つき・要管理者）

クラッシュ時に自動再起動させたい場合。**管理者として** PowerShell を開いて実行:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_autostart.ps1
```

解除（管理者）:

```powershell
powershell -ExecutionPolicy Bypass -File .\remove_autostart.ps1
```

> 補足：方法Bは登録に管理者権限が必要です（権限が無いと「アクセスが拒否されました」になります）。
> その場合は方法Aを使ってください。どちらも登録後は次回ログオン時から自動起動します。

---

## 停止・一時停止

| 操作 | 方法 |
|------|------|
| 完全停止 | `voice-journal` フォルダに `PAUSE.flag` を作成したうえでCtrl+C、またはタスクスケジューラでタスクを終了 |
| 一時停止（録音のみ停止） | `voice-journal\PAUSE.flag` という名前のファイルを作成する |
| 一時停止解除 | `PAUSE.flag` を削除する |

一時停止中はストリームが閉じられ、ファイルへの書き込みが止まります。ファイルを削除すると自動的に録音を再開します。

---

## 保存先

| データ | 場所 |
|--------|------|
| 録音FLACファイル（一時） | `C:\voice-journal-temp\` |
| 文字起こしテキスト | `.company\secretary\inbox\YYYY-MM-DD.md` |
| 失敗セグメント（退避） | `C:\voice-journal-temp\failed\` |
| ログファイル | `voice-journal\logs\voice-journal.log` |

文字起こし済みの音声FLACは自動的に削除されます（`delete_audio_after_transcribe: true`）。
`failed/` フォルダに退避されたFLACはリトライ上限を超えたものです。手動確認後に削除してください。

---

## ログフォーマット（inbox）

```
# 2026-05-31 音声ログ

## 14:00–15:00

（文字起こし本文）

## 15:00–16:00

（文字起こし本文）
```

---

## プライバシー注意事項

- マイクとPC音声を24時間録音します。通話相手・同席者の声も記録されます。
- 録音・記録の同意など、運用上の配慮はオーナーの責任で行ってください。
- 音声データは外部に送信されません（ローカル完結）。文字起こしもローカルのWhisperで処理します。
- テキストのみ `inbox` へ保存されます。音声は処理後に削除されます。
- 一時停止が必要な場合は `PAUSE.flag` を使用してください。

---

## トラブル対応

### ループバックが機能しない

WASAPI ループバックが利用できないデバイス・ドライバでは、システム音声の録音がスキップされます。ログに `Loopback stream failed` と表示される場合、マイクのみで動作を継続します。

### マイクが認識されない

マイクを接続してから再起動してください。デバイスが見つからない場合、30秒ごとに自動再試行します。

### 文字起こしが遅い（キューが溜まる）

ログに `Transcription queue backlog` が表示された場合:
- CPUのみの環境では `whisper_model` を `"tiny"` に変更してください。
- GPUがある場合は `whisper_device` を `"auto"` のままにしておくと自動でGPUを使用します。

### モデルのダウンロードに失敗する

初回起動時にインターネット接続が必要です。Hugging Face にアクセスできる環境で起動してください。

### ログの確認

```
voice-journal\logs\voice-journal.log
```
