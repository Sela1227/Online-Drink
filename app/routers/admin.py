from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from pydantic import ValidationError
from datetime import datetime, timedelta, timezone
import json

from app.database import get_db
from app.config import get_settings
from app.models.store import Store, StoreOption, CategoryType, OptionType
from app.models.menu import Menu, MenuCategory, MenuItem, ItemOption
from app.models.group import Group, taipei_now, taipei_to_utc
from app.schemas.menu import MenuImport, FullImport, MenuContent
from app.services.auth import get_admin_user
from app.services.import_service import import_store_and_menu, import_menu
from app.services.import_analysis import analyze_menu_content, describe_loc, json_error_context
from app.services.menu_diff import diff_menu

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


# ===== 匯入錯誤中文化（V1.7.0）=====
_FIELD_NAMES = {
    "store": "店家", "name": "名稱", "category": "分類", "logo_url": "logo 網址",
    "sugar_options": "甜度選項", "ice_options": "冰塊選項", "toppings": "加料",
    "menu": "菜單", "categories": "分類", "items": "品項", "uncategorized": "未分類品項",
    "price": "價格", "price_l": "大杯價格", "options": "加購選項",
    "price_diff": "加購價差", "store_id": "店家編號", "mode": "匯入模式",
}


def _translate_loc(loc: tuple) -> str:
    """把 Pydantic 的 loc 路徑翻成中文，如 ('menu','categories',0,'items',3,'price') → 第 1 個分類的第 4 個品項的價格"""
    parts = []
    i = 0
    while i < len(loc):
        key = loc[i]
        if isinstance(key, int):
            i += 1
            continue
        cn = _FIELD_NAMES.get(str(key), str(key))
        if i + 1 < len(loc) and isinstance(loc[i + 1], int):
            parts.append(f"第 {loc[i + 1] + 1} 個{cn}")
            i += 2
        else:
            parts.append(cn)
            i += 1
    return "的".join(parts) if parts else "資料"


def _translate_error_type(err: dict) -> str:
    """把 Pydantic 錯誤類型翻成中文"""
    t = err.get("type", "")
    if t == "missing":
        return "缺少此必填欄位"
    if t == "value_error":
        # V2.14.0：schema 自己寫的中文訊息（價格容錯、說明長度）直接用
        return str(err.get("msg", "")).replace("Value error, ", "", 1) or "格式錯誤"
    if "decimal" in t or "float" in t:
        return "不是有效的數字（「$30」「30元」會自動轉換；時價請填 \"時價\"）"
    if "int" in t:
        return "不是有效的整數"
    if t == "literal_error" or "enum" in t:
        return "值不在允許範圍內（分類只能是 drink / meal / group_buy）"
    if "string" in t:
        return "應該是文字"
    if "list" in t:
        return "應該是清單格式"
    if "dict" in t or "model" in t:
        return "格式結構不正確"
    return err.get("msg", "格式錯誤")


def humanize_validation_error(e: ValidationError, raw: dict | None = None) -> list[str]:
    """把 Pydantic ValidationError 轉成一串中文錯誤訊息。

    V2.12.0：傳入原始資料時，路徑會帶名稱——
    「分類[3]「小菜」→ 品項[6]「黃金泡菜」→ 價格：不是有效的數字」
    而不是「第 3 個分類的第 6 個品項的價格」要人自己去數。
    """
    msgs = []
    for err in e.errors():
        loc = err.get("loc", ())
        loc_cn = describe_loc(loc, raw) if raw is not None else _translate_loc(loc)
        msg_cn = _translate_error_type(err)
        msgs.append(f"{loc_cn}：{msg_cn}")
    return msgs


def _render_import_result(request, user, *, error_messages=None, data=None,
                          is_full_import=False, existing_menu=None,
                          duplicate_store=None, json_str=None,
                          target_store=None, source_label=None, analysis=None,
                          error_context=None, ignored_store_block=False,
                          diff=None, existing_version=0):
    """render 匯入結果片段（htmx 用），錯誤或成功預覽二擇一"""
    return templates.TemplateResponse("admin/partials/import_result.html", {
        "request": request,
        "user": user,
        "error_messages": error_messages,
        "data": data,
        "is_full_import": is_full_import,
        "existing_menu": existing_menu,
        "duplicate_store": duplicate_store,
        "json_str": json_str,
        "target_store": target_store,
        "source_label": source_label,
        "analysis": analysis,
        "error_context": error_context,
        "ignored_store_block": ignored_store_block,
        "diff": diff,
        "existing_version": existing_version,
    })


