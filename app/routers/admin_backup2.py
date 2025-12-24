"""
<<<<<<< HEAD
admin.py - 管理後台路由
修復版 2024/12/24
=======
admin.py 修復版

修復問題：
1. taipei filter 未註冊 - 使用者頁面黑屏
2. 店家分類更新錯誤 - 大小寫轉換
>>>>>>> 4b452d7a8c1a7e6d24fe5ae82e5328c0a33453d5
"""
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_
from datetime import datetime, timezone, timedelta
import json

from app.database import get_db
from app.models.user import User
from app.models.store import Store, CategoryType, StoreOption
from app.models.menu import Menu, MenuCategory, MenuItem, ItemOption
from app.models.group import Group
from app.models.order import Order, OrderStatus
from app.services.auth import get_admin_user
from app.services.import_service import import_store_from_json
from app.config import get_settings

try:
    from app.services.upload_service import upload_image
except ImportError:
    upload_image = None

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
settings = get_settings()

<<<<<<< HEAD

# ===== 註冊台北時區過濾器 =====
def to_taipei_time(dt):
=======
# ===== 重要：註冊台北時區過濾器 =====
def to_taipei_time(dt):
    """將 UTC 時間轉換為台北時間"""
>>>>>>> 4b452d7a8c1a7e6d24fe5ae82e5328c0a33453d5
    if dt is None:
        return None
    taipei_tz = timezone(timedelta(hours=8))
    if dt.tzinfo is None:
        utc_dt = dt.replace(tzinfo=timezone.utc)
    else:
        utc_dt = dt
    return utc_dt.astimezone(taipei_tz)

templates.env.filters['taipei'] = to_taipei_time


