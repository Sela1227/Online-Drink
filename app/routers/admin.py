from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, Response
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
from app.services.store_match import similar_stores as _similar_stores  # V2.16.1 B-8
from app.schemas.menu import UNCLEAR_PRICE_MSG  # V2.16.1 B-7

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
from app.templating import register_filters as _register_filters  # V2.15.1：money/taipei 共用
_register_filters(templates.env)
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
                          diff=None, existing_version=0, conflict=False, next_version=0,
                          stale=False, src_digest=None, cleaned_note=False,
                          unclear_items=None, similar=None):
    """render 匯入結果片段（htmx 用），錯誤或成功預覽二擇一"""
    return templates.TemplateResponse(request, "admin/partials/import_result.html", {
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
        "conflict": conflict,
        "next_version": next_version,
        "stale": stale,
        "src_digest": src_digest,
        "cleaned_note": cleaned_note,
        "unclear_items": unclear_items or [],  # V2.16.1 B-7：AI 填 "?" 的品項位置
        "similar": similar or [],              # V2.16.1 B-8：[(store, ratio, version, item_count)]
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
    
    return templates.TemplateResponse(request, "admin/index.html", {
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
    # V2.16.2：排序可選熱門——全體累計開團次數
    group_counts = dict(
        db.query(Group.store_id, _f.count(Group.id))
        .filter(Group.store_id.isnot(None))
        .group_by(Group.store_id).all()
    )
    from app.models.group import taipei_to_utc as _t2u  # noqa: F401  (保留匯入點以供日後時區統一)

    return templates.TemplateResponse(request, "admin/stores.html", {
        "item_counts": item_counts,
        "last_groups": last_groups,
        "group_counts": group_counts,
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
async def import_page(request: Request, store_id: int = None, load: str = None, db: Session = Depends(get_db)):
    """匯入頁面。V2.16.1：`load=current` 進頁就帶入使用中菜單（工作台「改幾個價格」）"""
    user = await get_admin_user(request, db)
    
    # V2.15.1 審核 P3-6：排除代購個人店；順序交給前端注音序（與店家列表一致）
    stores = db.query(Store).filter(Store.is_active == True, Store.is_personal != True).order_by(Store.name).all()
    # V2.16.1 B-10：搜尋選店要顯示「第 N 版 · M 項」，兩次聚合查詢不逐店
    stores_json = _stores_for_picker(db, stores)
    
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
    
    # V2.15.0：「匯入至」那列顯示使用中第幾版、幾項
    active_version, active_item_count = 0, 0
    if selected_store:
        _am = db.query(Menu).filter(Menu.store_id == selected_store.id, Menu.is_active == True).first()
        if _am:
            active_version = db.query(Menu).filter(Menu.store_id == selected_store.id, Menu.created_at <= _am.created_at).count()
            active_item_count = db.query(MenuItem).filter(MenuItem.menu_id == _am.id).count()

    return templates.TemplateResponse(request, "admin/import.html", {
        "request": request,
        "user": user,
        "stores": stores,
        "selected_store_id": store_id,
        "selected_store": selected_store,
        "recommendation": recommendation,
        "active_version": active_version,
        "active_item_count": active_item_count,
        "stores_json": stores_json,
        "load_current": (load == "current" and selected_store is not None),
    })


def _stores_for_picker(db, stores):
    """[{id, name, version, items}]，version=使用中是第幾版（店內序號，坑 #17），items=使用中品項數；沒菜單都是 0"""
    from sqlalchemy import func as _f
    ids = [s.id for s in stores]
    if not ids:
        return []
    menus = db.query(Menu.id, Menu.store_id, Menu.created_at, Menu.is_active).filter(Menu.store_id.in_(ids)).all()
    by_store = {}
    for m in menus:
        by_store.setdefault(m.store_id, []).append(m)
    active_ids = [m.id for m in menus if m.is_active]
    counts = {}
    if active_ids:
        counts = dict(db.query(MenuItem.menu_id, _f.count(MenuItem.id)).filter(MenuItem.menu_id.in_(active_ids)).group_by(MenuItem.menu_id).all())
    out = []
    for s in stores:
        ms = sorted(by_store.get(s.id, []), key=lambda m: (m.created_at, m.id))
        ver, n = 0, 0
        for i, m in enumerate(ms, 1):
            if m.is_active:
                ver, n = i, counts.get(m.id, 0)
                break
        out.append({"id": s.id, "name": s.name, "version": ver, "items": n})
    return out


def _menu_to_import_json(menu) -> dict:
    """V2.16.1 B-5：使用中版本 → 匯入格式（只放匯入會讀的欄位；時價寫 "時價"、停售／說明有才帶）"""
    def _num(d):
        if d is None:
            return None
        f = float(d)
        return int(f) if f == int(f) else f

    def _item(it):
        o = {"name": it.name, "price": "時價" if it.price_tbd else _num(it.price)}
        if it.price_l is not None and not it.price_tbd:
            o["price_l"] = _num(it.price_l)
        if it.options:
            o["options"] = [{"name": op.name, "price_diff": _num(op.price_diff) or 0} for op in it.options]
        if it.is_available is False:
            o["is_available"] = False
        if it.description:
            o["note"] = it.description
        return o

    cats = [{"name": c.name, "items": [_item(i) for i in c.items]} for c in (menu.categories or [])]
    loose = [_item(i) for i in (menu.items or []) if i.category_id is None]
    body = {"categories": cats}
    if loose:
        body["items"] = loose
    return {"menu": body}


@router.get("/stores/{store_id}/menu-json")
async def store_menu_json(store_id: int, request: Request, db: Session = Depends(get_db)):
    """V2.16.1 B-5：匯入頁「帶入目前菜單」用；回使用中版本的匯入格式 JSON"""
    from fastapi.responses import JSONResponse
    await get_admin_user(request, db)
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")
    menu = db.query(Menu).filter(Menu.store_id == store_id, Menu.is_active == True).first()
    if not menu:
        raise HTTPException(status_code=404, detail="這家店還沒有使用中的菜單")
    version = db.query(Menu).filter(Menu.store_id == store_id, Menu.created_at <= menu.created_at).count()
    data = _menu_to_import_json(menu)
    n = sum(len(c["items"]) for c in data["menu"]["categories"]) + len(data["menu"].get("items", []))
    return JSONResponse({"version": version, "items": n,
                         "text": json.dumps(data, ensure_ascii=False, indent=2)})


@router.post("/import/preview")
async def import_preview(
    request: Request,
    json_text: str = Form(None),
    json_file: UploadFile = File(None),
    store_id: str = Form(None),
    new_store_name: str = Form(None),
    new_store_category: str = Form(None),
    db: Session = Depends(get_db),
):
    """匯入預覽（V1.7.0：htmx 片段；V2.15.0 貼上自動觸發；V2.15.1 新店家欄位、清理 AI 包裝、原文雜湊）"""
    user = await get_admin_user(request, db)
    store_id_int = _parse_store_id(store_id)

    json_str = None
    source_label = None
    if json_file and json_file.filename:
        content = await json_file.read()
        try:
            json_str = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return _render_import_result(request, user, error_messages=["檔案編碼不是 UTF-8，請另存成 UTF-8 編碼再試"])
        source_label = f"檔案「{json_file.filename}」"
    elif json_text and json_text.strip():
        json_str = json_text.strip()
        source_label = "貼上的文字"
    if not json_str:
        return _render_import_result(request, user, error_messages=["請把菜單資料貼進上方的輸入框"])

    return _preview_from_text(request, user, db, json_str, store_id_int, source_label,
                              new_store_name=new_store_name, new_store_category=new_store_category)


def _parse_store_id(store_id) -> int | None:
    """表單的 store_id 可能是空字串（新增一家店）或數字字串"""
    if store_id and str(store_id).strip().isdigit():
        return int(store_id)
    return None


def _src_digest(raw: str) -> str:
    """V2.15.1 審核 P1-1：預覽時記輸入框原文的雜湊，確認時比對，內容變了就不寫入"""
    import hashlib
    return hashlib.sha256((raw or "").strip().encode("utf-8")).hexdigest()[:16]


def clean_pasted_json(s: str) -> tuple[str, bool]:
    """V2.15.1 審稿 B-1：去掉 AI 回覆常見的包裝——```json 圍欄、前後的說明文字、BOM。
    回傳 (清理後, 是否有清理)。只在原文解析失敗時才用，避免動到正常資料。"""
    import re as _re
    orig = (s or "").strip()
    t = orig.lstrip("\ufeff").strip()
    m = _re.search(r"```(?:json|JSON)?\s*(.*?)```", t, _re.S)
    if m:
        t = m.group(1).strip()
    i, j = t.find("{"), t.rfind("}")
    if i != -1 and j > i:
        t = t[i:j + 1]
    return t, t != orig


def _preview_from_text(request, user, db, json_str, store_id_int, source_label=None,
                       new_store_name=None, new_store_category=None, conflict=False, stale=False):
    """原文 → 解析（含 B-1 清理）→ 新店家欄位覆寫 → _preview_from_data"""
    cleaned_note = False
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        cleaned, changed = clean_pasted_json(json_str)
        data = None
        if changed:
            try:
                data = json.loads(cleaned)
                cleaned_note = True
            except json.JSONDecodeError:
                data = None
        if data is None:
            # V2.12.0：附上出錯行前後三行原文，不然「第 42 行第 1 字」對使用者毫無幫助
            return _render_import_result(request, user, error_messages=[
                f"資料格式有誤（第 {e.lineno} 行第 {e.colno} 字附近）：常見原因是少了逗號、引號或大括號沒有成對"
            ], error_context=json_error_context(json_str, e.lineno))

    if not isinstance(data, dict):
        return _render_import_result(request, user, error_messages=["資料最外層必須是物件（{...}），不能是陣列或單一值"])

    # V2.15.1 審核 P2-9：新增一家店時，店名與類別由畫面欄位決定（AI 指令要求店名留空，介面要有地方補）
    if not store_id_int:
        nm = (new_store_name or "").strip()
        cat = (new_store_category or "").strip().lower()
        if nm or cat:
            store_block = dict(data.get("store") or {})
            if nm:
                store_block["name"] = nm
            if cat in ("drink", "meal", "group_buy"):
                store_block["category"] = cat
            data = dict(data)
            data["store"] = store_block
            if "menu" not in data and "categories" in data:
                data["menu"] = {"categories": data.get("categories"), "items": data.get("items")}

    return _preview_from_data(request, user, db, data, store_id_int, source_label,
                              conflict=conflict, stale=stale, src_digest=_src_digest(json_str),
                              cleaned_note=cleaned_note)


def _preview_from_data(request, user, db, data, store_id_int, source_label=None, conflict=False,
                       stale=False, src_digest=None, cleaned_note=False):
    """V2.15.0：預覽的主體抽出來，確認時若發現版本被別人更新，用同一段重新比對並回傳片段（conflict=True）；
    V2.15.1：輸入框內容變了（stale=True）也走同一段"""
    json_str = None
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
            "沒有選定店家。請在上方「匯入至」選擇要更新的店家，或從店家工作台按「更新菜單」進來；",
            "若是要新增一家店，請在「匯入至」選「新增一家店」並填店名與類別。",
        ])

    # Pydantic 驗證
    try:
        if is_full_import:
            validated = FullImport(**data)
        else:
            validated = MenuImport(**data)
    except ValidationError as e:
        msgs = humanize_validation_error(e, data)
        # V2.16.1 B-7：AI 填 "?" 的集中成一張「請對照照片」卡，其他格式錯誤照舊列
        unclear = [m.split("：" + UNCLEAR_PRICE_MSG)[0].removeprefix("菜單 → ").strip() for m in msgs if UNCLEAR_PRICE_MSG in m]
        others = [m for m in msgs if UNCLEAR_PRICE_MSG not in m]
        return _render_import_result(request, user, error_messages=others, unclear_items=unclear)

    # 菜單匯入需確認店家存在
    existing_menu = None
    duplicate_store = None
    target_store = None
    similar = []
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
        from app.services.import_service import same_name_store
        duplicate_store = same_name_store(db, validated.store.name)
        # V2.16.1 B-8：沒有完全同名時，找近似店名（去空白／全形／括號／「店」字尾後相同、包含或相似度 ≥ 80%）
        if not duplicate_store:
            _cands = db.query(Store).filter(Store.is_active == True, Store.is_personal != True).all()
            for _s, _r in _similar_stores(validated.store.name, _cands):
                _am = db.query(Menu).filter(Menu.store_id == _s.id, Menu.is_active == True).first()
                _ver = db.query(Menu).filter(Menu.store_id == _s.id, Menu.created_at <= _am.created_at).count() if _am else 0
                _n = db.query(MenuItem).filter(MenuItem.menu_id == _am.id).count() if _am else 0
                similar.append((_s, _r, _ver, _n))
        if duplicate_store:
            # 同名店家會把菜單匯進既有店家，一樣要跟它的使用中版本比
            existing_menu = db.query(Menu).filter(
                Menu.store_id == duplicate_store.id,
                Menu.is_active == True
            ).first()

    # V2.13.1：有使用中版本就算差異，讓管理員按確認前看到這版會改掉什麼
    diff = None
    existing_version = 0
    next_version = 0
    if existing_menu:
        diff = diff_menu(existing_menu, validated.menu)
        # 店內序號（坑 #17：不用全域主鍵），最舊=第 1 版
        existing_version = db.query(Menu).filter(
            Menu.store_id == existing_menu.store_id,
            Menu.created_at <= existing_menu.created_at,
        ).count()
        # V2.15.1 審核 P2-4：「將建立第 N 版」要用目前最大版號＋1，不是使用中版本＋1（切回舊版後匯入會算錯）
        next_version = db.query(Menu).filter(Menu.store_id == existing_menu.store_id).count() + 1

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
        conflict=conflict,
        next_version=next_version,
        stale=stale,
        src_digest=src_digest,
        cleaned_note=cleaned_note,
        similar=similar,
    )




def _reject_blockers(menu_content):
    """V2.12.0 的 blockers 後端也要擋。V2.14.1 P1-4：**必須在 import_* 之前呼叫**——
    import_menu / import_store_and_menu 內部會 commit，放在之後等於資料已寫入、舊版已停用，
    畫面卻回 400，管理員再送一次就多一個版本。"""
    _blk = analyze_menu_content(menu_content)["blockers"]
    if _blk:
        raise HTTPException(status_code=400, detail="菜單有必須修正的問題：" + "；".join(_blk[:3]))


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
    base_menu_id: int = Form(0),
    json_text: str = Form(None),
    src_digest: str = Form(None),
    store_id: str = Form(None),
    new_store_name: str = Form(None),
    new_store_category: str = Form(None),
    db: Session = Depends(get_db),
):
    """執行匯入（V2.15.0：htmx 送出；版本被別人更新 → 回傳重新比對的片段；成功 → HX-Redirect）"""
    user = await get_admin_user(request, db)
    is_hx = request.headers.get("HX-Request") == "true"

    # V2.15.1 審核 P1-1：確認鈕送的是預覽當下的 json_str。輸入框之後若被改過（雜湊不同），
    # 不能寫入舊內容——改用輸入框目前的內容重新預覽，讓使用者再確認一次
    if json_text is not None and src_digest and _src_digest(json_text) != src_digest:
        if not is_hx:
            raise HTTPException(status_code=409, detail="輸入框內容已變更，請回匯入頁重新檢查")
        if not json_text.strip():
            return _render_import_result(request, user, error_messages=["輸入框已清空，請重新貼上菜單資料"])
        return _preview_from_text(request, user, db, json_text.strip(), _parse_store_id(store_id), "貼上的文字",
                                  new_store_name=new_store_name, new_store_category=new_store_category, stale=True)
    
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 格式錯誤: {e}")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="JSON 最外層必須是物件（{...}）")
    
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
            # V2.15.1 審核 P2-10：鎖住店家列，兩個同時進來的確認會排隊，後者會看到前者建的新版本
            if not db.query(Store).filter(Store.id == validated.store_id).with_for_update().first():
                raise HTTPException(status_code=400, detail="選定的店家不存在，請回匯入頁重新選擇")
            _reject_blockers(validated.menu)
            target_store_for_check = validated.store_id
        elif "store" in data:
            # 完整匯入模式（新增店家 + 菜單）
            validated = FullImport(**data)
            _reject_blockers(validated.menu)
            if db.bind.dialect.name == "postgresql":
                # 同名店家同時建立：用店名的 advisory lock 排隊（SQLite 單寫者，不需要）
                from sqlalchemy import text as _t
                db.execute(_t("SELECT pg_advisory_xact_lock(hashtext(:n))"), {"n": validated.store.name})
            _dup = db.query(Store).filter(Store.name == validated.store.name).with_for_update().first()
            target_store_for_check = _dup.id if _dup else None
        else:
            raise HTTPException(status_code=400, detail="JSON 格式錯誤")

        # V2.15.0（審核 P2-5 / 審稿 6.3）：預覽到確認之間，使用中版本若被別人更新，
        # 剛才看到的差異就不對了——不寫入，用同一段預覽邏輯重新比對後回傳片段。
        # 同時擋「內容完全相同」（審稿 6.1）——原本會多出一個一模一樣的版本。
        if target_store_for_check:
            _cur = db.query(Menu).filter(Menu.store_id == target_store_for_check, Menu.is_active == True).first()
            _cur_id = _cur.id if _cur else 0
            if _cur_id != (base_menu_id or 0):
                if is_hx:
                    if json_text and json_text.strip():
                        # 用輸入框原文重新預覽，片段才會帶新的 src_digest（下一次確認仍受 P1-1 保護）
                        return _preview_from_text(request, user, db, json_text.strip(), _parse_store_id(store_id), "貼上的文字",
                                                  new_store_name=new_store_name, new_store_category=new_store_category, conflict=True)
                    return _preview_from_data(request, user, db, data, data.get("store_id"), None, conflict=True)
                raise HTTPException(status_code=409, detail="使用中的菜單剛被更新，請回匯入頁重新檢查")
            if _cur:
                _d = diff_menu(_cur, validated.menu)
                if _d["identical"]:
                    raise HTTPException(status_code=400, detail="菜單沒有變更，不需要更新")

        if "store_id" in data:
            menu = import_menu(db, validated)
            target_store_id = menu.store_id
        else:
            store = import_store_and_menu(db, validated)
            target_store_id = store.id
        
        # V2.10.0：匯完直接去工作台驗收，不再丟回儀表板
        cat_count, item_count = _count_import(validated.menu)
        _ver = db.query(Menu).filter(Menu.store_id == target_store_id).count()
        url = f"/admin/stores/{target_store_id}?tab=menu&imported=1&cats={cat_count}&items={item_count}&ver={_ver}"
        if is_hx:
            return Response(status_code=200, headers={"HX-Redirect": url})
        return RedirectResponse(url=url, status_code=302)
    except ValidationError as e:
        # V2.15.1 審核 P3-7：正常流程不會走到（預覽已驗過），走到也要給中文
        raise HTTPException(status_code=400, detail="資料驗證錯誤：" + "；".join(humanize_validation_error(e, data)[:3]))


@router.get("/groups")
async def group_list(request: Request, db: Session = Depends(get_db)):
    """所有團單"""
    user = await get_admin_user(request, db)
    
    groups = db.query(Group).order_by(Group.created_at.desc()).all()
    
    return templates.TemplateResponse(request, "admin/groups.html", {
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

    # V2.14.1 P1-6：此店家的團若還有「修改中」訂單，先依快照還原（此時外鍵都還在）。
    # 否則快照裡的 menu_item_id 之後指向已刪的列，下次有人開那個團就 IntegrityError → 永久 500
    from app.models.order import Order as _Order, OrderStatus as _OS
    from app.services.order_restore import restore_snapshot as _restore
    _editing = db.query(_Order).join(Group, _Order.group_id == Group.id).filter(
        Group.store_id == store_id, _Order.status == _OS.EDITING
    ).all()
    for _o in _editing:
        _restore(db, _o)
    db.flush()

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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=settings", status_code=302)


@router.get("/stores/new")
async def new_store_page(request: Request, db: Session = Depends(get_db)):
    """手動新增店家（V2.13.0；上一輪管理後台審稿的提案 2）。

    原本新增店家只能靠 JSON 匯入帶 store 區塊、或核准推薦。只填店名與類別就建，
    建好直接進工作台，頂部就有「更新菜單」。
    注意：這條路由必須排在 /stores/{store_id} 之前，否則 "new" 會被當成 store_id 而 422。
    """
    user = await get_admin_user(request, db)
    existing = [s.name for s in db.query(Store.name).filter(Store.is_personal != True).all()]
    return templates.TemplateResponse(request, "admin/store_new.html", {
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
    saved: str = "",
    imported: int = 0,
    cats: int = 0,
    items: int = 0,
    ver: int = 0,
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

    # V2.21.0 分頁重組：菜單／共用選項（甜冰、加料）／店家設定（基本資料、分店、可見範圍）／更多。
    # 舊網址的 info／ops 對到新分頁（書籤與 V2.20.0 以前的導回網址）
    tab = {"info": "settings", "ops": "options"}.get(tab, tab)
    has_options = bool(store.category and store.category.value in ("drink", "meal"))
    if tab == "options" and not has_options:
        tab = "settings"
    if tab not in ("menu", "options", "settings", "more"):
        tab = "menu"

    def _values(opt_type):
        return [o.option_value for o in sorted([o for o in store.options if o.option_type == opt_type], key=lambda o: o.sort_order)]

    return templates.TemplateResponse(request, "admin/store_workbench.html", {
        "tab": tab,
        "created": created,
        "imported": imported, "imported_cats": cats, "imported_items": items, "imported_ver": ver,
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
        "sugar_list": _values(OptionType.SUGAR),
        "ice_list": _values(OptionType.ICE),
        "has_options": has_options,
        "saved": saved,
        "topping_rows": [{"id": t.id, "name": t.name, "price": float(t.price or 0), "active": bool(t.is_active)}
                         for t in sorted(store.toppings, key=lambda t: (t.sort_order or 0, t.id))],
        "request": request,
        "user": user,
        "store": store,
        "departments": departments,
        "store_dept_ids": store_dept_ids,
    })


@router.get("/stores/{store_id}/edit")
async def edit_store_page(store_id: int):
    """V2.13.0：編輯頁併入工作台，舊連結與書籤轉過去"""
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=settings", status_code=301)


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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=options&saved=options", status_code=302)


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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=settings", status_code=302)


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
    
    return templates.TemplateResponse(request, "admin/users.html", {
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

    return templates.TemplateResponse(request, "admin/users_duplicates.html", {
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
    
    return templates.TemplateResponse(request, "admin/user_detail.html", {
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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=settings", status_code=302)


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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=settings", status_code=302)


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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=settings", status_code=302)


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
    
    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=settings", status_code=302)


def _parse_topping_rows(raw: str) -> list[dict]:
    """V2.21.0：加料批次編輯的 JSON → 驗證過的列（依畫面順序）。

    畫面把整份清單（含新增的列）序列化成 [{id, name, price, active}]；
    不在清單裡的既有加料＝要刪除。任何一列不合法就整批 400、不寫入。
    """
    from decimal import Decimal, InvalidOperation
    try:
        rows = json.loads(raw or "[]")
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="加料資料格式錯誤，請重新整理後再試")
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail="加料資料格式錯誤，請重新整理後再試")
    if len(rows) > 50:
        raise HTTPException(status_code=400, detail="加料最多 50 項")
    result, seen = [], set()
    for idx, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise HTTPException(status_code=400, detail="加料資料格式錯誤，請重新整理後再試")
        name = str(row.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail=f"第 {idx} 項加料沒有名稱")
        if len(name) > 50:
            raise HTTPException(status_code=400, detail=f"加料「{name[:10]}…」名稱超過 50 字")
        if name in seen:
            raise HTTPException(status_code=400, detail=f"加料「{name}」重複了")
        seen.add(name)
        try:
            price = Decimal(str(row.get("price") if row.get("price") not in (None, "") else 0).strip())
        except (InvalidOperation, ValueError):
            raise HTTPException(status_code=400, detail=f"加料「{name}」的加價不是數字")
        if not price.is_finite() or price < 0 or price > 9999:
            raise HTTPException(status_code=400, detail=f"加料「{name}」的加價要在 0～9999 之間")
        tid = row.get("id")
        if tid in (None, ""):
            tid = None
        else:
            try:
                tid = int(tid)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="加料資料格式錯誤，請重新整理後再試")
        active = row.get("active", True)
        active = not (active is False or str(active).lower() in ("false", "0", ""))
        result.append({"id": tid, "name": name, "price": price, "active": active})
    return result


@router.post("/stores/{store_id}/toppings/batch")
async def save_toppings_batch(
    store_id: int,
    request: Request,
    toppings_json: str = Form("[]"),
    db: Session = Depends(get_db),
):
    """V2.21.0：加料一次儲存（取代原本逐筆新增／停用／刪除三支路由）。

    改名、改價、停用、排序、新增、刪除全部一次送出；依畫面順序重寫 sort_order。
    刪除前先把 order_item_toppings.store_topping_id 斷開（訂單存的是名稱與價格快照）——
    原本的逐筆刪除直接 db.delete，加料被點過就撞外鍵（審核 P2-14）。
    """
    from app.models.store import StoreTopping
    from app.models.order import OrderItemTopping
    user = await get_admin_user(request, db)

    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="店家不存在")

    rows = _parse_topping_rows(toppings_json)
    existing = {t.id: t for t in db.query(StoreTopping).filter(StoreTopping.store_id == store_id).all()}
    for r in rows:
        if r["id"] is not None and r["id"] not in existing:
            raise HTTPException(status_code=400, detail="加料清單已被別人改過，請重新整理後再試")

    keep = {r["id"] for r in rows if r["id"] is not None}
    gone = [tid for tid in existing if tid not in keep]
    if gone:
        db.query(OrderItemTopping).filter(OrderItemTopping.store_topping_id.in_(gone)).update(
            {OrderItemTopping.store_topping_id: None}, synchronize_session=False)
        for tid in gone:
            db.delete(existing[tid])
        db.flush()
    for idx, r in enumerate(rows):
        if r["id"] is None:
            db.add(StoreTopping(store_id=store_id, name=r["name"], price=r["price"], sort_order=idx, is_active=r["active"]))
        else:
            t = existing[r["id"]]
            t.name, t.price, t.sort_order, t.is_active = r["name"], r["price"], idx, r["active"]
    db.commit()

    return RedirectResponse(url=f"/admin/stores/{store_id}?tab=options&saved=toppings", status_code=302)


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
    
    return templates.TemplateResponse(request, "admin/feedbacks.html", {
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
    
    return templates.TemplateResponse(request, "admin/departments.html", {
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
    
    return templates.TemplateResponse(request, "admin/department_detail.html", {
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
    
    return templates.TemplateResponse(request, "admin/announcements.html", {
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
    
    return templates.TemplateResponse(request, "admin/announcement_edit.html", {
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
    
    return templates.TemplateResponse(request, "admin/recommendations.html", {
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
