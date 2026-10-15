from fastapi import APIRouter, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.models.group import Group
from app.models.order import Order, OrderItem, OrderStatus
from app.models.store import CategoryType, Store
from app.models.user import Announcement
from app.services.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# 加入台北時區過濾器
def to_taipei_time(dt):
    if dt is None:
        return None
    taipei_tz = timezone(timedelta(hours=8))
    if dt.tzinfo is None:
        utc_dt = dt.replace(tzinfo=timezone.utc)
    else:
        utc_dt = dt
    return utc_dt.astimezone(taipei_tz)

templates.env.filters['taipei'] = to_taipei_time


def month_buckets(today, count: int = 6):
    """往回推 count 個月，回傳 [(年, 月), ...]，最舊在前、當月在最後。

    V2.10.3：原本用 `today.replace(day=1) - timedelta(days=i*30)` 推算，但月份
    長度是 28-31 天，累積誤差會讓某些月份重複、某些月份消失（2026 年 3-5 月都
    會漏掉二月）。月份要用月份運算，不要用天數近似。
    """
    out, year, month = [], today.year, today.month
    for _ in range(count):
        out.append((year, month))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(out))


def taipei_slot(utc_dow: int, utc_hour: int) -> tuple[int, int]:
    """(UTC 星期, UTC 小時) → (台北星期, 台北小時)。

    V2.10.3：`Order.created_at` 是 UTC，`extract` 出來的小時與星期也是 UTC。
    午餐團多在台北 09:00-12:00＝UTC 01:00-04:00，未位移時「最常下單時段」會
    顯示 2:00 或 3:00。位移跨過 24 點時星期要進一天，所以兩者必須一起算。
    dow 慣例 0=週日，PostgreSQL 與 SQLite 一致。
    """
    taipei_hour = (utc_hour + 8) % 24
    taipei_dow = (utc_dow + 1) % 7 if utc_hour + 8 >= 24 else utc_dow
    return taipei_dow, taipei_hour


def visible_active_votes(db: Session, user, now, limit: int = 4):
    """進行中且該使用者看得到的投票（V2.11.2 N-02）。

    /home 與 /home/groups 原本各有一份逐字相同的查詢，兩份都沒有可見性過濾 ——
    部門私密投票的標題、票數、截止時間會出現在所有人的首頁上（點進去才 403，
    但該看不到的資訊已經露出來了）。抽成共用函式，不要再各改一邊。
    """
    from app.models.vote import Vote, VoteOption
    from app.services.visibility import visible_vote_clause
    return db.query(Vote).options(
        joinedload(Vote.creator),
        joinedload(Vote.options).joinedload(VoteOption.voters)
    ).filter(
        Vote.is_closed == False,
        Vote.deadline > now,
        visible_vote_clause(user),
    ).order_by(Vote.deadline.asc()).limit(limit).all()


def visible_closed_groups(db: Session, user, now, limit: int = 10):
    """已截止且該使用者看得到的團（V2.11.2 N-02）。

    /home 有過濾、/home/groups 沒有 —— 而首頁在團截止時會自動 htmx 刷新片段，
    私密的已截止團就從那裡冒出來。
    """
    from app.services.visibility import visible_group_clause
    return db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner)
    ).filter(
        or_(Group.is_closed == True, Group.deadline <= now),
        visible_group_clause(user),
    ).order_by(Group.deadline.desc()).limit(limit).all()


def get_active_announcements(db: Session, limit: int = 2):
    """首頁公告（V2.10.0）：啟用中且未到期，置頂優先、其次建立時間新到舊。

    資料庫存的是 naive UTC，故以 utcnow() 比對 expires_at。
    expires_at 為 NULL 代表不設到期，永久顯示。
    """
    return db.query(Announcement).filter(
        Announcement.is_active == True,
        or_(Announcement.expires_at == None, Announcement.expires_at > datetime.utcnow()),
    ).order_by(
        Announcement.is_pinned.desc(),
        Announcement.created_at.desc(),
    ).limit(limit).all()


def get_hot_items(db: Session, limit: int = 10):
    """取得全站熱門品項（最近 30 天）"""
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    hot_items = db.query(
        OrderItem.item_name,
        Store.name.label('store_name'),
        Store.logo_url.label('store_logo'),
        func.sum(OrderItem.quantity).label('total_qty'),
    ).join(Order).join(Group).join(Store).filter(
        Order.status == OrderStatus.SUBMITTED,
        Order.created_at >= thirty_days_ago,
    ).group_by(
        OrderItem.item_name,
        Store.name,
        Store.logo_url,
    ).order_by(
        func.sum(OrderItem.quantity).desc()
    ).limit(limit).all()
    
    return hot_items


