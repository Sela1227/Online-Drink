import json
from fastapi import APIRouter, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.models.group import Group, taipei_now
from app.models.order import Order, OrderItem, OrderStatus
from app.models.store import CategoryType, Store
from app.models.user import Announcement
from app.services.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
from app.templating import register_filters as _register_filters  # V2.15.1：money/taipei 共用
_register_filters(templates.env)

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


HOME_ANNOUNCEMENT_LIMIT = 5   # V2.17.0：首頁只展開第一則，其餘「還有 N 則」點開
HOME_VOTE_LIMIT = 4


def visible_stores_for(db: Session, user):
    """使用者看得到的店家（啟用中、非個人代購店；公開或部門交集；管理員全看）。

    V2.17.0：原本 /home 與 /home/groups 各複製一份逐店查部門（N+1），店家分頁再要
    第三份。抽成共用，部門關係一次撈完。
    """
    from app.models.department import UserDepartment, StoreDepartment
    all_stores = db.query(Store).options(joinedload(Store.branches)).filter(
        Store.is_personal != True,
        Store.is_active == True,
    ).order_by(Store.name).all()
    if user.is_admin:
        return all_stores
    user_dept_ids = {ud.department_id for ud in db.query(UserDepartment).filter(
        UserDepartment.user_id == user.id
    ).all()}
    store_depts: dict[int, set[int]] = {}
    for sd in db.query(StoreDepartment).all():
        store_depts.setdefault(sd.store_id, set()).add(sd.department_id)
    return [s for s in all_stores if s.is_public or (store_depts.get(s.id, set()) & user_dept_ids)]


def _open_groups(db: Session, user, now):
    """開放中且看得到的團，依截止時間近→遠（不分類）。"""
    from app.services.visibility import visible_group_clause
    return db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner),
        joinedload(Group.orders).joinedload(Order.items),
    ).filter(
        Group.is_closed == False,
        Group.deadline > now,
        visible_group_clause(user),
    ).order_by(Group.deadline.asc()).all()


def my_status_in(group, user) -> str:
    """我在這個團的狀態：submitted／unsent（購物車有東西沒送出）／none（還沒點）。"""
    from app.models.order import OrderStatus
    mo = next((o for o in group.orders if o.user_id == user.id), None)
    if mo is None:
        return "none"
    if mo.status == OrderStatus.SUBMITTED:
        return "submitted"
    return "unsent" if len(mo.items) > 0 else "none"


def split_home_groups(groups, user):
    """首頁分區（V2.17.0 IA）：

    「要你處理的」只放真的需要你動手的團——
      (a) 你是團主、而且（你自己還沒送出，或有人點了還沒送出要催）
      (b) 你購物車有東西但還沒送出
    其餘開放中的團一律放「開放中」，依截止排序，一個團只出現一次（不再分飲料／餐廳／團購）。
    「還沒點」的團不算要處理——每個開放的團都會是「還沒點」，全放進去就等於沒分。
    """
    attention, others = [], []
    for g in groups:
        st = my_status_in(g, user)
        is_owner = g.owner_id == user.id
        entry = {"group": g, "status": st, "is_owner": is_owner}
        if is_owner and (st != "submitted" or g.pending_count > 0):
            attention.append(entry)
        elif st == "unsent":
            attention.append(entry)
        else:
            others.append(entry)
    return attention, others


def _home_context(request: Request, db: Session, user):
    now = taipei_now()
    groups = _open_groups(db, user, now)
    attention, open_groups = split_home_groups(groups, user)
    announcements = get_active_announcements(db, limit=HOME_ANNOUNCEMENT_LIMIT)
    active_votes = visible_active_votes(db, user, now, limit=HOME_VOTE_LIMIT)
    # 投票卡要顯示「我投過了沒」
    from app.models.vote import VoteRecord, VoteOption
    voted_ids = {
        vid for (vid,) in db.query(VoteOption.vote_id).join(VoteRecord, VoteRecord.option_id == VoteOption.id)
        .filter(VoteRecord.user_id == user.id, VoteOption.vote_id.in_([v.id for v in active_votes]))
        .distinct().all()
    } if active_votes else set()
    return {
        "request": request,
        "user": user,
        "attention": attention,
        "open_groups": open_groups,
        "announcements": announcements,
        "active_votes": active_votes,
        "voted_ids": voted_ids,
        "now": now,
    }


