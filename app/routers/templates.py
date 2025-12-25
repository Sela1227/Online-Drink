from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.models.template import GroupTemplate
from app.models.store import Store, CategoryType
from app.models.group import Group
from app.models.menu import Menu
from app.services.auth import get_current_user

router = APIRouter(prefix="/templates", tags=["templates"])
templates = Jinja2Templates(directory="app/templates")

TAIPEI_TZ = timezone(timedelta(hours=8))


@router.get("")
async def template_list(request: Request, db: Session = Depends(get_db)):
    """我的開團模板列表"""
    user = await get_current_user(request, db)
    
    my_templates = db.query(GroupTemplate).filter(
        GroupTemplate.user_id == user.id
    ).options(
        joinedload(GroupTemplate.store)
    ).order_by(GroupTemplate.use_count.desc()).all()
    
    return templates.TemplateResponse("templates/list.html", {
        "request": request,
        "user": user,
        "my_templates": my_templates,
    })


@router.get("/new")
async def new_template_page(request: Request, db: Session = Depends(get_db)):
    """新增模板頁面"""
    user = await get_current_user(request, db)
    
    stores = db.query(Store).filter(Store.is_active == True).order_by(Store.name).all()
    
    return templates.TemplateResponse("templates/new.html", {
        "request": request,
        "user": user,
        "stores": stores,
    })


@router.post("")
async def create_template(
    request: Request,
    template_name: str = Form(...),
    store_id: int = Form(...),
    group_name: str = Form(...),
    default_duration: int = Form(60),
    note: str = Form(None),
    default_sugar: str = Form(None),
    default_ice: str = Form(None),
    lock_sugar: bool = Form(False),
    lock_ice: bool = Form(False),
    is_blind_mode: bool = Form(False),
    enable_lucky_draw: bool = Form(False),
    lucky_draw_count: int = Form(1),
    min_members: int = Form(None),
    auto_extend: bool = Form(False),
    auto_remind_minutes: int = Form(None),
    db: Session = Depends(get_db),
):
    """建立模板"""
    user = await get_current_user(request, db)
    
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    tpl = GroupTemplate(
        user_id=user.id,
        name=template_name,
        store_id=store_id,
        group_name=group_name,
        default_duration_minutes=default_duration,
        note=note.strip() if note else None,
        default_sugar=default_sugar if store.category == CategoryType.DRINK else None,
        default_ice=default_ice if store.category == CategoryType.DRINK else None,
        lock_sugar=lock_sugar if store.category == CategoryType.DRINK else False,
        lock_ice=lock_ice if store.category == CategoryType.DRINK else False,
        is_blind_mode=is_blind_mode,
        enable_lucky_draw=enable_lucky_draw,
        lucky_draw_count=lucky_draw_count if enable_lucky_draw else 1,
        min_members=min_members if min_members and min_members >= 2 else None,
        auto_extend=auto_extend if min_members else False,
    )
    db.add(tpl)
    db.commit()
    
    return RedirectResponse(url="/templates", status_code=302)


@router.post("/{template_id}/use")
async def use_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    """使用模板開團"""
    user = await get_current_user(request, db)
    
    tpl = db.query(GroupTemplate).filter(GroupTemplate.id == template_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    
    if tpl.user_id != user.id:
        raise HTTPException(status_code=403, detail="無權使用此模板")
    
    # 取得菜單
    menu = db.query(Menu).filter(
        Menu.store_id == tpl.store_id,
        Menu.is_active == True
    ).first()
    
    if not menu:
        raise HTTPException(status_code=400, detail="該店家尚無啟用的菜單")
    
    # 取得店家
    store = db.query(Store).filter(Store.id == tpl.store_id).first()
    
    # 計算截止時間
    now = datetime.now(TAIPEI_TZ).replace(tzinfo=None)
    deadline = now + timedelta(minutes=tpl.default_duration_minutes)
    
    # 建立團單
    group = Group(
        store_id=tpl.store_id,
        menu_id=menu.id,
        owner_id=user.id,
        branch_id=tpl.branch_id,
        name=tpl.group_name,
        note=tpl.note,
        category=store.category,
        deadline=deadline,
        is_public=tpl.is_public,
        default_sugar=tpl.default_sugar,
        default_ice=tpl.default_ice,
        lock_sugar=tpl.lock_sugar,
        lock_ice=tpl.lock_ice,
        is_blind_mode=tpl.is_blind_mode,
        enable_lucky_draw=tpl.enable_lucky_draw,
        lucky_draw_count=tpl.lucky_draw_count,
        min_members=tpl.min_members,
        auto_extend=tpl.auto_extend,
    )
    db.add(group)
    
    # 更新模板使用次數
    tpl.use_count += 1
    
    db.commit()
    db.refresh(group)
    
    return RedirectResponse(url=f"/groups/{group.id}", status_code=302)


@router.post("/{template_id}/delete")
async def delete_template(template_id: int, request: Request, db: Session = Depends(get_db)):
    """刪除模板"""
    user = await get_current_user(request, db)
    
    tpl = db.query(GroupTemplate).filter(GroupTemplate.id == template_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    
    if tpl.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="無權刪除此模板")
    
    db.delete(tpl)
    db.commit()
    
    return RedirectResponse(url="/templates", status_code=302)


@router.post("/save-from-group/{group_id}")
async def save_template_from_group(
    group_id: int,
    template_name: str = Form(...),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """從現有團單儲存為模板"""
    user = await get_current_user(request, db)
    
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="團單不存在")
    
    # 計算開放時間（分鐘）
    duration = 60  # 預設 1 小時
    
    tpl = GroupTemplate(
        user_id=user.id,
        name=template_name,
        store_id=group.store_id,
        branch_id=group.branch_id,
        group_name=group.name,
        default_duration_minutes=duration,
        note=group.note,
        default_sugar=group.default_sugar,
        default_ice=group.default_ice,
        lock_sugar=group.lock_sugar,
        lock_ice=group.lock_ice,
        is_blind_mode=group.is_blind_mode,
        enable_lucky_draw=group.enable_lucky_draw,
        lucky_draw_count=group.lucky_draw_count,
        min_members=group.min_members,
        auto_extend=group.auto_extend,
        is_public=group.is_public,
    )
    db.add(tpl)
    db.commit()
    
    return RedirectResponse(url=f"/groups/{group_id}", status_code=302)