@router.get("/home")
async def home(request: Request, db: Session = Depends(get_db)):
    """首頁 - 團列表"""
    user = await get_current_user(request, db)
    
    # 使用台北時間（因為 deadline 存的是台北時間）
    taipei_tz = timezone(timedelta(hours=8))
    now = datetime.now(taipei_tz).replace(tzinfo=None)
    
    # 取得用戶的部門 IDs
    from app.models.department import UserDepartment, GroupDepartment
    user_dept_ids = [ud.department_id for ud in db.query(UserDepartment).filter(
        UserDepartment.user_id == user.id
    ).all()]
    
    # V2.11.1 P0-05：原本是迴圈內逐筆查部門（N+1），而且只有這支路由有過濾，
    # /home/groups 與 /history 都沒有。改用 app/services/visibility.py 的共用 SQL 條件。
    from app.services.visibility import visible_group_clause
    _visible = visible_group_clause(user)
    
    # 開放中的飲料團（eager load orders 和 store）
    drink_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner),
        joinedload(Group.orders)
    ).filter(
        Group.category == CategoryType.DRINK,
        Group.is_closed == False,
        Group.deadline > now,
        _visible,
    ).order_by(Group.deadline.asc()).all()
    
    # 開放中的訂餐團
    meal_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner),
        joinedload(Group.orders)
    ).filter(
        Group.category == CategoryType.MEAL,
        Group.is_closed == False,
        Group.deadline > now,
        _visible,
    ).order_by(Group.deadline.asc()).all()
    
    # 開放中的團購團（新類型，可能不存在）
    try:
        groupbuy_groups = db.query(Group).options(
            joinedload(Group.store),
            joinedload(Group.owner),
            joinedload(Group.orders)
        ).filter(
            Group.category == CategoryType.GROUP_BUY,
            Group.is_closed == False,
            Group.deadline > now,
            _visible,
        ).order_by(Group.deadline.asc()).all()
    except Exception:
        db.rollback()
        groupbuy_groups = []
    
    # 我的進行中（開放團中，我是團主或已下單）
    my_active = []
    for g in (drink_groups + meal_groups + groupbuy_groups):
        mo = next((o for o in g.orders if o.user_id == user.id), None)
        if mo:
            my_active.append({"group": g, "status": mo.status.value})
        elif g.owner_id == user.id:
            my_active.append({"group": g, "status": "owner"})
    my_active.sort(key=lambda x: x["group"].deadline)

    # 已截止的團（最近 10 個）
    closed_groups = visible_closed_groups(db, user, now)
    
    # 超夯清單（全站熱門）
    hot_items = get_hot_items(db, limit=10)
    
    # 公告（V2.10.0：改讀 announcements 表）
    announcements = get_active_announcements(db)
    
    # 進行中的投票（V2.11.2 N-02：共用查詢，含可見性過濾）
    active_votes = visible_active_votes(db, user, now)
    
    # 店家列表（啟用中，根據部門過濾）
    from app.models.department import StoreDepartment
    all_stores = db.query(Store).filter(Store.is_personal != True).options(
        joinedload(Store.branches)
    ).filter(Store.is_active == True).order_by(Store.name).all()
    
    # 過濾用戶可見的店家
    def filter_visible_stores(stores_list):
        visible = []
        for s in stores_list:
            # 公開店家：所有人可見
            if s.is_public:
                visible.append(s)
                continue
            # 管理員可見所有
            if user.is_admin:
                visible.append(s)
                continue
            # 部門交集
            store_dept_ids = {sd.department_id for sd in db.query(StoreDepartment).filter(
                StoreDepartment.store_id == s.id
            ).all()}
            if store_dept_ids & set(user_dept_ids):
                visible.append(s)
        return visible
    
    stores = filter_visible_stores(all_stores)
    
    return templates.TemplateResponse("home.html", {
        "request": request,
        "user": user,
        "drink_groups": drink_groups,
        "meal_groups": meal_groups,
        "groupbuy_groups": groupbuy_groups,
        "closed_groups": closed_groups,
        "hot_items": hot_items,
        "announcements": announcements,
        "active_votes": active_votes,
        "stores": stores,
        "my_active": my_active,
        "now": now,
    })