@router.get("")
async def admin_home(request: Request, db: Session = Depends(get_db)):
    """後台首頁"""
    user = await get_admin_user(request, db)
    
    from app.models.user import User, Announcement
    from datetime import datetime, timedelta
    
    store_count = db.query(Store).filter(Store.is_personal != True).count()
    group_count = db.query(Group).count()
    user_count = db.query(User).filter(User.is_guest == False).count()
    
    # 計算在線人數
    online_threshold = datetime.utcnow() - timedelta(minutes=30)
    online_count = db.query(User).filter(
        User.last_active_at != None,
        User.last_active_at > online_threshold
    ).count()
    
    from app.models.user import Feedback
    
    # 公告（V2.10.0：數字改為「目前首頁顯示中的則數」，與團員看到的一致）
    active_announcement_count = db.query(Announcement).filter(
        Announcement.is_active == True,
        or_(Announcement.expires_at == None, Announcement.expires_at > datetime.utcnow()),
    ).count()
    
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
        "active_announcement_count": active_announcement_count,
        "feedback_count": feedback_count,
        "department_count": department_count,
        "recommendation_count": recommendation_count,
    })


@router.get("/stores")
async def store_list(request: Request, db: Session = Depends(get_db)):
    """店家列表"""
    user = await get_admin_user(request, db)
    
    from sqlalchemy import func as _f
    stores = db.query(Store).filter(Store.is_personal != True).options(
        joinedload(Store.branches)
    ).all()

    # V2.13.0：列表要顯示「現行菜單品項數」與「上次開團」——各一次聚合查詢，不逐店查（N+1）。
    # 排序交給前端按店名注音序（PostgreSQL 的 ORDER BY name 對中文是碼位序）。
    item_counts = dict(
        db.query(Menu.store_id, _f.count(MenuItem.id))
        .join(MenuItem, MenuItem.menu_id == Menu.id)
        .filter(Menu.is_active == True)
        .group_by(Menu.store_id).all()
    )
    last_groups = dict(
        db.query(Group.store_id, _f.max(Group.created_at))
        .filter(Group.store_id.isnot(None))
        .group_by(Group.store_id).all()
    )
    from app.models.group import taipei_to_utc as _t2u  # noqa: F401  (保留匯入點以供日後時區統一)

    return templates.TemplateResponse("admin/stores.html", {
        "item_counts": item_counts,
        "last_groups": last_groups,
        "request": request,
        "user": user,
        "stores": stores,
    })


@router.get("/stores/{store_id}/menus")
async def menu_list(store_id: int, imported: int = 0, cats: int = 0, items: int = 0):
    """V2.13.0：菜單版本頁併入工作台的「菜單」分頁"""
    q = f"?tab=menu&imported={imported}&cats={cats}&items={items}" if imported else "?tab=menu"
    return RedirectResponse(url=f"/admin/stores/{store_id}{q}", status_code=301)


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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=menu", status_code=302)


@router.get("/import")
async def import_page(request: Request, store_id: int = None, db: Session = Depends(get_db)):
    """匯入頁面"""
    user = await get_admin_user(request, db)
    
    stores = db.query(Store).filter(Store.is_active == True).order_by(Store.name).all()
    
    # 如果有指定 store_id，取得該店家
    selected_store = None
    recommendation = None
    if store_id:
        selected_store = db.query(Store).filter(Store.id == store_id).first()
    
    # V2.10.0：若該店家是從使用者推薦核准建立的，把推薦原始資料帶進來，
    # 管理員才能一邊看菜單照片一邊貼 JSON，不用另開分頁回推薦列表。
    if selected_store:
        from app.models.user import StoreRecommendation
        recommendation = db.query(StoreRecommendation).options(
            joinedload(StoreRecommendation.user)
        ).filter(
            StoreRecommendation.created_store_id == selected_store.id
        ).order_by(StoreRecommendation.reviewed_at.desc()).first()
    
    return templates.TemplateResponse("admin/import.html", {
        "request": request,
        "user": user,
        "stores": stores,
        "selected_store_id": store_id,
        "selected_store": selected_store,
        "recommendation": recommendation,
    })


