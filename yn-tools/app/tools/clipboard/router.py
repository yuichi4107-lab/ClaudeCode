"""ク���ップボード共有 - PC⇔���マホ間リアルタイム同期"""

import secrets
import time
from typing import Dict, Set

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates

from app.auth.dependencies import get_current_user, require_tool_access
from app.database import get_db
from app.users.models import User

router = APIRouter(prefix="/tools/clipboard", tags=["clipboard"])
templates = make_templates("app/templates")

# --- In-memory room store (ephemeral, no DB needed) ---

class Room:
    __slots__ = ("code", "created_at", "clips", "connections")

    def __init__(self, code: str):
        self.code = code
        self.created_at = time.time()
        self.clips: list[dict] = []          # [{text, created_at}, ...]
        self.connections: Set[WebSocket] = set()

# code -> Room
_rooms: Dict[str, Room] = {}

# Auto-expire rooms older than 24 hours
ROOM_TTL = 86400


def _generate_code() -> str:
    """4桁のルームコードを生成"""
    while True:
        code = f"{secrets.randbelow(10000):04d}"
        if code not in _rooms:
            return code


def _cleanup_expired():
    """期限切れルームを削除"""
    now = time.time()
    expired = [c for c, r in _rooms.items() if now - r.created_at > ROOM_TTL]
    for c in expired:
        del _rooms[c]


# --- HTTP Routes ---

@router.get("/", response_class=HTMLResponse)
async def clipboard_index(
    request: Request,
    user: User | None = Depends(get_current_user),
):
    """ページ表示はログイン不要（スマホからQRコードでアクセスするため）"""
    return templates.TemplateResponse(
        request, "tools/clipboard/index.html",
        {"user": user, "page": "clipboard"},
    )


@router.post("/api/create-room")
async def create_room(
    user: User = Depends(require_tool_access("clipboard")),
):
    """新しいルームを作成（ログイン必���）"""
    _cleanup_expired()
    code = _generate_code()
    _rooms[code] = Room(code)
    return {"code": code}


@router.post("/api/join-room")
async def join_room(request: Request):
    """ルームコードで参加確認（ログイン不要）"""
    body = await request.json()
    code = body.get("code", "").strip()
    if code not in _rooms:
        return {"ok": False, "error": "このコードのル���ムは見つかりません"}
    room = _rooms[code]
    return {"ok": True, "clips": room.clips}


# --- WebSocket for real-time sync (auth not required) ---

@router.websocket("/ws/{room_code}")
async def clipboard_ws(websocket: WebSocket, room_code: str):
    """WebSocket: ��ーム内のクリップボードをリアルタイム同期"""
    if room_code not in _rooms:
        await websocket.close(code=4004)
        return

    room = _rooms[room_code]
    await websocket.accept()
    room.connections.add(websocket)

    try:
        # Send existing clips on connect
        await websocket.send_json({"type": "init", "clips": room.clips})

        while True:
            data = await websocket.receive_json()

            if data.get("type") == "clip":
                text = data.get("text", "").strip()
                if not text:
                    continue
                clip = {"text": text, "created_at": time.time()}
                room.clips.append(clip)
                # Keep only last 50 clips
                if len(room.clips) > 50:
                    room.clips = room.clips[-50:]
                # Broadcast to all connections
                for ws in list(room.connections):
                    try:
                        await ws.send_json({"type": "new_clip", "clip": clip})
                    except Exception:
                        room.connections.discard(ws)

            elif data.get("type") == "clear":
                room.clips.clear()
                for ws in list(room.connections):
                    try:
                        await ws.send_json({"type": "cleared"})
                    except Exception:
                        room.connections.discard(ws)

    except WebSocketDisconnect:
        pass
    finally:
        room.connections.discard(websocket)
        # If no connections left, keep room alive for reconnection