# ===== 管理首頁 =====
@router.get("")
async def admin_index(
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
<<<<<<< HEAD
=======
    # 統計數據
>>>>>>> 4b452d7a8c1a7e6d24fe5ae82e5328c0a33453d5
    stats = {
        "total_users": db.query(User).count(),
        "total_stores": db.query(Store).filter(Store.is_active == True).count(),
        "total_groups": db.query(Group).count(),
        "active_groups": db.query(Group).filter(
            Group.is_closed == False,
            Group.deadline > datetime.utcnow()
        ).count(),
    }
    
<<<<<<< HEAD
=======
    # 在線人數
>>>>>>> 4b452d7a8c1a7e6d24fe5ae82e5328c0a33453d5
    thirty_minutes_ago = datetime.utcnow() - timedelta(minutes=30)
    try:
        online_count = db.query(User).filter(
            User.last_active_at >= thirty_minutes_ago
        ).count()
    except:
        online_count = 0
    
    return templates.TemplateResponse("admin/index.html", {
        "request": request,
        "user": user,
        "stats": stats,
        "online_count": online_count,
    })


# ===== 店家管理 =====
@router.get("/stores")
async def store_list(
    request: Request,
    category: str = None,
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    query = db.query(Store).filter(Store.is_active == True)
    
<<<<<<< HEAD
=======
    # 分類篩選
>>>>>>> 4b452d7a8c1a7e6d24fe5ae82e5328c0a33453d5
    if category:
        try:
            cat_type = CategoryType(category.lower())
            query = query.filter(Store.category == cat_type)
        except ValueError:
            pass
    
    stores = query.order_by(Store.name).all()
    
    return templates.TemplateResponse("admin/stores.html", {
        "request": request,
        "user": user,
        "stores": stores,
        "categories": list(CategoryType),
        "selected_category": category,
    })


@router.get("/stores/{store_id}")
async def store_detail(
    store_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    store = db.query(Store).options(
        joinedload(Store.menus).joinedload(Menu.categories).joinedload(MenuCategory.items)
    ).filter(Store.id == store_id).first()
    
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    return templates.TemplateResponse("admin/store_detail.html", {
        "request": request,
        "user": user,
        "store": store,
        "categories": list(CategoryType),
    })


@router.post("/stores/{store_id}/update")
async def update_store(
    store_id: int,
    name: str = Form(...),
    category: str = Form(...),
    phone: str = Form(None),
    logo: UploadFile = File(None),
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    store.name = name
    
    # ===== 修復：分類大小寫轉換 =====
    try:
<<<<<<< HEAD
=======
        # 先嘗試小寫（PostgreSQL enum 是小寫）
>>>>>>> 4b452d7a8c1a7e6d24fe5ae82e5328c0a33453d5
        category_lower = category.lower()
        store.category = CategoryType(category_lower)
    except ValueError:
        try:
<<<<<<< HEAD
            store.category = CategoryType[category.upper()]
        except KeyError:
=======
            # 如果失敗，嘗試用 name 取得
            store.category = CategoryType[category.upper()]
        except KeyError:
            # 保持原值
>>>>>>> 4b452d7a8c1a7e6d24fe5ae82e5328c0a33453d5
            pass
    
    if phone:
        store.phone = phone
    
<<<<<<< HEAD
=======
    # 上傳 Logo
>>>>>>> 4b452d7a8c1a7e6d24fe5ae82e5328c0a33453d5
    if logo and logo.filename and upload_image:
        try:
            logo_url = await upload_image(logo, folder="store_logos")
            if logo_url:
                store.logo_url = logo_url
        except Exception as e:
            print(f"Logo upload error: {e}")
    
    db.commit()
    
    return RedirectResponse(f"/admin/stores/{store_id}", status_code=302)


@router.post("/stores/{store_id}/delete")
async def delete_store(
    store_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    store = db.query(Store).filter(Store.id == store_id).first()
    if store:
<<<<<<< HEAD
=======
        # 軟刪除
>>>>>>> 4b452d7a8c1a7e6d24fe5ae82e5328c0a33453d5
        store.is_active = False
        db.commit()
    
    return RedirectResponse("/admin/stores", status_code=302)


# ===== JSON 匯入 =====
@router.get("/import")
async def import_page(
    request: Request,
    user = Depends(get_admin_user)
):
    return templates.TemplateResponse("admin/import.html", {
        "request": request,
        "user": user,
    })


@router.post("/import")
async def do_import(
    request: Request,
    json_file: UploadFile = File(None),
    json_text: str = Form(None),
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    try:
        if json_file and json_file.filename:
            content = await json_file.read()
            data = json.loads(content.decode('utf-8'))
        elif json_text:
            data = json.loads(json_text)
        else:
            raise ValueError("請提供 JSON 檔案或文字")
        
        result = import_store_from_json(db, data)
        
        return templates.TemplateResponse("admin/import.html", {
            "request": request,
            "user": user,
            "success": True,
            "message": f"成功匯入：{result['store_name']}，共 {result['item_count']} 個品項",
        })
    except Exception as e:
        return templates.TemplateResponse("admin/import.html", {
            "request": request,
            "user": user,
            "error": str(e),
        })


# ===== 使用者管理 =====
@router.get("/users")
async def user_list(
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    
<<<<<<< HEAD
=======
    # 計算在線人數
>>>>>>> 4b452d7a8c1a7e6d24fe5ae82e5328c0a33453d5
    thirty_minutes_ago = datetime.utcnow() - timedelta(minutes=30)
    try:
        online_count = db.query(User).filter(
            User.last_active_at >= thirty_minutes_ago
        ).count()
    except:
        online_count = 0
    
    return templates.TemplateResponse("admin/users.html", {
        "request": request,
        "user": user,
        "users": users,
        "online_count": online_count,
        "now": datetime.utcnow(),
    })


@router.get("/users/{user_id}")
async def user_detail(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin = Depends(get_admin_user)
):
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="用戶不存在")
    
<<<<<<< HEAD
=======
    # 取得該用戶的訂單統計
>>>>>>> 4b452d7a8c1a7e6d24fe5ae82e5328c0a33453d5
    order_count = db.query(Order).filter(
        Order.user_id == user_id,
        Order.status == OrderStatus.SUBMITTED
    ).count()
    
<<<<<<< HEAD
=======
    # 取得該用戶開過的團
>>>>>>> 4b452d7a8c1a7e6d24fe5ae82e5328c0a33453d5
    group_count = db.query(Group).filter(Group.owner_id == user_id).count()
    
    return templates.TemplateResponse("admin/user_detail.html", {
        "request": request,
        "user": admin,
        "target_user": target_user,
        "order_count": order_count,
        "group_count": group_count,
    })


@router.post("/users/{user_id}/toggle-admin")
async def toggle_admin(
    user_id: int,
    db: Session = Depends(get_db),
    admin = Depends(get_admin_user)
):
    target_user = db.query(User).filter(User.id == user_id).first()
    if target_user and target_user.id != admin.id:
        target_user.is_admin = not target_user.is_admin
        db.commit()
    
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/users/{user_id}/logout")
async def force_logout_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin = Depends(get_admin_user)
):
<<<<<<< HEAD
    target_user = db.query(User).filter(User.id == user_id).first()
    if target_user:
=======
    """強制登出特定用戶"""
    target_user = db.query(User).filter(User.id == user_id).first()
    if target_user:
        # 清除活動時間，讓 token 驗證失敗
>>>>>>> 4b452d7a8c1a7e6d24fe5ae82e5328c0a33453d5
        target_user.last_active_at = None
        db.commit()
    
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/users/logout-all")
async def logout_all_users(
    db: Session = Depends(get_db),
    admin = Depends(get_admin_user)
):
<<<<<<< HEAD
=======
    """一鍵登出所有用戶"""
    # 更新系統 token 版本
>>>>>>> 4b452d7a8c1a7e6d24fe5ae82e5328c0a33453d5
    try:
        from app.models.system import SystemSetting
        setting = db.query(SystemSetting).filter(
            SystemSetting.key == "token_version"
        ).first()
        if setting:
            setting.value = str(int(setting.value) + 1)
        else:
            setting = SystemSetting(key="token_version", value="2")
            db.add(setting)
        db.commit()
    except Exception as e:
        print(f"Logout all error: {e}")
    
    return RedirectResponse("/admin/users", status_code=302)


# ===== 公告管理 =====
@router.get("/announcements")
async def announcement_list(
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    try:
        from app.models.system import SystemSetting
        announcement = db.query(SystemSetting).filter(
            SystemSetting.key == "announcement"
        ).first()
        current_announcement = announcement.value if announcement else ""
    except:
        current_announcement = ""
    
    return templates.TemplateResponse("admin/announcements.html", {
        "request": request,
        "user": user,
        "current_announcement": current_announcement,
    })


@router.post("/announcements/update")
async def update_announcement(
    content: str = Form(""),
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    try:
        from app.models.system import SystemSetting
        announcement = db.query(SystemSetting).filter(
            SystemSetting.key == "announcement"
        ).first()
        if announcement:
            announcement.value = content
        else:
            announcement = SystemSetting(key="announcement", value=content)
            db.add(announcement)
        db.commit()
    except Exception as e:
        print(f"Announcement update error: {e}")
    
    return RedirectResponse("/admin/announcements", status_code=302)


# ===== 菜單品項管理 =====
@router.post("/stores/{store_id}/items/{item_id}/update")
async def update_menu_item(
    store_id: int,
    item_id: int,
    name: str = Form(...),
    price: float = Form(...),
    price_l: float = Form(None),
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if item:
        item.name = name
        item.price = price
        item.price_l = price_l
        db.commit()
    
    return RedirectResponse(f"/admin/stores/{store_id}", status_code=302)


@router.post("/stores/{store_id}/items/{item_id}/delete")
async def delete_menu_item(
    store_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_admin_user)
):
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    
    return RedirectResponse(f"/admin/stores/{store_id}", status_code=302)