@router.post("/import/preview")
async def import_preview(
    request: Request,
    json_text: str = Form(None),
    json_file: UploadFile = File(None),
    store_id: str = Form(None),
    db: Session = Depends(get_db),
):
    """匯入預覽（V1.7.0：htmx 片段，支援貼上 JSON / 上傳檔案，友善中文錯誤）"""
    user = await get_admin_user(request, db)

    # store_id 可能是空字串（下拉選「不指定」）或數字字串 → 安全轉 int
    store_id_int = None
    if store_id and str(store_id).strip().isdigit():
        store_id_int = int(store_id)

    # 取得 JSON 字串。V2.12.0：**上傳檔案優先**。原本是貼上優先，textarea 若留有
    # 上一次的內容，切到上傳分頁選了檔案，檔案會被無聲忽略、匯進去的是舊文字。
    # 使用者主動選了檔案，意圖很明確，應以檔案為準。
    json_str = None
    source_label = None
    if json_file and json_file.filename:
        content = await json_file.read()
        try:
            json_str = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return _render_import_result(request, user, error_messages=[
                "檔案編碼不是 UTF-8，請另存成 UTF-8 編碼的 JSON 檔再上傳"
            ])
        source_label = f"上傳檔案「{json_file.filename}」"
    elif json_text and json_text.strip():
        json_str = json_text.strip()
        source_label = "貼上的文字"
    if not json_str:
        return _render_import_result(request, user, error_messages=[
            "請貼上 JSON 內容，或切換到「上傳檔案」分頁選擇檔案"
        ])

    # 解析 JSON
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        # V2.12.0：附上出錯行前後三行原文，不然「第 42 行第 1 字」對使用者毫無幫助
        return _render_import_result(request, user, error_messages=[
            f"JSON 格式有誤（第 {e.lineno} 行第 {e.colno} 字附近）：常見原因是少了逗號、引號或大括號沒有成對"
        ], error_context=json_error_context(json_str, e.lineno))

    # 判斷匯入類型（V2.12.1：店家只由畫面上的選擇決定，JSON 裡的 store_id / mode 一律忽略）
    #
    # 原本有第三條分支「JSON 自帶 store_id」。它的存在讓使用者必須知道「店家編號」這個
    # 內部概念，AI 提示詞還得教人「先填 0 我再改」——結果就是 0 被原樣貼進來、各種
    # 「store_id 還是 0」的訊息、對照表。既然畫面上本來就能選店家，JSON 就不該再帶
    # 任何店家識別。有也不報錯，直接丟掉。
    ignored_store_block = False
    if store_id_int:
        menu_data = data.get("menu", data)
        if isinstance(data, dict) and "store" in data:
            # 使用者選了店家，卻貼了「新增店家」格式的 JSON：以畫面選的為準，但要告訴他
            ignored_store_block = True
        data = {"store_id": store_id_int, "mode": "new", "menu": menu_data}
        json_str = json.dumps(data, ensure_ascii=False)
        is_full_import = False
    elif "store" in data:
        is_full_import = True
        data = {"store": data["store"], "menu": data.get("menu", {})}
        json_str = json.dumps(data, ensure_ascii=False)
    else:
        return _render_import_result(request, user, error_messages=[
            "沒有選定店家。請在上方「匯到既有店家」選擇要匯入的店家，或從店家頁按「匯入新菜單」進來；",
            "若是要新增一家店，JSON 需要包含 store 欄位（店名與類別）。",
        ])

    # Pydantic 驗證
    try:
        if is_full_import:
            validated = FullImport(**data)
        else:
            validated = MenuImport(**data)
    except ValidationError as e:
        return _render_import_result(request, user, error_messages=humanize_validation_error(e, data))

    # 菜單匯入需確認店家存在
    existing_menu = None
    duplicate_store = None
    target_store = None
    if not is_full_import:
        # V2.12.1：store_id 只可能來自畫面選擇，不可能是 0；找不到代表店家被刪了
        store = db.query(Store).filter(Store.id == validated.store_id).first()
        target_store = store
        if not store:
            return _render_import_result(request, user, error_messages=[
                "選定的店家已不存在（可能剛被刪除），請重新選擇店家。",
            ])
        existing_menu = db.query(Menu).filter(
            Menu.store_id == validated.store_id,
            Menu.is_active == True
        ).first()
    else:
        # 完整匯入：偵測同名店家（完全比對）
        duplicate_store = db.query(Store).filter(Store.name == validated.store.name).first()
        if duplicate_store:
            # 同名店家會把菜單匯進既有店家，一樣要跟它的使用中版本比
            existing_menu = db.query(Menu).filter(
                Menu.store_id == duplicate_store.id,
                Menu.is_active == True
            ).first()

    # V2.13.1：有使用中版本就算差異，讓管理員按確認前看到這版會改掉什麼
    diff = None
    existing_version = 0
    if existing_menu:
        diff = diff_menu(existing_menu, validated.menu)
        # 店內序號（坑 #17：不用全域主鍵），最舊=第 1 版
        existing_version = db.query(Menu).filter(
            Menu.store_id == existing_menu.store_id,
            Menu.created_at <= existing_menu.created_at,
        ).count()

    # 成功 → 回傳預覽片段（V2.12.0：帶匯入對象、來源、品質分析）
    return _render_import_result(
        request, user,
        data=validated,
        is_full_import=is_full_import,
        existing_menu=existing_menu,
        duplicate_store=duplicate_store,
        json_str=json_str,
        target_store=(target_store if not is_full_import else None),
        source_label=source_label,
        analysis=analyze_menu_content(validated.menu),
        ignored_store_block=ignored_store_block,
        diff=diff,
        existing_version=existing_version,
    )


