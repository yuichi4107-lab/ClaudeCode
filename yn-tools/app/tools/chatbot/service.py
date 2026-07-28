"""AIチャットボットビルダー - LLM応答生成"""

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from .models import Chatbot, ChatMessage

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def get_bot_response(
    bot: Chatbot,
    user_message: str,
    session_id: str,
    db: AsyncSession,
) -> str:
    """ボットの応答を生成"""

    # システムプロンプト構築
    system_parts = [bot.system_prompt]
    if bot.knowledge.strip():
        system_parts.append(
            f"\n\n【ナレッジベース】\n"
            f"以下の情報を参考にして回答してください。ナレッジに記載のない情報は推測せず、"
            f"「その情報は持ち合わせておりません」と答えてください。\n\n{bot.knowledge}"
        )

    system_prompt = "\n".join(system_parts)

    # 直近の会話履歴を取得（最大20件）
    result = await db.execute(
        select(ChatMessage)
        .where(
            ChatMessage.bot_id == bot.bot_id,
            ChatMessage.session_id == session_id,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(20)
    )
    past_messages = list(reversed(result.scalars().all()))

    # メッセージ構築
    messages = [{"role": "system", "content": system_prompt}]
    for msg in past_messages:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_message})

    # LLM呼び出し
    client = _get_client()
    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=messages,
        temperature=0.5,
        max_tokens=1024,
    )
    assistant_reply = resp.choices[0].message.content or ""

    # メッセージ保存
    db.add(ChatMessage(bot_id=bot.bot_id, session_id=session_id, role="user", content=user_message))
    db.add(ChatMessage(bot_id=bot.bot_id, session_id=session_id, role="assistant", content=assistant_reply))

    # カウンタ更新
    bot.total_messages += 1
    await db.commit()

    return assistant_reply


# ---------- ウィジェット埋め込みコード生成 ----------

def generate_embed_code(bot_id: str, base_url: str) -> str:
    """Webサイト埋め込み用HTMLコードを生成"""
    return f"""<!-- YN Tools AIチャットボット -->
<script>
(function(){{
  var d=document,s=d.createElement('script');
  s.src='{base_url}/tools/chatbot/widget/{bot_id}/loader.js';
  s.async=true;
  d.head.appendChild(s);
}})();
</script>"""
