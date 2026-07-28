# マルチAI壁打ちツール (multi-ai-sparring)

役割の異なる複数のAIエージェントに、1つの議題について順番に議論させ、
人間が各ラウンドの区切りで割り込める「壁打ち」ツールです。
最後に司会AIが議論全体をまとめ、Markdownファイルに保存します。

すべてのAI呼び出しは **OpenRouter**（OpenAI互換API）経由なので、
`openai` ライブラリ1つで複数社のモデル（OpenAI / Anthropic / Google など）を使えます。

---

## 1. 必要なもの

- Python 3.10 以上（このMacでは `python3.12` が利用可能です）
- OpenRouter のAPIキー … https://openrouter.ai/keys で取得

---

## 2. インストール手順

ターミナルでこのフォルダに移動してから、順番に実行してください。

```bash
# 1) このフォルダへ移動
cd multi-ai-sparring

# 2) 仮想環境を作る（プロジェクト専用のPython環境。1回だけでOK）
python3.12 -m venv .venv

# 3) 仮想環境を有効化する（ヰーミナルを開くたびに実行）
source .venv/bin/activate

# 4) 必要なライブラリをインストールする
pip install -r requirements.txt
```

> Windows の場合、手順3は `.venv\Scripts\activate` です。

---

## 3. APIキーの設定

```bash
# .env.example をコピーして .env を作る
cp .env.example .env
```

作成した `.env` をテキストエディタで開き、キーを書き換えます。

```
OPENROUTER_API_KEY=sk-or-xxxxxxxxxxxxxxxxxxxx
```

> `.env` は `.gitignore` で除外済みなので、git には含まれません（安全）。

---

## 4. 実行方法

```bash
python main.py
```

1. 議題を入力します。
2. 3体のAIが、それぞれ別のモデルで順番に発言します。
3. 各ラウンドの最後に、次の操作を選べます。
   - **Enter だけ** → 次のラウンドへ
   - **文章を入力して Enter** → そのコメントを議論に追加して次のラウンドへ
   - **`q` と入力** → 議論を打ち切って結論フェーズへ
4. 最大ラウント数に達すると、司会AIが「対立点・合意点・結論・次アクション」をまとめます。
5. 議論全体が `logs/discussion_YYYYMMDD_HHMMSS.md` に保存されます。

---

## 5. 設定の変え方

`main.py` の冒頭にある設定エリアを編集してください。

| 設定 | 内容 |
|---|---|
| `MAX_ROUNDS` | 何ラウンド議論させるか（暴走防止の上限） |
| `MAX_REPLY_CHARS` | 1発言の目安文字数 |
| `TEMPERATURE` | 発言のばらつき・創造性（0.0〜2.0） |
| `AGENTS` | 各エージェントの「役割」と「モデル」 |
| `MODERATOR` | 司会（まとめ役）の役割とモデル |

モデル名は OpenRouter の表記に合わせます（一覧: https://openrouter.ai/models ）。
**存在しないモデル名を指定しても、プログラムは止まらず、警告を出して次へ進みます。**

---

## 6. よくあるエラー

| 症状 | 対処 |
|---|---|
| `APIキーが設定されていません` | `.env` を作り、`OPENROUTER_API_KEY` にキーを設定する |
| `openai ライブラリが見つかりません` | `pip install -r requirements.txt` を実行する |
| 特定のAIだけ「応答に失敗しました」と出る | そのモデル名が正しいか、OpenRouterに残高があるかを確認する |

---

## 7. 今回は未実装（拡張の余地）

- Web UI（後で Flask 等で追加予定）
- Telegram 連携（Mac mini ハブから操作する用途）
- 会話の永続化・再開機能
- 発言のストリービグ表示
