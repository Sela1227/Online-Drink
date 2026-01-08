from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from pydantic import ValidationError
from datetime import datetime, timedelta, timezone
import json

from app.database import get_db
from app.config import get_settings
from app.models.store import Store, StoreOption, CategoryType, OptionType
from app.models.menu import Menu, MenuCategory, MenuItem, ItemOption
from app.models.group import Group
from app.schemas.menu import MenuImport, FullImport, MenuContent
from app.services.auth import get_admin_user
from app.services.import_service import import_store_and_menu, import_menu

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()

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


@router.get("")
async def admin_home(request: Request, db: Session = Depends(get_db)):
    """後台首頁"""
    user = await get_admin_user(request, db)
    
    from app.models.user import User, Announcement
    from datetime import datetime, timedelta
    
    store_count = db.query(Store).count()
    group_count = db.query(Group).count()
    user_count = db.query(User).count()
    
    # 計算在線人數
    online_threshold = datetime.utcnow() - timedelta(minutes=30)
    online_count = db.query(User).filter(
        User.last_active_at != None,
        User.last_active_at > online_threshold
    ).count()
    
    # 取得公告
    from app.models.user import SystemSetting, Feedback
    settings_row = db.query(SystemSetting).first()
    announcement = settings_row.announcement if settings_row else None
    
    # 公告數量
    announcement_count = db.query(Announcement).count()
    has_active_announcement = db.query(Announcement).filter(Announcement.is_active == True).first() is not None
    
    # 待處理的問題回報數
    feedback_count = db.query(Feedback).filter(Feedback.status == "pending").count()
    
    # 部門數量
    from app.models.department import Department
    department_count = db.query(Department).filter(Department.is_active == True).count()
    
    # 待審核推薦數
    from app.models.user import StoreRecommendation
    recommendation_count = db.query(StoreRecommendation).filter(
        StoreRecommendation.status == "pending"
    ).count()
    
    return templates.TemplateResponse("admin/index.html", {
        "request": request,
        "user": user,
        "store_count": store_count,
        "group_count": group_count,
        "user_count": user_count,
        "online_count": online_count,
        "announcement": announcement,
        "announcement_count": announcement_count,
        "has_active_announcement": has_active_announcement,
        "feedback_count": feedback_count,
        "department_count": department_count,
        "recommendation_count": recommendation_count,
    })


@router.get("/stores")
async def store_list(request: Request, db: Session = Depends(get_db)):
    """店家列表"""
    user = await get_admin_user(request, db)
    
    stores = db.query(Store).options(
        joinedload(Store.branches)
    ).order_by(Store.created_at.desc()).all()
    
    return templates.TemplateResponse("admin/stores.html", {
        "request": request,
        "user": user,
        "stores": stores,
    })


@router.get("/stores/{store_id}/menus")
async def menu_list(store_id: int, request: Request, db: Session = Depends(get_db)):
    """菜單版本列表"""
    user = await get_admin_user(request, db)
    
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    menus = db.query(Menu).filter(Menu.store_id == store_id).order_by(Menu.created_at.desc()).all()
    
    return templates.TemplateResponse("admin/menus.html", {
        "request": request,
        "user": user,
        "store": store,
        "menus": menus,
    })


@router.post("/stores/{store_id}/menus/{menu_id}/activate")
async def activate_menu(store_id: int, menu_id: int, request: Request, db: Session = Depends(get_db)):
    """啟用菜單版本"""
    user = await get_admin_user(request, db)
    
    # 停用其他版本
    db.query(Menu).filter(Menu.store_id == store_id).update({"is_active": False})
    
    # 啟用指定版本
    menu = db.query(Menu).filter(Menu.id == menu_id, Menu.store_id == store_id).first()
    if menu:
        menu.is_active = True
        db.commit()
    
    return RedirectResponse(url=f"/admin/stores/{store_id}/menus", status_code=302)


@router.get("/import")
async def import_page(request: Request, store_id: int = None, db: Session = Depends(get_db)):
    """匯入頁面"""
    user = await get_admin_user(request, db)
    
    stores = db.query(Store).filter(Store.is_active == True).order_by(Store.name).all()
    
    # 如果有指定 store_id，取得該店家
    selected_store = None
    if store_id:
        selected_store = db.query(Store).filter(Store.id == store_id).first()
    
    return templates.TemplateResponse("admin/import.html", {
        "request": request,
        "user": user,
        "stores": stores,
        "selected_store_id": store_id,
        "selected_store": selected_store,
    })


