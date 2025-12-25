from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.models.vote import Vote, VoteOption, VoteRecord
from app.models.store import Store, CategoryType
from app.models.group import Group
from app.models.menu import Menu
from app.services.auth import get_current_user

router = APIRouter(prefix="/votes", tags=["votes"])
templates = Jinja2Templates(directory="app/templates")

# 台北時區
TAIPEI_TZ = timezone(timedelta(hours=8))


@router.get("")
async def vote_list(request: Request, db: Session = Depends(get_db)):
    """投票列表"""
    user = await get_current_user(request, db)
    
    # 取得進行中的投票
    now = datetime.now(TAIPEI_TZ).replace(tzinfo=None)
    active_votes = db.query(Vote).filter(
        Vote.is_closed == False,
        Vote.deadline > now
    ).options(
        joinedload(Vote.creator),
        joinedload(Vote.options).joinedload(VoteOption.store),
        joinedload(Vote.options).joinedload(VoteOption.voters)
    ).order_by(Vote.deadline.asc()).all()
    
    # 取得已結束的投票（最近10個）
    closed_votes = db.query(Vote).filter(
        (Vote.is_closed == True) | (Vote.deadline <= now)
    ).options(
        joinedload(Vote.creator),
        joinedload(Vote.options).joinedload(VoteOption.store)
    ).order_by(Vote.created_at.desc()).limit(10).all()
    
    return templates.TemplateResponse("votes/list.html", {
        "request": request,
        "user": user,
        "active_votes": active_votes,
        "closed_votes": closed_votes,
    })


@router.get("/new")
async def new_vote_page(request: Request, db: Session = Depends(get_db)):
    """新建投票頁面"""
    user = await get_current_user(request, db)
    
    # 取得所有啟用的店家
    stores = db.query(Store).filter(Store.is_active == True).order_by(Store.name).all()
    
    return templates.TemplateResponse("votes/new.html", {
        "request": request,
        "user": user,
        "stores": stores,
    })


@router.post("")
async def create_vote(
    request: Request,
    title: str = Form(...),
    deadline: str = Form(...),
    description: str = Form(None),
    is_multiple: bool = Form(False),
    db: Session = Depends(get_db),
):
    """建立投票"""
    user = await get_current_user(request, db)
    
    # 取得選擇的店家
    form_data = await request.form()
    store_ids = form_data.getlist("store_ids")
    
    if not store_ids:
        raise HTTPException(status_code=400, detail="請至少選擇一個店家")
    
    # 解析截止時間
    try:
        deadline_dt = datetime.fromisoformat(deadline)
    except ValueError:
        raise HTTPException(status_code=400, detail="截止時間格式錯誤")
    
    # 建立投票
    vote = Vote(
        creator_id=user.id,
        title=title,
        description=description.strip() if description else None,
        deadline=deadline_dt,
        is_multiple=is_multiple,
    )
    db.add(vote)
    db.flush()
    
    # 建立投票選項
    for store_id in store_ids:
        option = VoteOption(
            vote_id=vote.id,
            store_id=int(store_id),
            added_by_id=user.id,
        )
        db.add(option)
    
    db.commit()
    
    return RedirectResponse(url=f"/votes/{vote.id}", status_code=302)


@router.get("/{vote_id}")
async def vote_detail(vote_id: int, request: Request, db: Session = Depends(get_db)):
    """投票詳情頁"""
    user = await get_current_user(request, db)
    
    vote = db.query(Vote).filter(Vote.id == vote_id).options(
        joinedload(Vote.creator),
        joinedload(Vote.options).joinedload(VoteOption.store),
        joinedload(Vote.options).joinedload(VoteOption.voters).joinedload(VoteRecord.user)
    ).first()
    
    if not vote:
        raise HTTPException(status_code=404, detail="投票不存在")
    
    # 檢查用戶是否已投票
    my_votes = []
    for opt in vote.options:
        for voter in opt.voters:
            if voter.user_id == user.id:
                my_votes.append(opt.id)
    
    # 排序選項（按票數）
    sorted_options = sorted(vote.options, key=lambda x: x.vote_count, reverse=True)
    
    # 取得所有店家（用於提議新選項）
    stores = db.query(Store).filter(Store.is_active == True).order_by(Store.name).all()
    existing_store_ids = {opt.store_id for opt in vote.options}
    available_stores = [s for s in stores if s.id not in existing_store_ids]
    
    return templates.TemplateResponse("votes/detail.html", {
        "request": request,
        "user": user,
        "vote": vote,
        "sorted_options": sorted_options,
        "my_votes": my_votes,
        "available_stores": available_stores,
        "is_creator": vote.creator_id == user.id,
    })