@router.get("/home/groups")
async def home_groups_partial(request: Request, db: Session = Depends(get_db)):
    """首頁團單列表（HTMX partial）"""
    user = await get_current_user(request, db)
    
    # 使用台北時間（因為 deadline 存的是台北時間）
    taipei_tz = timezone(timedelta(hours=8))
    now = datetime.now(taipei_tz).replace(tzinfo=None)
    
    # V2.11.1 P0-05：這支是首頁在團截止時 htmx 自動刷新的片段，原本**完全沒有**
    # 可見性過濾，私密團與部門團會直接出現在所有人的首頁上。
    from app.services.visibility import visible_group_clause
    _visible = visible_group_clause(user)

    # 開放中的飲料團
    drink_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner),
        joinedload(Group.orders)
    ).filter(
        Group.category == CategoryType.DRINK,
        Group.is_closed == False,
        Group.deadline > now,
        _visible,
    ).order_by(Group.deadline.asc()).all()
    
    # 開放中的訂餐團
    meal_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner),
        joinedload(Group.orders)
    ).filter(
        Group.category == CategoryType.MEAL,
        Group.is_closed == False,
        Group.deadline > now,
        _visible,
    ).order_by(Group.deadline.asc()).all()
    
    # 開放中的團購團
    try:
        groupbuy_groups = db.query(Group).options(
            joinedload(Group.store),
            joinedload(Group.owner),
            joinedload(Group.orders)
        ).filter(
            Group.category == CategoryType.GROUP_BUY,
            Group.is_closed == False,
            Group.deadline > now,
            _visible,
        ).order_by(Group.deadline.asc()).all()
    except Exception:
        db.rollback()
        groupbuy_groups = []
    
    # 已截止的團（最近 10 個）
    closed_groups = visible_closed_groups(db, user, now)
    
    # 超夯清單
    hot_items = get_hot_items(db, limit=10)
    
    # 公告（V2.10.0：改讀 announcements 表）
    announcements = get_active_announcements(db)
    
    # 進行中的投票（V2.11.2 N-02：共用查詢，含可見性過濾）
    active_votes = visible_active_votes(db, user, now)
    
    # 取得用戶的部門 IDs
    from app.models.department import UserDepartment, StoreDepartment
    user_dept_ids = [ud.department_id for ud in db.query(UserDepartment).filter(
        UserDepartment.user_id == user.id
    ).all()]
    
    # 店家列表（根據部門過濾）
    all_stores = db.query(Store).filter(Store.is_personal != True).options(
        joinedload(Store.branches)
    ).filter(Store.is_active == True).order_by(Store.name).all()
    
    # 過濾用戶可見的店家
    visible_stores = []
    for s in all_stores:
        if s.is_public:
            visible_stores.append(s)
        elif user.is_admin:
            visible_stores.append(s)
        else:
            store_dept_ids = {sd.department_id for sd in db.query(StoreDepartment).filter(
                StoreDepartment.store_id == s.id
            ).all()}
            if store_dept_ids & set(user_dept_ids):
                visible_stores.append(s)
    stores = visible_stores
    
    return templates.TemplateResponse("partials/home_groups.html", {
        "request": request,
        "user": user,
        "drink_groups": drink_groups,
        "meal_groups": meal_groups,
        "groupbuy_groups": groupbuy_groups,
        "closed_groups": closed_groups,
        "hot_items": hot_items,
        "announcements": announcements,
        "active_votes": active_votes,
        "stores": stores,
    })


@router.get("/my/groups")
async def my_groups(request: Request, db: Session = Depends(get_db)):
    """我參與過的團單"""
    user = await get_current_user(request, db)
    
    # 我開的團 + 我有下單的團
    my_group_ids = db.query(Order.group_id).filter(Order.user_id == user.id).distinct()
    
    groups = db.query(Group).filter(
        or_(
            Group.owner_id == user.id,
            Group.id.in_(my_group_ids)
        )
    ).order_by(Group.created_at.desc()).all()
    
    return templates.TemplateResponse("my_groups.html", {
        "request": request,
        "user": user,
        "groups": groups,
    })


@router.get("/profile")
async def profile_page(request: Request, db: Session = Depends(get_db)):
    """個人資料頁面"""
    user = await get_current_user(request, db)
    
    # 統計資料
    order_count = db.query(Order).filter(Order.user_id == user.id).count()
    group_count = db.query(Group).filter(Group.owner_id == user.id).count()
    
    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": user,
        "order_count": order_count,
        "group_count": group_count,
    })


@router.get("/welcome")
async def welcome_page(request: Request, db: Session = Depends(get_db)):
    """首次登入歡迎頁面"""
    user = await get_current_user(request, db)
    
    return templates.TemplateResponse("welcome.html", {
        "request": request,
        "user": user,
    })


@router.post("/welcome")
async def complete_welcome(
    request: Request,
    nickname: str = Form(""),
    db: Session = Depends(get_db),
):
    """完成首次設定"""
    user = await get_current_user(request, db)
    
    # 設定暱稱（空白則用 LINE 名稱，但標記為已設定）
    nickname = nickname.strip()
    if nickname:
        user.nickname = nickname
    else:
        # 使用 LINE 名稱，但設定為相同值表示已完成設定
        user.nickname = user.display_name
    
    db.commit()
    
    return RedirectResponse(url="/home", status_code=302)


@router.post("/profile")
async def update_profile(
    request: Request,
    nickname: str = Form(...),
    db: Session = Depends(get_db),
):
    """更新個人資料"""
    from app.models.user import User
    
    user = await get_current_user(request, db)
    
    # 更新暱稱（系統顯示名）
    user.nickname = nickname.strip() if nickname else None
    db.commit()
    
    return RedirectResponse(url="/profile?success=1", status_code=302)


