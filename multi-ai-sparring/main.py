# -*- coding: utf-8 -*-
"""
マルチAI壁打ちツール (multi-ai-sparring)
=========================================

役割の異なる複数のAIエージェントに、1つの議題について順番に議論させ、
ユーザー（人間）が各ラウンドの区切りで議論に割り込める「壁打ち」ツールです。
最後に司会AIが議論全体をまとめ、Markdownファイルに保存します。

ポイント:
- すべてのAI呼び出し OpenRouter（OpenAI互換API）経由で行います。
  そのため openai ライブラリ1つで、複数社（OpenAI / Anthropic / Google など）の
  モデルをまとめて呼び出せます。
- 初心者でも読めるよう、関数ベースのシンプルな構成にしています。

使い方:
    python main.py
    （事前に .env に OPENROUTER_API_KEY を設定してください）
"""

# ---- 標準ライブラリ（Python に最初から付いてくる道具）----
import os                      # 環境変数やファイルパスを扱う
import sys                     # プログラムを途中で終了させる(sys.exit)
from datetime import datetime  # 現在日時（ログのファイル名・日時に使う）

# ---- 外部ライブラリ（pip でインストールが必要。未導入なら親切に案内して終了）----
try:
    # OpenRouter は OpenAI 互換 API なので、このSDKをそのまま使えます。
    from openai import OpenAI
except ImportError:
    print("【エラー】openai ライブラリが見つかりません。")
    print("次のコマンドでインストールしてください: pip install -r requirements.txt")
    sys.exit(1)

try:
    # .env ファイルから APIキー を読み込むためのライブラリ。
    from dotenv import load_dotenv
except ImportError:
    print("【エラー】python-dotenv ライブラリが見つかりません。")
    print("次のコマンドでインストールしてください: pip install -r requirements.txt")
    sys.exit(1)


# ============================================================
# === ここを編集すれば挙動を変えられます（設定エリア）       ===
# ============================================================

MAX_ROUNDS = 3          # 何ラウンド議論させるか（暴走防止のための上限）
MAX_REPLY_CHARS = 400   # 1発言の目安文字数（長くなりすぎないように指示する）

# 発言の「ばらつき・創造性」。0 に近いほど堅実、1 に近いほど多様（0.0〜2.0）。
TEMPERATURE = 0.7

# OpenRouter のエンドポイント（OpenAI互換）。基本このままで大丈夫です。
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# エージェント定義：役割（system プロンプト）と、割り当てるモデルをセットにします。
# モデル名は OpenRouter の表記に合わせます（一覧: https://openrouter.ai/models ）。
# ※ 存在しないモデル名でもプログラムは止まらず、警告を出して次へ進みます。
AGENTS = [
    {
        "name": "推進役",
        "model": "openai/gpt-4o-mini",
        "system": "あなたは推進役。議題に対し、実現に向けた具体案や前向きな可能性を積極的に提案する。",
    },
    {
        "name": "批判役",
        "model": "anthropic/claude-3.5-sonnet",
        "system": "あなたは批判役。前の発言のリスク・弱点・見落としを鋭く指摘する。ただし代替案も1つ添える。",
    },
    {
        "name": "整理役",
        "model": "google/gemini-flash-1.5",
        "system": "あなたは整理役。推進役と批判役の意見を踏まえ、論点を構造化し議論を一段深める。",
    },
]

# 司会（最後のまとめ役）
MODERATOR = {
    "name": "司会",
    "model": "anthropic/claude-3.5-sonnet",
    "system": (
        "あなたは司会。これまでの議論全体を踏まえ、"
        "(1)対立点 (2)合意点 (3)結論 (4)次にとるべき具体アクション "
        "を簡潔にまとめる。"
    ),
}

# 議論ログ（Markdownの終了保存先フォルム名
LOG_DIR = "logs"


# ============================================================
# === ここから下が処理の本体（関数の集まり）                 ===
# ============================================================

def load_api_key():
    """.env から OPENROUTER_API_KEY を読み込む。無ければ案内して終了する。"""
    load_dotenv()  # このファイルと同じフォルダにある .env を読み込む
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        # キーが未設定なら、初心者にも分かる手順を出して終了する。
        print("【エラー】APIキーが設定されていません。")
        print("1) .env.example をコピーして .env というファイルを作成してください。")
        print("2) .env の中の『OPENROUTER_API_KEY=』の後ろに、OpenRouterのキーを貼り付けてください。")
        print("   キーは https://openrouter.ai/keys で取得できます。")
        sys.exit(1)
    return api_key