def _count_import(content) -> tuple[int, int]:
    """算匯入了幾個分類、幾個品項（V2.10.0：給匯入成功提示用）"""
    cats = content.categories or []
    loose = content.items or []
    item_count = sum(len(c.items) for c in cats) + len(loose)
    return len(cats), item_count


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
    try:
        if "store_id" in data:
            # 菜單更新模式（忽略 store 欄位）
            menu_data = data.get("menu", {})
            if not menu_data:
                raise HTTPException(status_code=400, detail="JSON 缺少 menu 內容")
            validated = MenuImport(
                store_id=data["store_id"],
                mode="new",  # V2.11.1 P1-04：忽略外部送進來的 mode
                menu=menu_data
            )
            # V2.12.1：店家必須存在，否則 import_menu 會在外鍵上 500
            if not db.query(Store.id).filter(Store.id == validated.store_id).first():
                raise HTTPException(status_code=400, detail="選定的店家不存在，請回匯入頁重新選擇")
            menu = import_menu(db, validated)
            target_store_id = menu.store_id
        elif "store" in data:
            # 完整匯入模式（新增店家 + 菜單）
            validated = FullImport(**data)
            store = import_store_and_menu(db, validated)
            target_store_id = store.id
        else:
            raise HTTPException(status_code=400, detail="JSON 格式錯誤")
        
        # V2.12.0：blockers 在後端也要擋，不能只靠預覽頁不顯示按鈕
        _blk = analyze_menu_content(validated.menu)["blockers"]
        if _blk:
            raise HTTPException(status_code=400, detail="菜單有必須修正的問題：" + "；".join(_blk[:3]))
        
        # V2.10.0：匯完直接去菜單版本頁驗收，不再丟回儀表板
        cat_count, item_count = _count_import(validated.menu)
        return RedirectResponse(
            url=f"/admin/stores/{target_store_id}?tab=menu&imported=1&cats={cat_count}&items={item_count}",
            status_code=302,
        )
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


def _delete_group_cascade(db: Session, group: Group):
    """安全刪團（含 FK 連鎖：請客記錄 / 部門關聯 / 訂單 / 訂單項目的選項與加料）"""
    from app.models.treat import TreatRecord
    from app.models.department import GroupDepartment
    from app.models.order import Order, OrderItemOption, OrderItemTopping
    db.query(TreatRecord).filter(TreatRecord.group_id == group.id).delete()
    db.query(GroupDepartment).filter(GroupDepartment.group_id == group.id).delete()
    orders = db.query(Order).filter(Order.group_id == group.id).all()
    for order in orders:
        for item in order.items:
            db.query(OrderItemOption).filter(OrderItemOption.order_item_id == item.id).delete()
            db.query(OrderItemTopping).filter(OrderItemTopping.order_item_id == item.id).delete()
            db.delete(item)
        db.delete(order)
    db.delete(group)


@router.post("/groups/cleanup-test")
async def cleanup_test_groups(request: Request, db: Session = Depends(get_db)):
    """清除測試團：已截止、且沒有人下單（或只有團主自己下單）的團。

    V2.10.0：加上「僅限已截止」條件。原本查詢不篩團單狀態，而
    `all()` 對零訂單恆為真，導致「早上開、還沒人點」的進行中團單
    會被當成測試團實體刪除且不可復原。
    """
    await get_admin_user(request, db)
    # V2.10.1：deadline 是台北牆上時間，用 utcnow() 比會差 8 小時，
    # 害當天剛截止的測試團要等到晚上才清得掉（坑 #25）
    now = taipei_now()
    groups = db.query(Group).filter(
        or_(Group.is_closed == True, Group.deadline <= now)
    ).all()
    removed = 0
    for g in groups:
        # 沒有訂單，或全部訂單都是團主自己的 → 視為測試團
        if all(o.user_id == g.owner_id for o in g.orders):
            _delete_group_cascade(db, g)
            removed += 1
    db.commit()
    return RedirectResponse(url=f"/admin/groups?cleaned={removed}", status_code=302)


@router.post("/groups/{group_id}/delete")
async def admin_delete_group(group_id: int, request: Request, db: Session = Depends(get_db)):
    """管理員刪除單一團單"""
    await get_admin_user(request, db)
    group = db.query(Group).filter(Group.id == group_id).first()
    if group:
        _delete_group_cascade(db, group)
        db.commit()
    return RedirectResponse(url="/admin/groups", status_code=302)


@router.post("/stores/{store_id}/toggle")
async def toggle_store(store_id: int, request: Request, db: Session = Depends(get_db)):
    """啟用/停用店家"""
    user = await get_admin_user(request, db)
    
    store = db.query(Store).filter(Store.id == store_id).first()
    if store:
        store.is_active = not store.is_active
        db.commit()
    
    # 檢查來源頁面，回到對應頁面
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=more", status_code=302)


