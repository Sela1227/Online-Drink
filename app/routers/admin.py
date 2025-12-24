from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from pydantic import ValidationError
import json
from datetime import timezone, timedelta, datetime

from app.database import get_db
from app.config import get_settings
from app.models.store import Store, StoreOption, StoreBranch, CategoryType, OptionType
from app.models.menu import Menu, MenuCategory, MenuItem, ItemOption
from app.models.group import Group
from app.models.user import User
from app.schemas.menu import MenuImport, FullImport, MenuContent
from app.services.auth import get_admin_user
from app.services.import_service import import_store_and_menu, import_menu

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()

# 加入台北時區過濾器
def to_taipei_time(dt):
    """將 UTC 時間轉換為台北時間 (UTC+8)"""
    if dt is None:
        return None
    taipei_tz = timezone(timedelta(hours=8))
    utc_dt = dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(taipei_tz)

templates.env.filters['taipei'] = to_taipei_time


# ===============================
# 首頁
# ===============================
@router.get("")
async def admin_index(
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    store_count = db.query(Store).count()
    group_count = db.query(Group).count()
    user_count = db.query(User).count()
    
    # 計算在線用戶數 (5分鐘內活躍)
    five_minutes_ago = datetime.utcnow() - timedelta(minutes=5)
    online_count = db.query(User).filter(
        User.last_active_at > five_minutes_ago
    ).count()
    
    return templates.TemplateResponse("admin/index.html", {
        "request": request,
        "user": user,
        "store_count": store_count,
        "group_count": group_count,
        "user_count": user_count,
        "online_count": online_count,
    })


# ===============================
# 店家管理
# ===============================
@router.get("/stores")
async def store_list(
    request: Request,
    category: str = None,
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    query = db.query(Store).order_by(Store.name)
    
    # 篩選分類
    if category:
        try:
            cat_enum = CategoryType(category)
            query = query.filter(Store.category == cat_enum)
        except ValueError:
            pass
    
    stores = query.all()
    
    return templates.TemplateResponse("admin/stores.html", {
        "request": request,
        "user": user,
        "stores": stores,
        "selected_category": category,
        "categories": list(CategoryType),
    })


@router.get("/stores/{store_id}/edit")
async def edit_store_form(
    request: Request,
    store_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    store = db.query(Store).options(
        joinedload(Store.branches)
    ).filter(Store.id == store_id).first()
    if not store:
        return RedirectResponse("/admin/stores", status_code=302)
    
    return templates.TemplateResponse("admin/store_edit.html", {
        "request": request,
        "user": user,
        "store": store,
        "categories": list(CategoryType),
    })


@router.post("/stores/{store_id}/edit")
async def update_store(
    store_id: int,
    name: str = Form(...),
    category: str = Form(...),
    phone: str = Form(None),
    is_active: bool = Form(False),
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        return RedirectResponse("/admin/stores", status_code=302)
    
    store.name = name
    store.phone = phone
    store.is_active = is_active
    
    # ★★★ 關鍵修復：正確轉換 CategoryType ★★★
    # 表單送的可能是 "DRINK" 或 "drink"，需要轉換成正確的 enum
    try:
        # 先嘗試直接用小寫值
        category_lower = category.lower()
        store.category = CategoryType(category_lower)
    except ValueError:
        # 如果失敗，嘗試用 enum 名稱
        try:
            store.category = CategoryType[category.upper()]
        except KeyError:
            # 如果還是失敗，保持原值
            pass
    
    db.commit()
    
    return RedirectResponse("/admin/stores", status_code=302)


@router.post("/stores/{store_id}/logo")
async def update_store_logo(
    store_id: int,
    logo: UploadFile = File(...),
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        return RedirectResponse("/admin/stores", status_code=302)
    
    # 使用 Cloudinary
    try:
        import cloudinary
        import cloudinary.uploader
        
        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET
        )
        
        contents = await logo.read()
        result = cloudinary.uploader.upload(
            contents,
            folder="sela/stores",
            public_id=f"store_{store_id}",
            overwrite=True
        )
        
        store.logo_url = result['secure_url']
        db.commit()
    except Exception as e:
        print(f"Logo upload error: {e}")
    
    return RedirectResponse(f"/admin/stores/{store_id}/edit", status_code=302)


@router.post("/stores/{store_id}/branches")
async def add_store_branch(
    store_id: int,
    branch_name: str = Form(...),
    branch_phone: str = Form(None),
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        return RedirectResponse("/admin/stores", status_code=302)
    
    branch = StoreBranch(
        store_id=store_id,
        name=branch_name,
        phone=branch_phone
    )
    db.add(branch)
    db.commit()
    
    return RedirectResponse(f"/admin/stores/{store_id}/edit", status_code=302)


@router.post("/stores/{store_id}/branches/{branch_id}/delete")
async def delete_store_branch(
    store_id: int,
    branch_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    branch = db.query(StoreBranch).filter(
        StoreBranch.id == branch_id,
        StoreBranch.store_id == store_id
    ).first()
    
    if branch:
        db.delete(branch)
        db.commit()
    
    return RedirectResponse(f"/admin/stores/{store_id}/edit", status_code=302)


@router.post("/stores/{store_id}/delete")
async def delete_store(
    store_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    store = db.query(Store).filter(Store.id == store_id).first()
    if store:
        db.delete(store)
        db.commit()
    
    return RedirectResponse("/admin/stores", status_code=302)


# ===============================
# 匯入功能
# ===============================
@router.get("/import")
async def import_page(
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    stores = db.query(Store).order_by(Store.name).all()
    
    return templates.TemplateResponse("admin/import.html", {
        "request": request,
        "user": user,
        "stores": stores,
    })


@router.post("/import/full")
async def import_full(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    try:
        contents = await file.read()
        data = json.loads(contents)
        
        # 驗證格式
        import_data = FullImport(**data)
        
        # 匯入
        store = import_store_and_menu(db, import_data)
        
        return RedirectResponse(f"/admin/stores/{store.id}/edit", status_code=302)
    except ValidationError as e:
        return templates.TemplateResponse("admin/import.html", {
            "request": request,
            "user": user,
            "stores": db.query(Store).all(),
            "error": f"JSON 格式錯誤: {e}"
        })
    except Exception as e:
        return templates.TemplateResponse("admin/import.html", {
            "request": request,
            "user": user,
            "stores": db.query(Store).all(),
            "error": f"匯入失敗: {e}"
        })


@router.post("/import/menu")
async def import_menu_route(
    request: Request,
    store_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        return RedirectResponse("/admin/import", status_code=302)
    
    try:
        contents = await file.read()
        data = json.loads(contents)
        
        # 驗證格式
        menu_data = MenuContent(**data)
        
        # 匯入
        import_menu(db, store, menu_data)
        
        return RedirectResponse(f"/admin/stores/{store.id}/edit", status_code=302)
    except ValidationError as e:
        return templates.TemplateResponse("admin/import.html", {
            "request": request,
            "user": user,
            "stores": db.query(Store).all(),
            "error": f"JSON 格式錯誤: {e}"
        })
    except Exception as e:
        return templates.TemplateResponse("admin/import.html", {
            "request": request,
            "user": user,
            "stores": db.query(Store).all(),
            "error": f"匯入失敗: {e}"
        })


# ===============================
# 團單管理
# ===============================
@router.get("/groups")
async def group_list(
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    groups = db.query(Group).options(
        joinedload(Group.store),
        joinedload(Group.owner)
    ).order_by(Group.created_at.desc()).limit(50).all()
    
    return templates.TemplateResponse("admin/groups.html", {
        "request": request,
        "user": user,
        "groups": groups,
    })


# ===============================
# 用戶管理
# ===============================
@router.get("/users")
async def user_list(
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    
    return templates.TemplateResponse("admin/users.html", {
        "request": request,
        "user": user,
        "users": users,
    })


@router.get("/users/{user_id}")
async def user_detail(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db),
    admin_user = Depends(get_admin_user)
):
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        return RedirectResponse("/admin/users", status_code=302)
    
    # 取得用戶的團單和訂單
    groups = db.query(Group).filter(Group.owner_id == user_id).order_by(Group.created_at.desc()).limit(10).all()
    
    return templates.TemplateResponse("admin/user_detail.html", {
        "request": request,
        "user": admin_user,
        "target_user": target_user,
        "groups": groups,
    })


@router.post("/users/{user_id}/toggle-admin")
async def toggle_admin(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user = Depends(get_admin_user)
):
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        return RedirectResponse("/admin/users", status_code=302)
    
    # 不能取消自己的管理員
    if target_user.id == admin_user.id:
        return RedirectResponse(f"/admin/users/{user_id}", status_code=302)
    
    target_user.is_admin = not target_user.is_admin
    db.commit()
    
    return RedirectResponse(f"/admin/users/{user_id}", status_code=302)


@router.post("/users/{user_id}/update-nickname")
async def update_user_nickname(
    user_id: int,
    nickname: str = Form(None),
    db: Session = Depends(get_db),
    admin_user = Depends(get_admin_user)
):
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        return RedirectResponse("/admin/users", status_code=302)
    
    target_user.nickname = nickname if nickname else None
    db.commit()
    
    return RedirectResponse(f"/admin/users/{user_id}", status_code=302)
