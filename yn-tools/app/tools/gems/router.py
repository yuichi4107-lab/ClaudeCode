"""GEMS/GPT Library routes."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from app.core.templates import make_templates
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access
from app.database import get_db
from app.tools.gems.models import GemsFavorite, GemsItem
from app.tools.gems.service import get_categories, get_user_favorite_ids, search_items
from app.users.models import User

router = APIRouter(prefix="/tools/gems", tags=["gems"])
templates = make_templates("app/templates")


# ---------------------------------------------------------------------------
# Library list
# ---------------------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    user: User = Depends(require_tool_access("gems")),
    db: AsyncSession = Depends(get_db),
    type: str | None = Query(None),
    category: str | None = Query(None),
    q: str | None = Query(None),
):
    items = await search_items(db, item_type=type, category=category, q=q)
    categories = await get_categories(db)
    fav_ids = await get_user_favorite_ids(db, user.id)
    return templates.TemplateResponse(request, "tools/gems/index.html", {
        "user": user,
        "items": items,
        "categories": categories,
        "fav_ids": fav_ids,
        "current_type": type or "",
        "current_category": category or "",
        "current_q": q or "",
        "page": "gems",
    })


# ---------------------------------------------------------------------------
# Item detail
# ---------------------------------------------------------------------------
@router.get("/{item_id}", response_class=HTMLResponse)
async def detail(
    request: Request,
    item_id: int,
    user: User = Depends(require_tool_access("gems")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(GemsItem).where(GemsItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        return HTMLResponse("<h1>Not Found</h1>", status_code=404)
    fav_ids = await get_user_favorite_ids(db, user.id)
    return templates.TemplateResponse(request, "tools/gems/detail.html", {
        "user": user,
        "item": item,
        "is_fav": item.id in fav_ids,
        "page": "gems",
    })


# ---------------------------------------------------------------------------
# Download prompt
# ---------------------------------------------------------------------------
@router.get("/{item_id}/download")
async def download(
    item_id: int,
    user: User = Depends(require_tool_access("gems")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(GemsItem).where(GemsItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        return JSONResponse({"error": "not found"}, status_code=404)

    # Increment download count
    await db.execute(
        update(GemsItem).where(GemsItem.id == item_id).values(
            download_count=GemsItem.download_count + 1
        )
    )
    await db.commit()

    content = f"# {item.name}\n\n{item.prompt_content}"
    filename = f"{item.slug}.txt"
    return PlainTextResponse(
        content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Favorites
# ---------------------------------------------------------------------------
@router.post("/{item_id}/favorite")
async def toggle_favorite(
    item_id: int,
    user: User = Depends(require_tool_access("gems")),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(GemsFavorite).where(
            GemsFavorite.user_id == user.id,
            GemsFavorite.item_id == item_id,
        )
    )
    fav = existing.scalar_one_or_none()
    if fav:
        await db.delete(fav)
        await db.commit()
        return JSONResponse({"status": "removed"})
    else:
        db.add(GemsFavorite(user_id=user.id, item_id=item_id))
        await db.commit()
        return JSONResponse({"status": "added"})


@router.get("/favorites/list", response_class=HTMLResponse)
async def favorites_list(
    request: Request,
    user: User = Depends(require_tool_access("gems")),
    db: AsyncSession = Depends(get_db),
):
    fav_ids_result = await db.execute(
        select(GemsFavorite.item_id).where(GemsFavorite.user_id == user.id)
    )
    fav_item_ids = fav_ids_result.scalars().all()
    items = []
    if fav_item_ids:
        result = await db.execute(
            select(GemsItem).where(GemsItem.id.in_(fav_item_ids)).order_by(GemsItem.slug)
        )
        items = list(result.scalars().all())
    categories = await get_categories(db)
    return templates.TemplateResponse(request, "tools/gems/index.html", {
        "user": user,
        "items": items,
        "categories": categories,
        "fav_ids": set(fav_item_ids),
        "current_type": "",
        "current_level": "",
        "current_category": "",
        "current_q": "",
        "favorites_only": True,
        "page": "gems",
    })