@router.post("/stores/{store_id}/delete")
async def delete_store(store_id: int, request: Request, confirm_name: str = Form(""), db: Session = Depends(get_db)):
    """刪除店家（V1.10.0：斷開團單/訂單連結但保留歷史，不再被舊團單擋）"""
    user = await get_admin_user(request, db)

    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")

    # V2.13.0：不可復原的操作改成輸入店名確認（V2.11 審稿的危險操作包，延到現在）。
    # 歷史團的 store_id 會被清成 NULL、菜單全部刪除，confirm() 一下就刪太輕率。
    if confirm_name.strip() != store.name.strip():
        raise HTTPException(status_code=400, detail="輸入的店名與要刪除的店家不符，未刪除")

    store_name = store.name

    # 用 raw SQL 依「子→父」順序斷開外鍵、刪除資料。
    # 訂單明細（order_items / order_item_options）已有 item_name / option_name 等快照欄位，
    # 斷開 FK 後歷史訂單仍可完整顯示。團單保留，store_id/menu_id 設 NULL + 店名快照。
    from sqlalchemy import text as _sql
    sid = store_id
    db.execute(_sql("""
        UPDATE order_items SET menu_item_id = NULL
        WHERE menu_item_id IN (
            SELECT mi.id FROM menu_items mi
            JOIN menus m ON mi.menu_id = m.id
            WHERE m.store_id = :sid
        )
    """), {"sid": sid})
    db.execute(_sql("""
        UPDATE order_item_options SET item_option_id = NULL
        WHERE item_option_id IN (
            SELECT io.id FROM item_options io
            JOIN menu_items mi ON io.menu_item_id = mi.id
            JOIN menus m ON mi.menu_id = m.id
            WHERE m.store_id = :sid
        )
    """), {"sid": sid})
    # 加料快照：store_toppings 被刪後，order_item_toppings.store_topping_id 已是 nullable，直接斷開
    db.execute(_sql("""
        UPDATE order_item_toppings SET store_topping_id = NULL
        WHERE store_topping_id IN (
            SELECT id FROM store_toppings WHERE store_id = :sid
        )
    """), {"sid": sid})
    # 團單：填店名快照 + 斷開 store_id / menu_id
    db.execute(_sql("""
        UPDATE groups SET store_name = COALESCE(store_name, :sname), store_id = NULL, menu_id = NULL
        WHERE store_id = :sid
    """), {"sid": sid, "sname": store_name})

    # 候補快照斷開（V2.4.0 新表，原刪除流程未涵蓋 → 會擋住 DELETE menu_items）
    db.execute(_sql("""
        UPDATE order_item_backups SET menu_item_id = NULL
        WHERE menu_item_id IN (
            SELECT mi.id FROM menu_items mi
            JOIN menus m ON mi.menu_id = m.id
            WHERE m.store_id = :sid
        )
    """), {"sid": sid})
    
    # 刪菜單樹（item_options → menu_items → menu_categories → menus）
    db.execute(_sql("""
        DELETE FROM item_options WHERE menu_item_id IN (
            SELECT mi.id FROM menu_items mi JOIN menus m ON mi.menu_id = m.id WHERE m.store_id = :sid
        )
    """), {"sid": sid})
    db.execute(_sql("DELETE FROM menu_items WHERE menu_id IN (SELECT id FROM menus WHERE store_id = :sid)"), {"sid": sid})
    db.execute(_sql("DELETE FROM menu_categories WHERE menu_id IN (SELECT id FROM menus WHERE store_id = :sid)"), {"sid": sid})
    db.execute(_sql("DELETE FROM menus WHERE store_id = :sid"), {"sid": sid})
    # 刪店家加料、店家選項、分店、店家本身
    db.execute(_sql("DELETE FROM store_toppings WHERE store_id = :sid"), {"sid": sid})
    db.execute(_sql("DELETE FROM store_options WHERE store_id = :sid"), {"sid": sid})
    db.execute(_sql("DELETE FROM store_branches WHERE store_id = :sid"), {"sid": sid})
    db.execute(_sql("DELETE FROM user_favorites  WHERE store_id = :sid"), {"sid": sid})
    db.execute(_sql("DELETE FROM group_templates WHERE store_id = :sid"), {"sid": sid})
    # V2.11.1 P0-04：vote_options.store_id 是 NOT NULL 外鍵，原本完全沒處理，
    # 店家只要被任何投票引用過就會在最後一步觸發 IntegrityError（500），刪不掉。
    # 「每加新表要回頭檢查刪除流程」這條教訓在這裡又發生一次。
    db.execute(_sql("DELETE FROM vote_records WHERE option_id IN "
                    "(SELECT id FROM vote_options WHERE store_id = :sid)"), {"sid": sid})
    db.execute(_sql("DELETE FROM vote_options WHERE store_id = :sid"), {"sid": sid})
    db.execute(_sql("UPDATE votes SET winner_store_id = NULL WHERE winner_store_id = :sid"), {"sid": sid})
    # 不要依賴 ON DELETE CASCADE（P2-02：store_departments 實際上沒有設定）
    db.execute(_sql("DELETE FROM store_departments WHERE store_id = :sid"), {"sid": sid})
    db.execute(_sql("UPDATE store_recommendations SET created_store_id = NULL WHERE created_store_id = :sid"), {"sid": sid})

    db.execute(_sql("DELETE FROM stores WHERE id = :sid"), {"sid": sid})

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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=ops", status_code=302)