@router.post("/import/preview")
async def import_preview(
    request: Request,
    json_file: UploadFile = File(...),
    store_id: int = Form(None),
    db: Session = Depends(get_db),
):
    """匯入預覽"""
    user = await get_admin_user(request, db)
    
    # 取得 JSON 內容
    if not json_file or not json_file.filename:
        raise HTTPException(status_code=400, detail="請上傳 JSON 檔案")
    
    content = await json_file.read()
    json_str = content.decode("utf-8")
    
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 格式錯誤: {e}")
    
    # 判斷匯入類型
    # 如果有 store_id（更新菜單模式），忽略 JSON 中的 store 欄位
    if store_id:
        # 取出 menu 部分（如果有 store + menu 結構，忽略 store）
        menu_data = data.get("menu", data)
        data = {
            "store_id": store_id,
            "mode": "replace",
            "menu": menu_data
        }
        json_str = json.dumps(data, ensure_ascii=False)
        is_full_import = False
    elif "store" in data:
        # 完整匯入模式（新增店家 + 菜單）
        is_full_import = True
    else:
        raise HTTPException(status_code=400, detail="JSON 缺少 store（新增店家）或請選擇店家（更新菜單）")
    
    try:
        if is_full_import:
            validated = FullImport(**data)
        else:
            validated = MenuImport(**data)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"資料驗證錯誤: {e}")
    
    # 如果是菜單匯入，取得現有菜單做比較
    existing_menu = None
    if not is_full_import:
        store = db.query(Store).filter(Store.id == validated.store_id).first()
        if not store:
            raise HTTPException(status_code=404, detail="店家不存在")
        existing_menu = db.query(Menu).filter(
            Menu.store_id == validated.store_id,
            Menu.is_active == True
        ).first()
    
    return templates.TemplateResponse("admin/import_preview.html", {
        "request": request,
        "user": user,
        "data": validated,
        "is_full_import": is_full_import,
        "existing_menu": existing_menu,
        "json_str": json_str,
    })


@router.post("/import")
async def do_import(
    request: Request,
    json_str: str = Form(...),
    db: Session = Depends(get_db),
):
    """執行匯入"""
    user = await get_admin_user(request, db)
    
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 格式錯誤: {e}")
    
    # 判斷匯入類型
    # 如果有 store_id，視為菜單更新（忽略 store 欄位）
    if "store_id" in data:
        # 菜單更新模式（忽略 store 欄位）
        menu_data = data.get("menu", {})
        if not menu_data:
            raise HTTPException(status_code=400, detail="JSON 缺少 menu 內容")
        validated = MenuImport(
            store_id=data["store_id"],
            mode=data.get("mode", "replace"),
            menu=menu_data
        )
        menu = import_menu(db, validated)
    elif "store" in data:
        # 完整匯入模式（新增店家 + 菜單）
        validated = FullImport(**data)
        store = import_store_and_menu(db, validated)
    else:
        raise HTTPException(status_code=400, detail="JSON 格式錯誤")
    
    return RedirectResponse(url="/admin", status_code=302)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"資料驗證錯誤: {e}")


@router.get("/groups")
async def group_list(request: Request, db: Session = Depends(get_db)):
    """所有團單"""
    user = await get_admin_user(request, db)
    
    groups = db.query(Group).order_by(Group.created_at.desc()).all()
    
    return templates.TemplateResponse("admin/groups.html", {
        "request": request,
        "user": user,
        "groups": groups,
    })


@router.post("/stores/{store_id}/toggle")
async def toggle_store(store_id: int, request: Request, db: Session = Depends(get_db)):
    """啟用/停用店家"""
    user = await get_admin_user(request, db)
    
    store = db.query(Store).filter(Store.id == store_id).first()
    if store:
        store.is_active = not store.is_active
        db.commit()
    
    # 檢查來源頁面，回到對應頁面
    referer = request.headers.get("referer", "")
    if "/edit" in referer:
        return RedirectResponse(url=f"/admin/stores/{store_id}/edit", status_code=302)
    return RedirectResponse(url=f"/admin/stores/{store_id}", status_code=302)


@router.post("/stores/{store_id}/delete")
async def delete_store(store_id: int, request: Request, db: Session = Depends(get_db)):
    """刪除店家"""
    user = await get_admin_user(request, db)
    
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    # 檢查是否有關聯的團單
    group_count = db.query(Group).filter(Group.store_id == store_id).count()
    if group_count > 0:
        raise HTTPException(status_code=400, detail=f"無法刪除：此店家有 {group_count} 個團單")
    
    # 刪除相關資料（菜單、選項）
    for menu in store.menus:
        for item in menu.items:
            for opt in item.options:
                db.delete(opt)
            db.delete(item)
        for category in menu.categories:
            db.delete(category)
        db.delete(menu)
    
    for option in store.options:
        db.delete(option)
    
    db.delete(store)
    db.commit()
    
    return RedirectResponse(url="/admin/stores", status_code=302)


