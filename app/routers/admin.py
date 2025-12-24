from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from pydantic import ValidationError
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


@router.get("")
async def admin_home(request: Request, db: Session = Depends(get_db)):
    """後台首頁"""
    user = await get_admin_user(request, db)
    
    from app.models.user import User
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
    
    return templates.TemplateResponse("admin/index.html", {
        "request": request,
        "user": user,
        "store_count": store_count,
        "group_count": group_count,
        "user_count": user_count,
        "online_count": online_count,
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
async def import_page(request: Request, db: Session = Depends(get_db)):
    """匯入頁面"""
    user = await get_admin_user(request, db)
    
    stores = db.query(Store).filter(Store.is_active == True).all()
    
    return templates.TemplateResponse("admin/import.html", {
        "request": request,
        "user": user,
        "stores": stores,
    })


@router.post("/import/preview")
async def import_preview(
    request: Request,
    json_file: UploadFile = File(...),
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
    is_full_import = "store" in data
    
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
    
    is_full_import = "store" in data
    
    try:
        if is_full_import:
            validated = FullImport(**data)
            store = import_store_and_menu(db, validated)
        else:
            validated = MenuImport(**data)
            menu = import_menu(db, validated)
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
    
    return RedirectResponse(url="/admin/stores", status_code=302)


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


@router.get("/stores/{store_id}/edit")
async def edit_store_page(store_id: int, request: Request, db: Session = Depends(get_db)):
    """編輯店家頁面"""
    from app.models.store import StoreBranch
    user = await get_admin_user(request, db)
    
    store = db.query(Store).options(
        joinedload(Store.branches)
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
    store.category = CategoryType(category)
    
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
    branch_name: str = Form(...),
    branch_phone: str = Form(None),
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
        name=branch_name,
        phone=branch_phone if branch_phone else None,
    )
    db.add(branch)
    db.commit()
    
    return RedirectResponse(url=f"/admin/stores/{store_id}/edit", status_code=302)


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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}/edit", status_code=302)
