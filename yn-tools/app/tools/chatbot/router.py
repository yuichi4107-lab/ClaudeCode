"""AIチャットボットビルダー - ルーター"""

import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from app.core.templates import make_templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access, get_current_user
from app.database import get_db
from app.users.models import User

from .models import Chatbot, ChatMessage
from . import service
from app.tools.usage_limit import get_monthly_usage, get_limit, limit_error

router = APIRouter(prefix="/tools/chatbot", tags=["chatbot"])
templates = make_templates("app/templates")


# ---------- ダッシュボード ----------

@router.get("/", response_class=HTMLResponse)
async def chatbot_index(
    request: Request,
    user: User = Depends(require_tool_access("chatbot")),
    db: AsyncSession = Depends(get_db),
):
    """チャットボット一覧"""
    result = await db.execute(
        select(Chatbot)
        .where(Chatbot.user_id == user.id)
        .order_by(Chatbot.created_at.desc())
    )
    bots = result.scalars().all()
    monthly_used = await get_monthly_usage(db, user.id, "chatbot")

    return templates.TemplateResponse(
        request, "tools/chatbot/index.html", {
            "user": user,
            "page": "chatbot",
            "bots": bots,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("chatbot"),
        }
    )


# ---------- ボット作成 ----------

@router.get("/new", response_class=HTMLResponse)
async def chatbot_new(
    request: Request,
    user: User = Depends(require_tool_access("chatbot")),
):
    return templates.TemplateResponse(
        request, "tools/chatbot/edit.html", {
            "user": user,
            "page": "chatbot",
            "bot": None,
            "mode": "new",
        }
    )


@router.post("/new")
async def chatbot_create(
    request: Request,
    user: User = Depends(require_tool_access("chatbot")),
    db: AsyncSession = Depends(get_db),
    name: str = Form(default=""),
    description: str = Form(default=""),
    system_prompt: str = Form(default=""),
    knowledge: str = Form(default=""),
    welcome_message: str = Form(default="こんにちは！何かお手伝いできることはありますか？"),
    theme_color: str = Form(default="#4F46E5"),
):
    if not name.strip() or not system_prompt.strip():
        return {"error": "ボット名とシステムプロンプトは必須です。"}

    bot = Chatbot(
        user_id=user.id,
        name=name.strip(),
        description=description.strip(),
        system_prompt=system_prompt.strip(),
        knowledge=knowledge.strip(),
        welcome_message=welcome_message.strip(),
        theme_color=theme_color.strip(),
    )
    db.add(bot)
    await db.commit()
    await db.refresh(bot)

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/tools/chatbot/{bot.bot_id}", status_code=303)


# ---------- ボット詳細・編集 ----------

@router.get("/{bot_id}", response_class=HTMLResponse)
async def chatbot_detail(
    bot_id: str,
    request: Request,
    user: User = Depends(require_tool_access("chatbot")),
    db: AsyncSession = Depends(get_db),
):
    bot = await _get_user_bot(db, user.id, bot_id)
    if not bot:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/tools/chatbot/", status_code=303)

    # 統計（bot所有者のボットのみ集計）
    msg_count = await db.execute(
        select(func.count(ChatMessage.id))
        .join(Chatbot, ChatMessage.bot_id == Chatbot.bot_id)
        .where(ChatMessage.bot_id == bot_id, Chatbot.user_id == user.id)
    )
    session_count = await db.execute(
        select(func.count(func.distinct(ChatMessage.session_id)))
        .join(Chatbot, ChatMessage.bot_id == Chatbot.bot_id)
        .where(ChatMessage.bot_id == bot_id, Chatbot.user_id == user.id)
    )

    base_url = str(request.base_url).rstrip("/")
    embed_code = service.generate_embed_code(bot_id, base_url)

    return templates.TemplateResponse(
        request, "tools/chatbot/detail.html", {
            "user": user,
            "page": "chatbot",
            "bot": bot,
            "msg_count": msg_count.scalar() or 0,
            "session_count": session_count.scalar() or 0,
            "embed_code": embed_code,
            "base_url": base_url,
        }
    )


@router.get("/{bot_id}/edit", response_class=HTMLResponse)
async def chatbot_edit(
    bot_id: str,
    request: Request,
    user: User = Depends(require_tool_access("chatbot")),
    db: AsyncSession = Depends(get_db),
):
    bot = await _get_user_bot(db, user.id, bot_id)
    if not bot:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/tools/chatbot/", status_code=303)

    return templates.TemplateResponse(
        request, "tools/chatbot/edit.html", {
            "user": user,
            "page": "chatbot",
            "bot": bot,
            "mode": "edit",
        }
    )