@router.get("/stores/new")
async def new_store_page(request: Request, db: Session = Depends(get_db)):
    """手動新增店家（V2.13.0；上一輪管理後台審稿的提案 2）。

    原本新增店家只能靠 JSON 匯入帶 store 區塊、或核准推薦。只填店名與類別就建，
    建好直接進工作台，頂部就有「更新菜單」。
    注意：這條路由必須排在 /stores/{store_id} 之前，否則 "new" 會被當成 store_id 而 422。
    """
    user = await get_admin_user(request, db)
    existing = [s.name for s in db.query(Store.name).filter(Store.is_personal != True).all()]
    return templates.TemplateResponse("admin/store_new.html", {
        "request": request, "user": user, "existing_names": existing,
    })


@router.post("/stores/new")
async def create_store_manual(
    request: Request,
    name: str = Form(...),
    category: str = Form(...),
    phone: str = Form(None),
    address: str = Form(None),
    db: Session = Depends(get_db),
):
    user = await get_admin_user(request, db)
    from app.services.validation import clean_text
    name = clean_text(name, 100, field="店名", required=True)
    if category not in ("drink", "meal", "group_buy"):
        raise HTTPException(status_code=400, detail="類別錯誤")
    store = Store(
        name=name,
        category=CategoryType(category),
        phone=clean_text(phone, 50, field="電話"),
        address=clean_text(address, 300, field="地址"),
        is_active=True,
    )
    db.add(store)
    db.commit()
    return RedirectResponse(url=f"/admin/stores/{store.id}?tab=menu&created=1", status_code=302)


@router.get("/stores/{store_id}")
async def store_workbench(
    store_id: int,
    request: Request,
    tab: str = "menu",
    created: int = 0,
    imported: int = 0,
    cats: int = 0,
    items: int = 0,
    db: Session = Depends(get_db),
):
    """店家工作台（V2.13.0）：一頁取代 store_detail + store_edit + menus。

    原本同一家店要管三個網址，而且 detail 與 edit **都有**分店新增／刪除與停用／刪除
    （detail 的分店有啟用切換、edit 的沒有——已經不同步了）。合併後每個功能只有一處。
    分頁用 Alpine x-show 切換不跳頁，填到一半切去看別的分頁不會丟；各區保留自己的
    儲存鈕，因為後端是六支獨立的 POST，一顆全域儲存鈕不可能原子保存。
    """
    from app.models.store import StoreBranch, StoreTopping
    from app.models.department import Department, StoreDepartment
    from sqlalchemy import func as _f
    user = await get_admin_user(request, db)

    store = db.query(Store).options(
        joinedload(Store.branches),
        joinedload(Store.toppings),
        joinedload(Store.options)
    ).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")

    departments = db.query(Department).filter(Department.is_active == True).all()
    store_dept_ids = [sd.department_id for sd in db.query(StoreDepartment).filter(StoreDepartment.store_id == store_id).all()]

    # 菜單版本：新到舊；序號最舊=第 1 版
    menus = db.query(Menu).filter(Menu.store_id == store_id).order_by(Menu.created_at.desc()).all()
    total = len(menus)
    menu_versions = [(m, total - idx) for idx, m in enumerate(menus)]
    active_menu = next((m for m in menus if m.is_active), None)
    active_version = next((v for m, v in menu_versions if active_menu and m.id == active_menu.id), 0)
    active_item_count = sum(len(c.items) for c in active_menu.categories) + len([i for i in active_menu.items if i.category_id is None]) if active_menu else 0

    last_group = db.query(_f.max(Group.created_at)).filter(Group.store_id == store_id).scalar()
    group_count = db.query(_f.count(Group.id)).filter(Group.store_id == store_id).scalar() or 0
    active_group_count = db.query(_f.count(Group.id)).filter(
        Group.store_id == store_id, Group.is_closed == False, Group.deadline > taipei_now()
    ).scalar() or 0

    def _joined(opt_type):
        vals = sorted([o for o in store.options if o.option_type == opt_type], key=lambda o: o.sort_order)
        return ",".join(o.option_value for o in vals)

    if tab not in ("menu", "info", "ops", "more"):
        tab = "menu"

    return templates.TemplateResponse("admin/store_workbench.html", {
        "tab": tab,
        "created": created,
        "imported": imported, "imported_cats": cats, "imported_items": items,
        "menu_versions": menu_versions,
        "active_menu": active_menu,
        "active_version": active_version,
        "active_item_count": active_item_count,
        "last_group": last_group,
        "group_count": group_count,
        "menu_count": total,
        "active_group_count": active_group_count,
        "sugar_options": _joined(OptionType.SUGAR),
        "ice_options": _joined(OptionType.ICE),
        "request": request,
        "user": user,
        "store": store,
        "departments": departments,
        "store_dept_ids": store_dept_ids,
    })


@router.get("/stores/{store_id}/edit")
async def edit_store_page(store_id: int):
    """V2.13.0：編輯頁併入工作台，舊連結與書籤轉過去"""
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=info", status_code=301)


def _parse_option_values(raw: str) -> list[str]:
    """逗號分隔字串 → 去重、保序、去空白的選項清單（V2.10.0）。

    容忍全形逗號；單值長度受 StoreOption.option_value String(50) 限制。
    """
    result = []
    for part in (raw or "").replace("，", ",").split(","):
        value = part.strip()
        if value and value not in result:
            result.append(value[:50])
    return result[:20]


