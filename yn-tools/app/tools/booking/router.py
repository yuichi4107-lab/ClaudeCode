"""予約管理 - ルーター"""

import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access
from app.database import get_db
from app.users.models import User

from .models import BookingForm, Booking

router = APIRouter(prefix="/tools/booking", tags=["booking"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def booking_index(
    request: Request,
    user: User = Depends(require_tool_access("booking")),
    db: AsyncSession = Depends(get_db),
):
    """予約管理ダッシュボード"""
    forms_result = await db.execute(
        select(BookingForm).where(BookingForm.user_id == user.id).order_by(BookingForm.created_at.desc())
    )
    forms = forms_result.scalars().all()

    # Get bookings for all user's forms
    form_ids = [f.form_id for f in forms]
    bookings = []
    if form_ids:
        bookings_result = await db.execute(
            select(Booking)
            .where(Booking.form_id.in_(form_ids))
            .order_by(Booking.booked_date.desc(), Booking.booked_time.desc())
            .limit(50)
        )
        bookings = bookings_result.scalars().all()

    return templates.TemplateResponse(
        request, "tools/booking/index.html", {
            "user": user,
            "page": "booking",
            "forms": forms,
            "bookings": bookings,
        }
    )


@router.post("/api/forms/create")
async def api_create_form(
    user: User = Depends(require_tool_access("booking")),
    db: AsyncSession = Depends(get_db),
    name: str = Form(default=""),
    description: str = Form(default=""),
    duration_min: int = Form(default=60),
    available_days: str = Form(default="mon,tue,wed,thu,fri"),
    available_start: str = Form(default="09:00"),
    available_end: str = Form(default="18:00"),
):
    """予約フォーム作成"""
    if not name.strip():
        return {"error": "フォーム名を入力してください。"}

    form = BookingForm(
        user_id=user.id,
        name=name.strip(),
        description=description.strip() or None,
        duration_min=duration_min,
        available_days=available_days,
        available_start=available_start,
        available_end=available_end,
    )
    db.add(form)
    await db.commit()
    return {"ok": True, "form_id": form.form_id}


@router.post("/api/forms/delete/{form_id}")
async def api_delete_form(
    form_id: str,
    user: User = Depends(require_tool_access("booking")),
    db: AsyncSession = Depends(get_db),
):
    """予約フォーム削除"""
    result = await db.execute(
        select(BookingForm).where(BookingForm.form_id == form_id, BookingForm.user_id == user.id)
    )
    form = result.scalar_one_or_none()
    if not form:
        return {"error": "フォームが見つかりません。"}
    await db.delete(form)
    await db.commit()
    return {"ok": True}


@router.post("/api/bookings/cancel/{booking_id}")
async def api_cancel_booking(
    booking_id: int,
    user: User = Depends(require_tool_access("booking")),
    db: AsyncSession = Depends(get_db),
):
    """予約キャンセル"""
    result = await db.execute(
        select(Booking)
        .join(BookingForm, Booking.form_id == BookingForm.form_id)
        .where(Booking.id == booking_id, BookingForm.user_id == user.id)
    )
    booking = result.scalar_one_or_none()
    if not booking:
        return {"error": "予約が見つかりません。"}

    booking.status = "canceled"
    await db.commit()
    return {"ok": True}


# Public booking page (no auth)
@router.get("/p/{form_id}", response_class=HTMLResponse)
async def public_booking(
    request: Request,
    form_id: str,
    db: AsyncSession = Depends(get_db),
):
    """公開予約ページ"""
    result = await db.execute(
        select(BookingForm).where(BookingForm.form_id == form_id, BookingForm.is_active == True)
    )
    form = result.scalar_one_or_none()
    if not form:
        return HTMLResponse("<h1>予約フォームが見つかりません</h1>", status_code=404)

    # Get existing bookings for this form (to show unavailable slots)
    bookings_result = await db.execute(
        select(Booking.booked_date, Booking.booked_time)
        .where(Booking.form_id == form_id, Booking.status == "confirmed")
    )
    booked_slots = [(r[0], r[1]) for r in bookings_result.all()]

    return templates.TemplateResponse(
        request, "tools/booking/public.html", {
            "form": form,
            "booked_slots": booked_slots,
        }
    )


@router.post("/p/{form_id}/submit")
async def public_submit(
    form_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    guest_name: str = Form(default=""),
    guest_email: str = Form(default=""),
    guest_note: str = Form(default=""),
    booked_date: str = Form(default=""),
    booked_time: str = Form(default=""),
):
    """公開予約フォーム送信"""
    from app.tools.rate_limit import check_rate_limit, get_client_ip
    if err := check_rate_limit(get_client_ip(request), max_requests=5, window_sec=60):
        return {"error": err}

    guest_name = guest_name.strip()
    guest_email = guest_email.strip()
    if not guest_name or not guest_email:
        return {"error": "名前とメールアドレスは必須です。"}
    if len(guest_name) > 200:
        return {"error": "名前が長すぎます。"}
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', guest_email):
        return {"error": "メールアドレスの形式が正しくありません。"}
    if len(guest_note) > 2000:
        return {"error": "備考が長すぎます。"}
    if not booked_date or not booked_time:
        return {"error": "日付と時間を選択してください。"}

    # Check form exists
    result = await db.execute(
        select(BookingForm).where(BookingForm.form_id == form_id, BookingForm.is_active == True)
    )
    if not result.scalar_one_or_none():
        return {"error": "予約フォームが無効です。"}

    # Check slot not already booked
    existing = await db.execute(
        select(Booking).where(
            Booking.form_id == form_id,
            Booking.booked_date == booked_date,
            Booking.booked_time == booked_time,
            Booking.status == "confirmed",
        )
    )
    if existing.scalar_one_or_none():
        return {"error": "この時間帯はすでに予約済みです。"}

    booking = Booking(
        form_id=form_id,
        guest_name=guest_name.strip(),
        guest_email=guest_email.strip(),
        guest_note=guest_note.strip() or None,
        booked_date=booked_date,
        booked_time=booked_time,
    )
    db.add(booking)
    await db.commit()
    return {"ok": True, "message": "予約が完了しました。"}