@router.post("/stores/{store_id}/visibility")
async def update_store_visibility(
    store_id: int,
    request: Request,
    visibility: str = Form(...),
    department_ids: list[str] = Form(default=[]),
    db: Session = Depends(get_db)
):
    """更新店家可見範圍"""
    from app.models.department import StoreDepartment
    user = await get_admin_user(request, db)
    
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    # 更新公開狀態
    store.is_public = (visibility == "public")
    
    # 清除舊的部門關聯
    db.query(StoreDepartment).filter(StoreDepartment.store_id == store_id).delete()
    
    # 如果是限定部門，新增關聯
    if visibility == "departments" and department_ids:
        for dept_id in department_ids:
            sd = StoreDepartment(store_id=store_id, department_id=int(dept_id))
            db.add(sd)
    
    db.commit()
    
    return RedirectResponse(url=f"/admin/stores/{store_id}", status_code=302)


@router.get("/stores/{store_id}")
async def store_detail_page(store_id: int, request: Request, db: Session = Depends(get_db)):
    """店家詳情頁面"""
    from app.models.store import StoreBranch, StoreTopping
    from app.models.department import Department, StoreDepartment
    user = await get_admin_user(request, db)
    
    store = db.query(Store).options(
        joinedload(Store.branches),
        joinedload(Store.toppings),
        joinedload(Store.options)
    ).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    # 取得所有部門
    departments = db.query(Department).filter(Department.is_active == True).all()
    
    # 取得店家已綁定的部門 ID
    store_depts = db.query(StoreDepartment).filter(StoreDepartment.store_id == store_id).all()
    store_dept_ids = [sd.department_id for sd in store_depts]
    
    return templates.TemplateResponse("admin/store_detail.html", {
        "request": request,
        "user": user,
        "store": store,
        "departments": departments,
        "store_dept_ids": store_dept_ids,
    })


@router.get("/stores/{store_id}/edit")
async def edit_store_page(store_id: int, request: Request, db: Session = Depends(get_db)):
    """編輯店家頁面"""
    from app.models.store import StoreBranch, StoreTopping
    user = await get_admin_user(request, db)
    
    store = db.query(Store).options(
        joinedload(Store.branches),
        joinedload(Store.toppings),
        joinedload(Store.options)
    ).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    return templates.TemplateResponse("admin/store_edit.html", {
        "request": request,
        "user": user,
        "store": store,
    })


@router.post("/stores/{store_id}/edit")
async def update_store(
    store_id: int,
    request: Request,
    name: str = Form(...),
    category: str = Form(...),
    phone: str = Form(None),
    address: str = Form(None),
    website_url: str = Form(None),
    google_maps_url: str = Form(None),
    ubereats_url: str = Form(None),
    foodpanda_url: str = Form(None),
    logo_file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    """更新店家資料"""
    from app.services.upload_service import upload_image
    
    user = await get_admin_user(request, db)
    
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    store.name = name
    store.phone = phone.strip() if phone else None
    store.address = address.strip() if address else None
    store.website_url = website_url.strip() if website_url else None
    store.google_maps_url = google_maps_url.strip() if google_maps_url else None
    store.ubereats_url = ubereats_url.strip() if ubereats_url else None
    store.foodpanda_url = foodpanda_url.strip() if foodpanda_url else None
    
    # 分類修改 - 使用 raw SQL 直接用大寫值
    category_map = {
        'drink': 'DRINK',
        'meal': 'MEAL',
        'group_buy': 'GROUP_BUY'
    }
    if category in category_map:
        from sqlalchemy import text
        db.execute(
            text("UPDATE stores SET category = :cat WHERE id = :id"),
            {"cat": category_map[category], "id": store_id}
        )
    
    # 處理 Logo 上傳 (使用 Cloudinary)
    if logo_file and logo_file.filename:
        logo_url = await upload_image(logo_file, folder="sela/stores")
        if logo_url:
            store.logo_url = logo_url
    
    db.commit()
    
    return RedirectResponse(url="/admin/stores", status_code=302)


@router.get("/users")
async def user_list(request: Request, db: Session = Depends(get_db)):
    """使用者列表"""
    user = await get_admin_user(request, db)
    
    from app.models.user import User, SystemSetting
    from datetime import datetime, timedelta
    
    users = db.query(User).order_by(User.created_at.desc()).all()
    
    # 計算在線人數（30分鐘內有活動）
    online_threshold = datetime.utcnow() - timedelta(minutes=30)
    online_count = db.query(User).filter(
        User.last_active_at != None,
        User.last_active_at > online_threshold
    ).count()
    
    # 取得系統設定
    system_setting = db.query(SystemSetting).filter(SystemSetting.id == 1).first()
    
    return templates.TemplateResponse("admin/users.html", {
        "request": request,
        "user": user,
        "users": users,
        "online_count": online_count,
        "system_setting": system_setting,
    })


@router.post("/users/{user_id}/toggle-admin")
async def toggle_user_admin(user_id: int, request: Request, db: Session = Depends(get_db)):
    """切換使用者管理員權限"""
    admin = await get_admin_user(request, db)
    
    from app.models.user import User
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="使用者不存在")
    
    # 不能移除自己的管理員權限
    if target_user.id == admin.id:
        raise HTTPException(status_code=400, detail="無法移除自己的管理員權限")
    
    target_user.is_admin = not target_user.is_admin
    db.commit()
    
    return RedirectResponse(url="/admin/users", status_code=302)


