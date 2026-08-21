"""タスクマネージャー - ルーター"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from app.core.templates import make_templates
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access
from app.database import get_db
from app.users.models import User
from .models import Task

router = APIRouter(prefix="/tools/taskmanager", tags=["taskmanager"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    user: User = Depends(require_tool_access("taskmanager")),
    db: AsyncSession = Depends(get_db),
):
    tasks = (await db.execute(
        select(Task).where(Task.user_id == user.id).order_by(
            case(
                (Task.status == "doing", 1),
                (Task.status == "todo", 2),
                (Task.status == "done", 3),
                else_=4,
            ),
            case(
                (Task.priority == "high", 1),
                (Task.priority == "medium", 2),
                (Task.priority == "low", 3),
                else_=4,
            ),
            Task.created_at.desc(),
        )
    )).scalars().all()

    counts = {}
    for s in ("todo", "doing", "done"):
        r = await db.execute(
            select(func.count(Task.id)).where(Task.user_id == user.id, Task.status == s)
        )
        counts[s] = r.scalar() or 0

    return templates.TemplateResponse(
        request, "tools/taskmanager/index.html",
        {"user": user, "page": "taskmanager", "tasks": tasks, "counts": counts},
    )


@router.post("/api/create")
async def api_create(
    user: User = Depends(require_tool_access("taskmanager")),
    db: AsyncSession = Depends(get_db),
    title: str = Form(...),
    description: str = Form(""),
    priority: str = Form("medium"),
    due_date: str = Form(""),
):
    task = Task(
        user_id=user.id, title=title, description=description,
        priority=priority, due_date=due_date or None,
    )
    db.add(task)
    await db.commit()
    return JSONResponse({"status": "ok", "id": task.id})


@router.post("/api/{task_id}/update")
async def api_update(
    task_id: int,
    user: User = Depends(require_tool_access("taskmanager")),
    db: AsyncSession = Depends(get_db),
    title: str = Form(None),
    description: str = Form(None),
    status: str = Form(None),
    priority: str = Form(None),
    due_date: str = Form(None),
):
    task = (await db.execute(
        select(Task).where(Task.id == task_id, Task.user_id == user.id)
    )).scalar_one_or_none()
    if not task:
        return JSONResponse({"error": "not found"}, status_code=404)
    if title is not None:
        task.title = title
    if description is not None:
        task.description = description
    if status is not None:
        task.status = status
    if priority is not None:
        task.priority = priority
    if due_date is not None:
        task.due_date = due_date or None
    await db.commit()
    return JSONResponse({"status": "ok"})


@router.post("/api/{task_id}/delete")
async def api_delete(
    task_id: int,
    user: User = Depends(require_tool_access("taskmanager")),
    db: AsyncSession = Depends(get_db),
):
    task = (await db.execute(
        select(Task).where(Task.id == task_id, Task.user_id == user.id)
    )).scalar_one_or_none()
    if not task:
        return JSONResponse({"error": "not found"}, status_code=404)
    await db.delete(task)
    await db.commit()
    return JSONResponse({"status": "ok"})