@router.post("/stores/{store_id}/options")
async def update_store_options(
    store_id: int,
    request: Request,
    sugar_options: str = Form(""),
    ice_options: str = Form(""),
    db: Session = Depends(get_db),
):
    """儲存飲料的甜度／冰塊選項（V2.10.0）。

    整批取代：刪掉這家店既有的 store_options 再依填寫順序重建。
    甜冰有顯示順序，逐筆增刪要另做排序 UI，而這本來就是一次設定好的東西。
    訂單存的是 OrderItem.sugar/.ice 字串快照，不吃 store_options 的 id，
    所以重建不影響任何歷史訂單。

    原本只有完整 JSON 匯入會建立這些選項，導致從推薦核准建立的飲料店
    永遠沒有甜度冰塊，而後台無處可補（提案 3）。
    """
    user = await get_admin_user(request, db)
    
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    sugars = _parse_option_values(sugar_options)
    ices = _parse_option_values(ice_options)
    
    db.query(StoreOption).filter(StoreOption.store_id == store_id).delete(
        synchronize_session=False
    )
    for idx, value in enumerate(sugars):
        db.add(StoreOption(
            store_id=store_id, option_type=OptionType.SUGAR,
            option_value=value, sort_order=idx,
        ))
    for idx, value in enumerate(ices):
        db.add(StoreOption(
            store_id=store_id, option_type=OptionType.ICE,
            option_value=value, sort_order=idx,
        ))
    
    db.commit()
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=ops", status_code=302)


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
    provides_invoice: bool = Form(False),
    provides_receipt: bool = Form(False),
    logo_file: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    """更新店家資料"""
    from app.services.upload_service import upload_image
    
    user = await get_admin_user(request, db)
    
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    
    # V2.11.3 R-09：原本只 strip 不限長度。SQLite 照收，PostgreSQL 超過欄位長度會 500
    from app.services.validation import clean_text
    store.name = clean_text(name, 100, field="店名", required=True)
    store.phone = clean_text(phone, 50, field="電話")
    store.address = clean_text(address, 300, field="地址")
    # V2.11.1 P0-06：只 strip 不驗協定，javascript: 會被原樣寫進 href
    from app.services.validation import clean_http_url
    store.website_url = clean_http_url(website_url, field="官網網址")
    store.google_maps_url = clean_http_url(google_maps_url, field="Google 地圖網址")
    store.ubereats_url = clean_http_url(ubereats_url, field="Uber Eats 網址")
    store.foodpanda_url = clean_http_url(foodpanda_url, field="foodpanda 網址")
    store.provides_invoice = provides_invoice
    store.provides_receipt = provides_receipt
    
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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=info", status_code=302)


@router.get("/users")
async def user_list(request: Request, sort: str = "created", db: Session = Depends(get_db)):
    """使用者列表"""
    user = await get_admin_user(request, db)
    
    from app.models.user import User, SystemSetting
    from datetime import datetime, timedelta
    from sqlalchemy import nullslast
    
    sort_map = {
        "created": User.created_at.desc(),
        "last_login": nullslast(User.last_login_at.desc()),
        "last_active": nullslast(User.last_active_at.desc()),
        "name": User.display_name.asc(),
    }
    if sort not in sort_map:
        sort = "created"
    users = db.query(User).filter(User.is_guest == False).order_by(sort_map[sort]).all()
    
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
        "sort": sort,
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


@router.get("/users-duplicates")
async def users_duplicates(request: Request, db: Session = Depends(get_db)):
    """診斷：找出同名用戶（判斷是否真重複帳號）"""
    admin = await get_admin_user(request, db)

    from app.models.user import User
    from app.models.order import Order
    from collections import defaultdict

    all_users = db.query(User).filter(User.is_guest == False).all()
    # 依 show_name 分組（排除訪客帳號）
    by_name = defaultdict(list)
    for u in all_users:
        by_name[u.show_name].append(u)

    # 只保留有重複名稱的組
    dup_groups = []
    for name, users in by_name.items():
        if len(users) > 1:
            rows = []
            for u in users:
                order_count = db.query(Order).filter(Order.user_id == u.id).count()
                rows.append({
                    "id": u.id,
                    "line_tail": u.line_user_id[-6:] if u.line_user_id else "（無）",
                    "line_full": u.line_user_id or "",
                    "display_name": u.display_name,
                    "nickname": u.nickname,
                    "created_at": u.created_at,
                    "last_active_at": u.last_active_at,
                    "order_count": order_count,
                    "has_picture": bool(u.picture_url),
                })
            # 同組內若有「相同 line_user_id」才是真重複（理論上 unique 不該發生）
            line_ids = [u.line_user_id for u in users]
            true_dup = len(line_ids) != len(set(line_ids))
            dup_groups.append({
                "name": name,
                "count": len(users),
                "rows": sorted(rows, key=lambda r: r["order_count"], reverse=True),
                "true_dup": true_dup,
            })

    dup_groups.sort(key=lambda g: g["count"], reverse=True)

    return templates.TemplateResponse("admin/users_duplicates.html", {
        "request": request,
        "user": admin,
        "dup_groups": dup_groups,
        "total_users": len(all_users),
        "guest_count": db.query(User).filter(User.is_guest == True).count(),
    })