def build_log_text(discussion_log):
    """これまでの議論ログを、AIに渡すための1つの文字列に整形する。

    discussion_log は dict のリスト。各要素は次のどちらか:
      - {"type": "agent", "round": 1, "name": "推進役", "model": "...", "text": "..."}
      - {"type": "human", "round": 1, "text": "..."}
    """
    if not discussion_log:
        # まだ誰も発言していない（=最初の発言者）の場合の案内文。
        return "（まだ発言はありません。あなたが最初の発言者です。）"

    lines = []
    for entry in discussion_log:
        if entry["type"] == "agent":
            lines.append(f"【{entry['name']}】{entry['text']}")
        elif entry["type"] == "human":
            # 人間（進行役）の割り込みコメント。
            lines.append(f"【人間の補足】{entry['text']}")
    return "\n".join(lines)


def call_agent(client, agent, topic, discussion_log):
    """1体のエージェントに発言させ、その本文（文字列）を返す。

    失敗しても例外を投げず、エラー文言を返すことで、全体の議論を止めない。
    （モデル名の誤り・通信エラーなどはここで受け止めます）
    """
    log_text = build_log_text(discussion_log)

    # AIに渡すメッセージを組み立てる。
    #   system = そのエージェントの役割 + 文字数の目安
    #   user   = 議題・これまでの議論・あなたの役割
    messages = [
        {
            "role": "system",
            "content": (
                f"{agent['system']}\n"
                f"発言は日本語で、目安 {MAX_REPLY_CHARS} 文字程度に簡潔にまとめること。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"# 議題\n{topic}\n\n"
                f"# これまでの議論\n{log_text}\n\n"
                f"# あなたの役割\n{agent['name']}として、上記を踏まえて発言してください。"
            ),
        },
    ]

    try:
        # OpenRouter（OpenAI互換）にチャット補完をリクエストする。
        response = client.chat.completions.create(
            model=agent["model"],
            messages=messages,
            temperature=TEMPERATURE,
        )
        # 応答本文を取り出す（念のため None の場合は空文字に変換）。
        text = response.choices[0].message.content or ""
        return text.strip()
    except Exception as error:
        # ここに来るのは「モデル名が違う」「ネットワークエラー」などのとき。
        # 警告だけ出して、議論全体は続行する。
        print(f"  ⚠️ {agent['name']}（{agent['model']}）の呼び出しに失敗しました: {error}")
        return "（このエージェントは応答に失敗しました）"


def ask_user_intervention(round_number):
    """ラウンド終了後に、ユーザー（人間）の操作を受け付ける。

    戻り値:
      "next" → 次のラウンドへ進む（Enter だけ押した場合）
      "quit" → 議論を打ち切って結論フェーズへ（q を入力した場合）
      上記以外 → 入力されたコメント文字列（議論に追加する）
    """
    print()
    print(f"--- ラウンド{round_number} 終了 ---")
    print("[Enter]=次へ進む / 文章を入力=コメントを追加して次へ / q=議論を終了して結論へ")
    try:
        user_input = input(">>> ").strip()
    except EOFError:
        # パイプ実行などで入力が尽きた場合は、安全に次へ進む。
        return "next"

    if user_input == "":
        return "next"
    if user_input.lower() == "q":
        return "quit"
    return user_input  # それ以外はコメントとして扱う


def summarize(client, topic, discussion_log):
    """司会AIに議論全体をまとめさせ、まとめ本文（文字列）を返す。"""
    log_text = build_log_text(discussion_log)
    messages = [
        {"role": "system", "content": MODERATOR["system"]},
        {
            "role": "user",
            "content": (
                f"# 議題\n{topic}\n\n"
                f"# 議論の全記録\n{log_text}\n\n"
                "上記の議論を踏まえ、(1)対立点 (2)合意点 (3)結論 (4)次にとるべき具体アクション "
                "の4項目に分けて、日本語で簡潔にまとめてください。"
            ),
        },
    ]
    try:
        response = client.chat.completions.create(
            model=MODERATOR["model"],
            messages=messages,
            temperature=TEMPERATURE,
        )
        text = response.choices[0].message.content or ""
        return text.strip()
    except Exception as error:
        print(f"  ⚠️ 司会（{MODERATOR['model']}）の呼び出しに失敗しました: {error}")
        return "（司会のまとめ生成に失敗しました）"