@router.get("/history")
async def history(request: Request, page: int = 1, db: Session = Depends(get_db)):
    """歷史團單列表"""
    user = await get_current_user(request, db)
    
    taipei_tz = timezone(timedelta(hours=8))
    now = datetime.now(taipei_tz).replace(tzinfo=None)
    
    # V2.11.1 P0-06：page<=0 在 PostgreSQL 會讓 OFFSET 變負數而 500
    page = max(1, page)
    per_page = 20
    offset = (page - 1) * per_page
    
    # V2.11.1 P0-05：歷史列表原本沒有可見性過濾
    from app.services.visibility import visible_group_clause
    _visible = visible_group_clause(user)
    
    # 總數
    total = db.query(Group).filter(
        or_(Group.is_closed == True, Group.deadline <= now),
        _visible,
    ).count()
    
    # 分頁查詢
    closed_groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner),
        joinedload(Group.orders)
    ).filter(
        or_(Group.is_closed == True, Group.deadline <= now),
        _visible,
    ).order_by(Group.deadline.desc()).offset(offset).limit(per_page).all()
    
    total_pages = (total + per_page - 1) // per_page
    
    return templates.TemplateResponse("history.html", {
        "request": request,
        "user": user,
        "groups": closed_groups,
        "page": page,
        "total_pages": total_pages,
        "total": total,
    })


@router.get("/my-orders")
async def my_orders(request: Request, page: int = 1, db: Session = Depends(get_db)):
    """我的訂單歷史"""
    user = await get_current_user(request, db)
    
    page = max(1, page)  # V2.11.1 P0-06：負數 OFFSET 在 PostgreSQL 會 500

    per_page = 20
    offset = (page - 1) * per_page
    
    # 總數
    total = db.query(Order).filter(Order.user_id == user.id).count()
    
    # 分頁查詢
    orders = db.query(Order).options(
        joinedload(Order.group).joinedload(Group.store)
    ).filter(
        Order.user_id == user.id
    ).order_by(Order.created_at.desc()).offset(offset).limit(per_page).all()
    
    total_pages = (total + per_page - 1) // per_page
    
    return templates.TemplateResponse("my_orders.html", {
        "request": request,
        "user": user,
        "orders": orders,
        "page": page,
        "total_pages": total_pages,
        "total": total,
    })


@router.get("/feedback")
async def feedback_page(request: Request, db: Session = Depends(get_db)):
    """問題回報頁面"""
    user = await get_current_user(request, db)
    
    from app.models.user import Feedback
    
    # 取得用戶的回報記錄
    feedbacks = db.query(Feedback).filter(
        Feedback.user_id == user.id
    ).order_by(Feedback.created_at.desc()).limit(10).all()
    
    return templates.TemplateResponse("feedback.html", {
        "request": request,
        "user": user,
        "feedbacks": feedbacks,
    })


@router.post("/feedback")
async def submit_feedback(
    request: Request,
    content: str = Form(...),
    db: Session = Depends(get_db)
):
    """提交問題回報"""
    user = await get_current_user(request, db)
    
    from app.models.user import Feedback
    
    feedback = Feedback(
        user_id=user.id,
        content=content.strip()[:1000]  # 限制 1000 字
    )
    db.add(feedback)
    db.commit()
    
    return RedirectResponse(url="/feedback?success=1", status_code=302)


@router.get("/favorites")
async def favorites_page(request: Request, db: Session = Depends(get_db)):
    """收藏店家頁面"""
    user = await get_current_user(request, db)
    
    from app.models.user import UserFavorite
    
    favorites = db.query(UserFavorite).options(
        joinedload(UserFavorite.store)
    ).filter(
        UserFavorite.user_id == user.id
    ).order_by(UserFavorite.created_at.desc()).all()
    
    return templates.TemplateResponse("favorites.html", {
        "request": request,
        "user": user,
        "favorites": favorites,
    })


@router.post("/favorites/{store_id}")
async def toggle_favorite(
    request: Request,
    store_id: int,
    db: Session = Depends(get_db)
):
    """切換收藏狀態"""
    user = await get_current_user(request, db)
    
    from sqlalchemy.exc import IntegrityError
    from app.models.store import Store
    from app.models.user import UserFavorite
    
    # V2.11.1 P1-06：原本不檢查店家，傳不存在的 id 會 500（外鍵）。
    # 個人代購店與停用店家也不該被收藏——它們不會出現在選店清單裡。
    store = db.query(Store).filter(
        Store.id == store_id,
        Store.is_active == True,
        Store.is_personal != True,
    ).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    # 檢查是否已收藏
    existing = db.query(UserFavorite).filter(
        UserFavorite.user_id == user.id,
        UserFavorite.store_id == store_id
    ).first()
    
    if existing:
        db.delete(existing)
        db.commit()
    else:
        # 連點兩下時靠唯一索引仲裁，重複就當作已收藏
        try:
            with db.begin_nested():
                db.add(UserFavorite(user_id=user.id, store_id=store_id))
            db.commit()
        except IntegrityError:
            db.rollback()
    
    if request.headers.get("HX-Request") == "true":
        return {"status": "removed" if existing else "added"}
    return RedirectResponse(url=f"/stores/{store_id}", status_code=302)