@router.get("/home")
async def home(request: Request, db: Session = Depends(get_db)):
    """首頁「今天」（V2.17.0 IA）：公告一則＋投票卡（有才出現）＋要你處理的＋開放中"""
    user = await get_current_user(request, db)
    ctx = _home_context(request, db, user)
    # V2.25.0：管理員首頁最上面看得到新推薦（原本要「我的 → 管理後台 → 推薦」才看得到）
    ctx["new_rec_count"], ctx["new_recs"] = pending_recommendations(db, user)
    return templates.TemplateResponse(request, "home.html", ctx)


def pending_recommendations(db, user, limit: int = 3):
    """V2.25.0：待審核推薦（只給管理員）→ (總數, 最新 limit 筆)"""
    if not user or not user.is_admin:
        return 0, []
    from app.models.user import StoreRecommendation
    q = db.query(StoreRecommendation).filter(StoreRecommendation.status == "pending")
    n = q.count()
    if not n:
        return 0, []
    return n, q.options(joinedload(StoreRecommendation.user)).order_by(StoreRecommendation.created_at.desc()).limit(limit).all()


@router.get("/home/groups")
async def home_groups_partial(request: Request, db: Session = Depends(get_db)):
    """首頁片段（倒數歸零時 htmx 自動刷新）。與 /home 共用同一個 context，不再各寫一份查詢。"""
    user = await get_current_user(request, db)
    return templates.TemplateResponse(request, "partials/home_groups.html", _home_context(request, db, user))


@router.get("/my/groups")
async def my_groups():
    """V2.17.0：併入紀錄頁「我開的」"""
    return RedirectResponse(url="/records?tab=groups", status_code=302)


@router.get("/profile")
async def profile_page(request: Request, db: Session = Depends(get_db)):
    """個人資料頁面"""
    user = await get_current_user(request, db)
    
    # 統計資料
    from app.models.order import OrderStatus
    order_count = db.query(Order).filter(Order.user_id == user.id, Order.status == OrderStatus.SUBMITTED).count()
    group_count = db.query(Group).filter(Group.owner_id == user.id).count()
    # V2.17.0：部門顯示在個人卡上（✎ 進既有的我的部門頁）
    from app.models.department import UserDepartment, Department
    dept_names = [d.name for d in db.query(Department).join(
        UserDepartment, UserDepartment.department_id == Department.id
    ).filter(UserDepartment.user_id == user.id).order_by(Department.name).all()]
    
    return templates.TemplateResponse(request, "profile.html", {
        "request": request,
        "user": user,
        "order_count": order_count,
        "group_count": group_count,
        "dept_names": dept_names,
        "new_rec_count": pending_recommendations(db, user, limit=0)[0],  # V2.25.0
        "my_cities": __import__("app.services.city", fromlist=["parse_user_cities"]).parse_user_cities(user.cities),  # V2.26.0
    })


@router.get("/profile/cities")
async def profile_cities_page(request: Request, db: Session = Depends(get_db)):
    """V2.26.0：我會訂的縣市"""
    user = await get_current_user(request, db)
    from app.services.city import CITY_GROUPS, parse_user_cities
    counts = {}
    for s in visible_stores_for(db, user):
        if s.city:
            counts[s.city] = counts.get(s.city, 0) + 1
    return templates.TemplateResponse(request, "profile_cities.html", {
        "request": request, "user": user, "city_groups": CITY_GROUPS,
        "my_cities": parse_user_cities(user.cities), "city_counts": counts,
    })


@router.post("/profile/cities")
async def profile_cities_save(request: Request, db: Session = Depends(get_db)):
    """V2.26.0：只收 22 縣市的正式名稱；其他值丟掉。空＝全部顯示（存 NULL）"""
    user = await get_current_user(request, db)
    from app.services.city import ALL_CITIES
    form = await request.form()
    picked = [c for c in ALL_CITIES if c in set(form.getlist("cities"))]  # 依固定順序、去重
    user.cities = json.dumps(picked, ensure_ascii=False) if picked else None
    db.commit()
    return RedirectResponse(url="/stores", status_code=302)