@router.post("/{bot_id}/edit")
async def chatbot_update(
    bot_id: str,
    request: Request,
    user: User = Depends(require_tool_access("chatbot")),
    db: AsyncSession = Depends(get_db),
    name: str = Form(default=""),
    description: str = Form(default=""),
    system_prompt: str = Form(default=""),
    knowledge: str = Form(default=""),
    welcome_message: str = Form(default=""),
    theme_color: str = Form(default="#4F46E5"),
    is_active: bool = Form(default=True),
):
    bot = await _get_user_bot(db, user.id, bot_id)
    if not bot:
        return {"error": "ボットが見つかりません。"}

    bot.name = name.strip() or bot.name
    bot.description = description.strip()
    bot.system_prompt = system_prompt.strip() or bot.system_prompt
    bot.knowledge = knowledge.strip()
    bot.welcome_message = welcome_message.strip() or bot.welcome_message
    bot.theme_color = theme_color.strip()
    bot.is_active = is_active
    await db.commit()

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/tools/chatbot/{bot_id}", status_code=303)


@router.post("/{bot_id}/delete")
async def chatbot_delete(
    bot_id: str,
    user: User = Depends(require_tool_access("chatbot")),
    db: AsyncSession = Depends(get_db),
):
    bot = await _get_user_bot(db, user.id, bot_id)
    if not bot:
        return {"error": "ボットが見つかりません。"}
    await db.delete(bot)
    await db.commit()

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/tools/chatbot/", status_code=303)


# ---------- チャットAPI（公開・認証不要） ----------

@router.post("/api/chat/{bot_id}")
async def api_chat(
    bot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    message: str = Form(default=""),
    session_id: str = Form(default=""),
):
    """公開チャットAPI（ウィジェットから呼び出される）"""
    from app.tools.rate_limit import check_rate_limit, get_client_ip
    if err := check_rate_limit(get_client_ip(request), max_requests=10, window_sec=60):
        return {"error": err}

    result = await db.execute(
        select(Chatbot).where(Chatbot.bot_id == bot_id, Chatbot.is_active == True)
    )
    bot = result.scalar_one_or_none()
    if not bot:
        return {"error": "ボットが見つかりません。"}

    if not message.strip():
        return {"error": "メッセージを入力してください。"}

    # ボットオーナーの月次メッセージ上限チェック
    used = await get_monthly_usage(db, bot.user_id, "chatbot")
    if err := limit_error("chatbot", used, get_limit("chatbot")):
        return {"error": err}

    if not session_id:
        session_id = uuid.uuid4().hex[:16]

    reply = await service.get_bot_response(bot, message.strip(), session_id, db)

    return {"reply": reply, "session_id": session_id}


# ---------- ウィジェットJS（公開） ----------