# ============ 用戶部門管理 ============

@router.get("/my-departments")
async def my_departments_page(request: Request, db: Session = Depends(get_db)):
    """我的部門頁面"""
    user = await get_current_user(request, db)
    
    from app.models.department import Department, UserDepartment
    
    # 已加入的部門
    my_departments = db.query(UserDepartment).filter(
        UserDepartment.user_id == user.id
    ).all()
    
    my_dept_ids = [ud.department_id for ud in my_departments]
    
    # 可加入的部門（公開且未加入）
    available_departments = db.query(Department).filter(
        Department.is_active == True,
        Department.is_public == True,
        ~Department.id.in_(my_dept_ids) if my_dept_ids else True
    ).all()
    
    return templates.TemplateResponse("my_departments.html", {
        "request": request,
        "user": user,
        "my_departments": my_departments,
        "available_departments": available_departments,
    })


@router.post("/my-departments/{dept_id}/join")
async def join_department(request: Request, dept_id: int, db: Session = Depends(get_db)):
    """加入部門"""
    user = await get_current_user(request, db)
    
    from app.models.department import Department, UserDepartment, DeptRole
    
    dept = db.query(Department).filter(
        Department.id == dept_id,
        Department.is_active == True,
        Department.is_public == True
    ).first()
    
    if not dept:
        raise HTTPException(status_code=404, detail="部門不存在或不開放加入")
    
    # 檢查是否已加入
    existing = db.query(UserDepartment).filter(
        UserDepartment.user_id == user.id,
        UserDepartment.department_id == dept_id
    ).first()
    
    if not existing:
        ud = UserDepartment(
            user_id=user.id,
            department_id=dept_id,
            role=DeptRole.MEMBER
        )
        db.add(ud)
        db.commit()
    
    return RedirectResponse(url="/my-departments?success=1", status_code=302)


@router.post("/my-departments/{dept_id}/leave")
async def leave_department(request: Request, dept_id: int, db: Session = Depends(get_db)):
    """離開部門"""
    user = await get_current_user(request, db)
    
    from app.models.department import UserDepartment
    
    ud = db.query(UserDepartment).filter(
        UserDepartment.user_id == user.id,
        UserDepartment.department_id == dept_id
    ).first()
    
    if ud:
        db.delete(ud)
        db.commit()
    
    return RedirectResponse(url="/my-departments?success=1", status_code=302)


@router.get("/stores/{store_id}")
async def store_view(store_id: int, request: Request, db: Session = Depends(get_db)):
    """前台店家詳情頁（只讀）"""
    from app.models.store import StoreTopping
    from app.models.menu import Menu
    
    user = await get_current_user(request, db)
    
    store = db.query(Store).options(
        joinedload(Store.branches),
        joinedload(Store.toppings),
        joinedload(Store.options)
    ).filter(Store.id == store_id, Store.is_active == True).first()
    
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    # 取得該店家目前有開的團
    from app.models.group import Group
    taipei_tz = timezone(timedelta(hours=8))
    now = datetime.now(taipei_tz).replace(tzinfo=None)
    
    active_groups = db.query(Group).options(
        joinedload(Group.owner),
        joinedload(Group.orders)
    ).filter(
        Group.store_id == store_id,
        Group.is_closed == False,
        Group.deadline > now,
        Group.is_public == True,
    ).order_by(Group.deadline.asc()).all()
    
    # 檢查是否已收藏
    from app.models.user import UserFavorite
    is_favorited = db.query(UserFavorite).filter(
        UserFavorite.user_id == user.id,
        UserFavorite.store_id == store_id
    ).first() is not None
    
    # 取得啟用中的菜單
    active_menu = db.query(Menu).filter(
        Menu.store_id == store_id,
        Menu.is_active == True
    ).first()
    
    return templates.TemplateResponse("store_view.html", {
        "request": request,
        "user": user,
        "store": store,
        "active_groups": active_groups,
        "is_favorited": is_favorited,
        "active_menu": active_menu,
    })


@router.get("/stores/{store_id}/menu")
async def store_menu_view(store_id: int, request: Request, db: Session = Depends(get_db)):
    """前台店家菜單頁面（只讀）"""
    from app.models.menu import Menu, MenuCategory, MenuItem
    
    user = await get_current_user(request, db)
    
    store = db.query(Store).filter(Store.id == store_id, Store.is_active == True).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    # 取得啟用中的菜單
    menu = db.query(Menu).filter(
        Menu.store_id == store_id,
        Menu.is_active == True
    ).first()
    
    if not menu:
        raise HTTPException(status_code=404, detail="此店家尚無菜單")
    
    # 取得菜單分類和品項
    categories = db.query(MenuCategory).filter(
        MenuCategory.menu_id == menu.id
    ).order_by(MenuCategory.sort_order).all()
    
    return templates.TemplateResponse("store_menu.html", {
        "request": request,
        "user": user,
        "store": store,
        "menu": menu,
        "categories": categories,
    })