@router.post("/{vote_id}/vote")
async def cast_vote(
    vote_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """投票"""
    user = await get_current_user(request, db)
    
    vote = db.query(Vote).filter(Vote.id == vote_id).first()
    if not vote:
        raise HTTPException(status_code=404, detail="投票不存在")
    
    if not vote.is_open:
        raise HTTPException(status_code=400, detail="投票已結束")
    
    # 取得選擇的選項
    form_data = await request.form()
    option_ids = form_data.getlist("option_ids")
    
    if not option_ids:
        raise HTTPException(status_code=400, detail="請選擇至少一個選項")
    
    # 如果不允許多選，只取第一個
    if not vote.is_multiple and len(option_ids) > 1:
        option_ids = [option_ids[0]]
    
    # 清除用戶之前的投票
    for opt in vote.options:
        db.query(VoteRecord).filter(
            VoteRecord.option_id == opt.id,
            VoteRecord.user_id == user.id
        ).delete()
    
    # 新增投票
    for option_id in option_ids:
        record = VoteRecord(
            option_id=int(option_id),
            user_id=user.id,
        )
        db.add(record)
    
    db.commit()
    
    return RedirectResponse(url=f"/votes/{vote_id}", status_code=302)


@router.post("/{vote_id}/add-option")
async def add_option(
    vote_id: int,
    store_id: int = Form(...),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """提議新選項"""
    user = await get_current_user(request, db)
    
    vote = db.query(Vote).filter(Vote.id == vote_id).first()
    if not vote:
        raise HTTPException(status_code=404, detail="投票不存在")
    
    if not vote.is_open:
        raise HTTPException(status_code=400, detail="投票已結束")
    
    # 檢查店家是否已在選項中
    existing = db.query(VoteOption).filter(
        VoteOption.vote_id == vote_id,
        VoteOption.store_id == store_id
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="此店家已在選項中")
    
    # 新增選項
    option = VoteOption(
        vote_id=vote_id,
        store_id=store_id,
        added_by_id=user.id,
    )
    db.add(option)
    db.commit()
    
    return RedirectResponse(url=f"/votes/{vote_id}", status_code=302)


@router.post("/{vote_id}/close")
async def close_vote(vote_id: int, request: Request, db: Session = Depends(get_db)):
    """結束投票"""
    user = await get_current_user(request, db)
    
    vote = db.query(Vote).filter(Vote.id == vote_id).options(
        joinedload(Vote.options).joinedload(VoteOption.voters)
    ).first()
    
    if not vote:
        raise HTTPException(status_code=404, detail="投票不存在")
    
    if vote.creator_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有發起人可以結束投票")
    
    vote.is_closed = True
    
    # 找出票數最高的選項
    if vote.options:
        winner = max(vote.options, key=lambda x: x.vote_count)
        if winner.vote_count > 0:
            vote.winner_store_id = winner.store_id
    
    db.commit()
    
    return RedirectResponse(url=f"/votes/{vote_id}", status_code=302)


@router.post("/{vote_id}/create-group")
async def create_group_from_vote(vote_id: int, request: Request, db: Session = Depends(get_db)):
    """從投票結果開團"""
    user = await get_current_user(request, db)
    
    vote = db.query(Vote).filter(Vote.id == vote_id).first()
    if not vote:
        raise HTTPException(status_code=404, detail="投票不存在")
    
    if not vote.winner_store_id:
        raise HTTPException(status_code=400, detail="尚無勝出店家")
    
    if vote.created_group_id:
        return RedirectResponse(url=f"/groups/{vote.created_group_id}", status_code=302)
    
    # 取得勝出店家
    store = db.query(Store).filter(Store.id == vote.winner_store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    # 取得菜單
    menu = db.query(Menu).filter(
        Menu.store_id == store.id,
        Menu.is_active == True
    ).first()
    
    if not menu:
        raise HTTPException(status_code=400, detail="該店家尚無啟用的菜單")
    
    # 建立團單
    now = datetime.now(TAIPEI_TZ).replace(tzinfo=None)
    group = Group(
        store_id=store.id,
        menu_id=menu.id,
        owner_id=user.id,
        name=f"{vote.title} - {store.name}",
        category=store.category,
        deadline=now + timedelta(hours=2),  # 預設2小時後截止
    )
    db.add(group)
    db.flush()
    
    vote.created_group_id = group.id
    db.commit()
    
    return RedirectResponse(url=f"/groups/{group.id}", status_code=302)


@router.post("/{vote_id}/delete")
async def delete_vote(vote_id: int, request: Request, db: Session = Depends(get_db)):
    """刪除投票"""
    user = await get_current_user(request, db)
    
    vote = db.query(Vote).filter(Vote.id == vote_id).first()
    if not vote:
        raise HTTPException(status_code=404, detail="投票不存在")
    
    if vote.creator_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="只有發起人可以刪除投票")
    
    # 刪除相關資料
    for opt in vote.options:
        db.query(VoteRecord).filter(VoteRecord.option_id == opt.id).delete()
    db.query(VoteOption).filter(VoteOption.vote_id == vote_id).delete()
    db.delete(vote)
    db.commit()
    
    return RedirectResponse(url="/votes", status_code=302)
