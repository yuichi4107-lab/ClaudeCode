"""フォームビルダー - ルーター"""

import json
import secrets

from fastapi import APIRouter, Depends, Form as FastForm, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from app.core.templates import make_templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_tool_access
from app.database import get_db
from app.users.models import User
from .models import Form, FormResponse

router = APIRouter(prefix="/tools/formbuilder", tags=["formbuilder"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    user: User = Depends(require_tool_access("formbuilder")),
    db: AsyncSession = Depends(get_db),
):
    forms = (await db.execute(
        select(Form).where(Form.user_id == user.id).order_by(Form.created_at.desc())
    )).scalars().all()

    # Response counts per form
    resp_counts = {}
    for f in forms:
        r = await db.execute(
            select(func.count(FormResponse.id)).where(FormResponse.form_id == f.id)
        )
        resp_counts[f.id] = r.scalar() or 0

    return templates.TemplateResponse(
        request, "tools/formbuilder/index.html",
        {"user": user, "page": "formbuilder", "forms": forms, "resp_counts": resp_counts},
    )


@router.post("/api/create")
async def api_create(
    user: User = Depends(require_tool_access("formbuilder")),
    db: AsyncSession = Depends(get_db),
    title: str = FastForm(...),
    description: str = FastForm(""),
    fields_json: str = FastForm("[]"),
):
    form = Form(
        user_id=user.id, title=title, description=description,
        fields_json=fields_json, public_key=secrets.token_hex(8),
    )
    db.add(form)
    await db.commit()
    return JSONResponse({"status": "ok", "id": form.id, "public_key": form.public_key})


@router.get("/{form_id}/edit", response_class=HTMLResponse)
async def edit_form(
    form_id: int,
    request: Request,
    user: User = Depends(require_tool_access("formbuilder")),
    db: AsyncSession = Depends(get_db),
):
    form = (await db.execute(
        select(Form).where(Form.id == form_id, Form.user_id == user.id)
    )).scalar_one_or_none()
    if not form:
        return HTMLResponse("Not Found", status_code=404)

    return templates.TemplateResponse(
        request, "tools/formbuilder/edit.html",
        {"user": user, "page": "formbuilder", "form": form},
    )


@router.post("/api/{form_id}/update")
async def api_update(
    form_id: int,
    user: User = Depends(require_tool_access("formbuilder")),
    db: AsyncSession = Depends(get_db),
    title: str = FastForm(...),
    description: str = FastForm(""),
    fields_json: str = FastForm("[]"),
    is_active: str = FastForm("true"),
):
    form = (await db.execute(
        select(Form).where(Form.id == form_id, Form.user_id == user.id)
    )).scalar_one_or_none()
    if not form:
        return JSONResponse({"error": "not found"}, status_code=404)
    form.title = title
    form.description = description
    form.fields_json = fields_json
    form.is_active = is_active == "true"
    await db.commit()
    return JSONResponse({"status": "ok"})


@router.post("/api/{form_id}/delete")
async def api_delete(
    form_id: int,
    user: User = Depends(require_tool_access("formbuilder")),
    db: AsyncSession = Depends(get_db),
):
    form = (await db.execute(
        select(Form).where(Form.id == form_id, Form.user_id == user.id)
    )).scalar_one_or_none()
    if not form:
        return JSONResponse({"error": "not found"}, status_code=404)
    # Delete responses too
    responses = (await db.execute(
        select(FormResponse).where(FormResponse.form_id == form_id)
    )).scalars().all()
    for r in responses:
        await db.delete(r)
    await db.delete(form)
    await db.commit()
    return JSONResponse({"status": "ok"})


@router.get("/{form_id}/responses", response_class=HTMLResponse)
async def responses_list(
    form_id: int,
    request: Request,
    user: User = Depends(require_tool_access("formbuilder")),
    db: AsyncSession = Depends(get_db),
):
    form = (await db.execute(
        select(Form).where(Form.id == form_id, Form.user_id == user.id)
    )).scalar_one_or_none()
    if not form:
        return HTMLResponse("Not Found", status_code=404)

    responses = (await db.execute(
        select(FormResponse).where(FormResponse.form_id == form_id).order_by(FormResponse.created_at.desc())
    )).scalars().all()

    fields = json.loads(form.fields_json)
    parsed = []
    for r in responses:
        parsed.append({"id": r.id, "data": json.loads(r.data_json), "created_at": r.created_at})

    return templates.TemplateResponse(
        request, "tools/formbuilder/responses.html",
        {"user": user, "page": "formbuilder", "form": form, "fields": fields, "responses": parsed},
    )


# ---- Public form (no auth required) ----

@router.get("/p/{public_key}", response_class=HTMLResponse)
async def public_form(
    public_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    form = (await db.execute(
        select(Form).where(Form.public_key == public_key, Form.is_active == True)
    )).scalar_one_or_none()
    if not form:
        return HTMLResponse("このフォームは公開されていません。", status_code=404)

    fields = json.loads(form.fields_json)
    return templates.TemplateResponse(
        request, "tools/formbuilder/public.html",
        {"user": user, "form": form, "fields": fields, "submitted": False},
    )


@router.post("/p/{public_key}")
async def public_form_submit(
    public_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    from app.tools.rate_limit import check_rate_limit, get_client_ip
    if err := check_rate_limit(get_client_ip(request), max_requests=5, window_sec=60):
        return HTMLResponse(err, status_code=429)

    form = (await db.execute(
        select(Form).where(Form.public_key == public_key, Form.is_active == True)
    )).scalar_one_or_none()
    if not form:
        return HTMLResponse("Not Found", status_code=404)

    form_data = await request.form()
    data = {k: v for k, v in form_data.items()}
    response = FormResponse(form_id=form.id, data_json=json.dumps(data, ensure_ascii=False))
    db.add(response)
    await db.commit()

    fields = json.loads(form.fields_json)
    return templates.TemplateResponse(
        request, "tools/formbuilder/public.html",
        {"user": None, "form": form, "fields": fields, "submitted": True},
    )
