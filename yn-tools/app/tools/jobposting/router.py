"""求人票ジェネレーター - ルーター"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.templates import make_templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access
from app.database import get_db
from app.users.models import User

from .models import JobPosting
from . import service
from app.tools.usage_limit import get_monthly_usage, get_limit, limit_error

router = APIRouter(prefix="/tools/jobposting", tags=["jobposting"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def jobposting_index(
    request: Request,
    user: User = Depends(require_tool_access("jobposting")),
    db: AsyncSession = Depends(get_db),
):
    """求人票ジェネレーター ダッシュボード"""
    result = await db.execute(
        select(JobPosting)
        .where(JobPosting.user_id == user.id)
        .order_by(JobPosting.created_at.desc())
        .limit(20)
    )
    postings = result.scalars().all()

    monthly_used = await get_monthly_usage(db, user.id, "jobposting")

    return templates.TemplateResponse(
        request, "tools/jobposting/index.html", {
            "user": user,
            "page": "jobposting",
            "view": "dashboard",
            "postings": postings,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("jobposting"),
            "industry_templates": service.INDUSTRY_TEMPLATES,
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def jobposting_new(
    request: Request,
    user: User = Depends(require_tool_access("jobposting")),
    db: AsyncSession = Depends(get_db),
):
    """新規作成フォーム"""
    monthly_used = await get_monthly_usage(db, user.id, "jobposting")

    return templates.TemplateResponse(
        request, "tools/jobposting/index.html", {
            "user": user,
            "page": "jobposting",
            "view": "new",
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("jobposting"),
            "industry_templates": service.INDUSTRY_TEMPLATES,
        }
    )


@router.get("/{posting_id}", response_class=HTMLResponse)
async def jobposting_detail(
    posting_id: int,
    request: Request,
    user: User = Depends(require_tool_access("jobposting")),
    db: AsyncSession = Depends(get_db),
):
    """生成結果・編集画面"""
    result = await db.execute(
        select(JobPosting).where(
            JobPosting.id == posting_id,
            JobPosting.user_id == user.id,
        )
    )
    posting = result.scalar_one_or_none()
    if not posting:
        return RedirectResponse(url="/tools/jobposting/", status_code=303)

    monthly_used = await get_monthly_usage(db, user.id, "jobposting")

    return templates.TemplateResponse(
        request, "tools/jobposting/index.html", {
            "user": user,
            "page": "jobposting",
            "view": "detail",
            "posting": posting,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("jobposting"),
            "industry_templates": service.INDUSTRY_TEMPLATES,
            "display_text": posting.edited_text or posting.generated_text or "",
        }
    )


@router.post("/api/generate")
async def api_generate(
    request: Request,
    user: User = Depends(require_tool_access("jobposting")),
    db: AsyncSession = Depends(get_db),
    industry_template: str = Form(...),
    job_title: str = Form(...),
    company_name: str = Form(...),
    location: str = Form(...),
    salary_type: str = Form(...),
    salary_min: int = Form(...),
    salary_max: int | None = Form(default=None),
    work_hours: str = Form(...),
    holidays: str = Form(default=""),
    qualifications: str = Form(default=""),
    benefits: str = Form(default=""),
    pr_points: str = Form(default=""),
    target_format: str = Form(...),
):
    """AI生成API"""
    used = await get_monthly_usage(db, user.id, "jobposting")
    if err := limit_error("jobposting", used, get_limit("jobposting")):
        return {"error": err}

    try:
        generated_text = await service.generate_job_posting(
            industry_template=industry_template,
            job_title=job_title,
            company_name=company_name,
            location=location,
            salary_type=salary_type,
            salary_min=salary_min,
            salary_max=salary_max,
            work_hours=work_hours,
            holidays=holidays,
            qualifications=qualifications,
            benefits=benefits,
            pr_points=pr_points,
            target_format=target_format,
        )
    except Exception as e:
        return {"error": f"AI生成に失敗しました: {str(e)}"}

    # 保存名を自動生成
    from datetime import datetime
    month_str = datetime.now().strftime("%Y-%m")
    title = f"{job_title}_{month_str}"

    posting = JobPosting(
        user_id=user.id,
        title=title,
        industry_template=industry_template,
        job_title=job_title,
        company_name=company_name,
        location=location,
        salary_type=salary_type,
        salary_min=salary_min,
        salary_max=salary_max if salary_max else None,
        work_hours=work_hours,
        holidays=holidays or None,
        qualifications=qualifications or None,
        benefits=benefits or None,
        pr_points=pr_points or None,
        target_format=target_format,
        generated_text=generated_text,
    )
    db.add(posting)
    await db.commit()
    await db.refresh(posting)

    return {"id": posting.id, "generated_text": generated_text}


class SaveRequest(BaseModel):
    edited_text: str


@router.post("/api/{posting_id}/save")
async def api_save(
    posting_id: int,
    body: SaveRequest,
    user: User = Depends(require_tool_access("jobposting")),
    db: AsyncSession = Depends(get_db),
):
    """編集テキスト保存"""
    result = await db.execute(
        select(JobPosting).where(
            JobPosting.id == posting_id,
            JobPosting.user_id == user.id,
        )
    )
    posting = result.scalar_one_or_none()
    if not posting:
        return {"error": "求人票が見つかりません"}

    posting.edited_text = body.edited_text
    await db.commit()
    return {"ok": True}


class RegenerateRequest(BaseModel):
    field_overrides: dict = {}


@router.post("/api/{posting_id}/regenerate")
async def api_regenerate(
    posting_id: int,
    body: RegenerateRequest,
    user: User = Depends(require_tool_access("jobposting")),
    db: AsyncSession = Depends(get_db),
):
    """再生成API"""
    result = await db.execute(
        select(JobPosting).where(
            JobPosting.id == posting_id,
            JobPosting.user_id == user.id,
        )
    )
    posting = result.scalar_one_or_none()
    if not posting:
        return {"error": "求人票が見つかりません"}

    used = await get_monthly_usage(db, user.id, "jobposting")
    if err := limit_error("jobposting", used, get_limit("jobposting")):
        return {"error": err}

    overrides = body.field_overrides

    try:
        generated_text = await service.generate_job_posting(
            industry_template=overrides.get("industry_template", posting.industry_template),
            job_title=overrides.get("job_title", posting.job_title),
            company_name=overrides.get("company_name", posting.company_name),
            location=overrides.get("location", posting.location),
            salary_type=overrides.get("salary_type", posting.salary_type),
            salary_min=overrides.get("salary_min", posting.salary_min),
            salary_max=overrides.get("salary_max", posting.salary_max),
            work_hours=overrides.get("work_hours", posting.work_hours),
            holidays=overrides.get("holidays", posting.holidays or ""),
            qualifications=overrides.get("qualifications", posting.qualifications or ""),
            benefits=overrides.get("benefits", posting.benefits or ""),
            pr_points=overrides.get("pr_points", posting.pr_points or ""),
            target_format=overrides.get("target_format", posting.target_format),
        )
    except Exception as e:
        return {"error": f"AI生成に失敗しました: {str(e)}"}

    posting.generated_text = generated_text
    posting.edited_text = None  # 再生成時はユーザー編集をリセット
    await db.commit()

    return {"generated_text": generated_text}


@router.delete("/api/{posting_id}")
async def api_delete(
    posting_id: int,
    user: User = Depends(require_tool_access("jobposting")),
    db: AsyncSession = Depends(get_db),
):
    """削除API"""
    result = await db.execute(
        select(JobPosting).where(
            JobPosting.id == posting_id,
            JobPosting.user_id == user.id,
        )
    )
    posting = result.scalar_one_or_none()
    if not posting:
        return {"error": "求人票が見つかりません"}

    await db.delete(posting)
    await db.commit()
    return {"ok": True}


@router.get("/api/template/{slug}")
async def api_template(
    slug: str,
    user: User = Depends(require_tool_access("jobposting")),
):
    """業種テンプレートのデフォルト値取得"""
    defaults = service.get_template_defaults(slug)
    return defaults
