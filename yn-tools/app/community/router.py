"""Community routes - reviews, feedback, app requests."""

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.templates import make_templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_admin, require_login
from app.database import get_db
from app.community.models import AppRequest, AppRequestVote, Feedback, Review
from app.users.models import User

router = APIRouter(prefix="/community", tags=["community"])
templates = make_templates("app/templates")

TOOLS = [
    {"slug": "sales",       "name": "営業自動化"},
    {"slug": "mailer",      "name": "メール送信"},
    {"slug": "gems",        "name": "GEMS/GPTライブラリ"},
    {"slug": "docai",       "name": "文書処理"},
    {"slug": "contentgen",  "name": "コンテンツ作成"},
    {"slug": "webresearch", "name": "Webリサーチャー"},
    {"slug": "imagegen",    "name": "画像生成"},
    {"slug": "chatbot",     "name": "チャットボット"},
    {"slug": "qrcode",      "name": "QRコード"},
    {"slug": "fileconv",    "name": "ファイル変換"},
    {"slug": "taskmanager", "name": "タスク管理"},
    {"slug": "formbuilder", "name": "フォームビルダー"},
]

FEEDBACK_CATEGORIES = [
    {"value": "bug", "label": "バグ報告"},
    {"value": "improvement", "label": "改善要望"},
    {"value": "other", "label": "その他"},
]

REQUEST_STATUSES = {
    "open": "募集中",
    "planned": "計画中",
    "building": "開発中",
    "released": "リリース済",
    "declined": "見送り",
}


# ===========================================================================
# Reviews
# ===========================================================================
@router.get("/reviews", response_class=HTMLResponse)
async def reviews_list(
    request: Request,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    tool: str = Query(""),
):
    query = select(Review).order_by(Review.created_at.desc())
    if tool:
        query = query.where(Review.tool_slug == tool)
    reviews = (await db.execute(query)).scalars().all()

    # Collect user names
    user_ids = list({r.user_id for r in reviews})
    user_map = {}
    if user_ids:
        users = (await db.execute(
            select(User).where(User.id.in_(user_ids))
        )).scalars().all()
        user_map = {u.id: u for u in users}

    # Per-tool averages
    tool_stats = {}
    for t in TOOLS:
        avg = (await db.execute(
            select(func.avg(Review.rating)).where(Review.tool_slug == t["slug"])
        )).scalar()
        cnt = (await db.execute(
            select(func.count(Review.id)).where(Review.tool_slug == t["slug"])
        )).scalar() or 0
        tool_stats[t["slug"]] = {"avg": round(avg, 1) if avg else 0, "count": cnt}

    # Current user's existing reviews
    my_reviews = {}
    if user:
        my = (await db.execute(
            select(Review).where(Review.user_id == user.id)
        )).scalars().all()
        my_reviews = {r.tool_slug: r for r in my}

    return templates.TemplateResponse(request, "community/reviews.html", {
        "user": user, "page": "community",
        "reviews": reviews, "user_map": user_map,
        "tools": TOOLS, "tool_stats": tool_stats,
        "current_tool": tool, "my_reviews": my_reviews,
    })


@router.post("/reviews")
async def review_submit(
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
    tool_slug: str = Form(...),
    rating: int = Form(...),
    comment: str = Form(""),
):
    rating = max(1, min(5, rating))
    existing = (await db.execute(
        select(Review).where(Review.user_id == user.id, Review.tool_slug == tool_slug)
    )).scalar_one_or_none()

    if existing:
        existing.rating = rating
        existing.comment = comment
    else:
        db.add(Review(user_id=user.id, tool_slug=tool_slug, rating=rating, comment=comment))
    await db.commit()
    return RedirectResponse(url="/community/reviews", status_code=303)


# ===========================================================================
# Feedback
# ===========================================================================
@router.get("/feedback", response_class=HTMLResponse)
async def feedback_list(
    request: Request,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    status: str = Query(""),
    category: str = Query(""),
):
    query = select(Feedback).order_by(Feedback.created_at.desc())
    if status:
        query = query.where(Feedback.status == status)
    if category:
        query = query.where(Feedback.category == category)
    feedbacks = (await db.execute(query)).scalars().all()

    user_ids = list({f.user_id for f in feedbacks})
    user_map = {}
    if user_ids:
        users = (await db.execute(
            select(User).where(User.id.in_(user_ids))
        )).scalars().all()
        user_map = {u.id: u for u in users}

    status_counts = {}
    for s in ["open", "in-progress", "resolved", "closed"]:
        cnt = (await db.execute(
            select(func.count(Feedback.id)).where(Feedback.status == s)
        )).scalar() or 0
        status_counts[s] = cnt

    return templates.TemplateResponse(request, "community/feedback.html", {
        "user": user, "page": "community",
        "feedbacks": feedbacks, "user_map": user_map,
        "tools": TOOLS, "categories": FEEDBACK_CATEGORIES,
        "status_counts": status_counts,
        "current_status": status, "current_category": category,
    })