@router.get("/recommend")
async def recommend_store_page(request: Request, db: Session = Depends(get_db)):
    """推薦店家頁面"""
    user = await get_current_user(request, db)
    
    from app.models.user import StoreRecommendation
    
    # 取得我的推薦紀錄
    my_recommendations = db.query(StoreRecommendation).filter(
        StoreRecommendation.user_id == user.id
    ).order_by(StoreRecommendation.created_at.desc()).all()
    
    return templates.TemplateResponse("recommend.html", {
        "request": request,
        "user": user,
        "recommendations": my_recommendations,
    })


@router.post("/recommend")
async def submit_recommendation(
    request: Request,
    store_name: str = Form(...),
    category: str = Form(...),
    menu_url: str = Form(None),
    note: str = Form(None),
    menu_image: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    """提交店家推薦"""
    user = await get_current_user(request, db)
    
    # V2.11.1 P0-06：menu_url 會被輸出成後台推薦列表與匯入頁的 href，
    # 核准後又複製到 store.website_url 出現在所有人看得到的頁面。必須驗協定。
    from app.services.validation import clean_http_url
    menu_url = clean_http_url(menu_url, field="菜單網址")
    
    from app.models.user import StoreRecommendation
    from app.config import get_settings
    
    menu_image_url = None
    
    # 處理圖片上傳到 Cloudinary
    if menu_image and menu_image.filename:
        settings = get_settings()
        if settings.cloudinary_cloud_name:
            try:
                import cloudinary
                import cloudinary.uploader
                
                cloudinary.config(
                    cloud_name=settings.cloudinary_cloud_name,
                    api_key=settings.cloudinary_api_key,
                    api_secret=settings.cloudinary_api_secret
                )
                
                contents = await menu_image.read()
                result = cloudinary.uploader.upload(
                    contents,
                    folder="sela/recommendations",
                    resource_type="image"
                )
                menu_image_url = result.get("secure_url")
            except Exception as e:
                print(f"Cloudinary upload error: {e}")
    
    recommendation = StoreRecommendation(
        user_id=user.id,
        store_name=store_name.strip(),
        category=category,
        menu_url=menu_url.strip() if menu_url else None,
        menu_image_url=menu_image_url,
        note=note.strip() if note else None,
    )
    db.add(recommendation)
    db.commit()
    
    return RedirectResponse(url="/recommend?success=1", status_code=302)


@router.get("/stats")
async def stats_page(
    request: Request, 
    period: str = "month",
    start_date: str = None,
    end_date: str = None,
    db: Session = Depends(get_db)
):
    """個人消費統計頁面"""
    from sqlalchemy import func, extract, case
    from app.models.order import Order, OrderItem, OrderStatus
    from app.models.group import Group
    from app.models.store import Store, CategoryType
    from decimal import Decimal
    
    user = await get_current_user(request, db)
    
    # 台北時區
    taipei_tz = timezone(timedelta(hours=8))
    now = datetime.now(taipei_tz).replace(tzinfo=None)
    today = now.date()
    
    # 計算時間範圍
    if period == "custom" and start_date and end_date:
        try:
            date_start = datetime.strptime(start_date, "%Y-%m-%d")
            date_end = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        except:
            date_start = datetime(today.year, today.month, 1)
            date_end = now
            period = "month"
    elif period == "last_month":
        # 過去一個月（30天）
        date_start = now - timedelta(days=30)
        date_end = now
    elif period == "month":
        # 這個月
        date_start = datetime(today.year, today.month, 1)
        date_end = now
    elif period == "3months":
        # 過去三個月
        date_start = now - timedelta(days=90)
        date_end = now
    elif period == "year":
        # 今年
        date_start = datetime(today.year, 1, 1)
        date_end = now
    elif period == "all":
        # 全部
        date_start = datetime(2020, 1, 1)
        date_end = now
    else:
        # 預設：這個月
        date_start = datetime(today.year, today.month, 1)
        date_end = now
    
    # V2.10.2：date_start/date_end 是台北牆上時間（日曆邊界才符合使用者心智模型，
    # 且模板的「統計期間」直接顯示它們）；但 Order/Group.created_at 存的是 UTC，
    # 所以查詢另用一組轉換後的值。原本直接拿台北值去比，「本月」會漏掉每月前
    # 8 小時的資料（台北 9/1 00:00-08:00 開的團不算進本月）。坑 #25 的反向案例。
    from app.models.group import taipei_to_utc
    query_start = taipei_to_utc(date_start)
    query_end = taipei_to_utc(date_end)
    
    # 基礎過濾條件
    base_filters = [
        Order.user_id == user.id,
        Order.status == OrderStatus.SUBMITTED,
        Order.created_at >= query_start,
        Order.created_at <= query_end
    ]
    
    # ===== 基本統計 =====
    total_orders = db.query(Order).filter(*base_filters).count()
    
    # 計算總金額：從 OrderItem 計算 (unit_price * quantity)
    total_amount = db.query(
        func.sum(OrderItem.unit_price * OrderItem.quantity)
    ).select_from(OrderItem).join(
        Order, OrderItem.order_id == Order.id
    ).filter(*base_filters).scalar() or Decimal("0")
    
    avg_amount = total_amount / total_orders if total_orders > 0 else Decimal("0")
    
    # ===== 按類別統計 =====
    category_stats = {}
    for cat in [CategoryType.DRINK, CategoryType.MEAL, CategoryType.GROUP_BUY]:
        cat_orders = db.query(Order).join(
            Group, Order.group_id == Group.id
        ).filter(
            *base_filters,
            Group.category == cat
        ).count()
        cat_amount = db.query(
            func.sum(OrderItem.unit_price * OrderItem.quantity)
        ).select_from(OrderItem).join(
            Order, OrderItem.order_id == Order.id
        ).join(
            Group, Order.group_id == Group.id
        ).filter(
            *base_filters,
            Group.category == cat
        ).scalar() or Decimal("0")
        category_stats[cat.value] = {
            "orders": cat_orders,
            "amount": cat_amount
        }
    
    # ===== 最愛店家 TOP 5 =====
    favorite_stores = db.query(
        Store.id,
        Store.name,
        Store.logo_url,
        func.count(func.distinct(Order.id)).label("order_count"),
        func.sum(OrderItem.unit_price * OrderItem.quantity).label("total_spent")
    ).select_from(OrderItem).join(
        Order, OrderItem.order_id == Order.id
    ).join(
        Group, Order.group_id == Group.id
    ).join(
        Store, Group.store_id == Store.id
    ).filter(
        *base_filters
    ).group_by(Store.id).order_by(func.count(func.distinct(Order.id)).desc()).limit(5).all()
    
    # ===== 最常點的品項 TOP 10 =====
    favorite_items = db.query(
        OrderItem.item_name,
        func.sum(OrderItem.quantity).label("total_qty"),
        func.sum(OrderItem.unit_price * OrderItem.quantity).label("total_spent")
    ).select_from(OrderItem).join(
        Order, OrderItem.order_id == Order.id
    ).filter(
        *base_filters
    ).group_by(OrderItem.item_name).order_by(func.sum(OrderItem.quantity).desc()).limit(10).all()
    
    # ===== 最常跟團的團主 TOP 5 =====
    from app.models.user import User
    favorite_owners = db.query(
        User.id,
        User.display_name,
        User.nickname,
        User.picture_url,
        func.count(Order.id).label("follow_count")
    ).select_from(Order).join(
        Group, Order.group_id == Group.id
    ).join(
        User, Group.owner_id == User.id
    ).filter(
        *base_filters,
        Group.owner_id != user.id  # 排除自己開的團
    ).group_by(User.id).order_by(func.count(Order.id).desc()).limit(5).all()
    
    # ===== 開團統計 =====
    groups_created = db.query(Group).filter(
        Group.owner_id == user.id,
        Group.created_at >= query_start,
        Group.created_at <= query_end
    ).count()
    
    # ===== 抽獎統計 =====
    # 中獎次數
    lucky_wins = db.query(Group).filter(
        Group.lucky_winner_ids.contains(str(user.id)),
        Group.created_at >= query_start,
        Group.created_at <= query_end
    ).count()
    
    # 被請客次數（在有 treat_user_id 的團中有訂單）
    treated_count = db.query(Order).join(
        Group, Order.group_id == Group.id
    ).filter(
        *base_filters,
        Group.treat_user_id.isnot(None),
        Group.treat_user_id != user.id
    ).count()
    
    # 請客次數
    treat_count = db.query(Group).filter(
        Group.treat_user_id == user.id,
        Group.created_at >= query_start,
        Group.created_at <= query_end
    ).count()
    
    # ===== 月度趨勢（最近6個月）=====
    # V2.10.3：月份桶邏輯見 month_buckets()（舊寫法會重複/跳月）
    monthly_trend = []
    for bucket_year, bucket_month in month_buckets(today):
        month_start = datetime(bucket_year, bucket_month, 1)
        if bucket_month == 12:
            month_end = datetime(bucket_year + 1, 1, 1) - timedelta(seconds=1)
        else:
            month_end = datetime(bucket_year, bucket_month + 1, 1) - timedelta(seconds=1)
        
        month_amount = db.query(
            func.sum(OrderItem.unit_price * OrderItem.quantity)
        ).select_from(OrderItem).join(
            Order, OrderItem.order_id == Order.id
        ).filter(
            Order.user_id == user.id,
            Order.status == OrderStatus.SUBMITTED,
            # 月份邊界是台北日曆，created_at 是 UTC（坑 #25），要轉
            Order.created_at >= taipei_to_utc(month_start),
            Order.created_at <= taipei_to_utc(month_end)
        ).scalar() or Decimal("0")
        
        monthly_trend.append({
            "month": month_start.strftime("%m月"),
            "amount": int(month_amount)
        })
    
    # ===== 時段與星期分析 =====
    # V2.10.3：created_at 是 UTC，extract 出來的小時與星期也是 UTC。午餐團多在
    # 台北 09:00-12:00＝UTC 01:00-04:00，原本「最常下單時段」會顯示 2:00 或 3:00。
    # 一次撈出 (UTC 星期, UTC 小時) 的分布，再於 Python 位移 +8 小時；跨過 24 點
    # 時星期要進一天，所以兩者必須一起算，不能各自 group by。
    # 在 Python 位移而非用 SQL 的 interval，是為了不綁資料庫方言，煙霧測試才能在
    # SQLite 上跑（坑 #25 的同一族問題）。
    slot_stats = db.query(
        extract('dow', Order.created_at).label('dow'),
        extract('hour', Order.created_at).label('hour'),
        func.count(Order.id).label('count')
    ).filter(
        *base_filters
    ).group_by(
        extract('dow', Order.created_at),
        extract('hour', Order.created_at)
    ).all()
    
    hour_counts = {}
    weekday_counts = {}
    for row in slot_stats:
        utc_hour = int(row.hour)
        utc_dow = int(row.dow)
        count = int(row.count)
        taipei_dow, taipei_hour = taipei_slot(utc_dow, utc_hour)
        hour_counts[taipei_hour] = hour_counts.get(taipei_hour, 0) + count
        weekday_counts[taipei_dow] = weekday_counts.get(taipei_dow, 0) + count
    
    peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else 12
    
    weekday_names = ['日', '一', '二', '三', '四', '五', '六']
    peak_weekday = max(weekday_counts, key=weekday_counts.get) if weekday_counts else 1
    
    # ===== 甜度冰塊偏好（飲料）=====
    sugar_stats = db.query(
        OrderItem.sugar,
        func.count(OrderItem.id).label('count')
    ).select_from(OrderItem).join(
        Order, OrderItem.order_id == Order.id
    ).join(
        Group, Order.group_id == Group.id
    ).filter(
        *base_filters,
        Group.category == CategoryType.DRINK,
        OrderItem.sugar.isnot(None)
    ).group_by(OrderItem.sugar).order_by(func.count(OrderItem.id).desc()).limit(3).all()
    
    ice_stats = db.query(
        OrderItem.ice,
        func.count(OrderItem.id).label('count')
    ).select_from(OrderItem).join(
        Order, OrderItem.order_id == Order.id
    ).join(
        Group, Order.group_id == Group.id
    ).filter(
        *base_filters,
        Group.category == CategoryType.DRINK,
        OrderItem.ice.isnot(None)
    ).group_by(OrderItem.ice).order_by(func.count(OrderItem.id).desc()).limit(3).all()
    
    # ===== 加料偏好 =====
    from app.models.order import OrderItemTopping
    topping_stats = db.query(
        OrderItemTopping.topping_name,
        func.count(OrderItemTopping.id).label('count')
    ).select_from(OrderItemTopping).join(
        OrderItem, OrderItemTopping.order_item_id == OrderItem.id
    ).join(
        Order, OrderItem.order_id == Order.id
    ).filter(
        *base_filters
    ).group_by(OrderItemTopping.topping_name).order_by(func.count(OrderItemTopping.id).desc()).limit(5).all()
    
    return templates.TemplateResponse("stats.html", {
        "request": request,
        "user": user,
        "period": period,
        "start_date": start_date or date_start.strftime("%Y-%m-%d"),
        "end_date": end_date or date_end.strftime("%Y-%m-%d"),
        "date_start": date_start,
        "date_end": date_end,
        # 基本統計
        "total_orders": total_orders,
        "total_amount": total_amount,
        "avg_amount": avg_amount,
        # 分類統計
        "category_stats": category_stats,
        # 排行榜
        "favorite_stores": favorite_stores,
        "favorite_items": favorite_items,
        "favorite_owners": favorite_owners,
        # 開團統計
        "groups_created": groups_created,
        # 趣味統計
        "lucky_wins": lucky_wins,
        "treated_count": treated_count,
        "treat_count": treat_count,
        # 趨勢
        "monthly_trend": monthly_trend,
        # 時段
        "peak_hour": int(peak_hour),
        "peak_weekday": weekday_names[int(peak_weekday)],
        # 偏好
        "sugar_stats": sugar_stats,
        "ice_stats": ice_stats,
        "topping_stats": topping_stats,
    })
