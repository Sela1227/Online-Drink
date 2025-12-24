from fastapi import APIRouter, Request, Depends, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
from datetime import timezone, timedelta

from app.database import get_db
from app.models.feedback import Feedback, FeedbackType, FeedbackStatus
from app.services.auth import get_current_user, get_admin_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# 加入台北時區過濾器
def to_taipei_time(dt):
    if dt is None:
        return None
    taipei_tz = timezone(timedelta(hours=8))
    utc_dt = dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(taipei_tz)

templates.env.filters['taipei'] = to_taipei_time


@router.get("")
async def feedback_list(
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """我的問題回報列表"""
    feedbacks = db.query(Feedback).filter(
        Feedback.user_id == user.id
    ).order_by(Feedback.created_at.desc()).all()
    
    return templates.TemplateResponse("feedback/list.html", {
        "request": request,
        "user": user,
        "feedbacks": feedbacks,
        "feedback_types": list(FeedbackType),
    })


@router.post("/submit")
async def submit_feedback(
    request: Request,
    type: str = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """提交問題回報"""
    feedback = Feedback(
        user_id=user.id,
        type=FeedbackType(type),
        title=title,
        content=content,
    )
    db.add(feedback)
    db.commit()
    
    return RedirectResponse("/feedback", status_code=302)


# ===== 管理員路由 =====
@router.get("/admin")
async def admin_feedback_list(
    request: Request,
    status: str = None,
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    """管理員：問題回報列表"""
    query = db.query(Feedback).order_by(Feedback.created_at.desc())
    
    if status:
        query = query.filter(Feedback.status == FeedbackStatus(status))
    
    feedbacks = query.all()
    
    return templates.TemplateResponse("admin/feedbacks.html", {
        "request": request,
        "user": user,
        "feedbacks": feedbacks,
        "selected_status": status,
        "statuses": list(FeedbackStatus),
    })


@router.post("/admin/{feedback_id}/update")
async def update_feedback_status(
    feedback_id: int,
    status: str = Form(...),
    admin_note: str = Form(None),
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    """管理員：更新問題狀態"""
    feedback = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if feedback:
        feedback.status = FeedbackStatus(status)
        feedback.admin_note = admin_note
        db.commit()
    
    return RedirectResponse("/feedback/admin", status_code=302)