@router.post("/feedback")
async def feedback_submit(
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
    tool_slug: str = Form("general"),
    category: str = Form("other"),
    title: str = Form(...),
    body: str = Form(...),
):
    db.add(Feedback(
        user_id=user.id, tool_slug=tool_slug,
        category=category, title=title, body=body,
    ))
    await db.commit()
    return RedirectResponse(url="/community/feedback", status_code=303)


@router.get("/feedback/{feedback_id}", response_class=HTMLResponse)
async def feedback_detail(
    request: Request, feedback_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    fb = (await db.execute(
        select(Feedback).where(Feedback.id == feedback_id)
    )).scalar_one_or_none()
    if not fb:
        return HTMLResponse("Not Found", status_code=404)

    author = (await db.execute(
        select(User).where(User.id == fb.user_id)
    )).scalar_one_or_none()

    tool_name = next((t["name"] for t in TOOLS if t["slug"] == fb.tool_slug), "全般")
    cat_label = next((c["label"] for c in FEEDBACK_CATEGORIES if c["value"] == fb.category), fb.category)

    return templates.TemplateResponse(request, "community/feedback_detail.html", {
        "user": user, "page": "community",
        "fb": fb, "author": author,
        "tool_name": tool_name, "cat_label": cat_label,
    })


@router.post("/feedback/{feedback_id}/reply")
async def feedback_admin_reply(
    feedback_id: int,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    admin_reply: str = Form(""),
    new_status: str = Form(""),
):
    fb = (await db.execute(
        select(Feedback).where(Feedback.id == feedback_id)
    )).scalar_one_or_none()
    if fb:
        if admin_reply:
            fb.admin_reply = admin_reply
        if new_status:
            fb.status = new_status
        await db.commit()
    return RedirectResponse(url=f"/community/feedback/{feedback_id}", status_code=303)


# ===========================================================================
# App Requests
# ===========================================================================
@router.get("/requests", response_class=HTMLResponse)
async def requests_list(
    request: Request,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    sort: str = Query("votes"),
    status: str = Query(""),
):
    query = select(AppRequest)
    if status:
        query = query.where(AppRequest.status == status)

    if sort == "new":
        query = query.order_by(AppRequest.created_at.desc())
    else:
        query = query.order_by(AppRequest.vote_count.desc(), AppRequest.created_at.desc())

    app_requests = (await db.execute(query)).scalars().all()

    user_ids = list({r.user_id for r in app_requests})
    user_map = {}
    if user_ids:
        users = (await db.execute(
            select(User).where(User.id.in_(user_ids))
        )).scalars().all()
        user_map = {u.id: u for u in users}

    # Current user's votes
    my_votes: set[int] = set()
    if user:
        votes = (await db.execute(
            select(AppRequestVote.request_id).where(AppRequestVote.user_id == user.id)
        )).scalars().all()
        my_votes = set(votes)

    status_counts = {}
    for s in REQUEST_STATUSES:
        cnt = (await db.execute(
            select(func.count(AppRequest.id)).where(AppRequest.status == s)
        )).scalar() or 0
        status_counts[s] = cnt

    return templates.TemplateResponse(request, "community/requests.html", {
        "user": user, "page": "community",
        "app_requests": app_requests, "user_map": user_map,
        "my_votes": my_votes, "request_statuses": REQUEST_STATUSES,
        "status_counts": status_counts,
        "current_sort": sort, "current_status": status,
    })


@router.post("/requests")
async def request_submit(
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
    title: str = Form(...),
    description: str = Form(...),
):
    ar = AppRequest(user_id=user.id, title=title, description=description, vote_count=1)
    db.add(ar)
    await db.flush()
    db.add(AppRequestVote(request_id=ar.id, user_id=user.id))
    await db.commit()
    return RedirectResponse(url="/community/requests", status_code=303)


@router.post("/requests/{request_id}/vote")
async def request_vote(
    request_id: int,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    ar = (await db.execute(
        select(AppRequest).where(AppRequest.id == request_id)
    )).scalar_one_or_none()
    if not ar:
        return RedirectResponse(url="/community/requests", status_code=303)

    existing = (await db.execute(
        select(AppRequestVote).where(
            AppRequestVote.request_id == request_id,
            AppRequestVote.user_id == user.id,
        )
    )).scalar_one_or_none()

    if existing:
        await db.delete(existing)
        ar.vote_count = max(0, ar.vote_count - 1)
    else:
        db.add(AppRequestVote(request_id=request_id, user_id=user.id))
        ar.vote_count += 1

    await db.commit()
    return RedirectResponse(url="/community/requests", status_code=303)


@router.post("/requests/{request_id}/status")
async def request_update_status(
    request_id: int,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    new_status: str = Form(...),
    admin_note: str = Form(""),
):
    ar = (await db.execute(
        select(AppRequest).where(AppRequest.id == request_id)
    )).scalar_one_or_none()
    if ar:
        ar.status = new_status
        if admin_note:
            ar.admin_note = admin_note
        await db.commit()
    return RedirectResponse(url="/community/requests", status_code=303)