@router.post("/users-cleanup-guests")
async def cleanup_guest_users(request: Request, db: Session = Depends(get_db)):
    """清理訪客空殼帳號（徹底刪除，含其訂單；使用者確認舊訪客訂單不重要）"""
    admin = await get_admin_user(request, db)

    from app.models.user import User
    from app.models.group import Group
    from sqlalchemy import text as _sql, bindparam

    # 找出所有訪客帳號 id（排除有開團的，避免動到團單擁有權）
    all_guest_ids = [g.id for g in db.query(User).filter(User.is_guest == True).all()]
    owner_ids = {gid for (gid,) in db.query(Group.owner_id).filter(Group.owner_id.in_(all_guest_ids)).all()} if all_guest_ids else set()
    guest_ids = [gid for gid in all_guest_ids if gid not in owner_ids]
    if not guest_ids:
        return RedirectResponse(url="/admin/users-duplicates?cleaned=0", status_code=302)

    params = {"ids": tuple(guest_ids)}
    def _exec(sql):
        db.execute(_sql(sql).bindparams(bindparam("ids", expanding=True)), params)

    # 依子→父順序斷鏈刪除（訪客的訂單樹）
    _exec("""
        DELETE FROM order_item_toppings WHERE order_item_id IN (
            SELECT oi.id FROM order_items oi JOIN orders o ON oi.order_id = o.id
            WHERE o.user_id IN :ids
        )
    """)
    _exec("""
        DELETE FROM order_item_options WHERE order_item_id IN (
            SELECT oi.id FROM order_items oi JOIN orders o ON oi.order_id = o.id
            WHERE o.user_id IN :ids
        )
    """)
    _exec("DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE user_id IN :ids)")
    _exec("DELETE FROM orders WHERE user_id IN :ids")
    for tbl in ["user_departments", "user_favorites", "user_presets"]:
        try:
            _exec(f"DELETE FROM {tbl} WHERE user_id IN :ids")
        except Exception:
            pass
    _exec("DELETE FROM users WHERE id IN :ids")
    db.commit()

    return RedirectResponse(
        url=f"/admin/users-duplicates?cleaned={len(guest_ids)}",
        status_code=302
    )


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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=ops", status_code=302)


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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=ops", status_code=302)


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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=ops", status_code=302)


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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=ops", status_code=302)


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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=ops", status_code=302)


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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=ops", status_code=302)


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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=ops", status_code=302)


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
        User.is_guest == False,
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
    
    from app.models.user import Announcement
    
    expires_dt = _parse_taipei_to_utc(expires_at)
    
    ann = Announcement(
        title=title.strip(),
        content=content.strip(),
        is_pinned=is_pinned,
        expires_at=expires_dt,
        created_by_id=user.id,
    )
    db.add(ann)
    
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
    
    ann.expires_at = _parse_taipei_to_utc(expires_at)
    
    db.commit()
    
    return RedirectResponse(url="/admin/announcements", status_code=302)


def _safe_url_or_none(value):
    """驗不過就回 None（V2.11.1 P0-06，用於複製既有資料的場合）"""
    from app.services.validation import clean_http_url
    try:
        return clean_http_url(value)
    except Exception:
        return None


def _parse_taipei_to_utc(value: str):
    """datetime-local 表單值（台北牆上時間）→ naive UTC，與全站儲存慣例一致。

    V2.10.0：原本 fromisoformat 直接存，等於把台北時間當 UTC 存，差 8 小時。
    過去 expires_at 完全沒被比對過所以沒人發現；現在首頁會依它過濾，必須正確。
    """
    if not value:
        return None
    try:
        local_dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    # V2.10.2：轉換邏輯收斂到 taipei_to_utc()，這裡只負責解析字串
    return taipei_to_utc(local_dt)


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
        # V2.11.1 P0-06：舊資料可能是核准前就存進去的惡意協定，複製時再驗一次；
        # 擋不過就留空而不是讓整個核准失敗（推薦本身沒問題，只是網址不能用）
        website_url=_safe_url_or_none(rec.menu_url),
    )
    db.add(new_store)
    db.flush()  # 取得新店家 ID
    
    # 更新推薦狀態
    rec.status = "approved"
    rec.reviewed_at = datetime.utcnow()
    rec.reviewer_id = user.id
    rec.created_store_id = new_store.id
    
    db.commit()
    
    # V2.10.0：核准是起點不是終點 — 直接送到菜單匯入頁（該頁有「稍後再匯入」出口）
    return RedirectResponse(url=f"/admin/import?store_id={new_store.id}", status_code=302)


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