@router.get("/welcome")
async def welcome_page(request: Request, db: Session = Depends(get_db)):
    """首次登入歡迎頁面"""
    user = await get_current_user(request, db)
    
    return templates.TemplateResponse(request, "welcome.html", {
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
async def history():
    """V2.17.0：歷史團單併入紀錄頁（我點的／我開的）"""
    return RedirectResponse(url="/records", status_code=302)


@router.get("/my-orders")
async def my_orders():
    """V2.17.0：我的訂單併入紀錄頁「我點的」"""
    return RedirectResponse(url="/records", status_code=302)


RECORDS_PER_PAGE = 20
RECORDS_TABS = ("orders", "groups", "stats")


@router.get("/records")
async def records_page(request: Request, tab: str = "orders", page: int = 1, db: Session = Depends(get_db)):
    """紀錄分頁（V2.17.0 IA 根頁）：我點的｜我開的｜統計。
    原本「我的訂單」「歷史團單」「我參與過的團」「消費統計」四頁散在個人頁與首頁底下，合成一頁三分頁。
    統計分頁沿用 /stats（期間篩選的網址都在那裡），只是加上同一列分頁 chip。
    """
    user = await get_current_user(request, db)
    if tab not in RECORDS_TABS:
        tab = "orders"
    if tab == "stats":
        return RedirectResponse(url="/stats", status_code=302)
    page = max(1, page)  # V2.11.1 P0-06：負數 OFFSET 在 PostgreSQL 會 500
    offset = (page - 1) * RECORDS_PER_PAGE
    now = taipei_now()
    ctx = {"request": request, "user": user, "tab": tab, "page": page}

    if tab == "orders":
        base = db.query(Order).options(
            joinedload(Order.group).joinedload(Group.store),
            joinedload(Order.items),
        ).join(Group, Order.group_id == Group.id).filter(Order.user_id == user.id)
        _open = (Group.is_closed == False) & (Group.deadline > now)
        # 進行中的不分頁（最多就今天那幾個），之前的分頁
        active = base.filter(_open).order_by(Group.deadline.asc()).all()
        past_q = base.filter(~_open)
        total = past_q.count()
        past = past_q.order_by(Order.created_at.desc()).offset(offset).limit(RECORDS_PER_PAGE).all()
        ctx.update({"active_orders": active, "past_orders": past, "total": total,
                    "total_pages": (total + RECORDS_PER_PAGE - 1) // RECORDS_PER_PAGE})
    else:
        q = db.query(Group).options(
            joinedload(Group.store), joinedload(Group.orders).joinedload(Order.items),
        ).filter(Group.owner_id == user.id)
        total = q.count()
        groups = q.order_by(Group.created_at.desc()).offset(offset).limit(RECORDS_PER_PAGE).all()
        ctx.update({"groups": groups, "total": total,
                    "total_pages": (total + RECORDS_PER_PAGE - 1) // RECORDS_PER_PAGE})
    return templates.TemplateResponse(request, "records.html", ctx)


@router.get("/feedback")
async def feedback_page(request: Request, db: Session = Depends(get_db)):
    """問題回報頁面"""
    user = await get_current_user(request, db)
    
    from app.models.user import Feedback
    
    # 取得用戶的回報記錄
    feedbacks = db.query(Feedback).filter(
        Feedback.user_id == user.id
    ).order_by(Feedback.created_at.desc()).limit(10).all()
    
    return templates.TemplateResponse(request, "feedback.html", {
        "request": request,
        "user": user,
        "feedbacks": feedbacks,
        "prefill": (request.query_params.get("prefill") or "")[:300],  # V2.16.0 A-8：從團頁「回報價格不符」帶入
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
async def favorites_page():
    """V2.17.0：收藏店家頁併入店家分頁的「只看收藏」，舊網址轉址（書籤不壞）"""
    return RedirectResponse(url="/stores?fav=1", status_code=302)


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
    
    return templates.TemplateResponse(request, "my_departments.html", {
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


def store_catalog_context(db: Session, user):
    """店家分頁的資料（V2.17.0）：看得到的店家＋收藏＋全體開團次數／上次開團（排序用）。
    與開團選店覆蓋層同一套排序鍵（localStorage `sela_store_sort`），資料形狀也對齊。
    """
    from app.models.user import UserFavorite
    stores = visible_stores_for(db, user)
    favorite_ids = [f.store_id for f in db.query(UserFavorite).filter(UserFavorite.user_id == user.id).all()]
    group_counts = dict(
        db.query(Group.store_id, func.count(Group.id)).filter(Group.store_id.isnot(None)).group_by(Group.store_id).all()
    )
    _last = db.query(Group.store_id, func.max(Group.created_at)).filter(Group.store_id.isnot(None)).group_by(Group.store_id).all()
    last_group_at = {sid: (to_taipei_time(dt).strftime("%m/%d") if dt else "") for sid, dt in _last}
    last_group_ts = {sid: (dt.timestamp() if dt else 0) for sid, dt in _last}
    payload = [{
        "id": s.id,
        "name": s.name,
        "category": s.category.value if s.category else "meal",
        "logo_url": s.logo_url or "",
        "group_count": group_counts.get(s.id, 0),
        "last_group": last_group_at.get(s.id, ""),
        "last_ts": last_group_ts.get(s.id, 0),
        # V2.26.0：縣市篩選、最新加入排序
        "city": s.city or "",
        "created_ts": s.created_at.timestamp() if s.created_at else 0,
        "created": to_taipei_time(s.created_at).strftime("%Y/%m/%d") if s.created_at else "",
    } for s in stores]
    from app.services.city import parse_user_cities
    return {"stores_json": payload, "favorite_ids": favorite_ids, "store_total": len(stores),
            "my_cities": parse_user_cities(user.cities)}


@router.get("/stores")
async def stores_page(request: Request, fav: int = 0, db: Session = Depends(get_db)):
    """店家分頁（V2.17.0 IA 新根頁）：搜尋、分類、只看收藏、排序；底部推薦入口"""
    user = await get_current_user(request, db)
    ctx = store_catalog_context(db, user)
    ctx.update({"request": request, "user": user, "fav_only": bool(fav)})
    return templates.TemplateResponse(request, "stores.html", ctx)


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
    
    return templates.TemplateResponse(request, "store_view.html", {
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
    
    return templates.TemplateResponse(request, "store_menu.html", {
        "request": request,
        "user": user,
        "store": store,
        "menu": menu,
        "categories": categories,
    })


RECOMMEND_MAX_PHOTOS = 5  # V2.16.2：推薦店家的菜單照片上限


@router.get("/recommend")
async def recommend_store_page(request: Request, db: Session = Depends(get_db)):
    """推薦店家頁面"""
    user = await get_current_user(request, db)
    
    from app.models.user import StoreRecommendation
    
    # 取得我的推薦紀錄
    my_recommendations = db.query(StoreRecommendation).filter(
        StoreRecommendation.user_id == user.id
    ).order_by(StoreRecommendation.created_at.desc()).all()
    
    return templates.TemplateResponse(request, "recommend.html", {
        "request": request,
        "user": user,
        "recommendations": my_recommendations,
        "max_photos": RECOMMEND_MAX_PHOTOS,
    })


@router.post("/recommend")
async def submit_recommendation(
    request: Request,
    store_name: str = Form(...),
    category: str = Form(...),
    menu_url: str = Form(None),
    note: str = Form(None),
    menu_image: list[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """提交店家推薦。V2.16.2：菜單照片可多張（最多 5），改走 upload_service（審核 P2-F5）"""
    user = await get_current_user(request, db)
    
    # V2.11.1 P0-06：menu_url 會被輸出成後台推薦列表與匯入頁的 href，
    # 核准後又複製到 store.website_url 出現在所有人看得到的頁面。必須驗協定。
    from app.services.validation import clean_http_url
    menu_url = clean_http_url(menu_url, field="菜單網址")
    
    from app.models.user import StoreRecommendation
    from app.services.upload_service import upload_image
    files = [f for f in (menu_image or []) if f and f.filename]
    if len(files) > RECOMMEND_MAX_PHOTOS:
        raise HTTPException(status_code=400, detail=f"菜單照片最多 {RECOMMEND_MAX_PHOTOS} 張")
    # 一張失敗整筆 400（格式／大小／Cloudinary），不會留下半筆推薦
    urls = []
    for f in files:
        u = await upload_image(f, folder="sela/recommendations", max_size=1600)
        if u:
            urls.append(u)

    recommendation = StoreRecommendation(
        user_id=user.id,
        store_name=store_name.strip(),
        category=category,
        menu_url=menu_url.strip() if menu_url else None,
        menu_image_url=urls[0] if urls else None,
        menu_image_urls=json.dumps(urls) if urls else None,
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
    
    return templates.TemplateResponse(request, "stats.html", {
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