@router.get("/users/{user_id}")
async def user_detail(user_id: int, request: Request, db: Session = Depends(get_db)):
    """使用者詳細資訊頁面"""
    admin = await get_admin_user(request, db)
    
    from app.models.user import User
    from app.models.order import Order
    from app.models.group import Group
    
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="使用者不存在")
    
    # 取得該用戶的訂單
    orders = db.query(Order).options(
        joinedload(Order.group)
    ).filter(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(20).all()
    
    # 取得該用戶開的團
    groups = db.query(Group).filter(Group.owner_id == user_id).order_by(Group.created_at.desc()).limit(20).all()
    
    # 統計
    order_count = db.query(Order).filter(Order.user_id == user_id).count()
    group_count = db.query(Group).filter(Group.owner_id == user_id).count()
    
    return templates.TemplateResponse("admin/user_detail.html", {
        "request": request,
        "user": admin,
        "target_user": target_user,
        "orders": orders,
        "groups": groups,
        "order_count": order_count,
        "group_count": group_count,
    })


@router.post("/users/logout-all")
async def logout_all_users(request: Request, db: Session = Depends(get_db)):
    """一鍵登出所有用戶"""
    admin = await get_admin_user(request, db)
    
    from app.models.user import SystemSetting
    import logging
    logger = logging.getLogger("admin")
    
    # 增加 token_version，讓所有舊 token 失效
    system_setting = db.query(SystemSetting).filter(SystemSetting.id == 1).first()
    if system_setting:
        old_version = system_setting.token_version
        system_setting.token_version += 1
        db.commit()
        logger.info(f"管理員 {admin.display_name} 執行一鍵登出，token_version: {old_version} → {system_setting.token_version}")
    
    return RedirectResponse(url="/admin/users?logout_all=success", status_code=302)


@router.post("/stores/{store_id}/branches")
async def add_branch(
    store_id: int,
    request: Request,
    name: str = Form(...),
    phone: str = Form(None),
    address: str = Form(None),
    db: Session = Depends(get_db),
):
    """新增分店"""
    from app.models.store import StoreBranch
    user = await get_admin_user(request, db)
    
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    branch = StoreBranch(
        store_id=store_id,
        name=name.strip(),
        phone=phone.strip() if phone else None,
        address=address.strip() if address else None,
    )
    db.add(branch)
    db.commit()
    
    return RedirectResponse(url=f"/admin/stores/{store_id}", status_code=302)


@router.post("/stores/{store_id}/branches/{branch_id}/delete")
async def delete_branch(
    store_id: int,
    branch_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """刪除分店"""
    from app.models.store import StoreBranch
    user = await get_admin_user(request, db)
    
    branch = db.query(StoreBranch).filter(
        StoreBranch.id == branch_id,
        StoreBranch.store_id == store_id
    ).first()
    
    if branch:
        db.delete(branch)
        db.commit()
    
    return RedirectResponse(url=f"/admin/stores/{store_id}", status_code=302)


@router.post("/stores/{store_id}/branches/{branch_id}")
async def update_branch(
    store_id: int,
    branch_id: int,
    request: Request,
    name: str = Form(...),
    phone: str = Form(None),
    address: str = Form(None),
    db: Session = Depends(get_db),
):
    """編輯分店"""
    from app.models.store import StoreBranch
    user = await get_admin_user(request, db)
    
    branch = db.query(StoreBranch).filter(
        StoreBranch.id == branch_id,
        StoreBranch.store_id == store_id
    ).first()
    
    if branch:
        branch.name = name.strip()
        branch.phone = phone.strip() if phone else None
        branch.address = address.strip() if address else None
        db.commit()
    
    return RedirectResponse(url=f"/admin/stores/{store_id}", status_code=302)


@router.post("/stores/{store_id}/branches/{branch_id}/toggle")
async def toggle_branch(
    store_id: int,
    branch_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """切換分店啟用狀態"""
    from app.models.store import StoreBranch
    user = await get_admin_user(request, db)
    
    branch = db.query(StoreBranch).filter(
        StoreBranch.id == branch_id,
        StoreBranch.store_id == store_id
    ).first()
    
    if branch:
        branch.is_active = not branch.is_active
        db.commit()
    
    return RedirectResponse(url=f"/admin/stores/{store_id}", status_code=302)


@router.post("/stores/{store_id}/toppings")
async def add_topping(
    store_id: int,
    request: Request,
    topping_name: str = Form(...),
    topping_price: float = Form(0),
    db: Session = Depends(get_db),
):
    """新增加料"""
    from app.models.store import StoreTopping
    user = await get_admin_user(request, db)
    
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    # 取得目前最大 sort_order
    max_sort = db.query(StoreTopping).filter(
        StoreTopping.store_id == store_id
    ).count()
    
    topping = StoreTopping(
        store_id=store_id,
        name=topping_name.strip(),
        price=topping_price,
        sort_order=max_sort,
        is_active=True,
    )
    db.add(topping)
    db.commit()
    
    return RedirectResponse(url=f"/admin/stores/{store_id}/edit", status_code=302)


@router.post("/stores/{store_id}/toppings/{topping_id}/delete")
async def delete_topping(
    store_id: int,
    topping_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """刪除加料"""
    from app.models.store import StoreTopping
    user = await get_admin_user(request, db)
    
    topping = db.query(StoreTopping).filter(
        StoreTopping.id == topping_id,
        StoreTopping.store_id == store_id
    ).first()
    
    if topping:
        db.delete(topping)
        db.commit()
    
    return RedirectResponse(url=f"/admin/stores/{store_id}/edit", status_code=302)


@router.post("/stores/{store_id}/toppings/{topping_id}/toggle")
async def toggle_topping(
    store_id: int,
    topping_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """切換加料啟用狀態"""
    from app.models.store import StoreTopping
    user = await get_admin_user(request, db)
    
    topping = db.query(StoreTopping).filter(
        StoreTopping.id == topping_id,
        StoreTopping.store_id == store_id
    ).first()
    
    if topping:
        topping.is_active = not topping.is_active
        db.commit()
    
    return RedirectResponse(url=f"/admin/stores/{store_id}/edit", status_code=302)


@router.post("/announcement")
async def update_announcement(
    request: Request,
    announcement: str = Form(""),
    db: Session = Depends(get_db)
):
    """更新首頁公告"""
    user = await get_admin_user(request, db)
    
    from app.models.user import SystemSetting
    
    settings = db.query(SystemSetting).first()
    if settings:
        settings.announcement = announcement.strip() if announcement.strip() else None
        settings.updated_at = datetime.utcnow()
    else:
        settings = SystemSetting(announcement=announcement.strip() if announcement.strip() else None)
        db.add(settings)
    
    db.commit()
    
    return RedirectResponse(url="/admin", status_code=302)


@router.get("/feedbacks")
async def feedback_list(request: Request, db: Session = Depends(get_db)):
    """問題回報列表"""
    user = await get_admin_user(request, db)
    
    from app.models.user import Feedback, User
    
    # 取得所有回報，pending 優先
    all_feedbacks = db.query(Feedback).options(
        joinedload(Feedback.user)
    ).order_by(
        Feedback.status.asc(),  # pending 排前面
        Feedback.created_at.desc()
    ).all()
    
    # 分離最近 5 筆和歷史
    recent_feedbacks = all_feedbacks[:5]
    history_feedbacks = all_feedbacks[5:]
    
    return templates.TemplateResponse("admin/feedbacks.html", {
        "request": request,
        "user": user,
        "recent_feedbacks": recent_feedbacks,
        "history_feedbacks": history_feedbacks,
    })


@router.post("/feedbacks/{feedback_id}/resolve")
async def resolve_feedback(
    request: Request,
    feedback_id: int,
    db: Session = Depends(get_db)
):
    """標記問題已處理"""
    user = await get_admin_user(request, db)
    
    from app.models.user import Feedback
    
    feedback = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if feedback:
        feedback.status = "resolved"
        feedback.resolved_at = datetime.utcnow()
        db.commit()
    
    return RedirectResponse(url="/admin/feedbacks", status_code=302)


# ============ 部門管理 ============

@router.get("/departments")
async def department_list(request: Request, db: Session = Depends(get_db)):
    """部門列表"""
    user = await get_admin_user(request, db)
    
    from app.models.department import Department
    
    departments = db.query(Department).order_by(Department.created_at.desc()).all()
    
    return templates.TemplateResponse("admin/departments.html", {
        "request": request,
        "user": user,
        "departments": departments,
    })


@router.post("/departments")
async def create_department(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db)
):
    """新增部門"""
    user = await get_admin_user(request, db)
    
    from app.models.department import Department
    
    dept = Department(
        name=name.strip(),
        description=description.strip() if description else None
    )
    db.add(dept)
    db.commit()
    
    return RedirectResponse(url="/admin/departments", status_code=302)


@router.get("/departments/{dept_id}")
async def department_detail(request: Request, dept_id: int, db: Session = Depends(get_db)):
    """部門詳情"""
    user = await get_admin_user(request, db)
    
    from app.models.department import Department, UserDepartment
    from app.models.user import User
    
    department = db.query(Department).filter(Department.id == dept_id).first()
    if not department:
        raise HTTPException(status_code=404, detail="部門不存在")
    
    members = db.query(UserDepartment).filter(
        UserDepartment.department_id == dept_id
    ).all()
    
    # 取得尚未加入此部門的用戶
    member_ids = [m.user_id for m in members]
    available_users = db.query(User).filter(
        ~User.id.in_(member_ids) if member_ids else True
    ).order_by(User.display_name).all()
    
    return templates.TemplateResponse("admin/department_detail.html", {
        "request": request,
        "user": user,
        "department": department,
        "members": members,
        "available_users": available_users,
    })


@router.post("/departments/{dept_id}/toggle")
async def toggle_department(request: Request, dept_id: int, db: Session = Depends(get_db)):
    """啟用/停用部門"""
    user = await get_admin_user(request, db)
    
    from app.models.department import Department
    
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if dept:
        dept.is_active = not dept.is_active
        db.commit()
    
    return RedirectResponse(url="/admin/departments", status_code=302)


@router.post("/departments/{dept_id}/update")
async def update_department(
    request: Request,
    dept_id: int,
    name: str = Form(...),
    description: str = Form(""),
    is_public: str = Form(None),
    db: Session = Depends(get_db)
):
    """更新部門"""
    user = await get_admin_user(request, db)
    
    from app.models.department import Department
    
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if dept:
        dept.name = name.strip()
        dept.description = description.strip() if description else None
        dept.is_public = is_public == "1"
        db.commit()
    
    return RedirectResponse(url=f"/admin/departments/{dept_id}", status_code=302)


@router.post("/departments/{dept_id}/members")
async def add_department_member(
    request: Request,
    dept_id: int,
    user_id: int = Form(...),
    role: str = Form("member"),
    db: Session = Depends(get_db)
):
    """新增部門成員"""
    user = await get_admin_user(request, db)
    
    from app.models.department import UserDepartment, DeptRole
    
    # 檢查是否已存在
    existing = db.query(UserDepartment).filter(
        UserDepartment.user_id == user_id,
        UserDepartment.department_id == dept_id
    ).first()
    
    if not existing:
        ud = UserDepartment(
            user_id=user_id,
            department_id=dept_id,
            role=DeptRole.LEADER if role == "leader" else DeptRole.MEMBER
        )
        db.add(ud)
        db.commit()
    
    return RedirectResponse(url=f"/admin/departments/{dept_id}", status_code=302)


@router.post("/departments/{dept_id}/members/{member_id}/toggle-role")
async def toggle_member_role(
    request: Request,
    dept_id: int,
    member_id: int,
    db: Session = Depends(get_db)
):
    """切換成員角色"""
    user = await get_admin_user(request, db)
    
    from app.models.department import UserDepartment, DeptRole
    
    ud = db.query(UserDepartment).filter(UserDepartment.id == member_id).first()
    if ud:
        ud.role = DeptRole.MEMBER if ud.role == DeptRole.LEADER else DeptRole.LEADER
        db.commit()
    
    return RedirectResponse(url=f"/admin/departments/{dept_id}", status_code=302)


@router.post("/departments/{dept_id}/members/{member_id}/remove")
async def remove_department_member(
    request: Request,
    dept_id: int,
    member_id: int,
    db: Session = Depends(get_db)
):
    """移除部門成員"""
    user = await get_admin_user(request, db)
    
    from app.models.department import UserDepartment
    
    ud = db.query(UserDepartment).filter(UserDepartment.id == member_id).first()
    if ud:
        db.delete(ud)
        db.commit()
    
    return RedirectResponse(url=f"/admin/departments/{dept_id}", status_code=302)


# ============ 公告管理 ============

@router.get("/announcements")
async def announcements_page(request: Request, db: Session = Depends(get_db)):
    """公告管理頁面"""
    user = await get_admin_user(request, db)
    
    from app.models.user import Announcement
    
    announcements = db.query(Announcement).options(
        joinedload(Announcement.created_by)
    ).order_by(Announcement.is_pinned.desc(), Announcement.created_at.desc()).all()
    
    return templates.TemplateResponse("admin/announcements.html", {
        "request": request,
        "user": user,
        "announcements": announcements,
    })


@router.post("/announcements")
async def create_announcement(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    is_pinned: bool = Form(False),
    expires_at: str = Form(None),
    db: Session = Depends(get_db)
):
    """新增公告"""
    user = await get_admin_user(request, db)
    
    from app.models.user import Announcement, SystemSetting
    
    expires_dt = None
    if expires_at:
        try:
            expires_dt = datetime.fromisoformat(expires_at)
        except:
            pass
    
    ann = Announcement(
        title=title.strip(),
        content=content.strip(),
        is_pinned=is_pinned,
        expires_at=expires_dt,
        created_by_id=user.id,
    )
    db.add(ann)
    
    # 同步更新 SystemSetting 的公告
    _sync_announcement_from_active(db)
    
    db.commit()
    
    return RedirectResponse(url="/admin/announcements", status_code=302)


@router.post("/announcements/{ann_id}/toggle")
async def toggle_announcement(ann_id: int, request: Request, db: Session = Depends(get_db)):
    """啟用/停用公告"""
    user = await get_admin_user(request, db)
    
    from app.models.user import Announcement
    
    ann = db.query(Announcement).filter(Announcement.id == ann_id).first()
    if ann:
        ann.is_active = not ann.is_active
        _sync_announcement_from_active(db)
        db.commit()
    
    return RedirectResponse(url="/admin/announcements", status_code=302)


@router.post("/announcements/{ann_id}/pin")
async def pin_announcement(ann_id: int, request: Request, db: Session = Depends(get_db)):
    """置頂公告"""
    user = await get_admin_user(request, db)
    
    from app.models.user import Announcement
    
    ann = db.query(Announcement).filter(Announcement.id == ann_id).first()
    if ann:
        ann.is_pinned = True
        _sync_announcement_from_active(db)
        db.commit()
    
    return RedirectResponse(url="/admin/announcements", status_code=302)


@router.post("/announcements/{ann_id}/unpin")
async def unpin_announcement(ann_id: int, request: Request, db: Session = Depends(get_db)):
    """取消置頂"""
    user = await get_admin_user(request, db)
    
    from app.models.user import Announcement
    
    ann = db.query(Announcement).filter(Announcement.id == ann_id).first()
    if ann:
        ann.is_pinned = False
        _sync_announcement_from_active(db)
        db.commit()
    
    return RedirectResponse(url="/admin/announcements", status_code=302)


@router.post("/announcements/{ann_id}/delete")
async def delete_announcement(ann_id: int, request: Request, db: Session = Depends(get_db)):
    """刪除公告"""
    user = await get_admin_user(request, db)
    
    from app.models.user import Announcement
    
    ann = db.query(Announcement).filter(Announcement.id == ann_id).first()
    if ann:
        db.delete(ann)
        _sync_announcement_from_active(db)
        db.commit()
    
    return RedirectResponse(url="/admin/announcements", status_code=302)


@router.get("/announcements/{ann_id}/edit")
async def edit_announcement_page(ann_id: int, request: Request, db: Session = Depends(get_db)):
    """編輯公告頁面"""
    user = await get_admin_user(request, db)
    
    from app.models.user import Announcement
    
    ann = db.query(Announcement).options(
        joinedload(Announcement.created_by)
    ).filter(Announcement.id == ann_id).first()
    
    if not ann:
        raise HTTPException(status_code=404, detail="公告不存在")
    
    return templates.TemplateResponse("admin/announcement_edit.html", {
        "request": request,
        "user": user,
        "announcement": ann,
    })


@router.post("/announcements/{ann_id}")
async def update_announcement(
    ann_id: int,
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    is_pinned: bool = Form(False),
    is_active: bool = Form(False),
    expires_at: str = Form(None),
    db: Session = Depends(get_db)
):
    """更新公告"""
    user = await get_admin_user(request, db)
    
    from app.models.user import Announcement
    
    ann = db.query(Announcement).filter(Announcement.id == ann_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="公告不存在")
    
    ann.title = title.strip()
    ann.content = content.strip()
    ann.is_pinned = is_pinned
    ann.is_active = is_active
    
    if expires_at:
        try:
            ann.expires_at = datetime.fromisoformat(expires_at)
        except:
            ann.expires_at = None
    else:
        ann.expires_at = None
    
    _sync_announcement_from_active(db)
    db.commit()
    
    return RedirectResponse(url="/admin/announcements", status_code=302)


def _sync_announcement_from_active(db: Session, new_ann=None):
    """從啟用的公告同步到 SystemSetting"""
    from app.models.user import Announcement, SystemSetting
    
    # 先 flush 確保新資料可以被查詢到
    db.flush()
    
    # 取得最新啟用的公告（優先置頂，再按建立時間）
    active = db.query(Announcement).filter(
        Announcement.is_active == True
    ).order_by(Announcement.is_pinned.desc(), Announcement.created_at.desc()).first()
    
    content = None
    if active:
        content = f"【{active.title}】\n{active.content}"
    
    settings = db.query(SystemSetting).first()
    if settings:
        settings.announcement = content
    else:
        settings = SystemSetting(announcement=content)
        db.add(settings)


# ============== 店家推薦審核 ==============

@router.get("/recommendations")
async def recommendation_list(request: Request, db: Session = Depends(get_db)):
    """店家推薦審核列表"""
    user = await get_admin_user(request, db)
    
    from app.models.user import StoreRecommendation
    
    # 待審核
    pending = db.query(StoreRecommendation).options(
        joinedload(StoreRecommendation.user)
    ).filter(
        StoreRecommendation.status == "pending"
    ).order_by(StoreRecommendation.created_at.desc()).all()
    
    # 已處理
    processed = db.query(StoreRecommendation).options(
        joinedload(StoreRecommendation.user)
    ).filter(
        StoreRecommendation.status != "pending"
    ).order_by(StoreRecommendation.reviewed_at.desc()).limit(20).all()
    
    return templates.TemplateResponse("admin/recommendations.html", {
        "request": request,
        "user": user,
        "pending": pending,
        "processed": processed,
    })


@router.post("/recommendations/{rec_id}/approve")
async def approve_recommendation(
    rec_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """核准店家推薦"""
    user = await get_admin_user(request, db)
    
    from app.models.user import StoreRecommendation
    
    rec = db.query(StoreRecommendation).filter(StoreRecommendation.id == rec_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="推薦不存在")
    
    if rec.status != "pending":
        return RedirectResponse(url="/admin/recommendations", status_code=302)
    
    # 建立新店家
    category_map = {
        "drink": CategoryType.DRINK,
        "meal": CategoryType.MEAL,
        "group_buy": CategoryType.GROUP_BUY,
    }
    
    new_store = Store(
        name=rec.store_name,
        category=category_map.get(rec.category, CategoryType.MEAL),
        website_url=rec.menu_url,
    )
    db.add(new_store)
    db.flush()  # 取得新店家 ID
    
    # 更新推薦狀態
    rec.status = "approved"
    rec.reviewed_at = datetime.utcnow()
    rec.reviewer_id = user.id
    rec.created_store_id = new_store.id
    
    db.commit()
    
    return RedirectResponse(url="/admin/recommendations", status_code=302)


@router.post("/recommendations/{rec_id}/reject")
async def reject_recommendation(
    rec_id: int,
    request: Request,
    reject_reason: str = Form(None),
    db: Session = Depends(get_db)
):
    """拒絕店家推薦"""
    user = await get_admin_user(request, db)
    
    from app.models.user import StoreRecommendation
    
    rec = db.query(StoreRecommendation).filter(StoreRecommendation.id == rec_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="推薦不存在")
    
    if rec.status != "pending":
        return RedirectResponse(url="/admin/recommendations", status_code=302)
    
    rec.status = "rejected"
    rec.reviewed_at = datetime.utcnow()
    rec.reviewer_id = user.id
    rec.reject_reason = reject_reason.strip() if reject_reason else None
    
    db.commit()
    
    return RedirectResponse(url="/admin/recommendations", status_code=302)