def save_log(topic, discussion_log, summary):
    """議題・日時・全発言・まとめを Markdown ファイルに保存し、保存先パスを返す。"""
    os.makedirs(LOG_DIR, exist_ok=True)  # logs フォルダが無ければ作成する
    now = datetime.now()
    filename = f"discussion_{now:%Y%m%d_%H%M%S}.md"
    filepath = os.path.join(LOG_DIR, filename)

    lines = []
    lines.append("# AI壁打ちログ\n")
    lines.append(f"- 日時: {now:%Y-%m-%d %H:%M}")
    lines.append(f"- 議題: {topic}")

    # 発言ログを「ラウンドごと」にまとめて書き出す。
    current_round = None
    for entry in discussion_log:
        if entry["type"] == "agent":
            # 新しいラウンドに入ったら見出しを追加する。
            if entry["round"] != current_round:
                current_round = entry["round"]
                lines.append(f"\n## ラウンド{current_round}")
            lines.append(f"### {entry['name']}（{entry['model']}）")
            lines.append(entry["text"])
        elif entry["type"] == "human":
            # 人間の補足は、そのラウンドの発言の後ろに引用形式で入れる。
            lines.append(f"> 人間の補足: {entry['text']}")

    # 最後に司会のまとめを追加する。
    lines.append("\n## 結論（司会）")
    lines.append(summary)

    # ファイルへ書き込む（文字コードは UTF-8）。
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    return filepath


def main():
    """プログラム全体の流れを管理する関数。"""
    print("=" * 50)
    print(" マルチAI壁打ちツール")
    print("=" * 50)

    # 1) APIキーを読み込む（無ければここで終了）。
    api_key = load_api_key()

    # 2) OpenRouter 用のクライアントを作る。
    #    base_url を OpenRouter に向けるのがポイント。
    client = OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)

    # 3) 議題を受け取る。
    try:
        topic = input("\n議題を入力してください: ").strip()
    except EOFError:
        topic = ""
    if not topic:
        print("議題が空のため終了します。")
        sys.exit(0)

    # 4) 議論ログ（発言の履歴）を入れておくリスト。
    discussion_log = []

    print(f"\n議題:「{topic}」")
    print(f"{len(AGENTS)}体のAIが、最大 {MAX_ROUNDS} ラウンド議論します。\n")

    # 5) ラウンドを MAX_ROUNDS 回まで繰り返す。
    for round_number in range(1, MAX_ROUNDS + 1):
        print(f"\n========== ラウンド {round_number} / {MAX_ROUNDS} ==========")

        # 各エージェントを、上から順に1回ずつ発言させる。
        for agent in AGENTS:
            # 先に「誰が発言中か」を表示（リアルタイム感を出す）。
            print(f"\n【{agent['name']}（{agent['model']}）】", flush=True)
            text = call_agent(client, agent, topic, discussion_log)
            print(text)
            # 発言をログに追加する。
            discussion_log.append({
                "type": "agent",
                "round": round_number,
                "name": agent["name"],
                "model": agent["model"],
                "text": text,
            })

        # ラウンド終了後、ユーザーの介入を受け付ける。
        action = ask_user_intervention(round_number)
        if action == "quit":
            print("\n議論を打ち切り、結論フェーズに移ります。")
            break
        elif action == "next":
            continue
        else:
            # コメントが入力された → 「人間の補足」としてログに追加。
            # これは次のラウンドのAIたちの発言に反映される。
            discussion_log.append({
                "type": "human",
                "round": round_number,
                "text": action,
            })
            print("（あなたのコメントを議論に追加しました）")

    # 6) 司会が議論全体をまとめる。
    print("\n========== 結論（司会） ==========")
    print(f"【{MODERATOR['name']}（{MODERATOR['model']}）】", flush=True)
    summary = summarize(client, topic, discussion_log)
    print(summary)

    # 7) Markdown ログを保存する。
    filepath = save_log(topic, discussion_log, summary)
    print(f"\n✅ 議論ログを保存しました: {filepath}")


# ------------------------------------------------------------
# 拡張の余地（今回は未実装。コメントとして残しておく）:
#   - Web UI（後で Flask 等で追加予定）
#   - Telegram 連携（Mac mini ハブから操作する用途）
#   - 会話の永続化・再開機能
#   - 発言のストリーミング表示（文字が少しずつ出るようにする）
# ------------------------------------------------------------

if __name__ == "__main__":
    # Ctrl+C で止めても、見苦しいエラーを出さずに終了する。
    try:
        main()
    except KeyboardInterrupt:
        print("\n中断しました。")
        sys.exit(0)