@router.get("/widget/{bot_id}/loader.js")
async def widget_loader(
    bot_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """埋め込みウィジェットのJavaScript"""
    result = await db.execute(
        select(Chatbot).where(Chatbot.bot_id == bot_id, Chatbot.is_active == True)
    )
    bot = result.scalar_one_or_none()
    if not bot:
        return PlainTextResponse("// Bot not found", media_type="application/javascript")

    base_url = str(request.base_url).rstrip("/")
    color = bot.theme_color or "#4F46E5"
    import json as _json
    welcome = _json.dumps(bot.welcome_message or "", ensure_ascii=False)
    bot_name = _json.dumps(bot.name or "", ensure_ascii=False)

    js = f"""(function(){{
  if(document.getElementById('yn-chatbot-widget'))return;

  var sessionId='';
  var isOpen=false;

  // Styles
  var style=document.createElement('style');
  style.textContent=`
    #yn-chatbot-btn{{position:fixed;bottom:20px;right:20px;width:56px;height:56px;border-radius:50%;background:{color};color:#fff;border:none;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.2);z-index:9999;display:flex;align-items:center;justify-content:center;font-size:24px;transition:transform .2s}}
    #yn-chatbot-btn:hover{{transform:scale(1.1)}}
    #yn-chatbot-panel{{position:fixed;bottom:86px;right:20px;width:380px;max-width:calc(100vw - 40px);height:500px;max-height:calc(100vh - 120px);background:#fff;border-radius:16px;box-shadow:0 8px 30px rgba(0,0,0,.15);z-index:9999;display:none;flex-direction:column;overflow:hidden}}
    #yn-chatbot-panel.open{{display:flex}}
    .yn-header{{background:{color};color:#fff;padding:14px 16px;font-weight:600;font-size:14px;display:flex;justify-content:space-between;align-items:center}}
    .yn-close{{background:none;border:none;color:#fff;cursor:pointer;font-size:18px;opacity:.8}}
    .yn-close:hover{{opacity:1}}
    .yn-messages{{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px}}
    .yn-msg{{max-width:80%;padding:10px 14px;border-radius:12px;font-size:13px;line-height:1.5;word-wrap:break-word}}
    .yn-msg.user{{align-self:flex-end;background:{color};color:#fff;border-bottom-right-radius:4px}}
    .yn-msg.bot{{align-self:flex-start;background:#f3f4f6;color:#1f2937;border-bottom-left-radius:4px}}
    .yn-input-area{{border-top:1px solid #e5e7eb;padding:10px;display:flex;gap:8px}}
    .yn-input-area input{{flex:1;border:1px solid #d1d5db;border-radius:8px;padding:8px 12px;font-size:13px;outline:none}}
    .yn-input-area input:focus{{border-color:{color}}}
    .yn-input-area button{{background:{color};color:#fff;border:none;border-radius:8px;padding:8px 16px;cursor:pointer;font-size:13px;font-weight:500}}
    .yn-input-area button:disabled{{opacity:.5;cursor:not-allowed}}
    .yn-typing{{align-self:flex-start;padding:10px 14px;border-radius:12px;background:#f3f4f6;font-size:13px;color:#9ca3af}}
  `;
  document.head.appendChild(style);

  // Button
  var btn=document.createElement('button');
  btn.id='yn-chatbot-btn';
  btn.innerHTML='&#x1f4ac;';
  btn.onclick=function(){{
    isOpen=!isOpen;
    panel.classList.toggle('open',isOpen);
    if(isOpen&&msgs.children.length===0)addMsg('bot',{welcome});
  }};
  document.body.appendChild(btn);

  // Panel
  var panel=document.createElement('div');
  panel.id='yn-chatbot-panel';
  panel.innerHTML=`
    <div class="yn-header"><span id="yn-bot-name"></span><button class="yn-close" onclick="document.getElementById('yn-chatbot-panel').classList.remove('open')">&times;</button></div>
    <div class="yn-messages" id="yn-msgs"></div>
    <div class="yn-input-area"><input id="yn-input" placeholder="メッセージを入力..." onkeypress="if(event.key==='Enter')document.getElementById('yn-send').click()"><button id="yn-send">送信</button></div>
  `;
  document.body.appendChild(panel);
  document.getElementById('yn-bot-name').textContent={bot_name};

  var msgs=document.getElementById('yn-msgs');
  var input=document.getElementById('yn-input');
  var sendBtn=document.getElementById('yn-send');

  function addMsg(role,text){{
    var d=document.createElement('div');
    d.className='yn-msg '+role;
    d.textContent=text;
    msgs.appendChild(d);
    msgs.scrollTop=msgs.scrollHeight;
  }}

  sendBtn.onclick=async function(){{
    var text=input.value.trim();
    if(!text)return;
    addMsg('user',text);
    input.value='';
    sendBtn.disabled=true;

    var typing=document.createElement('div');
    typing.className='yn-typing';
    typing.textContent='入力中...';
    msgs.appendChild(typing);
    msgs.scrollTop=msgs.scrollHeight;

    try{{
      var fd=new FormData();
      fd.append('message',text);
      fd.append('session_id',sessionId);
      var r=await fetch('{base_url}/tools/chatbot/api/chat/{bot_id}',{{method:'POST',body:fd}});
      var data=await r.json();
      typing.remove();
      if(data.error){{addMsg('bot','エラー: '+data.error);}}
      else{{sessionId=data.session_id;addMsg('bot',data.reply);}}
    }}catch(e){{typing.remove();addMsg('bot','通信エラーが発生しました。');}}
    sendBtn.disabled=false;
    input.focus();
  }};
}})();"""

    return PlainTextResponse(js, media_type="application/javascript")


# ---------- テスト画面 ----------

@router.get("/{bot_id}/test", response_class=HTMLResponse)
async def chatbot_test(
    bot_id: str,
    request: Request,
    user: User = Depends(require_tool_access("chatbot")),
    db: AsyncSession = Depends(get_db),
):
    bot = await _get_user_bot(db, user.id, bot_id)
    if not bot:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/tools/chatbot/", status_code=303)

    base_url = str(request.base_url).rstrip("/")

    return templates.TemplateResponse(
        request, "tools/chatbot/test.html", {
            "user": user,
            "page": "chatbot",
            "bot": bot,
            "base_url": base_url,
        }
    )


# ---------- ヘルパー ----------

async def _get_user_bot(db: AsyncSession, user_id: int, bot_id: str) -> Chatbot | None:
    result = await db.execute(
        select(Chatbot).where(Chatbot.bot_id == bot_id, Chatbot.user_id == user_id)
    )
    return result.scalar_one_or_none()
