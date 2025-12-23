from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from pydantic import ValidationError
import json
import cloudinary
import cloudinary.uploader

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

# 設定 Cloudinary
if settings.cloudinary_cloud_name:
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
    )


@router.get("")
async def admin_home(request: Request, db: Session = Depends(get_db)):
    """後台首頁"""
    user = await get_admin_user(request, db)
    
    from app.models.user import User
    store_count = db.query(Store).count()
    group_count = db.query(Group).count()
    user_count = db.query(User).count()
    
    return templates.TemplateResponse("admin/index.html", {
        "request": request,
        "user": user,
        "store_count": store_count,
        "group_count": group_count,
        "user_count": user_count,
    })


@router.get("/stores")
async def store_list(request: Request, db: Session = Depends(get_db)):
    """店家列表"""
    user = await get_admin_user(request, db)
    
    stores = db.query(Store).order_by(Store.created_at.desc()).all()
    
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
    json_text: str = Form(None),
    json_file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    """匯入預覽"""
    user = await get_admin_user(request, db)
    
    # 取得 JSON 內容
    if json_file and json_file.filename:
        content = await json_file.read()
        json_str = content.decode("utf-8")
    elif json_text:
        json_str = json_text
    else:
        raise HTTPException(status_code=400, detail="請提供 JSON 內容")
    
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
            return RedirectResponse(url=f"/admin/stores/{store.id}/menus", status_code=302)
        else:
            validated = MenuImport(**data)
            menu = import_menu(db, validated)
            return RedirectResponse(url=f"/admin/stores/{validated.store_id}/menus", status_code=302)
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


@router.get("/stores/{store_id}/edit")
async def edit_store_page(store_id: int, request: Request, db: Session = Depends(get_db)):
    """編輯店家頁面"""
    user = await get_admin_user(request, db)
    
    store = db.query(Store).filter(Store.id == store_id).first()
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
    logo_url: str = Form(None),
    db: Session = Depends(get_db),
):
    """更新店家資料"""
    user = await get_admin_user(request, db)
    
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    store.name = name
    if logo_url:
        store.logo_url = logo_url
    
    db.commit()
    
    return RedirectResponse(url="/admin/stores", status_code=302)


@router.post("/stores/{store_id}/logo")
async def upload_store_logo(
    store_id: int,
    request: Request,
    logo: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """上傳店家 Logo"""
    user = await get_admin_user(request, db)
    
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    # 檢查是否有設定 Cloudinary
    if not settings.cloudinary_cloud_name:
        raise HTTPException(status_code=400, detail="尚未設定 Cloudinary")
    
    # 檢查檔案類型
    if not logo.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="只能上傳圖片")
    
    try:
        # 上傳到 Cloudinary
        result = cloudinary.uploader.upload(
            logo.file,
            folder="group-buy/stores",
            public_id=f"store_{store_id}",
            overwrite=True,
            transformation=[
                {"width": 200, "height": 200, "crop": "fill"},
                {"quality": "auto"},
                {"format": "webp"}
            ]
        )
        
        # 更新店家 Logo URL
        store.logo_url = result['secure_url']
        db.commit()
        
        return JSONResponse({
            "success": True,
            "url": result['secure_url']
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上傳失敗: {str(e)}")


@router.get("/users")
async def user_list(request: Request, db: Session = Depends(get_db)):
    """使用者列表"""
    user = await get_admin_user(request, db)
    
    from app.models.user import User
    users = db.query(User).order_by(User.created_at.desc()).all()
    
    return templates.TemplateResponse("admin/users.html", {
        "request": request,
        "user": user,
        "users": users,
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
