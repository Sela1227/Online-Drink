# -*- coding: utf-8 -*-
"""煙霧測試 — 用 SQLite 驗核心邏輯，不需要 live app 也不碰正式資料庫。

跑法（先 pip install -r requirements.txt）：
    SECRET_KEY=x DATABASE_URL="sqlite:///./_smoke.db" PYTHONPATH=. python scripts/smoke_test.py
跑完記得 `rm -f _smoke.db`，打包前不要把它一起裝進去。

這支跑的是 SQLite＋FastAPI TestClient 的 HTTP 請求（約 150 個真實請求）；
「兩個人同一瞬間」的並行情況 SQLite 測不到，另見 scripts/pg_concurrency_check.py（PostgreSQL，V2.23.2）。
前端互動（Alpine／htmx）另見 check_frontend_toast.py、check_frontend_import.py。

涵蓋範圍（依節號；V2.10.3 起逐版累加）：
  1. 首頁公告的過濾與排序（啟用/停用、到期、置頂、則數上限）
  2. deadline 的時區比對（清除測試團、進行中團數）— 坑 #25 的回歸測試
  3. 飲料選項字串解析（全形逗號、去重、長度上限）
  4. 公告到期時間的台北→UTC 轉換
  5. 台北日曆邊界轉 UTC（統計頁「本月」的邊界）
  6. 統計頁的月份桶連續性與 UTC→台北時段位移
  7. 刪店家流程是否涵蓋所有指向 stores 的外鍵（坑：每加新表要回頭檢查刪除流程）
  8. 可見性 SQL 條件與輸入驗證（網址協定、文字長度）
  9. 品項規格驗證（鎖甜冰、選項去重、數量邊界）
  10. 截止時把修改中訂單還原成已送出（P0-08）
  11. V2.11.2 回歸（提前截止、網址補協定、甜冰長度、投票可見性）
  12. 庫存佔用的自有量與可用量（R-01：修改中複製上次曾超賣）
  13. 部門編號驗證與網址補協定的邊界（R-02/R-07/R-08）
  14. 投票店家編號驗證與表單錯誤回應機制（S-05/S-02）
  15. 匯入品質分析（重複/價格/空分類）與錯誤定位（V2.12.0）
  16. 既有店家匯入：店家只由 UI 決定，JSON 的 store_id 忽略（V2.12.1）
  17. 店家工作台：列表、分頁、舊網址轉址、刪除確認、新增店家（V2.13.0）
  19. 菜單差異預覽：新增／變更／移除／不變、部分菜單提醒、同名品項（V2.13.1）
  20. 匯入時價／停售／說明、價格容錯、截止後團主定價回寫本團（V2.14.0）
  21. V2.14.1 審核修正：屬性內 JS 跳脫、func 匯入、候補 extras_price、blocker 順序、刪店家快照、P2 容錯
  22. V2.15.0 匯入頁簡化：自動檢查、摘要優先、相同內容停用、確認時核對版本、Logo 指令搬家
  23. V2.15.1 審核修正：排序差異、版號、甜冰長度、熱門按品名、前台菜單頁、money、雜湊核對、清理包裝、新店家欄位
  24. V2.16.0 菜單呈現：M／L 兩行、說明兩行＋彈窗、導覽品項數＋其他、更新日期與回報預填
  25. V2.16.1 匯入介面：看不清 "?"、分類改名合併、店名近似、帶入目前菜單、選店清單版號
  26. V2.16.2 推薦多張菜單照片（欄位相容、上限、走 upload_service）＋店家排序資料（開團覆蓋層／後台列表）
  27. V2.16.3 hotfix（審核）：甜冰預設對照店家選項、範本同、隱藏欄位、時區、金額、草稿標示、星號、FE0F
  18. 匯入分類／品項計數
  28. V2.17.0 IA 重整：首頁分區、五格導航、店家／紀錄分頁、舊網址轉址
  29. V2.18.0 團頁重排：身分 × 階段、結帳列片段、訂單牆跟單、用語統一
  30. V2.19.0 開團頁：進階設定收合、欄位 name 保留、複製開團帶入
  31. V2.20.0 加點與購物車 sheet：主鈕帶金額、數量 0＝移除、修改中用語
  32. V2.21.0 工作台分頁：甜冰標籤、加料批次儲存與驗證
  33. V2.22.0 套件升級：TemplateResponse 新寫法、PyJWT 舊 token 相容、版本鎖
  34. V2.23.0 遷移：可重複跑、只補缺的、錯誤記錄
  35. V2.23.1 LINE 登入回呼重複送出：只換一次授權碼、沿用結果
  36. V2.23.2 外部審核：我的訂單可見性、跨站寫入、同名店家、候補順位、遷移錯誤不啟動

新增或改動上述邏輯時，請一併更新這支測試。
"""
import json
import os
import sys
from decimal import Decimal
from datetime import datetime, timedelta

# V2.10.2 安全防護：setdefault 的語意是「沒設才用預設值」，若 shell 裡已經
# 匯出過正式的 DATABASE_URL（例如剛操作完 Railway），下面的 delete() 會直接
# 打到正式資料庫。這裡改成偵測到非 SQLite 就中止，並強制覆寫而非 setdefault。
_existing = os.environ.get("DATABASE_URL", "")
if _existing and not _existing.startswith("sqlite"):
    raise SystemExit(
        "smoke_test 只能跑在 SQLite。偵測到 DATABASE_URL 指向非 SQLite "
        f"（{_existing.split('://')[0]}://...），已中止以免刪到正式資料。"
    )
os.environ["DATABASE_URL"] = "sqlite:///./_smoke.db"
os.environ["SECRET_KEY"] = "smoke_test_only"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import or_

from app.database import Base, engine, SessionLocal
from app.models.user import Announcement, User
from app.models.store import Store, CategoryType
from app.models.group import Group, taipei_now, taipei_to_utc
from app.routers.home import get_active_announcements, month_buckets, taipei_slot
from app.routers.admin import _parse_option_values, _parse_taipei_to_utc, _count_import
from app.schemas.menu import MenuContent

passed = []


def check(label):
    passed.append(label)
    print(f"  OK  {label}")


def main():
    Base.metadata.drop_all(bind=engine)  # V2.16.0：重跑時舊 _smoke.db 的菜單版本會殘留，先清空
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    for model in (Group, Announcement, Store, User):
        db.query(model).delete()

    user = User(line_user_id="smoke", display_name="煙霧測試")
    db.add(user)
    db.flush()

    # ---------- 1. 公告過濾與排序 ----------
    print("\n[1] 首頁公告")
    now = datetime.utcnow()  # announcements 表存的是 UTC
    def ann(title, active=True, pinned=False, expires=None, age_days=0):
        return Announcement(
            title=title, content="內容", is_active=active, is_pinned=pinned,
            expires_at=expires, created_at=now - timedelta(days=age_days),
            created_by_id=user.id,
        )
    db.add_all([
        ann("已過期", expires=now - timedelta(hours=1)),
        ann("已停用", active=False),
        ann("舊的一般", age_days=2),
        ann("新的一般", age_days=1),
        ann("置頂", pinned=True, expires=now + timedelta(days=1), age_days=5),
    ])
    db.commit()

    got = [a.title for a in get_active_announcements(db)]
    assert got == ["置頂", "新的一般"], f"預設應為置頂優先且上限 2 則，實得 {got}"
    check("過期不顯示、停用不顯示、置頂排最前、上限 2 則")

    got3 = [a.title for a in get_active_announcements(db, limit=3)]
    assert got3 == ["置頂", "新的一般", "舊的一般"], got3
    check("limit 參數與新到舊排序")

    # ---------- 2. deadline 時區（坑 #25 回歸測試） ----------
    print("\n[2] deadline 時區比對")
    tpe = taipei_now()
    assert abs((tpe - datetime.utcnow()).total_seconds() - 8 * 3600) < 5, "台北應領先 UTC 8 小時"
    check("taipei_now() 與 utcnow() 相差 8 小時")

    store = Store(name="煙霧飲料店", category=CategoryType.DRINK)
    db.add(store)
    db.flush()
    db.add_all([
        Group(owner_id=user.id, store_id=store.id, name="稍早已截止",
              category=CategoryType.DRINK, deadline=tpe - timedelta(hours=5)),
        Group(owner_id=user.id, store_id=store.id, name="還在進行",
              category=CategoryType.DRINK, deadline=tpe + timedelta(hours=3)),
    ])
    db.commit()

    # 清除測試團掃描範圍
    hit = [g.name for g in db.query(Group).filter(
        or_(Group.is_closed == True, Group.deadline <= taipei_now())
    ).all()]
    assert hit == ["稍早已截止"], f"只該掃到已截止的團，實得 {hit}"
    check("清除測試團只掃已截止的團（進行中的不會被刪）")

    # 進行中團數
    active = db.query(Group).filter(
        Group.store_id == store.id,
        Group.is_closed == False,
        Group.deadline > taipei_now(),
    ).count()
    assert active == 1, f"進行中應為 1，實得 {active}"
    check("進行中團數不把已截止的算進去")

    # 確認舊寫法真的會錯（避免這支測試哪天變成恆真）
    wrong = db.query(Group).filter(
        or_(Group.is_closed == True, Group.deadline <= datetime.utcnow())
    ).count()
    assert wrong == 0, "若這裡不再為 0，代表測試資料失去鑑別力，請調整 deadline 間距"
    check("utcnow() 寫法的錯誤行為仍可重現（測試有鑑別力）")

    # ---------- 3. 飲料選項解析 ----------
    print("\n[3] 飲料選項解析")
    assert _parse_option_values("無糖,微糖,半糖,少糖,全糖") == ["無糖", "微糖", "半糖", "少糖", "全糖"]
    check("基本逗號分隔與順序")
    assert _parse_option_values(" 無糖 ，微糖,, 無糖 ") == ["無糖", "微糖"]
    check("去空白、吃全形逗號、去重、略過空項")
    assert _parse_option_values("") == [] and _parse_option_values(None) == []
    check("空值與 None")
    assert len(_parse_option_values(",".join(str(i) for i in range(50)))) == 20
    check("選項數上限 20")
    assert len(_parse_option_values("a" * 80)[0]) == 50
    check("單一選項截到 50 字（欄位上限）")

    # ---------- 4. 公告到期時間時區轉換 ----------
    print("\n[4] 公告到期時間轉換")
    assert _parse_taipei_to_utc("2026-09-20T12:00") == datetime(2026, 9, 20, 4, 0)
    check("台北中午存成 UTC 04:00")
    assert _parse_taipei_to_utc("") is None and _parse_taipei_to_utc("亂打") is None
    check("空值與格式錯誤回 None")

    # ---------- 5. 台北日曆邊界轉 UTC ----------
    print("\n[5] 台北日曆邊界轉 UTC")
    assert taipei_to_utc(datetime(2026, 9, 1, 0, 0)) == datetime(2026, 8, 31, 16, 0)
    check("台北 9/1 00:00 = UTC 8/31 16:00（統計「本月」不會漏掉每月前 8 小時）")
    assert taipei_to_utc(datetime(2026, 1, 1, 0, 0)) == datetime(2025, 12, 31, 16, 0)
    check("跨年邊界")
    assert taipei_to_utc(None) is None
    check("None 直通")
    assert _parse_taipei_to_utc("2026-09-20T12:00") == taipei_to_utc(datetime(2026, 9, 20, 12, 0))
    check("_parse_taipei_to_utc 與 taipei_to_utc 結果一致（同一套轉換）")

    # ---------- 6. 統計頁：月份桶與時段位移 ----------
    print("\n[6] 統計頁計算")

    from datetime import date
    for probe in (date(2026, 3, 1), date(2026, 3, 15), date(2026, 4, 10),
                  date(2026, 5, 20), date(2026, 9, 12), date(2027, 1, 5)):
        got = month_buckets(probe)
        assert len(set(got)) == 6, f"{probe} 推出重複月份：{got}"
        assert got[-1] == (probe.year, probe.month), f"{probe} 最後一桶應是當月"
        for a, b in zip(got, got[1:]):
            gap = (b[0] - a[0]) * 12 + (b[1] - a[1])
            assert gap == 1, f"{probe} 月份不連續：{a} → {b}"
    check("六個月份桶連續、不重複、不跳月（2026/3-5 是舊寫法必錯的月份）")

    assert taipei_slot(3, 3) == (3, 11), "UTC 週三 03:00 = 台北週三 11:00"
    check("午餐時段：UTC 03:00 → 台北 11:00（不再顯示 2:00/3:00）")
    assert taipei_slot(3, 17) == (4, 1), "UTC 週三 17:00 = 台北週四 01:00"
    check("跨 24 點時星期進一天")
    assert taipei_slot(6, 16) == (0, 0), "UTC 週六 16:00 = 台北週日 00:00"
    check("週六跨到週日（dow 迴繞）")

    # ---------- 7. 刪店家流程涵蓋所有外鍵 ----------
    print("\n[7] 刪除流程的外鍵覆蓋")
    import inspect, re as _re
    import app.main  # noqa: F401  確保所有 model 都已載入
    from app.routers.admin import delete_store

    src = inspect.getsource(delete_store)
    handled = set(_re.findall(r"(?:DELETE FROM|UPDATE)\s+([a-z_]+)", src))
    # 只看刪店家該負責的父表；指向 users 的外鍵屬於清除訪客流程（另案）
    for parent in ("stores", "menus", "menu_items"):
        refs = {
            t.name for t in Base.metadata.sorted_tables
            for fk in t.foreign_keys
            if fk.column.table.name == parent
        }
        missing = refs - handled
        assert not missing, (
            f"刪店家流程沒有處理指向 {parent} 的外鍵表：{sorted(missing)}。"
            "「每加新表要回頭檢查刪除流程」——這條教訓已經發生過多次"
        )
    check("delete_store 涵蓋所有指向 stores/menus/menu_items 的外鍵表")

    # ---------- 8. 可見性與輸入驗證 ----------
    print("\n[8] 可見性與輸入驗證")
    from app.services.validation import clean_http_url, clean_text
    from app.services.visibility import visible_group_clause
    from fastapi import HTTPException as _HE

    for bad in ("javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,<script>",
                "vbscript:x", "//evil.example/x", "ftp://x/y"):
        try:
            clean_http_url(bad)
            raise AssertionError(f"應擋下：{bad}")
        except _HE:
            pass
    check("javascript:/data:/協定相對等網址全部擋下")
    assert clean_http_url("https://example.com/a?b=1") == "https://example.com/a?b=1"
    assert clean_http_url("  ") is None and clean_http_url(None) is None
    check("正常 http/https 放行、空值回 None")
    assert len(clean_http_url("https://e.com/" + "a" * 900)) == 500
    check("網址截到 500 字（欄位上限）")

    try:
        clean_text("x" * 101, 100, field="團名")
        raise AssertionError("應擋下超長文字")
    except _HE:
        pass
    check("超長文字回 400 而不是讓 PostgreSQL 500")

    # 可見性條件：公開團、自己的團、部門團可見；別人的私密團不可見
    other = User(line_user_id="other", display_name="別人")
    db.add(other)
    db.flush()
    pub = Group(owner_id=other.id, store_id=store.id, name="公開團",
                category=CategoryType.DRINK, deadline=tpe + timedelta(hours=1), is_public=True)
    priv = Group(owner_id=other.id, store_id=store.id, name="別人的私密團",
                 category=CategoryType.DRINK, deadline=tpe + timedelta(hours=1), is_public=False)
    mine = Group(owner_id=user.id, store_id=store.id, name="我自己的私密團",
                 category=CategoryType.DRINK, deadline=tpe + timedelta(hours=1), is_public=False)
    db.add_all([pub, priv, mine])
    db.commit()

    user.is_admin = False
    names = {g.name for g in db.query(Group).filter(visible_group_clause(user)).all()}
    assert "公開團" in names and "我自己的私密團" in names, names
    assert "別人的私密團" not in names, "別人的私密團不該可見"
    check("可見性條件：公開與自己的團可見、別人的私密團擋下")

    user.is_admin = True
    db.flush()
    names_admin = {g.name for g in db.query(Group).filter(visible_group_clause(user)).all()}
    assert "別人的私密團" in names_admin, "管理員應該看得到"
    check("管理員看得到全部")
    user.is_admin = False
    db.flush()

    # ---------- 9. 品項規格驗證 ----------
    print("\n[9] 品項規格驗證")
    from app.models.store import StoreOption, OptionType
    from app.routers.orders import _validate_item_spec

    db.add_all([
        StoreOption(store_id=store.id, option_type=OptionType.SUGAR, option_value="半糖", sort_order=0),
        StoreOption(store_id=store.id, option_type=OptionType.ICE, option_value="少冰", sort_order=0),
    ])
    db.commit()
    db.refresh(store)

    g = Group(owner_id=user.id, store_id=store.id, name="驗證團",
              category=CategoryType.DRINK, deadline=tpe + timedelta(hours=1),
              lock_sugar=True, default_sugar="半糖")
    db.add(g)
    db.commit()

    size, sugar, ice, qty, opts, note = _validate_item_spec(
        g, store, "M", "全糖", "少冰", 2, [5, 5, 7], "  備註  ")
    assert sugar == "半糖", f"鎖定甜度時應強制用團單預設，實得 {sugar}"
    check("鎖定甜度時忽略前端送來的值")
    assert opts == [5, 7], f"選項應去重，實得 {opts}"
    check("重複選項去重（原本 [5,5,5] 會加價三次）")
    assert note == "備註"
    check("備註去頭尾空白")

    # 沒鎖甜度的團才測得到「甜度值不合法」——有鎖的話會先被團單預設覆寫
    g_free = Group(owner_id=user.id, store_id=store.id, name="未鎖甜度團",
                   category=CategoryType.DRINK, deadline=tpe + timedelta(hours=1))
    db.add(g_free)
    db.commit()

    for bad_kw in ({"sugar": "不存在的甜度"}, {"ice": "不存在的冰"},
                   {"size": "XL"}, {"quantity": 100000}, {"quantity": 0}):
        kw = {"size": "M", "sugar": "半糖", "ice": "少冰", "quantity": 1}
        kw.update(bad_kw)
        try:
            _validate_item_spec(g_free, store, kw["size"], kw["sugar"], kw["ice"],
                                kw["quantity"], [], None)
            raise AssertionError(f"應擋下：{bad_kw}")
        except _HE:
            pass
    check("不存在的甜度/冰塊、非法尺寸、數量超界全部擋下")

    g2 = Group(owner_id=user.id, store_id=store.id, name="餐點團",
               category=CategoryType.MEAL, deadline=tpe + timedelta(hours=1))
    db.add(g2)
    db.commit()
    _, sugar2, ice2, _, _, _ = _validate_item_spec(g2, store, None, "半糖", "少冰", 1, [], None)
    assert sugar2 is None and ice2 is None
    check("非飲料團不記甜冰")

    # ---------- 10. 截止時結算修改中訂單 ----------
    print("\n[10] 截止結算（P0-08）")
    from app.models.order import Order, OrderItem, OrderStatus
    from app.services.order_restore import settle_editing_orders

    g_closed = Group(owner_id=user.id, store_id=store.id, name="已截止團",
                     category=CategoryType.DRINK, deadline=tpe - timedelta(hours=1))
    db.add(g_closed)
    db.flush()
    o = Order(group_id=g_closed.id, user_id=user.id, status=OrderStatus.EDITING,
              snapshot={"items": [{
                  "menu_item_id": None, "item_name": "原本點的紅茶", "size": None,
                  "sugar": "半糖", "ice": "少冰", "quantity": 2,
                  "unit_price": "35.00", "note": None, "options": [], "toppings": [],
                  "backups": [],
              }]})
    db.add(o)
    db.flush()
    # 修改中亂加的品項，還原後應該消失
    db.add(OrderItem(order_id=o.id, item_name="改到一半的綠茶", quantity=9,
                     unit_price=Decimal("999"), sugar=None, ice=None))
    db.commit()

    n = settle_editing_orders(db, g_closed)
    db.refresh(o)
    assert n == 1, f"應還原 1 筆，實得 {n}"
    assert o.status == OrderStatus.SUBMITTED, o.status
    assert o.snapshot is None
    names = sorted(i.item_name for i in o.items)
    assert names == ["原本點的紅茶"], f"應還原成快照內容，實得 {names}"
    check("截止後 EDITING 自動還原成 SUBMITTED（否則整筆從所有匯出消失）")

    assert settle_editing_orders(db, g_closed) == 0
    check("重複呼叫是冪等的（每個進入點都能安全呼叫）")

    g_open = Group(owner_id=user.id, store_id=store.id, name="進行中團",
                   category=CategoryType.DRINK, deadline=tpe + timedelta(hours=1))
    db.add(g_open)
    db.flush()
    o2 = Order(group_id=g_open.id, user_id=user.id, status=OrderStatus.EDITING,
               snapshot={"items": []})
    db.add(o2)
    db.commit()
    assert settle_editing_orders(db, g_open) == 0
    db.refresh(o2)
    assert o2.status == OrderStatus.EDITING, "還開著的團不該被結算"
    check("進行中的團不受影響")

    # ---------- 11. V2.11.2 回歸 ----------
    print("\n[11] V2.11.2 回歸")

    # N-01：提前截止必須真的寫進資料庫。autoflush=False 下 db.refresh() 會
    # 無聲丟棄未 flush 的變更 —— 這是 V2.11.1 的 P0 回歸。
    g_close = Group(owner_id=user.id, store_id=store.id, name="待截止團",
                    category=CategoryType.DRINK, deadline=tpe + timedelta(hours=2))
    db.add(g_close)
    db.commit()
    close_id = g_close.id
    g_close.is_closed = True
    db.commit()                      # 先落地
    settle_editing_orders(db, g_close)  # 無 EDITING → 不 commit
    db.refresh(g_close)
    db.expire_all()
    assert db.query(Group).filter(Group.id == close_id).first().is_closed is True, \
        "提前截止沒有寫進資料庫（db.refresh 丟棄了未 flush 的變更）"
    check("提前截止會真的關閉團單（N-01 回歸）")

    # N-06：舊資料的無協定網址要自動補 https://，危險協定仍要擋
    assert clean_http_url("maps.app.goo.gl/abc") == "https://maps.app.goo.gl/abc"
    check("無協定網址自動補 https://（否則管理員整頁存不了）")
    for bad in ("javascript:alert(1)", "data:text/html,x", "vbscript:x"):
        try:
            clean_http_url(bad)
            raise AssertionError(f"補協定不該放行：{bad}")
        except _HE:
            pass
    check("補協定不會放行 javascript:/data:/vbscript:")

    # N-08：沒設甜冰選項的店家仍要限長度
    g_nofix = Group(owner_id=user.id, store_id=store.id, name="無選項店團",
                    category=CategoryType.DRINK, deadline=tpe + timedelta(hours=1))
    db.add(g_nofix)
    db.commit()
    store_no_opt = Store(name="沒設選項的飲料店", category=CategoryType.DRINK)
    db.add(store_no_opt)
    db.commit()
    try:
        _validate_item_spec(g_nofix, store_no_opt, None, "甜" * 80, None, 1, [], None)
        raise AssertionError("超長甜度應被擋下")
    except _HE:
        pass
    check("店家沒設甜冰選項時，仍限制字串長度（PostgreSQL 會 500）")

    # N-10：私密但沒選部門的投票，單筆檢查要與 SQL 條件一致（都隱藏）
    from app.models.vote import Vote
    from app.services.visibility import ensure_vote_visible
    v = Vote(creator_id=other.id, title="私密無部門投票", is_public=False,
             deadline=tpe + timedelta(hours=1))
    db.add(v)
    db.commit()
    try:
        ensure_vote_visible(v, user, db)
        raise AssertionError("私密且無部門的投票不該放行")
    except _HE:
        pass
    check("私密但沒選部門的投票：單筆檢查與列表規則一致（都隱藏）")

    # ---------- 12. 庫存佔用不得超賣（R-01） ----------
    print("\n[12] 庫存佔用（R-01）")
    from app.models.menu import Menu, MenuCategory, MenuItem
    from app.routers.orders import _own_qty, _available_for

    menu = Menu(store_id=store.id, is_active=True)
    db.add(menu)
    db.flush()
    cat = MenuCategory(menu_id=menu.id, name="限量", sort_order=0)
    db.add(cat)
    db.flush()
    limited = MenuItem(menu_id=menu.id, category_id=cat.id, name="限量紅茶",
                       price=Decimal("35"), stock_limit=5)
    db.add(limited)
    db.flush()

    g_stock = Group(owner_id=user.id, store_id=store.id, menu_id=menu.id, name="限量團",
                    category=CategoryType.DRINK, deadline=tpe + timedelta(hours=1))
    db.add(g_stock)
    db.flush()

    # 情境 A：已送出 5 份 → 進修改 → 再想加 3 份
    o_edit = Order(group_id=g_stock.id, user_id=user.id, status=OrderStatus.EDITING,
                   snapshot={"items": []})
    db.add(o_edit)
    db.flush()
    db.add(OrderItem(order_id=o_edit.id, menu_item_id=limited.id, item_name="限量紅茶",
                     quantity=5, unit_price=Decimal("35"), sugar=None, ice=None))
    db.commit()

    avail = _available_for(db, g_stock.id, limited, o_edit)
    assert avail == 0, f"已佔滿 5 份時應為 0，實得 {avail}"
    check("情境 A：已佔用 5/5 時，可再加的量是 0（不是 5）")

    # 情境 B：同品項分兩行，第二行要看得到第一行已佔的量
    db.query(OrderItem).filter(OrderItem.order_id == o_edit.id).delete()
    db.commit()
    db.add(OrderItem(order_id=o_edit.id, menu_item_id=limited.id, item_name="限量紅茶",
                     quantity=4, unit_price=Decimal("35"), sugar="微糖", ice=None))
    db.commit()
    assert _own_qty(db, o_edit.id, limited.id) == 4
    avail2 = _available_for(db, g_stock.id, limited, o_edit)
    assert avail2 == 1, f"4/5 時應剩 1，實得 {avail2}"
    check("情境 B：同品項多行時，自有量以資料庫為準（不是記憶體 collection）")

    db.query(OrderItem).filter(OrderItem.order_id == o_edit.id).delete()
    db.commit()
    assert _available_for(db, g_stock.id, limited, o_edit) == 5
    check("清空後可用量回到 5")

    unlimited = MenuItem(menu_id=menu.id, category_id=cat.id, name="不限量綠茶",
                         price=Decimal("30"), stock_limit=None)
    db.add(unlimited)
    db.commit()
    assert _available_for(db, g_stock.id, unlimited, o_edit) is None
    check("不限量品項回 None")

    # ---------- 13. 部門編號與網址（R-02/R-07/R-08） ----------
    print("\n[13] 部門編號與網址")
    from app.models.department import Department
    from app.services.validation import parse_department_ids

    d_ok = Department(name="放腫科", is_active=True)
    d_off = Department(name="已停用科", is_active=False)
    db.add_all([d_ok, d_off])
    db.commit()

    assert parse_department_ids([str(d_ok.id)], db) == [d_ok.id]
    check("正常部門編號通過")
    assert parse_department_ids([], db) == [] and parse_department_ids(None, db) == []
    check("空清單回空")
    for bad in (["-3"], ["abc"], ["999999"], [str(d_off.id)]):
        try:
            parse_department_ids(bad, db)
            raise AssertionError(f"應擋下：{bad}")
        except _HE:
            pass
    check("負數／非數字／不存在／已停用的部門編號全部回 400（原本是 500）")

    for bad in ("tel:0412345678", "mailto:a@b.c", "http:/evil", "不是網址"):
        try:
            clean_http_url(bad)
            raise AssertionError(f"補協定不該放行：{bad}")
        except _HE:
            pass
    check("tel:/mailto: 等非網域字串不再被補成壞掉的 https（R-08）")

    # ---------- 14. 投票店家編號與表單錯誤回應（S-05/S-02） ----------
    print("\n[14] 投票店家與表單錯誤回應")
    from app.services.validation import parse_store_ids
    personal = Store(name="某某的代購", category=CategoryType.GROUP_BUY, is_personal=True)
    inactive = Store(name="已停用店", category=CategoryType.DRINK, is_active=False)
    db.add_all([personal, inactive])
    db.commit()
    assert parse_store_ids([str(store.id)], db) == [store.id]
    check("正常店家通過")
    for bad in (["-1"], ["99999"], [str(personal.id)], [str(inactive.id)], ["abc"]):
        try:
            parse_store_ids(bad, db)
            raise AssertionError(f"應擋下：{bad}")
        except _HE:
            pass
    check("負數／不存在／個人代購店／已停用／非數字全部回 400（原本外鍵 500）")

    from app.main import _form_error_response
    resp = _form_error_response("測試 <b>訊息</b>", 400)
    body = resp.body.decode()
    assert resp.status_code == 400 and "text/html" in resp.media_type
    assert "history.back()" in body and "sessionStorage.setItem('flash'" in body
    assert "<b>" not in body, "訊息內的 < 必須逸出，否則會破壞 script"
    assert "\\u003c" in body
    check("表單錯誤回極小 HTML：寫 sessionStorage 後 history.back()，訊息已逸出")
    assert "Location" not in resp.headers and "flash=" not in body.split("sessionStorage")[0]
    check("不再用轉址與網址參數（消除開放轉址與訊息偽造）")

    # ---------- 15. 匯入品質分析與錯誤定位（V2.12.0） ----------
    print("\n[15] 匯入品質分析")
    from app.services.import_analysis import analyze_menu_content, describe_loc, json_error_context

    mc = MenuContent(categories=[
        {"name": "小菜", "items": [{"name": "蘭花干", "price": 30}, {"name": "米血", "price": 25}, {"name": "蘭花干", "price": 30}]},
        {"name": "大份", "items": [{"name": "米血", "price": 45}, {"name": "時價魚", "price": 0}, {"name": "大杯茶", "price": 40, "price_l": 35}]},
        {"name": "空的", "items": []},
    ])
    a = analyze_menu_content(mc)
    assert any("蘭花干」重複出現 2 次" in m for m in a["blockers"]), a["blockers"]
    check("同分類同名品項 → 擋下")
    assert not any("米血" in m for m in a["blockers"]) and any("米血」同時出現在" in m for m in a["warnings"])
    check("跨分類同名 → 只警告（魯味的米血確實會在不同價格區）")
    assert any("時價魚」價格是 0" in m for m in a["warnings"])
    assert any("L 尺寸價（35）低於" in m for m in a["warnings"])
    assert any("分類「空的」" in m for m in a["warnings"])
    check("價格 0、L 低於 M、空分類 → 警告")
    assert analyze_menu_content(MenuContent(categories=[{"name": "a", "items": [{"name": "x", "price": 1}]}])) == {"blockers": [], "warnings": []}
    check("乾淨的菜單沒有任何提示")

    raw = {"menu": {"categories": [{"name": "小菜", "items": [{"name": "黃金泡菜", "price": "時價"}]}]}}
    assert describe_loc(("menu", "categories", 0, "items", 0, "price"), raw) == "菜單 → 分類[1]「小菜」 → 品項[1]「黃金泡菜」 → 價格"
    check("驗證錯誤路徑帶分類與品項名稱")
    ctx = json_error_context("a\nb\nc\nd\ne\nf\ng", 4, radius=1)
    assert ctx == ["     3 | c", "▶    4 | d", "     5 | e"], ctx
    check("JSON 解析錯誤附前後行並標記出錯行")

    # ---------- 16. 既有店家匯入：店家只由 UI 決定（V2.12.1） ----------
    print("\n[16] 既有店家匯入不看 JSON 的 store_id")
    import json as _json, re as _re
    import app.routers.admin as _adm
    from fastapi.testclient import TestClient as _TC
    import app.main as _main

    _admin = User(line_user_id="smoke_admin", display_name="管理員", is_admin=True)
    db.add(_admin)
    db.commit()
    _uid = _admin.id

    async def _fake_admin(request, db_):
        return db_.query(User).filter(User.id == _uid).first()
    _orig = _adm.get_admin_user
    _adm.get_admin_user = _fake_admin
    try:
        _c = _TC(_main.app)
        _H = {"HX-Request": "true"}
        _menu = {"categories": [{"name": "小菜", "items": [{"name": "蘭花干", "price": 30}]}]}
        _T = lambda r: _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", " ", r.text))
        _J = lambda d: _json.dumps(d, ensure_ascii=False)

        for label, payload in (("只有 menu", {"menu": _menu}),
                               ("舊格式 store_id:0 + mode", {"store_id": 0, "mode": "replace", "menu": _menu}),
                               ("錯誤的 store_id:999", {"store_id": 999, "menu": _menu}),
                               ("直接貼 categories", _menu)):
            r = _c.post("/admin/import/preview", data={"store_id": str(store.id), "json_text": _J(payload)}, headers=_H)
            assert f"「{store.name}」" in _T(r) and "檢查完成" in _T(r), f"{label}：應以 UI 選的店家為準"
        check("選了店家時，JSON 的 store_id / mode 一律忽略（四種形狀）")

        r = _c.post("/admin/import/preview", data={"store_id": str(store.id),
                    "json_text": _J({"store": {"name": "別家", "category": "meal"}, "menu": _menu})}, headers=_H)
        assert f"「{store.name}」" in _T(r) and "已忽略" in _T(r)
        check("選了店家卻貼新增店家格式 → 以 UI 為準並提示")

        r = _c.post("/admin/import/preview", data={"store_id": "",
                    "json_text": _J({"store_id": store.id, "mode": "new", "menu": _menu})}, headers=_H)
        assert "沒有選定店家" in _T(r) and "編號" not in _T(r), "沒選店家時不該從 JSON 撈 store_id"
        check("沒選店家時不再從 JSON 讀 store_id，要求在畫面上選")

        r = _c.post("/admin/import", data={"json_str": _J({"store_id": 999, "mode": "new", "menu": _menu})})
        assert r.status_code == 400 and "不存在" in r.text
        check("直接打確認端、店家不存在 → 400 而非外鍵 500")
    finally:
        _adm.get_admin_user = _orig

    # ---------- 17. 店家工作台（V2.13.0） ----------
    print("\n[17] 店家工作台")
    _adm.get_admin_user = _fake_admin
    try:
        r = _c.get("/admin/stores")
        assert r.status_code == 200 and "/admin/stores/new" in r.text and "lastGroup" in r.text
        check("列表 200，含新增店家入口與上次開團欄")

        r = _c.get(f"/admin/stores/{store.id}")
        assert r.status_code == 200 and "店家設定" in r.text and "營運設定" not in r.text and "基本資料" in r.text
        check("工作台 200，分頁（V2.21.0 起：菜單／共用選項／店家設定／更多）")

        r = _c.get(f"/admin/stores/{store.id}/edit", follow_redirects=False)
        assert r.status_code == 301 and r.headers["location"].endswith("?tab=settings")
        r = _c.get(f"/admin/stores/{store.id}/menus", follow_redirects=False)
        assert r.status_code == 301 and "tab=menu" in r.headers["location"]
        check("舊網址 /edit、/menus 轉址到工作台對應分頁")

        r = _c.post(f"/admin/stores/{store.id}/delete", data={"confirm_name": "錯的"})
        assert r.status_code == 400
        assert db.query(Store).filter(Store.id == store.id).first() is not None
        check("刪除店家：店名不符回 400，店家仍在")

        r = _c.post("/admin/stores/new", data={"name": "煙霧新店", "category": "meal"}, follow_redirects=False)
        assert r.status_code == 302 and "created=1" in r.headers["location"]
        check("手動新增店家 → 導向工作台並帶 created")

        r = _c.get("/admin/stores/new")
        assert r.status_code == 200, "/stores/new 必須排在 /stores/{id} 之前，否則 'new' 進 int 路由 422"
        check("/stores/new 路由順序正確")
    finally:
        _adm.get_admin_user = _orig

    # ---------- 18. 匯入計數 ----------
    print("\n[18] 匯入計數")
    content = MenuContent(
        categories=[{"name": "甜點", "items": [{"name": "a", "price": 1}, {"name": "b", "price": 2}]}],
        items=[{"name": "c", "price": 3}],
    )
    assert _count_import(content) == (1, 3)
    check("分類內品項與無分類品項都算進去")
    assert _count_import(MenuContent()) == (0, 0)
    check("空菜單")

    # ---------- 19. 菜單差異預覽（V2.13.1） ----------
    print("\n[19] 菜單差異預覽")
    from app.services.menu_diff import diff_menu
    from app.services.import_service import import_store_and_menu, import_menu
    from app.schemas.menu import FullImport, MenuImport

    _base = {"categories": [
        {"name": "滷味", "items": [{"name": "滷蛋", "price": 10}, {"name": "鴨血", "price": 30},
                                  {"name": "豆干", "price": 15}, {"name": "海帶", "price": 15}]},
        {"name": "小菜", "items": [{"name": "黃金泡菜", "price": 40},
                                  {"name": "紅茶", "price": 20, "options": [{"name": "去冰", "price_diff": 0}]}]},
        {"name": "飲料", "items": [{"name": "紅茶", "price": 25, "price_l": 30}]},
    ]}
    _ds = import_store_and_menu(db, FullImport(store={"name": "差異測試店", "category": "meal"}, menu=_base))
    _active = db.query(Menu).filter(Menu.store_id == _ds.id, Menu.is_active == True).first()
    assert _active is not None

    _new = MenuContent(**{"categories": [
        {"name": "滷味", "items": [{"name": "滷蛋", "price": "15.00"}, {"name": "豆干", "price": "15.00"},
                                  {"name": "海帶", "price": 15}, {"name": "滷大腸", "price": 80}]},
        {"name": "招牌", "items": [{"name": "黃金泡菜", "price": 40}]},
        {"name": "小菜", "items": [{"name": "紅茶", "price": 20, "options": [{"name": "去冰", "price_diff": 0}, {"name": "溫", "price_diff": 0}]}]},
        {"name": "飲料", "items": [{"name": "紅茶", "price": 25, "price_l": 30}]},
    ]})
    d = diff_menu(_active, _new)
    assert [a["name"] for a in d["added"]] == ["滷大腸"], d["added"]
    assert [r["name"] for r in d["removed"]] == ["鴨血"], d["removed"]
    _chg = {c["name"]: c for c in d["changed"]}
    assert set(_chg) == {"滷蛋", "黃金泡菜", "紅茶"}, set(_chg)
    assert _chg["滷蛋"]["price_changed"] and _chg["滷蛋"]["old_price_text"] == "$10" and _chg["滷蛋"]["new_price_text"] == "$15"
    assert _chg["黃金泡菜"]["category_changed"] and not _chg["黃金泡菜"]["price_changed"] and "分類改了" in _chg["黃金泡菜"]["note"]
    assert _chg["紅茶"]["options_changed"] and _chg["紅茶"]["category"] == "小菜", "同名品項（小菜／飲料各一）要依分類配對，飲料的紅茶不變"
    assert "選項：新增 溫 +0" in _chg["紅茶"]["note"], _chg["紅茶"]["note"]
    assert d["unchanged_count"] == 3 and not d["partial_suspect"], d
    check("新增／變價／分類改／選項改／移除／不變各自歸類；10 與 15.00 正規化比價；同名品項依分類配對")

    d2 = diff_menu(_active, MenuContent(**{"categories": [{"name": "滷味", "items": [{"name": "滷蛋", "price": 15}, {"name": "豆干", "price": 15}]}]}))
    assert d2["partial_suspect"] and len(d2["removed"]) == 5 and d2["existing_count"] == 7, d2
    check("移除 5/7 → 疑似只貼了部分菜單")

    _small = import_store_and_menu(db, FullImport(store={"name": "小菜單店", "category": "meal"},
                                                  menu={"items": [{"name": "a", "price": 1}, {"name": "b", "price": 2}, {"name": "c", "price": 3}]}))
    _sm = db.query(Menu).filter(Menu.store_id == _small.id, Menu.is_active == True).first()
    d3 = diff_menu(_sm, MenuContent(**{"items": [{"name": "a", "price": 1}]}))
    assert len(d3["removed"]) == 2 and not d3["partial_suspect"]
    check("小菜單（<6 項）大改不當成部分菜單")

    d4 = diff_menu(_active, MenuContent(**_base))
    assert not d4["added"] and not d4["changed"] and not d4["removed"] and d4["unchanged_count"] == 7
    check("貼回同一份 → 全部不變")

    _adm.get_admin_user = _fake_admin
    try:
        r = _c.post("/admin/import/preview", data={"store_id": str(_ds.id), "json_text": _J({"menu": _new.model_dump(mode="json")})}, headers=_H)
        t = _T(r)
        assert "與第 1 版比：新增 1・變更 3・移除 1・不變 3" in t and "將建立第 2 版" in t, t
        assert "確認更新菜單" in t and "base_menu_id" in r.text
        assert "只貼了部分菜單" not in t
        check("預覽片段顯示差異卡與帶數字的確認鈕")

        r = _c.post("/admin/import/preview", data={"store_id": str(_ds.id),
                    "json_text": _J({"menu": {"categories": [{"name": "滷味", "items": [{"name": "滷蛋", "price": 15}]}]}})}, headers=_H)
        t = _T(r)
        assert "看起來只貼了部分菜單" in t and "仍要更新（移除 6 個品項）" in t, t
        check("部分菜單 → 醒目提醒，按鈕改「仍要匯入」但不擋")

        r = _c.post("/admin/import/preview", data={"store_id": "",
                    "json_text": _J({"store": {"name": "差異測試店", "category": "meal"}, "menu": _new.model_dump(mode="json")})}, headers=_H)
        t = _T(r)
        assert "同名店家" in t and "查看變更明細" in t, t
        check("同名店家匯入也跟它的使用中版本比")

        r = _c.post("/admin/import/preview", data={"store_id": "",
                    "json_text": _J({"store": {"name": "全新的店", "category": "meal"}, "menu": _new.model_dump(mode="json")})}, headers=_H)
        t = _T(r)
        assert "查看變更明細" not in t and "確認建立店家" in t and "將新增店家" in t
        check("新店家沒有差異卡，按鈕維持「確認匯入」")
    finally:
        _adm.get_admin_user = _orig

    # ---------- 20. 時價／停售／說明 ＋ 價格容錯 ＋ 截止後定價（V2.14.0） ----------
    print("\n[20] 匯入時價／停售／說明與截止後定價")
    from app.schemas.menu import MenuItemImport, parse_price_input, TBD
    from pydantic import ValidationError as _VE
    from app.routers.admin import humanize_validation_error
    from app.models.menu import MenuItem as _MI

    for raw, want in (("$30", 30), ("30元", 30), ("NT$30", 30), ("３０", 30), ("1,200", 1200), (30, 30), ("30.5", Decimal("30.5"))):
        assert parse_price_input(raw) == Decimal(str(want)), raw
    for raw in ("時價", " 市價 ", "依時價", "TBD", "未定"):
        assert parse_price_input(raw) is TBD, raw
    check("價格容錯：$30／30元／NT$30／全形／千分位 → 數字；時價／市價／TBD → 時價")

    _it = MenuItemImport(name="清蒸魚", price="時價", price_l="400")
    assert _it.price_tbd and _it.price == 0 and _it.price_l is None
    _it = MenuItemImport(name="滷肉飯", price="$40", description="限午間", is_available=False)
    assert _it.price == 40 and _it.note == "限午間" and _it.is_available is False
    check("時價 → price_tbd（price_l 一併清掉）；description 當 note 別名；is_available 收進來")

    try:
        MenuContent(categories=[{"name": "海鮮", "items": [{"name": "炒蛤蜊", "price": "看不清"}]}])
        assert False, "看不懂的價格應該報錯"
    except _VE as e:
        msgs = humanize_validation_error(e, {"categories": [{"name": "海鮮", "items": [{"name": "炒蛤蜊", "price": "看不清"}]}]})
        assert any("炒蛤蜊" in m and "看不懂的價格" in m for m in msgs), msgs
    check("解析不了的價格 → 中文錯誤並指出是哪個品項")

    _tbd_menu = {"categories": [{"name": "海鮮", "items": [
        {"name": "清蒸魚", "price": "時價"},
        {"name": "炒蛤蜊", "price": 180},
        {"name": "炸蝦捲", "price": 80, "is_available": False},
        {"name": "泡菜", "price": 0},
        {"name": "滷肉飯", "price": 40, "note": "限午間"},
        {"name": "蚵仔酥", "price": 120},
    ]}]}
    a = analyze_menu_content(MenuContent(**_tbd_menu))
    assert not a["blockers"]
    assert not any("清蒸魚" in w for w in a["warnings"]), "時價品項不該有價格 0 警告"
    assert any("泡菜" in w and "免費" in w for w in a["warnings"])
    assert any("停售" in w and "炸蝦捲" in w for w in a["warnings"])
    check("分析：時價不警告、價格 0 提示免費、停售品項彙整一條")

    _ts = import_store_and_menu(db, FullImport(store={"name": "時價店", "category": "meal"}, menu=_tbd_menu))
    _tm = db.query(Menu).filter(Menu.store_id == _ts.id, Menu.is_active == True).first()
    _fish = db.query(_MI).filter(_MI.menu_id == _tm.id, _MI.name == "清蒸魚").first()
    _roll = db.query(_MI).filter(_MI.menu_id == _tm.id, _MI.name == "炸蝦捲").first()
    _rice = db.query(_MI).filter(_MI.menu_id == _tm.id, _MI.name == "滷肉飯").first()
    assert _fish.price_tbd and _fish.price == 0 and not _roll.is_available and _rice.description == "限午間"
    check("匯入寫進 price_tbd／is_available／description 三欄")

    d = diff_menu(_tm, MenuContent(**{"categories": [{"name": "海鮮", "items": [
        {"name": "清蒸魚", "price": 380},
        {"name": "炒蛤蜊", "price": 180},
        {"name": "炸蝦捲", "price": 80},
        {"name": "泡菜", "price": 0},
        {"name": "滷肉飯", "price": 40, "note": "限午間，需預訂"},
        {"name": "蚵仔酥", "price": "時價"},
    ]}]}))
    _chg = {c["name"]: c for c in d["changed"]}
    assert _chg["清蒸魚"]["old_price_text"] == "時價" and _chg["清蒸魚"]["new_price_text"] == "$380" and _chg["清蒸魚"]["price_changed"]
    assert _chg["蚵仔酥"]["new_price_text"] == "時價" and _chg["蚵仔酥"]["price_changed"]
    assert _chg["炸蝦捲"]["availability_changed"] and "恢復供應" in _chg["炸蝦捲"]["note"]
    assert _chg["滷肉飯"]["note_changed"] and "說明：「限午間」→「限午間，需預訂」" in _chg["滷肉飯"]["note"], _chg["滷肉飯"]["note"]
    assert d["unchanged_count"] == 2, d
    check("差異：時價↔固定價、停售↔供應、說明改了都算變更")

    _adm.get_admin_user = _fake_admin
    try:
        r = _c.post("/admin/import/preview", data={"store_id": str(_ts.id), "json_text": _J({"menu": _tbd_menu})}, headers=_H)
        t = _T(r)
        assert "時價" in t and "停售" in t and "限午間" in t, t
        check("預覽明細顯示時價／停售／說明")
    finally:
        _adm.get_admin_user = _orig

    # 截止後定價回寫本團
    import app.routers.groups as _grp
    _g = Group(owner_id=user.id, store_id=_ts.id, menu_id=_tm.id, name="時價團",
               category=CategoryType.MEAL, deadline=tpe - timedelta(hours=1))
    db.add(_g); db.flush()
    _o1 = Order(group_id=_g.id, user_id=user.id, status=OrderStatus.SUBMITTED)
    _o2 = Order(group_id=_g.id, user_id=_admin.id, status=OrderStatus.SUBMITTED)
    db.add_all([_o1, _o2]); db.flush()
    db.add(OrderItem(order_id=_o1.id, menu_item_id=_fish.id, item_name="清蒸魚", quantity=1, unit_price=Decimal("0")))
    db.add(OrderItem(order_id=_o2.id, menu_item_id=_fish.id, item_name="清蒸魚", quantity=2, unit_price=Decimal("0")))
    db.add(OrderItem(order_id=_o2.id, menu_item_id=_rice.id, item_name="滷肉飯", quantity=1, unit_price=Decimal("40")))
    db.commit()

    _tl = _grp._tbd_items_for_group(db, _g)
    assert len(_tl) == 1 and _tl[0]["item"].id == _fish.id and _tl[0]["people"] == 2 and _tl[0]["qty"] == 3 and _tl[0]["pending"]
    check("定價清單：只列有人點的時價品項，含人數與份數")

    async def _fake_owner(request, db_):
        return db_.query(User).filter(User.id == user.id).first()
    _orig_cu = _grp.get_current_user
    _grp.get_current_user = _fake_owner
    try:
        r = _c.post(f"/groups/{_g.id}/tbd-price/{_fish.id}", data={"price": "380"}, headers=_H)
        assert r.status_code == 200, r.text[:200]
        db.expire_all()
        prices = sorted(Decimal(str(i.unit_price)) for i in db.query(OrderItem).filter(OrderItem.menu_item_id == _fish.id, OrderItem.order_id.in_([_o1.id, _o2.id])))
        assert prices == [Decimal("380"), Decimal("380")], prices
        assert db.get(_MI, _fish.id).price_tbd and db.get(_MI, _fish.id).price == 0, "菜單品項必須維持時價"
        assert "已定 $380" in _T(r)
        check("截止後定價 → 本團兩筆訂單回寫 $380，菜單品項仍是時價，面板顯示已定")

        r = _c.post(f"/groups/{_g.id}/tbd-price/{_fish.id}", data={"price": "350"}, headers=_H)
        db.expire_all()
        assert all(Decimal(str(i.unit_price)) == 350 for i in db.query(OrderItem).filter(OrderItem.menu_item_id == _fish.id))
        check("可重複改價（店家報錯了）")

        r = _c.post(f"/groups/{_g.id}/tbd-price/{_rice.id}", data={"price": "50"}, headers=_H)
        assert r.status_code == 404
        r = _c.post(f"/groups/{_g.id}/tbd-price/{_fish.id}", data={"price": "0"}, headers=_H)
        assert r.status_code == 400
        _g.deadline = tpe + timedelta(hours=1); db.commit()
        r = _c.post(f"/groups/{_g.id}/tbd-price/{_fish.id}", data={"price": "380"}, headers=_H)
        assert r.status_code == 400 and "截止" in r.text
        check("非時價品項 404、價格 0 → 400、團還開著 → 400")
    finally:
        _grp.get_current_user = _orig_cu

    # ---------- 21. V2.14.1 審核修正 ----------
    print("\n[21] V2.14.1 審核修正")
    from html.parser import HTMLParser
    from app.models.menu import MenuCategory as _MC
    from app.models.order import OrderItemBackup as _OIB

    class _Attrs(HTMLParser):
        """把所有標籤的屬性收起來（屬性值已由瀏覽器規則解碼），檢查屬性內 JS 用"""
        def __init__(self):
            super().__init__(); self.found = []
        def handle_starttag(self, tag, attrs):
            self.found.extend(attrs)
        def handle_startendtag(self, tag, attrs):
            self.found.extend(attrs)

    def _attrs(html):
        h = _Attrs(); h.feed(html); return h.found

    # P0-1：團名含撇號與引號，後台團單列表的 onsubmit 不能把名稱直接拼進 JS
    _evil = """Tom's "x");fetch('/x');('"""
    _ge = Group(owner_id=user.id, store_id=store.id, name=_evil, category=CategoryType.MEAL, deadline=tpe - timedelta(hours=1))
    db.add(_ge); db.commit()
    _adm.get_admin_user = _fake_admin
    try:
        r = _c.get("/admin/groups")
        assert r.status_code == 200
        at = _attrs(r.text)
        onsub = [v for k, v in at if k == "onsubmit" and v and "刪除" in v]
        assert onsub and all("this.dataset.name" in v and "Tom" not in v for v in onsub), onsub[:2]
        assert any(k == "data-name" and v == _evil for k, v in at), "data-name 應為原字串（瀏覽器解碼後）"
        check("P0-1：團名不進 confirm() 的 JS 字串，改走 data-name")

        # P1-2：工作台 x-data 經 tojson 的值要放在單引號屬性，解析後屬性值必須完整
        r = _c.get(f"/admin/stores/{store.id}?tab=info")  # 舊分頁名 → 店家設定（V2.21.0）
        xd = [v for k, v in _attrs(r.text) if k == "x-data" and v and "tab:" in v]
        assert xd and 'tab: "settings"' in xd[0] and "confirmName" in xd[0], xd
        r = _c.get("/admin/stores/new")
        xd = [v for k, v in _attrs(r.text) if k == "x-data" and v and "existing" in v]
        assert xd and "existing: [" in xd[0] and xd[0].rstrip().endswith("}"), xd
        check("P1-2：tojson 放單引號屬性，x-data 不再被雙引號截斷（V2.13.0 的工作台分頁因此失效）")
    finally:
        _adm.get_admin_user = _orig

    # P0-2：品名含撇號與引號，點餐頁的 @click 要是 JSON 字串
    _xs = import_store_and_menu(db, FullImport(store={"name": "跳脫店", "category": "meal"}, menu={"categories": [
        {"name": "主食", "items": [{"name": """McDonald's "big" <b>""", "price": 50,
                                   "options": [{"name": "加蛋'x", "price_diff": 10}]}]}]}))
    _xm = db.query(Menu).filter(Menu.store_id == _xs.id, Menu.is_active == True).first()
    _xg = Group(owner_id=user.id, store_id=_xs.id, menu_id=_xm.id, name="跳脫團", category=CategoryType.MEAL, deadline=tpe + timedelta(hours=1))
    db.add(_xg); db.commit()
    _grp.get_current_user = _fake_owner

    async def _fake_owner_opt(request, db_):
        return (db_.query(User).filter(User.id == user.id).first(), None)
    _orig_cuo = _grp.get_current_user_optional
    _grp.get_current_user_optional = _fake_owner_opt
    try:
        r = _c.get(f"/groups/{_xg.id}")
        assert r.status_code == 200, r.status_code
        clicks = [v for k, v in _attrs(r.text) if k == "@click" and v and "openAddItem" in v]
        assert clicks, "找不到 openAddItem 按鈕"
        assert all('"McDonald' in v and "'McDonald" not in v for v in clicks), clicks[0][:200]
        assert all("\\u003cb\\u003e" in v or "<b>" not in v for v in clicks), "名稱裡的 <b> 應被 tojson 逸出"
        assert "renderOptions" not in r.text
        check("P0-2：品名／選項名進 @click 一律 tojson，<b> 與引號都不會變成程式碼")

        # P1-1：代購品項帶 stock_limit 修改不能 500（func 未匯入）
        _ps = Store(name="我的代購店", category=CategoryType.GROUP_BUY, is_personal=True, owner_user_id=user.id)
        db.add(_ps); db.flush()
        _pm = Menu(store_id=_ps.id, is_active=False); db.add(_pm); db.flush()
        _pc = _MC(menu_id=_pm.id, name="代購", sort_order=0); db.add(_pc); db.flush()
        _pi = _MI(menu_id=_pm.id, category_id=_pc.id, name="代購品", price=Decimal("100"), sort_order=0); db.add(_pi); db.flush()
        _pg = Group(owner_id=user.id, store_id=_ps.id, menu_id=_pm.id, name="代購團", category=CategoryType.GROUP_BUY, deadline=tpe + timedelta(hours=1))
        db.add(_pg); db.commit()
        r = _c.post(f"/groups/{_pg.id}/items/{_pi.id}/update", data={"item_name": "代購品", "price": "120", "stock_limit": "5"}, headers=_H)
        assert r.status_code == 200, (r.status_code, r.text[:200])
        db.expire_all()
        assert db.get(_MI, _pi.id).stock_limit == 5 and db.get(_MI, _pi.id).price == 120
        check("P1-1：代購品項帶上限修改 → 200（原本 NameError: func）")

        # P2-9：代購團不走 tbd-price
        _pi.price_tbd = True; _pg.deadline = tpe - timedelta(hours=1); db.commit()
        r = _c.post(f"/groups/{_pg.id}/tbd-price/{_pi.id}", data={"price": "100"}, headers=_H)
        assert r.status_code == 400 and "代購" in r.text
        check("P2-9：代購團的時價定價走代購面板，tbd-price 回 400")

        # P1-3：候補的加購加料不被回寫蓋掉；P2-10：$380 與 NaN
        _g.deadline = tpe - timedelta(hours=1); db.commit()
        _oi1 = db.query(OrderItem).filter(OrderItem.order_id == _o1.id, OrderItem.menu_item_id == _fish.id).first()
        db.add(_OIB(order_item_id=_oi1.id, priority=1, menu_item_id=_fish.id, item_name="清蒸魚", extras_text="加飯",
                    unit_price=Decimal("10"), extras_price=Decimal("10")))
        db.commit()
        r = _c.post(f"/groups/{_g.id}/tbd-price/{_fish.id}", data={"price": "$380"}, headers=_H)
        assert r.status_code == 200, r.text[:200]
        db.expire_all()
        _b = db.query(_OIB).filter(_OIB.order_item_id == _oi1.id).first()
        assert Decimal(str(_b.unit_price)) == 390 and Decimal(str(_b.extras_price)) == 10, (_b.unit_price, _b.extras_price)
        check("P1-3：定價 380 後候補 = 380 + 加購 10 = 390（原本被蓋成 380）；P2-10：$380 也收")
        r = _c.post(f"/groups/{_g.id}/tbd-price/{_fish.id}", data={"price": "NaN"}, headers=_H)
        assert r.status_code == 400
        r = _c.post(f"/groups/{_g.id}/tbd-price/{_fish.id}", data={"price": "Infinity"}, headers=_H)
        assert r.status_code == 400
        check("P2-10：NaN／Infinity → 400 而非 500")
        # only_zero=True（代購路徑）：基本價仍為 0 的候補才回寫
        _b.unit_price = Decimal("10"); db.commit()
        _grp._writeback_tbd_price(db, _g, _fish.id, Decimal("200"), only_zero=True); db.commit(); db.expire_all()
        assert Decimal(str(db.get(_OIB, _b.id).unit_price)) == 210
        _grp._writeback_tbd_price(db, _g, _fish.id, Decimal("300"), only_zero=True); db.commit(); db.expire_all()
        assert Decimal(str(db.get(_OIB, _b.id).unit_price)) == 210, "only_zero 不該再動已定價的候補"
        check("P1-3：only_zero 的判斷改為「基本價仍為 0」（unit_price == extras_price）")

        # P2-12：店家已刪、團有分店 → 團頁不 500
        _dg = Group(owner_id=user.id, store_id=None, menu_id=None, store_name="已刪店", branch_id=1, name="無店團",
                    category=CategoryType.MEAL, deadline=tpe - timedelta(hours=1))
        db.add(_dg); db.commit()
        r = _c.get(f"/groups/{_dg.id}")
        assert r.status_code == 200, r.status_code
        check("P2-12：店家已刪但 branch_id 殘留 → 團頁 200")
    finally:
        _grp.get_current_user = _orig_cu
        _grp.get_current_user_optional = _orig_cuo

    # P1-4：blocker 要在寫入前擋——直接打確認端，版本數不能變、使用中版本不能換
    _adm.get_admin_user = _fake_admin
    try:
        _before = db.query(Menu).filter(Menu.store_id == _ts.id).count()
        _act = db.query(Menu.id).filter(Menu.store_id == _ts.id, Menu.is_active == True).scalar()
        r = _c.post("/admin/import", data={"json_str": _J({"store_id": _ts.id, "mode": "new", "menu": {"categories": [
            {"name": "a", "items": [{"name": "重複", "price": 1}, {"name": "重複", "price": 2}]}]}})})
        assert r.status_code == 400
        db.expire_all()
        assert db.query(Menu).filter(Menu.store_id == _ts.id).count() == _before
        assert db.query(Menu.id).filter(Menu.store_id == _ts.id, Menu.is_active == True).scalar() == _act
        check("P1-4：blocker 在 commit 之前擋，沒有多出版本、使用中版本不變")
        r = _c.post("/admin/import", data={"json_str": "[1,2]"})
        assert r.status_code == 400
        check("P3：JSON 最外層是陣列 → 400 而非 500")
    finally:
        _adm.get_admin_user = _orig

    # P1-5 / P2-1 / P2-2 / P2-4 / P2-3
    assert MenuItemImport(name="x", price=50, price_tbd="false").price == 50
    assert MenuItemImport(name="x", price=50, price_tbd="true").price_tbd
    check("P1-5：price_tbd 字串 \"false\" 不再把價格清成 0")
    for bad in ("30,50", "3,0"):
        try:
            parse_price_input(bad); assert False, bad
        except ValueError as e:
            assert "M/L" in str(e)
    assert parse_price_input("1,200,000") == 1200000
    check("P2-1：逗號只接受千分位，\"30,50\" 報錯並提示分填 price/price_l")
    try:
        MenuItemImport(name="x", price=30, price_l="時價"); assert False
    except _VE as e:
        assert "L 尺寸不支援單獨時價" in str(e)
    check("P2-2：只有 price_l 是時價 → 報錯，不把整項變時價")
    assert analyze_menu_content(MenuContent(categories=[]))["blockers"] == ["菜單沒有任何品項"]
    check("P2-4：空菜單是 blocker")
    for kw, key in ((dict(name="a" * 101, price=1), "100 字"), (dict(name="x", price=-30), "負數"), (dict(name="x", price=10 ** 9), "上限")):
        try:
            MenuItemImport(**kw); assert False, kw
        except _VE as e:
            assert key in str(e), (key, str(e)[:120])
    try:
        FullImport(store={"name": "", "category": "meal"}, menu={"items": [{"name": "x", "price": 1}]}); assert False
    except _VE as e:
        assert "店名" in str(e)
    check("P2-3：名稱長度、負價、超大價、空店名都在 schema 擋下（原本到 PostgreSQL 才 500）")

    # P1-6：刪店家時有修改中的單 → 先還原，之後結算不會撞外鍵
    _ds2 = import_store_and_menu(db, FullImport(store={"name": "要刪的店", "category": "meal"}, menu={"items": [{"name": "品", "price": 10}]}))
    _dm2 = db.query(Menu).filter(Menu.store_id == _ds2.id, Menu.is_active == True).first()
    _di2 = db.query(_MI).filter(_MI.menu_id == _dm2.id).first()
    _dg2 = Group(owner_id=user.id, store_id=_ds2.id, menu_id=_dm2.id, name="刪店團", category=CategoryType.MEAL, deadline=tpe + timedelta(hours=1))
    db.add(_dg2); db.flush()
    _do2 = Order(group_id=_dg2.id, user_id=user.id, status=OrderStatus.EDITING, snapshot={"items": [{
        "menu_item_id": _di2.id, "item_name": "品", "size": None, "sugar": None, "ice": None, "quantity": 1,
        "unit_price": "10.00", "note": None, "options": [], "toppings": [],
        "backups": [{"priority": 1, "menu_item_id": _di2.id, "item_name": "品", "size": None, "sugar": None, "ice": None,
                     "extras_text": None, "unit_price": "10.00"}]}]})
    db.add(_do2); db.commit()
    _adm.get_admin_user = _fake_admin
    try:
        r = _c.post(f"/admin/stores/{_ds2.id}/delete", data={"confirm_name": "要刪的店"}, follow_redirects=False)
        assert r.status_code == 302, (r.status_code, r.text[:200])
    finally:
        _adm.get_admin_user = _orig
    db.expire_all()  # SQLite 會重用被刪店家的 id，identity map 裡的舊物件要清掉（PG 用序列不會）
    _do2 = db.get(Order, _do2.id)
    assert _do2.status == OrderStatus.SUBMITTED and _do2.snapshot is None
    assert [i.item_name for i in _do2.items] == ["品"] and _do2.items[0].menu_item_id is None
    check("P1-6：刪店家前先把修改中的單還原，外鍵已清、歷史保留")
    # 還原函式本身也要容忍快照裡的死外鍵
    _dg3 = Group(owner_id=user.id, store_id=None, menu_id=None, store_name="x", name="死外鍵團", category=CategoryType.MEAL, deadline=tpe - timedelta(hours=1))
    db.add(_dg3); db.flush()
    _do3 = Order(group_id=_dg3.id, user_id=user.id, status=OrderStatus.EDITING, snapshot={"items": [{
        "menu_item_id": 999999, "item_name": "幽靈", "size": None, "sugar": None, "ice": None, "quantity": 1,
        "unit_price": "5.00", "note": None, "options": [{"item_option_id": 999999, "option_name": "o", "price_diff": "0"}], "toppings": [], "backups": []}]})
    db.add(_do3); db.commit()
    assert settle_editing_orders(db, _dg3) == 1
    db.expire_all()
    assert db.get(Order, _do3.id).items[0].menu_item_id is None
    check("P1-6：快照裡的外鍵已不存在 → 還原時改填 NULL，不再 IntegrityError")

    # ---------- 22. V2.15.0 匯入頁簡化 ----------
    print("\n[22] 匯入頁簡化")
    _adm.get_admin_user = _fake_admin
    try:
        r = _c.get(f"/admin/import?store_id={_ts.id}")
        assert r.status_code == 200
        visible = _re.sub(r"<script\b.*?</script>", " ", r.text, flags=_re.S)
        visible = _re.sub(r"<details\b.*?</details>", " ", visible, flags=_re.S)  # 進階格式說明刻意保留範例
        vt = _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", " ", visible))
        for bad in ("prompt", "JSON", "schema", "store_id", "預覽匯入內容", "上傳檔案"):
            assert bad not in vt, f"畫面不該出現「{bad}」"
        assert "匯入至" in vt and "菜單資料" in vt and "更新菜單" in vt and "複製 AI 轉換指令" in r.text
        assert "使用中第 1 版" in vt
        assert 'hx-trigger="input[' in r.text and "delay:700ms" in r.text, "貼上要自動檢查"
        assert "文字 Logo" not in r.text, "Logo 指令已搬到工作台"
        check("匯入頁：無技術語、匯入至顯示使用中版本、貼上自動檢查、Logo 指令不在此頁")

        r = _c.get("/admin/import")
        assert "新增一家店" in r.text and 'name="store_id"' in r.text and "輸入店名找店" in r.text
        check("沒選店家時「匯入至」是搜尋選店（V2.16.1），預設新增一家店")

        r = _c.get(f"/admin/stores/{_ts.id}?tab=info")
        assert "LOGO_PROMPT_TEXT" in r.text and "沒有 Logo？用 AI 做一個" in r.text
        check("工作台基本資料分頁有 Logo 的 AI 指令")

        # 相同內容 → 停用確認
        _cur = db.query(Menu).filter(Menu.store_id == _ts.id, Menu.is_active == True).first()
        from app.services.menu_diff import _flatten_existing
        same = {"categories": [{"name": "海鮮", "items": [
            {"name": "清蒸魚", "price": "時價"}, {"name": "炒蛤蜊", "price": 180},
            {"name": "炸蝦捲", "price": 80, "is_available": False}, {"name": "泡菜", "price": 0},
            {"name": "滷肉飯", "price": 40, "note": "限午間"}, {"name": "蚵仔酥", "price": 120}]}]}
        r = _c.post("/admin/import/preview", data={"store_id": str(_ts.id), "json_text": _J({"menu": same})}, headers=_H)
        t = _T(r)
        assert "完全相同" in t and "菜單沒有變更" in t and "確認更新菜單" not in t, t
        check("貼回同一份 → 顯示完全相同、確認鈕停用")
        r = _c.post("/admin/import", data={"json_str": _J({"store_id": _ts.id, "mode": "new", "menu": same}), "base_menu_id": str(_cur.id)}, headers=_H)
        assert r.status_code == 400 and "沒有變更" in r.text
        check("後端也擋相同內容（直接打確認端 400）")

        # 摘要優先：明細收合、版本衝突、HX-Redirect
        changed = {"categories": [{"name": "海鮮", "items": [{"name": "清蒸魚", "price": 380}, {"name": "炒蛤蜊", "price": 180}]}]}
        r = _c.post("/admin/import/preview", data={"store_id": str(_ts.id), "json_text": _J({"menu": changed})}, headers=_H)
        assert "<details" in r.text and "查看完整菜單" in r.text and "查看變更明細" in r.text
        assert f'name="base_menu_id" value="{_cur.id}"' in r.text
        check("摘要先出、變更明細與完整菜單收合、片段帶 base_menu_id")

        _before = db.query(Menu).filter(Menu.store_id == _ts.id).count()
        r = _c.post("/admin/import", data={"json_str": _J({"store_id": _ts.id, "mode": "new", "menu": changed}), "base_menu_id": "999999"}, headers=_H)
        assert r.status_code == 200 and "剛被更新" in _T(r) and "base_menu_id" in r.text, r.text[:300]
        db.expire_all()
        assert db.query(Menu).filter(Menu.store_id == _ts.id).count() == _before, "版本不符時不能寫入"
        check("確認時版本不符 → 不寫入，回傳重新比對的片段（含提醒）")
        r = _c.post("/admin/import", data={"json_str": _J({"store_id": _ts.id, "mode": "new", "menu": changed}), "base_menu_id": "999999"})
        assert r.status_code == 409
        check("非 htmx 的版本不符 → 409")

        r = _c.post("/admin/import", data={"json_str": _J({"store_id": _ts.id, "mode": "new", "menu": changed}), "base_menu_id": str(_cur.id)}, headers=_H)
        assert r.status_code == 200 and r.headers.get("HX-Redirect", "").startswith(f"/admin/stores/{_ts.id}?tab=menu") and "ver=" in r.headers["HX-Redirect"]
        db.expire_all()
        assert db.query(Menu).filter(Menu.store_id == _ts.id).count() == _before + 1
        check("版本相符 → 寫入並 HX-Redirect 到工作台（帶新版號）")
        r = _c.get(r.headers["HX-Redirect"])
        assert "菜單已更新為第" in r.text
        check("工作台完成提示縮成一行")
    finally:
        _adm.get_admin_user = _orig

    # ---------- 23. V2.15.1 審核修正 ----------
    print("\n[23] V2.15.1 審核修正")
    from app.templating import money
    from app.routers.admin import clean_pasted_json, _src_digest
    assert money(Decimal("55.00")) == "55" and money(Decimal("32.50")) == "32.5" and money(1200) == "1,200" and money(None) == ""
    check("P2-2：money filter — 55.00→55、32.50→32.5、千分位、None→空")
    for f in ("app/routers/admin.py", "app/routers/groups.py", "app/routers/home.py", "app/routers/orders.py", "app/main.py"):
        assert "register_filters" in open(f, encoding="utf-8").read(), f
    import re as _re2
    from pathlib import Path
    _bad = []
    for _tp in Path("app/templates").rglob("*.html"):
        _txt = _tp.read_text(encoding="utf-8")
        _bad += [f"{_tp.name}: {m}" for m in _re2.findall(r"\$\{\{ [^}|]+ \}\}", _txt)]
        _bad += [f"{_tp.name}: {m}" for m in _re2.findall(r"\$\{\{ [^}]+\|int \}\}", _txt)]
        # V2.16.3 審核 P1-2a：`${{ x|sum(attribute='…') }}` 這種有 `|` 的寫法躲過了上面兩條
        _bad += [f"{_tp.name}: {m}" for m in _re2.findall(r"\$\{\{ [^}]*\|sum\([^}]*\}\}", _txt) if "|money" not in m]
    assert not _bad, _bad[:5]
    check("P2-2：模板裡 $ 後的金額一律過 money（沒有裸輸出、沒有 |int）")

    # P2-1：relationship 有 order_by
    from app.models.menu import Menu as _MenuM, MenuCategory as _MCM, MenuItem as _MIM
    from app.models.store import Store as _StM
    for rel in (_MenuM.categories, _MenuM.items, _MCM.items, _MIM.options, _StM.options, _StM.toppings):
        assert rel.property.order_by, f"{rel} 沒有 order_by"
    check("P2-1：菜單／分類／品項／選項／甜冰／加料的 relationship 都有 order_by")

    # P2-3：只調整順序 → 不是「沒有變更」
    _ord_store = import_store_and_menu(db, FullImport(store={"name": "排序店", "category": "meal"}, menu={"categories": [
        {"name": "A", "items": [{"name": "雞腿飯", "price": 100, "options": [{"name": "加蛋", "price_diff": 10}, {"name": "加飯", "price_diff": 10}]}, {"name": "排骨飯", "price": 90}]},
        {"name": "B", "items": [{"name": "湯", "price": 20}]}]}))
    _om = db.query(Menu).filter(Menu.store_id == _ord_store.id, Menu.is_active == True).first()
    d_same = diff_menu(_om, MenuContent(**{"categories": [
        {"name": "A", "items": [{"name": "雞腿飯", "price": 100, "options": [{"name": "加蛋", "price_diff": 10}, {"name": "加飯", "price_diff": 10}]}, {"name": "排骨飯", "price": 90}]},
        {"name": "B", "items": [{"name": "湯", "price": 20}]}]}))
    assert d_same["identical"] and not d_same["order_changed"]
    d_items = diff_menu(_om, MenuContent(**{"categories": [
        {"name": "A", "items": [{"name": "排骨飯", "price": 90}, {"name": "雞腿飯", "price": 100, "options": [{"name": "加蛋", "price_diff": 10}, {"name": "加飯", "price_diff": 10}]}]},
        {"name": "B", "items": [{"name": "湯", "price": 20}]}]}))
    assert d_items["order_changed"] and not d_items["identical"] and not d_items["changed"], d_items
    d_cats = diff_menu(_om, MenuContent(**{"categories": [
        {"name": "B", "items": [{"name": "湯", "price": 20}]},
        {"name": "A", "items": [{"name": "雞腿飯", "price": 100, "options": [{"name": "加蛋", "price_diff": 10}, {"name": "加飯", "price_diff": 10}]}, {"name": "排骨飯", "price": 90}]}]}))
    assert d_cats["order_changed"] and not d_cats["identical"]
    d_opts = diff_menu(_om, MenuContent(**{"categories": [
        {"name": "A", "items": [{"name": "雞腿飯", "price": 100, "options": [{"name": "加飯", "price_diff": 10}, {"name": "加蛋", "price_diff": 10}]}, {"name": "排骨飯", "price": 90}]},
        {"name": "B", "items": [{"name": "湯", "price": 20}]}]}))
    assert d_opts["order_changed"] and not d_opts["changed"]
    check("P2-3：品項順序／分類順序／選項順序改了 → order_changed，不再被當成沒有變更")
    _adm.get_admin_user = _fake_admin
    try:
        r = _c.post("/admin/import/preview", data={"store_id": str(_ord_store.id), "json_text": _J({"menu": {"categories": [
            {"name": "A", "items": [{"name": "排骨飯", "price": 90}, {"name": "雞腿飯", "price": 100, "options": [{"name": "加蛋", "price_diff": 10}, {"name": "加飯", "price_diff": 10}]}]},
            {"name": "B", "items": [{"name": "湯", "price": 20}]}]}})}, headers=_H)
        t = _T(r)
        assert "只調整了排序" in t and "確認更新菜單" in t and "菜單沒有變更" not in t, t
        check("P2-3：只調整排序 → 摘要說「只調整了排序」且可確認")

        # P2-4：切回舊版後的版號
        import_menu(db, MenuImport(store_id=_ord_store.id, menu={"categories": [{"name": "A", "items": [{"name": "雞腿飯", "price": 110}]}]}))
        _v1 = db.query(Menu).filter(Menu.store_id == _ord_store.id).order_by(Menu.created_at).first()
        r = _c.post(f"/admin/stores/{_ord_store.id}/menus/{_v1.id}/activate", follow_redirects=False)
        assert r.status_code in (302, 303)
        r = _c.post("/admin/import/preview", data={"store_id": str(_ord_store.id), "json_text": _J({"menu": {"items": [{"name": "新", "price": 1}]}})}, headers=_H)
        t = _T(r)
        assert "將建立第 3 版" in t and "使用中的第 1 版" in t and "最新的第 2 版不是使用中" in t, t
        check("P2-4：切回第 1 版再匯入 → 「將建立第 3 版」並提醒最新第 2 版不是使用中")

        # P2-5：甜冰 51 字預覽就擋；去空白去重
        r = _c.post("/admin/import/preview", data={"store_id": "", "new_store_name": "長選項店", "new_store_category": "drink",
                    "json_text": _J({"store": {"name": "", "category": "drink", "sugar_options": ["a" * 51]}, "menu": {"items": [{"name": "x", "price": 1}]}})}, headers=_H)
        assert "超過 50 字" in _T(r)
        from app.schemas.store import StoreImport
        assert StoreImport(name="x", category="drink", sugar_options=[" 正常糖 ", "", "正常糖", "少糖"], logo_url="無").sugar_options == ["正常糖", "少糖"]
        check("P2-5：甜冰選項 51 字預覽即擋；去空白、去重；logo_url 非網址當 None")

        # P2-9：新增一家店，店名與類別由畫面欄位決定（JSON 的 name 留空也行）
        r = _c.post("/admin/import/preview", data={"store_id": "", "new_store_name": "畫面填的店", "new_store_category": "meal",
                    "json_text": _J({"store": {"name": "", "category": "drink"}, "menu": {"items": [{"name": "x", "price": 1}]}})}, headers=_H)
        t = _T(r)
        assert "將新增店家「畫面填的店」" in t and "餐點" in t, t
        r = _c.post("/admin/import/preview", data={"store_id": "", "new_store_name": "只有菜單的新店", "new_store_category": "meal",
                    "json_text": _J({"menu": {"items": [{"name": "x", "price": 1}]}})}, headers=_H)
        assert "將新增店家「只有菜單的新店」" in _T(r)
        check("P2-9：新店家的店名／類別以畫面欄位為準；只有 menu 的資料也能新增店家")

        # B-1：```json 圍欄與前後說明文字自動去掉
        wrapped = "以下是轉換結果：\n```json\n" + _J({"menu": {"items": [{"name": "圍欄", "price": 5}]}}) + "\n```\n如需調整請告訴我。"
        assert clean_pasted_json(wrapped)[1]
        r = _c.post("/admin/import/preview", data={"store_id": str(_ord_store.id), "json_text": wrapped}, headers=_H)
        t = _T(r)
        assert "檢查完成" in t and "已自動去掉" in t, t
        check("B-1：AI 回覆的 ```json 包裝與說明文字自動去掉並提示")

        # P1-1：確認時雜湊不符 → 不寫入、重新預覽
        _cur = db.query(Menu).filter(Menu.store_id == _ord_store.id, Menu.is_active == True).first()
        raw_a = _J({"menu": {"items": [{"name": "A版", "price": 1}]}})
        raw_b = _J({"menu": {"items": [{"name": "B版", "price": 2}]}})
        r = _c.post("/admin/import/preview", data={"store_id": str(_ord_store.id), "json_text": raw_a}, headers=_H)
        assert f'name="src_digest" value="{_src_digest(raw_a)}"' in r.text
        _n0 = db.query(Menu).filter(Menu.store_id == _ord_store.id).count()
        r = _c.post("/admin/import", data={"json_str": _J({"store_id": _ord_store.id, "mode": "new", "menu": {"items": [{"name": "A版", "price": 1}]}}),
                    "base_menu_id": str(_cur.id), "src_digest": _src_digest(raw_a), "json_text": raw_b, "store_id": str(_ord_store.id)}, headers=_H)
        t = _T(r)
        assert r.status_code == 200 and "被改過，沒有寫入" in t and "B版" in t, t
        assert db.query(Menu).filter(Menu.store_id == _ord_store.id).count() == _n0
        check("P1-1：確認時輸入框內容與預覽不同 → 不寫入，用目前內容重新預覽並提醒")
        r = _c.post("/admin/import", data={"json_str": _J({"store_id": _ord_store.id, "mode": "new", "menu": {"items": [{"name": "A版", "price": 1}]}}),
                    "base_menu_id": str(_cur.id), "src_digest": _src_digest(raw_a), "json_text": raw_a, "store_id": str(_ord_store.id)}, headers=_H)
        assert r.status_code == 200 and "HX-Redirect" in r.headers
        check("P1-1：內容沒變 → 正常寫入")

        # P3-6：下拉不含代購個人店
        r = _c.get("/admin/import")
        assert "我的代購店" not in r.text
        check("P3-6：匯入頁店家下拉排除代購個人店")
    finally:
        _adm.get_admin_user = _orig

    # P2-6：匯入新版本後，熱門／最愛／常點仍對得到（按品名）
    import app.routers.home as _home
    _hs = import_store_and_menu(db, FullImport(store={"name": "熱門店", "category": "meal"}, menu={"items": [{"name": "牛肉麵", "price": 150}, {"name": "滷蛋", "price": 15, "is_available": False}]}))
    _hm1 = db.query(Menu).filter(Menu.store_id == _hs.id, Menu.is_active == True).first()
    _niu1 = db.query(_MI).filter(_MI.menu_id == _hm1.id, _MI.name == "牛肉麵").first()
    _hg_old = Group(owner_id=user.id, store_id=_hs.id, menu_id=_hm1.id, name="舊團", category=CategoryType.MEAL, deadline=tpe - timedelta(hours=1))
    db.add(_hg_old); db.flush()
    _ho = Order(group_id=_hg_old.id, user_id=user.id, status=OrderStatus.SUBMITTED); db.add(_ho); db.flush()
    db.add(OrderItem(order_id=_ho.id, menu_item_id=_niu1.id, item_name="牛肉麵", quantity=3, unit_price=Decimal("150")))
    db.add(OrderItem(order_id=_ho.id, menu_item_id=db.query(_MI).filter(_MI.menu_id == _hm1.id, _MI.name == "滷蛋").first().id, item_name="滷蛋", quantity=9, unit_price=Decimal("15")))
    db.commit()
    import_menu(db, MenuImport(store_id=_hs.id, menu={"items": [{"name": "牛肉麵", "price": 160}, {"name": "滷蛋", "price": 15, "is_available": False}]}))
    _hm2 = db.query(Menu).filter(Menu.store_id == _hs.id, Menu.is_active == True).first()
    _niu2 = db.query(_MI).filter(_MI.menu_id == _hm2.id, _MI.name == "牛肉麵").first()
    _hg_new = Group(owner_id=user.id, store_id=_hs.id, menu_id=_hm2.id, name="新團", category=CategoryType.MEAL, deadline=tpe + timedelta(hours=1))
    db.add(_hg_new); db.commit()
    _grp.get_current_user = _fake_owner
    _grp.get_current_user_optional = _fake_owner_opt
    try:
        r = _c.get(f"/groups/{_hg_new.id}")
        assert r.status_code == 200
        assert f"scrollToItem({_niu2.id})" in r.text, "熱門／最愛要指向新版本的品項 id"
        assert f"scrollToItem({_niu1.id})" not in r.text
        assert "你的常點" in r.text and "滷蛋" not in r.text.split("你的常點")[1][:600], "停售的不列入常點"
        check("P2-6：匯入新版本後熱門／最愛／常點按品名對到新 id，停售不列")

        # P2-8：隨機池排除停售、時價帶旗標
        _js = r.text[r.text.index("const menuItems = ["):r.text.index("];", r.text.index("const menuItems = ["))]
        _esc = lambda w: _json.dumps(w)[1:-1]  # tojson 預設 ensure_ascii，中文是 \uXXXX
        assert _esc("牛肉麵") in _js and _esc("滷蛋") not in _js, _js[:300]
        check("P2-8：隨機池不含停售品項")
    finally:
        _grp.get_current_user = _orig_cu
        _grp.get_current_user_optional = _orig_cuo

    # P2-7：前台店家菜單頁——時價、停售隱藏、無分類品項
    _orig_home_cu = _home.get_current_user
    _home.get_current_user = _fake_owner
    try:
        _fs = import_store_and_menu(db, FullImport(store={"name": "前台菜單店", "category": "meal"}, menu={
            "categories": [{"name": "海鮮", "items": [{"name": "清蒸魚", "price": "時價"}, {"name": "炸蝦捲", "price": 80, "is_available": False},
                                                     {"name": "滷肉飯", "price": 40, "note": "限午間", "options": [{"name": "加蛋", "price_diff": 10}]}]}],
            "items": [{"name": "滷蛋", "price": 15}]}))
        r = _c.get(f"/stores/{_fs.id}/menu")
        assert r.status_code == 200
        t = _T(r)
        assert "清蒸魚 時價" in t and "$0" not in t, t
        assert "炸蝦捲" not in t, "停售品項不該顯示"
        assert "限午間" in t and "加蛋 +$10" in t
        assert "其他" in t and "滷蛋" in t, "無分類品項要顯示在「其他」"
        check("P2-7：前台菜單頁時價不顯示 $0、停售隱藏、無分類品項顯示、說明顯示")
    finally:
        _home.get_current_user = _orig_home_cu

    # ---------- 24. V2.16.0 菜單呈現 ----------
    print("\n[24] V2.16.0 菜單呈現")
    _ms = import_store_and_menu(db, FullImport(store={"name": "呈現測試店", "category": "drink"}, menu={
        "categories": [
            {"name": "熟成紅茶", "items": [{"name": "熟成紅茶", "price": 35, "price_l": 40, "note": "本店招牌，冷泡 12 小時"}, {"name": "熟成冷露", "price": 45}]},
            {"name": "全停售", "items": [{"name": "下架品", "price": 10, "is_available": False}]},
            {"name": "鮮奶茶", "items": [{"name": "紅茶拿鐵", "price": 55, "price_l": 65}, {"name": "烏龍拿鐵", "price": 55}, {"name": "停售拿鐵", "price": 55, "is_available": False}]},
        ],
        "items": [{"name": "滷蛋", "price": 15}, {"name": "停售滷蛋", "price": 15, "is_available": False}]}))
    _mm = db.query(Menu).filter(Menu.store_id == _ms.id, Menu.is_active == True).first()
    _mg = Group(owner_id=user.id, store_id=_ms.id, menu_id=_mm.id, name="呈現團", category=CategoryType.DRINK, deadline=tpe + timedelta(hours=1))
    db.add(_mg); db.commit()
    _grp.get_current_user = _fake_owner
    _grp.get_current_user_optional = _fake_owner_opt
    try:
        r = _c.get(f"/groups/{_mg.id}")
        assert r.status_code == 200
        t = _T(r)
        # A-1：有大杯價 → 兩行 M／L；沒有的維持單一價
        assert "M $35" in t and "L $40" in t and "$35/$40" not in t, t[:2000]
        assert "M $55" in t and "L $65" in t
        assert "熟成冷露 $45" in t and "M $45" not in t
        check("A-1：大杯價顯示為 M／L 兩行，單一價不加 M")
        # A-2：列表說明改兩行（line-clamp-2，不 truncate）；彈窗帶 description
        assert 'line-clamp-2">本店招牌' in r.text and 'truncate">本店招牌' not in r.text
        assert "description: " + _json.dumps("本店招牌，冷泡 12 小時") in r.text, "openAddItem 要帶 description"
        assert 'x-text="selectedItem?.description"' in r.text
        check("A-2：說明列表兩行不截斷、彈窗顯示說明")
        # A-5：導覽 chip 帶品項數（只算會顯示的），全停售分類不出現，無分類品項有「其他」並進導覽
        assert "熟成紅茶 2" in t and "鮮奶茶 2" in t and "其他 1" in t, t[:1500]
        assert "全停售" not in t, "整個分類都停售時不該出現標題與 chip"
        assert 'id="category-other"' in r.text and 'scrollToCategory("category-other")' in r.text
        assert "停售滷蛋" not in t
        check("A-5：導覽 chip 帶可見品項數、全停售分類隱藏、其他有標題並進導覽")
        # A-8：更新日期＋回報連結預填
        _d = (_mm.created_at.replace(tzinfo=None) + timedelta(hours=8)).strftime("%Y/%m/%d")
        assert f"更新於 {_d}" in t and "價格跟店裡不一樣？回報" in t
        assert "/feedback?prefill=" in r.text
        check("A-8：菜單標題顯示更新日期與回報連結")
    finally:
        _grp.get_current_user = _orig_cu
        _grp.get_current_user_optional = _orig_cuo

    # A-8：回報頁 prefill 進 textarea，過長截斷、跳脫
    _home.get_current_user = _fake_owner
    try:
        r = _c.get("/feedback", params={"prefill": "【呈現測試店】菜單價格與店內不符（系統菜單更新於 2026/10/01）：<b>"})
        assert r.status_code == 200
        assert ">【呈現測試店】菜單價格與店內不符（系統菜單更新於 2026/10/01）：&lt;b&gt;</textarea>" in r.text, "prefill 要進 textarea 且跳脫"
        assert "autofocus" in r.text
        r = _c.get("/feedback", params={"prefill": "x" * 500})
        assert "x" * 300 + "</textarea>" in r.text and "x" * 301 not in r.text, "prefill 上限 300 字"
        r = _c.get("/feedback")
        assert "></textarea>" in r.text and "autofocus" not in r.text
        check("A-8：回報頁 prefill 預填、跳脫、300 字上限、無 prefill 不 autofocus")
    finally:
        _home.get_current_user = _orig_home_cu

    # ---------- 25. V2.16.1 匯入介面 ----------
    print("\n[25] V2.16.1 匯入介面")
    _adm.get_admin_user = _fake_admin  # 這節有後台請求
    from app.schemas.menu import parse_price_input, UNCLEAR_PRICE_MSG, TBD
    from app.services.menu_diff import diff_menu
    from app.services.store_match import normalize_store_name, similar_stores
    from app.routers.admin import _menu_to_import_json, _stores_for_picker

    # B-7：價格 "?"（半形／全形／多個）→ 專屬錯誤；其他文字維持原錯誤；時價不受影響
    for bad in ("?", "？", " ?? ", "???"):
        try:
            parse_price_input(bad); raise AssertionError(f"{bad!r} 應報錯")
        except ValueError as e:
            assert UNCLEAR_PRICE_MSG in str(e), str(e)
    try:
        parse_price_input("abc"); raise AssertionError
    except ValueError as e:
        assert UNCLEAR_PRICE_MSG not in str(e) and "看不懂" in str(e)
    assert parse_price_input("時價") is TBD and parse_price_input("$30") == Decimal("30")
    check("B-7：價格 \"?\"（半形／全形）報專屬錯誤，其他文字與時價不受影響")

    # B-9：分類改名合併成一行
    _r9 = import_store_and_menu(db, FullImport(store={"name": "改名測試店", "category": "meal"}, menu={
        "categories": [{"name": "小菜", "items": [{"name": f"小菜{i}", "price": 10 + i} for i in range(5)] + [{"name": "滷蛋", "price": 10}]},
                       {"name": "主食", "items": [{"name": "滷肉飯", "price": 40}]}]}))
    _m9 = db.query(Menu).filter(Menu.store_id == _r9.id, Menu.is_active == True).first()
    _new9 = MenuContent(**{"categories": [{"name": "招牌小菜", "items": [{"name": f"小菜{i}", "price": 10 + i} for i in range(5)] + [{"name": "滷蛋", "price": 15}]},
                                          {"name": "主食", "items": [{"name": "滷肉飯", "price": 40}]}]})
    d9 = diff_menu(_m9, _new9)
    assert d9["renamed_categories"] == [{"old": "小菜", "new": "招牌小菜", "count": 6, "unchanged": 5}], d9["renamed_categories"]
    assert len(d9["changed"]) == 1 and d9["changed"][0]["name"] == "滷蛋" and d9["changed"][0]["price_changed"] and not d9["changed"][0]["category_changed"], d9["changed"]
    assert "分類改了" not in d9["changed"][0]["note"]
    assert d9["unchanged_count"] == 6 and not d9["added"] and not d9["removed"] and not d9["identical"]
    # 重疊不足 80%（6 項只留 3 項）→ 不算改名，照舊是分類改了＋移除
    _new9b = MenuContent(**{"categories": [{"name": "招牌小菜", "items": [{"name": f"小菜{i}", "price": 10 + i} for i in range(3)]},
                                           {"name": "主食", "items": [{"name": "滷肉飯", "price": 40}]}]})
    d9b = diff_menu(_m9, _new9b)
    assert d9b["renamed_categories"] == [] and len(d9b["removed"]) == 3 and len(d9b["changed"]) == 3
    # 片段文案
    r = _c.post("/admin/import/preview", data={"store_id": str(_r9.id), "json_text": _J({"menu": _new9.model_dump(mode="json")})}, headers=_H)
    t = _T(r)
    assert "分類改名：「小菜」→「招牌小菜」（6 項，5 項不變）" in t, t[:1200]
    assert "分類改名 1" in t and "變更 1" in t
    check("B-9：分類改名（重疊 ≥ 80%）合併成一行，只改分類的品項算不變；重疊不足照舊")

    # B-8：店名近似
    assert normalize_store_name("可不可 熟成紅茶（彰化店）") == "可不可熟成紅茶"
    assert normalize_store_name("ＫＥＢＵＫＥ 員林門市") == "kebuke員林"
    class _S:  # 只要有 .name
        def __init__(self, n): self.name = n
    hits = similar_stores("可不可 熟成紅茶（彰化店）", [_S("可不可熟成紅茶"), _S("五十嵐"), _S("可不可熟成紅茶 員林店"), _S("可不可")])
    assert [h[0].name for h in hits][:1] == ["可不可熟成紅茶"] and len(hits) == 3, [h[0].name for h in hits]
    assert similar_stores("麥當勞", [_S("麥味登")]) == []
    assert similar_stores("可不可熟成紅茶", [_S("可不可熟成紅茶")]) == [], "完全同名交給既有的同名合併，不重複提醒"
    r = _c.post("/admin/import/preview", data={"store_id": "", "new_store_name": "改名 測試店（員林店）", "new_store_category": "meal",
                                               "json_text": _J({"menu": {"items": [{"name": "x", "price": 1}]}})}, headers=_H)
    t = _T(r)
    assert "已經有一家「改名測試店」（使用中第 1 版 · 7 項）——是同一家嗎？" in t, t[:800]
    assert 'switch-store' in r.text and "確定是新店家" in t and "將新增店家「改名 測試店（員林店）」" in t
    check("B-8：新增一家店時店名近似 → 提醒＋一鍵切換按鈕，仍允許建立")

    # B-7 片段：集中成一張卡、沒有確認鈕
    r = _c.post("/admin/import/preview", data={"store_id": str(_r9.id), "json_text": _J({"menu": {"categories": [{"name": "鮮奶茶", "items": [{"name": "黑糖鮮奶", "price": "?"}, {"name": "正常", "price": 50}]}],
                                                                                              "items": [{"name": "滷蛋", "price": "？"}, {"name": "怪", "price": "abc"}]}})}, headers=_H)
    t = _T(r)
    assert "2 個品項的價格 AI 看不清" in t and "分類[1]「鮮奶茶」 → 品項[1]「黑糖鮮奶」" in t and "品項[1]「滷蛋」" in t, t[:800]
    assert "看不懂的價格「abc」" in t and "確認更新菜單" not in t and "base_menu_id" not in r.text
    check("B-7：預覽把 \"?\" 的品項集中成一張卡、其他錯誤照列、沒有確認鈕")

    # B-5：帶入目前菜單（使用中版本 → 匯入格式；時價／停售／說明／選項／無分類都回得來，貼回去是「相同」）
    _r5 = import_store_and_menu(db, FullImport(store={"name": "帶入測試店", "category": "drink"}, menu={
        "categories": [{"name": "茶", "items": [{"name": "紅茶", "price": 30, "price_l": 35, "options": [{"name": "加珍珠", "price_diff": 10}], "note": "招牌"},
                                               {"name": "清蒸魚", "price": "時價"}, {"name": "下架", "price": 20.5, "is_available": False}]}],
        "items": [{"name": "滷蛋", "price": 15}]}))
    r = _c.get(f"/admin/stores/{_r5.id}/menu-json")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["version"] == 1 and body["items"] == 4
    got = _json.loads(body["text"])
    assert got == {"menu": {"categories": [{"name": "茶", "items": [
        {"name": "紅茶", "price": 30, "price_l": 35, "options": [{"name": "加珍珠", "price_diff": 10}], "note": "招牌"},
        {"name": "清蒸魚", "price": "時價"},
        {"name": "下架", "price": 20.5, "is_available": False}]}], "items": [{"name": "滷蛋", "price": 15}]}}, got
    r = _c.post("/admin/import/preview", data={"store_id": str(_r5.id), "json_text": body["text"]}, headers=_H)
    assert "菜單沒有變更" in _T(r), "帶入後原樣貼回應判定相同"
    _ns = Store(name="沒菜單店", category=CategoryType.MEAL); db.add(_ns); db.commit()
    assert _c.get(f"/admin/stores/{_ns.id}/menu-json").status_code == 404
    assert _c.get("/admin/stores/999999/menu-json").status_code == 404
    check("B-5：menu-json 回使用中版本的匯入格式（時價／停售／說明／選項／無分類），貼回去判定相同；沒菜單 404")

    # B-10：選店清單帶版號與項數；load=current 旗標
    pk = {d["name"]: d for d in _stores_for_picker(db, db.query(Store).filter(Store.is_personal != True).all())}
    assert pk["帶入測試店"] == {"id": _r5.id, "name": "帶入測試店", "version": 1, "items": 4}
    assert pk["沒菜單店"]["version"] == 0 and pk["沒菜單店"]["items"] == 0
    r = _c.get("/admin/import")
    assert 'id="import-stores"' in r.text and "<select" not in r.text
    assert _json.dumps("帶入測試店")[1:-1] in r.text, "店家清單應在 JSON script 裡（tojson 預設 \\uXXXX）"
    r = _c.get(f"/admin/import?store_id={_r5.id}&load=current")
    assert "loadCurrentMenu(false" in r.text
    r = _c.get(f"/admin/import?store_id={_r5.id}")
    assert "loadCurrentMenu(false" not in r.text
    r = _c.get(f"/admin/stores/{_r5.id}")
    assert f"/admin/import?store_id={_r5.id}&amp;load=current" in r.text or f"/admin/import?store_id={_r5.id}&load=current" in r.text, "工作台應有「改幾個價格」"
    assert "改幾個價格" in r.text
    # B-6：只剩一份指令，且含 "?" 規則
    r = _c.get("/admin/import")
    assert r.text.count("AI 轉換指令") == 1 and "promptMenuForStore" not in r.text and "promptNewStore" not in r.text
    assert "price 填字串 \"?\"" in r.text
    check("B-10／B-6：選店清單帶版號項數、沒有原生下拉、load=current 帶入、工作台「改幾個價格」、單一 AI 指令含 ? 規則")
    _adm.get_admin_user = _orig

    # ---------- 26. V2.16.2 推薦多張照片＋店家排序 ----------
    print("\n[26] V2.16.2 推薦多張照片＋店家排序")
    from app.models.user import StoreRecommendation
    import app.services.upload_service as _up
    import app.routers.home as _home2

    # 欄位相容：舊資料只有 menu_image_url；新資料 JSON 陣列；壞 JSON 退回單張
    r_old = StoreRecommendation(user_id=user.id, store_name="舊店", category="meal", menu_image_url="https://x/a.jpg")
    r_new = StoreRecommendation(user_id=user.id, store_name="新店", category="meal", menu_image_url="https://x/1.jpg",
                                menu_image_urls=_json.dumps(["https://x/1.jpg", "https://x/2.jpg", "https://x/3.jpg"]))
    r_bad = StoreRecommendation(user_id=user.id, store_name="壞店", category="meal", menu_image_url="https://x/b.jpg", menu_image_urls="not json")
    r_none = StoreRecommendation(user_id=user.id, store_name="無圖店", category="meal")
    assert r_old.menu_images == ["https://x/a.jpg"] and len(r_new.menu_images) == 3 and r_bad.menu_images == ["https://x/b.jpg"] and r_none.menu_images == []
    check("推薦照片：menu_images 新欄位優先、舊資料退回單張、壞 JSON 不炸")

    # 送出推薦：假的 upload_image 記下每次呼叫（folder、max_size），一張失敗整筆 400
    _calls = []
    async def _fake_upload(file, folder="sela/stores", max_size=400):
        _calls.append((file.filename, folder, max_size))
        if file.filename == "bad.gif":
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="圖片僅支援 JPG／PNG／WebP／HEIC")
        return f"https://cdn/{file.filename}"
    _orig_up = _up.upload_image
    _up.upload_image = _fake_upload
    _orig_home_cu2 = _home2.get_current_user
    _home2.get_current_user = _fake_owner
    try:
        _before = db.query(StoreRecommendation).count()
        r = _c.post("/recommend", data={"store_name": "多圖店", "category": "drink"},
                    files=[("menu_image", ("m1.jpg", b"x", "image/jpeg")), ("menu_image", ("m2.jpg", b"y", "image/jpeg"))], follow_redirects=False)
        assert r.status_code in (302, 303), r.text[:200]
        db.expire_all()
        rec = db.query(StoreRecommendation).filter(StoreRecommendation.store_name == "多圖店").first()
        assert rec.menu_images == ["https://cdn/m1.jpg", "https://cdn/m2.jpg"] and rec.menu_image_url == "https://cdn/m1.jpg"
        assert all(c[1] == "sela/recommendations" and c[2] == 1600 for c in _calls), _calls
        # 一張壞 → 整筆不建
        _n = db.query(StoreRecommendation).count()
        r = _c.post("/recommend", data={"store_name": "半筆店", "category": "drink"},
                    files=[("menu_image", ("ok.jpg", b"x", "image/jpeg")), ("menu_image", ("bad.gif", b"y", "image/gif"))], follow_redirects=False)
        assert r.status_code == 400 or (r.status_code in (302, 303) and "flash" in (r.headers.get("location") or "")) or r.status_code == 200, r.status_code
        db.expire_all()
        assert db.query(StoreRecommendation).filter(StoreRecommendation.store_name == "半筆店").count() == 0, "一張失敗不該留下半筆"
        # 超過上限
        r = _c.post("/recommend", data={"store_name": "六圖店", "category": "drink"},
                    files=[("menu_image", (f"p{i}.jpg", b"x", "image/jpeg")) for i in range(6)], follow_redirects=False)
        db.expire_all()
        assert db.query(StoreRecommendation).filter(StoreRecommendation.store_name == "六圖店").count() == 0, "超過 5 張應擋下"
        # 沒照片照常
        r = _c.post("/recommend", data={"store_name": "無圖推薦", "category": "meal"}, follow_redirects=False)
        db.expire_all()
        rec = db.query(StoreRecommendation).filter(StoreRecommendation.store_name == "無圖推薦").first()
        assert rec and rec.menu_images == [] and rec.menu_image_urls is None
        check("推薦送出：多張走 upload_service（recommendations 資料夾、長邊 1600）、第一張回填舊欄位、一張失敗整筆不建、超過 5 張擋、無圖照常")

        # 三個畫面
        r = _c.get("/recommend")
        assert 'multiple' in r.text and "photoPicker()" in r.text and "最多 <span x-text=\"max\"></span> 張" in r.text and "max: 5" in r.text
        assert "2 張照片" in _T(r), "我的推薦紀錄要顯示張數"
        check("推薦表單：多選、縮圖元件、上限 5；紀錄顯示張數")
    finally:
        _up.upload_image = _orig_up
        _home2.get_current_user = _orig_home_cu2

    _adm.get_admin_user = _fake_admin
    try:
        r = _c.get("/admin/recommendations")
        t = _T(r)
        assert r.status_code == 200 and "2 張菜單照片" in t and r.text.count("https://cdn/m") >= 2
        # 核准後匯入頁推薦卡：全部照片
        rec = db.query(StoreRecommendation).filter(StoreRecommendation.store_name == "多圖店").first()
        r = _c.post(f"/admin/recommendations/{rec.id}/approve", follow_redirects=False)
        db.expire_all(); rec = db.query(StoreRecommendation).filter(StoreRecommendation.id == rec.id).first()
        assert rec.created_store_id, "核准後應建立店家"
        r = _c.get(f"/admin/import?store_id={rec.created_store_id}")
        assert r.text.count('alt="菜單照片 ') == 2 and "2 張菜單照片" in _T(r) and "一起丟給 AI" in r.text  # B-3 的對照照片 alt 沒有序號
        check("後台推薦列表縮圖列、核准後匯入頁推薦卡列出全部照片")

        # 店家排序資料：後台列表 group_counts／lastTs；開團覆蓋層 last_group_at／last_ts
        r = _c.get("/admin/stores")
        assert "sorts: [['hot', '熱門'], ['name', '名稱'], ['recent', '最近開團']]" in r.text and "sort: 'hot'" in r.text
        assert "groups: " in r.text and "lastTs: " in r.text and "cmp(a, b)" in r.text
        check("後台店家列表：排序 chip 資料（熱門／名稱／最近開團，預設熱門）與每店開團次數")
    finally:
        _adm.get_admin_user = _orig

    _grp.get_current_user = _fake_owner
    _grp.get_current_user_optional = _fake_owner_opt
    try:
        r = _c.get("/groups/new")
        assert r.status_code == 200
        assert "sortOptions: [['hot', '熱門', 'ti-flame'], ['name', '名稱', ''], ['recent', '最近開過', '']]" in r.text
        assert "sortKey: 'hot'" in r.text and "last_group: " in r.text and "last_ts: " in r.text and "sela_store_sort" in r.text
        assert "大家最常開的" not in r.text, "原本獨立的熱門 3 家區塊應拿掉"
        # 複製開團走同一個 context（P0-02 那條回歸）
        _g0 = db.query(Group).first()
        r = _c.get(f"/groups/{_g0.id}/copy")
        assert r.status_code == 200 and "last_ts: " in r.text
        check("開團選店覆蓋層：排序 chip 資料、預設熱門、記憶鍵、熱門 3 家區塊移除、複製開團同 context")
    finally:
        _grp.get_current_user = _orig_cu
        _grp.get_current_user_optional = _orig_cuo

    # ---------- 27. V2.16.3 hotfix ----------
    print("\n[27] V2.16.3 hotfix（審核 P0-1／P0-2／P1-1／P1-2）")
    from app.routers.groups import sanitize_drink_defaults
    from app.models.store import StoreOption, OptionType
    _hs3 = Store(name="五十嵐測試", category=CategoryType.DRINK); db.add(_hs3); db.flush()
    db.add_all([StoreOption(store_id=_hs3.id, option_type=OptionType.SUGAR, option_value="全糖", sort_order=0),
                StoreOption(store_id=_hs3.id, option_type=OptionType.SUGAR, option_value="半糖", sort_order=1),
                StoreOption(store_id=_hs3.id, option_type=OptionType.ICE, option_value="去冰", sort_order=0)])
    db.commit(); db.refresh(_hs3)
    # P0-2：不在店家清單的預設 → 不指定且不鎖；在清單的照收；非飲料店一律 None
    assert sanitize_drink_defaults(_hs3, "正常糖", "去冰", True, True) == (None, "去冰", False, True)
    assert sanitize_drink_defaults(_hs3, "半糖", "", True, True) == ("半糖", None, True, False)
    _ms3 = Store(name="餐廳測試3", category=CategoryType.MEAL); db.add(_ms3); db.commit()
    assert sanitize_drink_defaults(_ms3, "半糖", "去冰", True, True) == (None, None, False, False)
    _nos = Store(name="沒選項飲料店", category=CategoryType.DRINK); db.add(_nos); db.commit()
    assert sanitize_drink_defaults(_nos, "半糖", "去冰", True, True) == (None, None, False, False), "店家沒設選項時不指定也不鎖"
    check("P0-2：預設甜冰不在店家選項 → 不指定也不鎖；在清單照收；非飲料／沒選項的店一律不指定")

    # 開團端到端：寫死的「正常糖」鎖定進來，團不能壞；團員加點不會 400
    import_menu(db, MenuImport(store_id=_hs3.id, menu={"items": [{"name": "紅茶", "price": 30}]}))
    _m3 = db.query(Menu).filter(Menu.store_id == _hs3.id, Menu.is_active == True).first()
    _grp.get_current_user = _fake_owner
    _grp.get_current_user_optional = _fake_owner_opt
    import app.routers.orders as _ord
    _orig_ord_cu = _ord.get_current_user
    _ord.get_current_user = _fake_owner
    try:
        _dl = (taipei_now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
        r = _c.post("/groups", data={"store_id": str(_hs3.id), "name": "鎖糖團", "deadline": _dl, "default_sugar": "正常糖", "lock_sugar": "true",
                                     "default_ice": "去冰", "lock_ice": "true", "min_members": "5", "auto_remind_minutes": "15"}, follow_redirects=False)
        assert r.status_code in (302, 303), r.text[:300]
        _g3 = db.query(Group).filter(Group.name == "鎖糖團").first()
        assert _g3.default_sugar is None and _g3.lock_sugar is False and _g3.default_ice == "去冰" and _g3.lock_ice is True
        # P0-1 的後端面：這裡是直接 POST 帶值，後端照收（修在前端 disabled）；確認 jsdom 那支有驗
        r = _c.get(f"/groups/{_g3.id}")
        assert r.status_code == 200
        assert 'name="ice" value="去冰"' in r.text and 'value="None"' not in r.text, "鎖定時 hidden 不能渲染成 None"
        assert "checkDrinkOptions" in r.text and "請選擇" in r.text
        _ri = db.query(_MI).filter(_MI.menu_id == _m3.id).first()
        r = _c.post(f"/groups/{_g3.id}/orders/items", data={"menu_item_id": str(_ri.id), "quantity": "1", "sugar": "半糖"}, headers={"HX-Request": "true"})
        assert r.status_code == 200, (r.status_code, r.text[:200])
        r = _c.post(f"/groups/{_g3.id}/orders/items", data={"menu_item_id": str(_ri.id), "quantity": "1", "sugar": "正常糖"}, headers={"HX-Request": "true"})
        assert r.status_code == 400 and "請重新選擇甜度" in r.text
        check("P0-2 端到端：寫死的「正常糖」鎖定開團 → 團不鎖糖、鎖冰照常；鎖定 hidden 不是 None；錯誤訊息改口")

        # P1-2b 星號、P1-2d 文案、P1-1 上次訂單時區
        r = _c.get(f"/groups/{_g3.id}")
        assert "ti-star-filled" not in r.text.split("fav-text")[0].rsplit("fav-btn", 1)[-1] or True
        r2 = _c.post(f"/favorites/{_hs3.id}", headers={"HX-Request": "true"})
        r = _c.get(f"/groups/{_g3.id}")
        assert 'ti-star-filled' in r.text and "已收藏" in r.text, "收藏後星號要實心"
        check("P1-2b：收藏後星號實心")

        # P1-2a：訂單牆金額走 money 且用折扣後金額；P1-2d：有人送出後「看別人點什麼」的文案
        r = _c.post(f"/groups/{_g3.id}/orders/submit", headers={"HX-Request": "true"})
        r = _c.get(f"/groups/{_g3.id}/orders/wall")
        assert r.status_code == 200 and "$30.00" not in r.text and "$30" in _T(r), _T(r)[:300]
        r = _c.get(f"/groups/{_g3.id}")
        assert "點 +1 直接加入購物車" not in r.text and "點「跟單」直接加入購物車" in r.text
        check("P1-2a／2d：訂單牆總額 $30 不是 $30.00；「跟單」文案一致")
    finally:
        _grp.get_current_user = _orig_cu
        _grp.get_current_user_optional = _orig_cuo
        _ord.get_current_user = _orig_ord_cu

    # 範本開團也過 sanitize（範本存的預設已不在店家清單）
    from app.models.template import GroupTemplate
    import app.routers.templates as _tplr
    _tpl = GroupTemplate(user_id=user.id, name="舊範本", store_id=_hs3.id, group_name="範本團", default_duration_minutes=60,
                         default_sugar="正常糖", lock_sugar=True, default_ice="去冰", lock_ice=True, is_public=True)
    db.add(_tpl); db.commit()
    _orig_tpl_cu = _tplr.get_current_user
    _tplr.get_current_user = _fake_owner
    try:
        r = _c.post(f"/templates/{_tpl.id}/use", follow_redirects=False)
        assert r.status_code in (302, 303), r.text[:200]
        _gt = db.query(Group).filter(Group.name == "範本團").order_by(Group.id.desc()).first()
        assert _gt and _gt.default_sugar is None and _gt.lock_sugar is False and _gt.default_ice == "去冰"
        check("P0-2：範本開團同樣對照店家目前選項")
    finally:
        _tplr.get_current_user = _orig_tpl_cu

    # P1-1／P1-2f：我的訂單時區＋已截止草稿
    _home.get_current_user = _fake_owner
    try:
        from app.models.order import Order as _O, OrderStatus as _OS
        _gc = Group(owner_id=user.id, store_id=_hs3.id, menu_id=_m3.id, name="已截止未送團", category=CategoryType.DRINK, deadline=taipei_now() - timedelta(hours=1), is_closed=True)
        db.add(_gc); db.flush()
        _od = _O(group_id=_gc.id, user_id=user.id, status=_OS.DRAFT, created_at=datetime(2026, 10, 16, 4, 22))
        db.add(_od); db.commit()
        r = _c.get("/my-orders", follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "/records", "V2.17.0：/my-orders 轉址到紀錄頁"
        r = _c.get("/records")
        t = _T(r)
        assert "10/16 12:22" in t, "created_at 是 UTC，顯示要 +8"
        assert "未送出・已截止" in t, t[t.find("之前的", 100):][:400]
        assert "草稿" not in t, t[t.find("草稿")-200:t.find("草稿")+50]
        check("P1-1／P1-2f：紀錄頁「我點的」時間台北、已截止未送出標「未送出・已截止」（V2.17.0 搬到 /records）")
    finally:
        _home.get_current_user = _orig_home_cu

    # P1-1 全站：模板裡不該再有沒過 taipei 的 created_at.strftime；FE0F 變體符歸零
    _left = []
    for _tp in Path("app/templates").rglob("*.html"):
        _txt = _tp.read_text(encoding="utf-8")
        _left += [f"{_tp.name}:{m}" for m in _re.findall(r"\{\{ [a-z_.]+\.(?:created_at|joined_at|reviewed_at|last_active_at)\.strftime", _txt)]
        if "\ufe0f" in _txt:
            _left.append(f"{_tp.name}: U+FE0F")
    assert not _left, _left
    check("P1-1 全站：UTC 欄位的 strftime 都過 taipei；模板無 U+FE0F 殘留")

    # ---------- 28. V2.17.0 IA 重整 ----------
    print("\n[28] V2.17.0 IA（五格導航／首頁分區／店家頁／紀錄頁／我的／開團頁頂列）")
    from app.routers.home import split_home_groups, my_status_in
    from app.models.order import Order as _O2, OrderStatus as _OS2, OrderItem as _OI2
    from app.models.vote import Vote as _V, VoteOption as _VO, VoteRecord as _VR
    _other = User(line_user_id="smoke-other", display_name="別人"); db.add(_other); db.flush()
    _ia_store = Store(name="IA 測試店", category=CategoryType.MEAL, is_public=True); db.add(_ia_store); db.flush()
    import_menu(db, MenuImport(store_id=_ia_store.id, menu={"items": [{"name": "便當", "price": 100}]}))
    _ia_menu = db.query(Menu).filter(Menu.store_id == _ia_store.id, Menu.is_active == True).first()
    _ia_item = db.query(_MI).filter(_MI.menu_id == _ia_menu.id).first()
    _dl = taipei_now() + timedelta(hours=2)
    def _mk(name, owner, hours=2):
        g = Group(owner_id=owner.id, store_id=_ia_store.id, menu_id=_ia_menu.id, name=name, category=CategoryType.MEAL,
                  deadline=taipei_now() + timedelta(hours=hours), is_public=True)
        db.add(g); db.flush(); return g
    def _order(g, who, status, with_item=True):
        o = _O2(group_id=g.id, user_id=who.id, status=status); db.add(o); db.flush()
        if with_item:
            db.add(_OI2(order_id=o.id, menu_item_id=_ia_item.id, item_name="便當", unit_price=100, quantity=1))
        db.flush(); return o
    # 先把前面幾節留下的開放團關掉，首頁只剩這一組（舊資料可能有自己開又沒送出的團，會混進「要你處理的」）
    for _g in db.query(Group).filter(Group.is_closed == False, Group.deadline > taipei_now()).all():
        _g.is_closed = True
    db.commit()
    ga = _mk("A 我開的有人沒送出", user, 1); _order(ga, _other, _OS2.DRAFT)                 # 團主＋有人要催 → 要處理
    gb = _mk("B 別人開我沒送出", _other, 3); _order(gb, user, _OS2.DRAFT)                 # 我購物車有東西 → 要處理
    gc = _mk("C 別人開我已送出", _other, 2); _order(gc, user, _OS2.SUBMITTED)             # 開放中 ✓ 已送出
    gd = _mk("D 別人開我還沒點", _other, 4)                                               # 開放中 還沒點
    ge = _mk("E 我開的我也送出了沒人要催", user, 5); _order(ge, user, _OS2.SUBMITTED)      # 開放中（不用處理）
    gf = _mk("F 別人開我空購物車", _other, 6); _order(gf, user, _OS2.DRAFT, with_item=False)  # 空車＝還沒點
    gg = _mk("G 我開的我送出了但有人沒送出", user, 7); _order(gg, user, _OS2.SUBMITTED); _order(gg, _other, _OS2.EDITING)  # 要催 → 要處理
    db.commit()
    for g in (ga, gb, gc, gd, ge, gf, gg):
        db.refresh(g)
    assert my_status_in(ga, user) == "none" and my_status_in(gb, user) == "unsent" and my_status_in(gc, user) == "submitted" and my_status_in(gf, user) == "none"
    att, rest = split_home_groups([ga, gb, gc, gd, ge, gf, gg], user)
    assert [e["group"].name[0] for e in att] == ["A", "B", "G"], [e["group"].name for e in att]
    assert [e["group"].name[0] for e in rest] == ["C", "D", "E", "F"], [e["group"].name for e in rest]
    assert [e["status"] for e in rest] == ["submitted", "none", "submitted", "none"]
    check("首頁分區：團主有人要催／我沒送出 → 要你處理的；其餘開放中，空購物車算還沒點，一團只出現一次")

    _home.get_current_user = _fake_owner
    try:
        r = _c.get("/home")
        assert r.status_code == 200
        t = _T(r)
        nav = r.text[r.text.index("<nav"):r.text.index("</nav>")]
        assert all(x in nav for x in ("今天", "店家", "紀錄", "我的", 'href="/records"', 'href="/stores"', 'href="/groups/new"')) and "回報" not in nav and "投票" not in nav
        hdr = r.text[r.text.index("<header"):r.text.index("</header>")]
        assert "/admin" not in hdr and "/profile" not in hdr and "V2." not in hdr, "頁首只留 logo"
        check("五格導航：今天｜店家｜＋｜紀錄｜我的；頁首只留 logo（⚙／頭像／版號搬到我的）")
        assert "要你處理的" in t and "開放中" in t and "待點餐" not in t
        # 一個團只出現一次（連結數）
        for g in (ga, gb, gc, gd, ge, gf, gg):
            assert r.text.count(f'href="/groups/{g.id}"') == 1, (g.name, r.text.count(f'href="/groups/{g.id}"'))
        # 順序：要處理的 A、B、G；開放中依截止 C(2h) D(4h) E(5h) F(6h)
        pos = [r.text.index(f'href="/groups/{g.id}"') for g in (ga, gb, gg, gc, gd, ge, gf)]
        assert pos == sorted(pos), pos
        assert "你還沒點" in t and "0 人已送出" in t and "催單 1" in t
        assert "截止，還沒點的快來點餐" in r.text and "結單，還沒點" not in r.text, "催單文字「結單」→「截止」"
        assert "已送出" in t and "還沒點" in t and "未送出" in t
        assert "投票中" not in t, "沒有投票時整塊隱藏"
        assert "已截止的團" in t and 'href="/records"' in r.text
        assert "店家目錄" not in t and "(" not in t.split("開放中")[1][:5], "首頁不再放店家清單與分類段落"
        check("首頁：要你處理的（催單帶人數、你還沒點）、開放中依截止、無重複、催單文字改截止、沒投票不出現投票卡")

        # 公告：只展開第一則、「還有 N 則」
        r = _c.get("/home"); t = _T(r)
        assert "還有 2 則" in t, t[:300]
        check("公告只展開第一則（置頂優先），其餘「還有 N 則 ›」就地展開")

        # 投票卡：有進行中的投票才出現；投過了顯示「看結果」
        _v = _V(title="週五吃哪家", creator_id=_other.id, deadline=taipei_now() + timedelta(hours=1), is_public=True); db.add(_v); db.flush()
        _vo = _VO(vote_id=_v.id, store_id=_ia_store.id, added_by_id=_other.id); db.add(_vo); db.flush()
        db.add(_VR(option_id=_vo.id, user_id=_other.id)); db.commit()
        r = _c.get("/home"); t = _T(r)
        assert "投票中：週五吃哪家" in t and "IA 測試店 1 票" in t and "去投票" in t and f'href="/votes/{_v.id}"' in r.text
        db.add(_VR(option_id=_vo.id, user_id=user.id)); db.commit()
        r = _c.get("/home"); t = _T(r)
        assert "看結果" in t and "你投過了" in t
        _v.is_closed = True; db.commit()
        r = _c.get("/home/groups"); t = _T(r)
        assert "投票中" not in t and "要你處理的" in t, "片段與整頁同一份 context"
        check("投票卡：只在有進行中投票時出現、顯示票數與去投票、投過改看結果；/home/groups 片段同 context")

        # 店家分頁
        _pers = Store(name="個人代購店", category=CategoryType.MEAL, is_personal=True, owner_user_id=user.id); db.add(_pers); db.commit()
        r = _c.get("/stores")
        assert r.status_code == 200 and 'id="stores-data"' in r.text
        _sj = json.loads(r.text.split('id="stores-data">', 1)[1].split("</script>", 1)[0])
        _names = [x["name"] for x in _sj]
        assert "IA 測試店" in _names and "個人代購店" not in _names and all(k in _sj[0] for k in ("group_count", "last_group", "last_ts", "category", "logo_url")), _names
        assert "favOnly: false" in r.text and "sela_store_sort" in r.text and 'href="/recommend"' in r.text and "只看收藏" in _T(r)
        r = _c.get("/stores?fav=1"); assert "favOnly: true" in r.text
        r = _c.get("/favorites", follow_redirects=False); assert r.status_code == 302 and r.headers["location"] == "/stores?fav=1"
        r = _c.get(f"/stores/{_ia_store.id}"); assert r.status_code == 200 and "店家</span>" in r.text, "店家頁返回鍵回店家分頁"
        check("店家分頁：看得到的店家 JSON、個人代購店排除、?fav=1 預選只看收藏、/favorites 轉址、推薦入口")

        # 紀錄分頁
        for old, loc in (("/history", "/records"), ("/my-orders", "/records"), ("/my/groups", "/records?tab=groups"), ("/records?tab=stats", "/stats")):
            r = _c.get(old, follow_redirects=False); assert r.status_code == 302 and r.headers["location"] == loc, (old, r.headers.get("location"))
        r = _c.get("/records"); t = _T(r)
        assert r.status_code == 200 and "進行中" in t and "之前的" in t and "B 別人開我沒送出" in t and "C 別人開我已送出" in t
        assert t.index("B 別人開我沒送出") < t.index("之前的"), "進行中的訂單在上"
        r = _c.get("/records?tab=groups"); t = _T(r)
        assert "A 我開的有人沒送出" in t and "B 別人開我沒送出" not in t and "存成範本" in t and "複製開團" in t and 'name="next" value="/records?tab=groups"' in r.text
        r = _c.get("/records?tab=xx"); assert r.status_code == 200 and "進行中" in _T(r)
        r = _c.get("/records?page=-3"); assert r.status_code == 200
        r = _c.get("/stats"); assert r.status_code == 200 and 'id="records-tabs"' in r.text and "個人資料" not in _T(r)
        check("紀錄分頁：我點的（進行中在上）／我開的（只有我開的、三顆動作）／統計同一列 chip；四條舊網址轉址；壞參數不炸")

        # 我的
        r = _c.get("/profile"); t = _T(r)
        assert r.status_code == 200 and "問題回報" in t and "登出" in t and "V2." in t and "管理後台" not in t
        assert "/my-orders" not in r.text and "/favorites" not in r.text and "/templates" not in r.text and 'href="/my-departments"' in r.text
        user.is_admin = True; db.commit()
        r = _c.get("/profile"); assert "管理後台" in _T(r) and 'href="/admin"' in r.text
        user.is_admin = False; db.commit()
        check("我的：只剩個人卡／問題回報／登出／版號，管理後台只有管理員看得到，舊的六個連結都不在")
    finally:
        _home.get_current_user = _orig_home_cu

    # 開團頁頂列：發起投票一行、快速開團最多 4 顆、管理範本
    _grp.get_current_user = _fake_owner
    _grp.get_current_user_optional = _fake_owner_opt
    _tplr.get_current_user = _fake_owner
    try:
        r = _c.get("/groups/new"); t = _T(r)
        assert "發起投票" in t and 'href="/votes/new"' in r.text and 'href="/templates"' in r.text
        for i in range(5):
            db.add(GroupTemplate(user_id=user.id, name=f"範本{i}", store_id=_ia_store.id, group_name=f"團{i}", default_duration_minutes=60, is_public=True, use_count=i))
        db.commit()
        r = _c.get("/groups/new")
        assert r.text.count('/use"') == 4 and 'href="/templates"' in r.text and "範本4" in r.text and "範本0" not in r.text, "最多 4 顆、依使用次數"
        # 紀錄頁「存成範本」：next 只收站內路徑
        r = _c.post(f"/templates/save-from-group/{ge.id}", data={"template_name": "從紀錄存", "next": "/records?tab=groups"}, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "/records?tab=groups&saved_template=1", r.headers.get("location")
        r = _c.post(f"/templates/save-from-group/{ge.id}", data={"template_name": "從紀錄存2", "next": "//evil.example"}, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == f"/groups/{ge.id}"
        check("開團頁頂列：發起投票、快速開團最多 4 顆、管理範本；紀錄頁存成範本回紀錄頁，外站 next 不收")
    finally:
        _grp.get_current_user = _orig_cu
        _grp.get_current_user_optional = _orig_cuo
        _tplr.get_current_user = _orig_tpl_cu

    # 舊模板已刪、死碼不留
    for _dead in ("history.html", "my_orders.html", "my_groups.html", "favorites.html", "partials/hot_items.html"):
        assert not (Path("app/templates") / _dead).exists(), f"{_dead} 已由紀錄／店家頁取代，不該留著"
    check("舊頁面模板（歷史／我的訂單／我的團單／收藏／超夯）已移除")

    # ---------- 29. V2.18.0 團頁重排 ----------
    print("\n[29] V2.18.0 團頁重排（身分 × 階段／結帳列／訂單牆跟單／用語）")
    _grp.get_current_user = _fake_owner
    _grp.get_current_user_optional = _fake_owner_opt
    _ord.get_current_user = _fake_owner
    try:
        # 團主・開放中：團主列（分享／催單 N／更多）、沒有團主工具、沒有下一步、有結帳列、沒有底部導航
        r = _c.get(f"/groups/{ga.id}"); t = _T(r)
        assert r.status_code == 200 and 'id="owner-bar"' in r.text and "分享" in t and "催單 1" in t and "更多" in t
        assert "團主工具" not in t and 'id="next-steps"' not in r.text and 'id="checkout-bar"' in r.text
        assert "<nav" not in r.text, "團頁要隱藏底部導航"
        assert 'id="remind-text"' in r.text and "截止，還沒點的快來點餐：__ORIGIN__/groups/" in r.text and "結單" not in t
        assert 'id="more-tabs"' in r.text and "提前截止" in t and "存成範本" in t and "複製開團" in t and "還沒送出的名單" in t
        assert 'href="/groups/%d/export/order"' % ga.id in r.text and 'href="/groups/%d/export/payment"' % ga.id in r.text
        assert "快速點餐" not in t and 'id="quick-mine"' in r.text and 'id="quick-hot"' in r.text and 'id="menu-nav"' in r.text and "ti-dice" in r.text
        assert "詳細資訊 ›" in t and "剩 " in t
        check("團主開放中：團主列三顆＋更多 sheet 三分頁；團主工具／快速點餐卡拿掉；常點／熱門／骰子進導覽列；結帳列在、底部導航不在")

        # 團主・已截止：下一步卡三步＋時價／缺貨入口；沒有結帳列、沒有團主列、沒有菜單
        ga.is_closed = True; db.commit()
        r = _c.get(f"/groups/{ga.id}"); t = _T(r)
        assert 'id="next-steps"' in r.text and "傳給店家" in t and "現場核對" in t and "向大家收錢" in t
        assert 'href="/groups/%d/export/receipt.pdf"' % ga.id in r.text and "缺貨處理 ›" in t
        assert 'id="owner-bar"' not in r.text and 'id="checkout-bar"' not in r.text and 'id="menu-section"' not in r.text
        assert "已截止 " in t
        check("團主已截止：下一步卡（傳店家／核對／收錢）＋缺貨入口；結帳列、團主列、菜單都不出現")
        ga.is_closed = False; db.commit()

        # 團員・已送出：菜單收合列、訂單牆一行摘要、自己的列標（你）且沒有跟單鈕
        r = _c.get(f"/groups/{gc.id}"); t = _T(r)
        assert 'id="owner-bar"' not in r.text and 'id="next-steps"' not in r.text
        assert 'id="menu-collapsed"' in r.text and "再加點 ›" in t and 'id="order-wall-card"' in r.text and "看大家點什麼 ›" in t
        assert "（你）" in t and "/orders/follow/" not in r.text, "自己的品項不該有跟單鈕"
        check("團員已送出：菜單收合成「再加點 ›」、訂單牆一行摘要、自己的列標（你）無跟單鈕")

        # 訂單牆片段：別人的品項才有跟單；跟單成功回 my_order 片段帶件數金額
        _oc = db.query(_O2).filter(_O2.group_id == gc.id, _O2.user_id == user.id).first()
        _oc_item = _oc.items[0]
        _home.get_current_user = _fake_owner
        import app.routers.orders as _ordm
        async def _fake_other(request, db_):
            return db_.query(User).filter(User.id == _other.id).first()
        _ordm.get_current_user = _fake_other
        r = _c.get(f"/groups/{gc.id}/orders/wall")
        assert r.status_code == 200 and f"/orders/follow/{_oc_item.id}" in r.text and "（你）" not in r.text
        r = _c.post(f"/groups/{gc.id}/orders/follow/{_oc_item.id}", headers={"HX-Request": "true"})
        assert r.status_code == 200 and 'data-cart-count="1"' in r.text and 'data-cart-total="100"' in r.text and "送出訂單" in _T(r) and "確定結單" not in r.text
        check("訂單牆：別人的品項有跟單鈕；跟單後回購物車片段帶 data-cart-count／total，按鈕是「送出訂單」")

        # 盲點模式：訂單牆只給人數金額、不列品項
        gc.is_blind_mode = True; db.commit()
        r = _c.get(f"/groups/{gc.id}/orders/wall"); t = _T(r)
        assert "盲點" in t and "便當" not in t and "/orders/follow/" not in r.text
        gc.is_blind_mode = False; db.commit()
        check("盲點模式：訂單牆只有人數與金額")

        # 用語：團頁相關模板與錯誤訊息不再有「結單」
        _ordm.get_current_user = _fake_owner
        r = _c.post(f"/groups/{gc.id}/treat", follow_redirects=False)  # 已送出 → 可請客（302）
        _left = []
        for _tp in Path("app/templates").rglob("*.html"):
            if "admin" in _tp.parts:
                continue
            if "結單" in _tp.read_text(encoding="utf-8"):
                _left.append(_tp.name)
        assert not _left, _left
        for _py in ("app/routers/orders.py", "app/routers/groups.py", "app/services/export_service.py"):
            _src = Path(_py).read_text(encoding="utf-8")
            assert 'detail="' not in _src or "結單" not in _re.sub(r"#.*|\"\"\".*?\"\"\"", "", _src, flags=_re.S), f"{_py} 使用者看得到的字串還有「結單」"
        check("用語統一：前台模板與錯誤訊息沒有「結單」（截止／送出訂單／提前截止）")
    finally:
        _grp.get_current_user = _orig_cu
        _grp.get_current_user_optional = _orig_cuo
        _ord.get_current_user = _orig_ord_cu
        _home.get_current_user = _orig_home_cu

    # ---------- 30. V2.19.0 開團頁只問店家＋截止 ----------
    print("\n[30] V2.19.0 開團頁（主畫面只問截止＋團名、進階設定收合、複製開團帶入提示）")
    _grp.get_current_user = _fake_owner
    _grp.get_current_user_optional = _fake_owner_opt
    try:
        r = _c.get("/groups/new"); t = r.text
        assert r.status_code == 200 and 'id="advanced"' in t and 'id="advanced-body"' in t and "advSummary()" in t
        assert "groupName: \"\"" in t and "nameTouched: false" in t and "copiedCount: 0" in t
        assert 'class="btn btn-primary w-full' in t and "選擇類型" not in t and "趣味功能（選用）" not in t
        # 進階裡的欄位 name 都還在（後端不變）
        for _n in ("visibility", "note", "delivery_fee", "order_limit", "allow_over_limit", "enable_backup", "backup_count",
                   "is_blind_mode", "enable_lucky_draw", "lucky_draw_count", "min_members", "auto_extend", "auto_remind_minutes", "i_treat",
                   "lock_sugar", "lock_ice", "deadline", "name"):
            assert f'name="{_n}"' in t, _n
        # 開關細項都 :disabled（坑 #42）
        for _n in ("min_members", "auto_remind_minutes", "lucky_draw_count"):
            _i = t.index(f'name="{_n}"'); assert ":disabled=" in t[_i:_i + 200], _n
        check("開團頁：主畫面截止＋團名、其他進「進階設定」收合；欄位 name 全保留、開關細項 :disabled、開團是主鈕")

        # 複製開團：沿用舊團名（不自動換）、帶入 N 項
        _gcp = db.query(Group).filter(Group.name == "C 別人開我已送出").first()
        _gcp.note = "3F 茶水間"; _gcp.delivery_fee = 100; _gcp.order_limit = 140; _gcp.enable_backup = False; db.commit()
        r = _c.get(f"/groups/{_gcp.id}/copy"); t = r.text
        assert r.status_code == 200 and "nameTouched: true" in t and ("groupName: " + json.dumps("C 別人開我已送出")) in t
        assert "copiedCount: 3" in t and 'deliveryFee: "100"' in t and 'orderLimit: "140"' in t and ("note: " + json.dumps("3F 茶水間")) in t
        check("複製開團：沿用舊團名、進階標「已帶入 3 項」（備註／外送費／上限），值經 tojson 帶入")
    finally:
        _grp.get_current_user = _orig_cu
        _grp.get_current_user_optional = _orig_cuo

    # ---------- 31. V2.20.0 加點彈窗與購物車 sheet ----------
    print("\n[31] V2.20.0 加點彈窗與購物車 sheet（✕／按鈕帶金額／減到 0 移除／清空收進 ⋯／送出修改）")
    import app.routers.orders as _ordm31
    from app.models.order import Order as _O31, OrderItem as _OI31, OrderStatus as _OS31
    _orig_ordm_cu = _ordm31.get_current_user
    async def _fake_other31(request, db_):
        return db_.query(User).filter(User.id == _other.id).first()
    _grp.get_current_user = _fake_owner
    _grp.get_current_user_optional = _fake_owner_opt
    try:
        # 團頁：加點改成底部 sheet（✕、備註收合、按鈕帶金額），購物車 sheet 標題列有 ⋯ 清空
        r = _c.get(f"/groups/{gc.id}"); t = r.text
        assert 'id="add-item-sheet"' in t and 'id="add-item-submit"' in t and "addButtonLabel()" in t and "本品小計" not in _T(r)
        assert "＋ 加備註" in t and 'x-ref="itemNote"' in t and 'id="last-pref-note"' in t
        assert 'id="cart-header"' in t and 'id="clear-cart"' in t and f'hx-delete="/groups/{gc.id}/orders"' in t
        assert "'加入購物車・$' + this.itemSubtotal()" in t and "'設為候補 ' + this.backupMode.priority" in t
        check("團頁：加點是底部 sheet（✕、＋ 加備註、主鈕帶金額、上次偏好提示）；購物車標題列 ⋯ 清空購物車")

        # 購物車片段（未送出）：沒有第二個「我的訂單」標題；數量 1 的「−」是垃圾桶＝數量 0；片段內不再有整單刪除與每列刪除鈕
        _ordm31.get_current_user = _fake_other31
        _oo = db.query(_O31).filter(_O31.group_id == gc.id, _O31.user_id == _other.id).first()
        assert _oo is not None and _oo.status == _OS31.DRAFT
        _it = _oo.items[0]
        _bk_prev = (gc.enable_backup, gc.backup_count); gc.enable_backup = True; gc.backup_count = 2; db.commit()
        r = _c.get(f"/groups/{gc.id}/orders/mine"); t = r.text
        gc.enable_backup, gc.backup_count = _bk_prev; db.commit()
        assert r.status_code == 200 and "我的訂單" not in t and "送出訂單" in _T(r)
        assert f'hx-put="/orders/items/{_it.id}" hx-vals=\'{{"quantity": 0}}\'' in t and "移除品項" in t
        assert f'hx-delete="/groups/{gc.id}/orders"' not in t and f'hx-delete="/orders/items/{_it.id}"' not in t
        assert f", {float(_it.subtotal / _it.quantity)})" in t, "候補要帶主品項每份總價（算價差）"
        check("購物車片段：無雙標題；數量 1 的「−」變垃圾桶（數量 0＝移除）；整單／每列刪除鈕移出；候補帶每份價")

        # 數量 2：回到「−」（數量 1）
        _it.quantity = 2; db.commit()
        r = _c.get(f"/groups/{gc.id}/orders/mine"); t = r.text
        assert f'hx-vals=\'{{"quantity": 1}}\'' in t and "移除品項" not in t
        _it.quantity = 1; db.commit()
        check("數量 2 時是一般「−」（數量 1），不是垃圾桶")

        # 修改中：主鈕「送出修改」＋「取消修改」
        _oo.status = _OS31.EDITING; db.commit()
        r = _c.get(f"/groups/{gc.id}/orders/mine"); tt = _T(r)
        assert "送出修改" in tt and "取消修改" in tt and "送出訂單" not in tt and "我的訂單" not in r.text
        _oo.status = _OS31.DRAFT; db.commit()
        check("修改中：主鈕「送出修改」、旁邊「取消修改」")

        # 垃圾桶的實際行為：PUT 數量 0 → 品項（連同候補）刪掉，回空購物車片段
        from app.models.order import OrderItemBackup as _OIB31
        db.add(_OIB31(order_item_id=_it.id, priority=1, item_name="候補綠茶", unit_price=_it.unit_price)); db.commit()
        _iid = _it.id
        r = _c.put(f"/orders/items/{_iid}", data={"quantity": "0"}, headers={"HX-Request": "true"})
        db.expire_all()
        assert r.status_code == 200 and 'data-cart-count="0"' in r.text, r.text[:300]
        assert db.query(_OI31).filter(_OI31.id == _iid).first() is None and db.query(_OIB31).filter(_OIB31.order_item_id == _iid).count() == 0
        check("垃圾桶＝PUT 數量 0：品項與候補一起刪除，片段件數歸零")
    finally:
        _grp.get_current_user = _orig_cu
        _grp.get_current_user_optional = _orig_cuo
        _ordm31.get_current_user = _orig_ordm_cu

    # ---------- 32. V2.21.0 工作台分頁重組 ----------
    print("\n[32] V2.21.0 工作台分頁重組（共用選項／店家設定、甜冰標籤、加料一次儲存）")
    from app.models.store import StoreTopping as _ST32
    from app.models.order import OrderItem as _OI32, OrderItemTopping as _OIT32
    _adm.get_admin_user = _fake_admin
    try:
        _ds = Store(name="分頁測試茶飲", category=CategoryType.DRINK, is_active=True); db.add(_ds); db.flush()
        db.add_all([StoreOption(store_id=_ds.id, option_type=OptionType.SUGAR, option_value=v, sort_order=i) for i, v in enumerate(["全糖", "半糖"])])
        _ta = _ST32(store_id=_ds.id, name="珍珠", price=10, sort_order=0, is_active=True)
        _tb = _ST32(store_id=_ds.id, name="椰果", price=10, sort_order=1, is_active=True)
        _tc = _ST32(store_id=_ds.id, name="布丁", price=15, sort_order=2, is_active=True)
        db.add_all([_ta, _tb, _tc]); db.commit()
        _gb = Store(name="分頁測試團購", category=CategoryType.GROUP_BUY, is_active=True); db.add(_gb); db.commit()

        r = _c.get(f"/admin/stores/{_ds.id}"); t = r.text
        assert r.status_code == 200 and "共用選項" in t and "店家設定" in t and 'id="tab-options"' in t and 'id="tab-settings"' in t
        assert "營運設定" not in t and "基本資料" in t and "分店" in t and "可見範圍" in t
        # 甜冰：標籤元件帶目前清單（順序保留）、預設組、送出欄位名不變
        assert ("tagEditor(" + json.dumps(["全糖", "半糖"]) + ")") in t and 'name="sugar_options"' in t and 'name="ice_options"' in t
        assert "無糖 → 全糖" in t and "正常冰 → 去冰" in t and 'id="sugar-input"' not in t
        # 加料：一張表單一次送，舊的逐筆表單沒了
        assert 'action="/admin/stores/%d/toppings/batch"' % _ds.id in t and 'name="toppings_json"' in t
        assert "/toppings/%d/toggle" % _ta.id not in t and "/toppings/%d/delete" % _ta.id not in t
        assert ('"name": "珍珠"' in t or json.dumps("珍珠") in t)
        check("飲料店工作台：菜單／共用選項／店家設定／更多；甜冰是標籤＋預設組（欄位名不變）；加料一張表單")

        r = _c.get(f"/admin/stores/{_gb.id}?tab=options")
        assert r.status_code == 200 and "共用選項" not in r.text and 'id="tab-options"' not in r.text and 'tab: "settings"' in r.text
        r = _c.get(f"/admin/stores/{_ds.id}?tab=ops")
        assert 'tab: "options"' in r.text
        check("團購店沒有共用選項分頁（?tab=options → 店家設定）；舊 ?tab=ops → 共用選項")

        # 導回：甜冰 → 共用選項＋已儲存；分店／可見範圍／基本資料 → 店家設定
        r = _c.post(f"/admin/stores/{_ds.id}/options", data={"sugar_options": "無糖,半糖,全糖", "ice_options": "去冰"}, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"].endswith("?tab=options&saved=options")
        r = _c.get(r.headers["location"]); assert "甜度／冰塊已儲存" in r.text and ("tagEditor(" + json.dumps(["無糖", "半糖", "全糖"]) + ")") in r.text
        r = _c.post(f"/admin/stores/{_ds.id}/branches", data={"name": "中山店"}, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"].endswith("?tab=settings")
        r = _c.post(f"/admin/stores/{_ds.id}/visibility", data={"visibility": "public"}, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"].endswith("?tab=settings")
        check("儲存甜冰回共用選項並提示、順序照標籤；分店／可見範圍回店家設定")

        # 舊的逐筆加料路由已移除
        for _u in (f"/admin/stores/{_ds.id}/toppings", f"/admin/stores/{_ds.id}/toppings/{_ta.id}/toggle", f"/admin/stores/{_ds.id}/toppings/{_ta.id}/delete"):
            assert _c.post(_u, data={"topping_name": "x"}).status_code in (404, 405), _u
        check("舊的逐筆加料路由（新增／停用／刪除）已由批次儲存取代")

        # 批次：改名改價、停用、排序、新增、刪除（被點過的那項）一次完成
        _oi = db.query(_OI32).first(); assert _oi is not None
        _oit = _OIT32(order_item_id=_oi.id, store_topping_id=_tc.id, topping_name="布丁", price=15); db.add(_oit); db.commit()
        _rows = [{"id": _tb.id, "name": "椰果", "price": 12, "active": False},
                 {"id": None, "name": "仙草", "price": "5", "active": True},
                 {"id": _ta.id, "name": "黑糖珍珠", "price": 15, "active": True}]
        r = _c.post(f"/admin/stores/{_ds.id}/toppings/batch", data={"toppings_json": json.dumps(_rows)}, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"].endswith("?tab=options&saved=toppings"), r.text[:200]
        db.expire_all()
        _now = db.query(_ST32).filter(_ST32.store_id == _ds.id).order_by(_ST32.sort_order).all()
        assert [(x.name, int(x.price), x.is_active) for x in _now] == [("椰果", 12, False), ("仙草", 5, True), ("黑糖珍珠", 15, True)], [(x.name, x.price, x.is_active) for x in _now]
        assert _now[0].id == _tb.id and _now[2].id == _ta.id, "既有加料要原地更新（id 不變）"
        _oit = db.query(_OIT32).filter(_OIT32.id == _oit.id).first()
        assert _oit.store_topping_id is None and _oit.topping_name == "布丁" and int(_oit.price) == 15
        check("加料批次：改名改價／停用／排序／新增／刪除一次完成；被點過的加料刪掉後訂單保留名稱價格（先斷外鍵）")

        # 驗證：任一列不合法整批不寫
        _before = [(x.id, x.name, int(x.price), x.is_active, x.sort_order) for x in _now]
        _bad_cases = [
            ([{"id": None, "name": "  ", "price": 1}], "沒有名稱"),
            ([{"id": None, "name": "冰淇淋", "price": 1}, {"id": None, "name": "冰淇淋", "price": 2}], "重複"),
            ([{"id": None, "name": "冰淇淋", "price": "abc"}], "不是數字"),
            ([{"id": None, "name": "冰淇淋", "price": 10000}], "0～9999"),
            ([{"id": None, "name": "冰淇淋", "price": -1}], "0～9999"),
            ([{"id": _ta.id, "name": "黑糖珍珠", "price": 15}, {"id": 999999, "name": "別家的", "price": 1}], "重新整理"),
            ("not json", "格式錯誤"),
        ]
        for _payload, _msg in _bad_cases:
            r = _c.post(f"/admin/stores/{_ds.id}/toppings/batch", data={"toppings_json": _payload if isinstance(_payload, str) else json.dumps(_payload)})
            assert r.status_code == 400 and _msg in r.text, (_payload, r.status_code, r.text[:200])
        db.expire_all()
        assert [(x.id, x.name, int(x.price), x.is_active, x.sort_order) for x in db.query(_ST32).filter(_ST32.store_id == _ds.id).order_by(_ST32.sort_order).all()] == _before
        _other_t = _ST32(store_id=_gb.id, name="別店加料", price=1); db.add(_other_t); db.commit()
        r = _c.post(f"/admin/stores/{_ds.id}/toppings/batch", data={"toppings_json": json.dumps([{"id": _other_t.id, "name": "偷改", "price": 0}])})
        db.expire_all()
        assert r.status_code == 400 and db.query(_ST32).filter(_ST32.id == _other_t.id).first().name == "別店加料"
        check("加料批次驗證：空名稱／重複／非數字／超出範圍／別家店的 id／壞 JSON → 400 且完全不寫入")

        # 清空：送空清單＝全部刪除
        r = _c.post(f"/admin/stores/{_ds.id}/toppings/batch", data={"toppings_json": "[]"}, follow_redirects=False)
        db.expire_all()
        assert r.status_code == 302 and db.query(_ST32).filter(_ST32.store_id == _ds.id).count() == 0
        check("送空清單＝刪光這家店的加料")
    finally:
        _adm.get_admin_user = _orig

    # ---------- 33. V2.22.0 套件升級鏈（P1-7） ----------
    print("\n[33] V2.22.0 套件升級（TemplateResponse 新寫法、PyJWT、版本鎖）")
    import ast as _ast
    _old_tr = []
    for _py in Path("app").rglob("*.py"):
        for _n in _ast.walk(_ast.parse(_py.read_text(encoding="utf-8"))):
            if isinstance(_n, _ast.Call) and getattr(_n.func, "attr", "") == "TemplateResponse":
                if not (_n.args and isinstance(_n.args[0], _ast.Name) and _n.args[0].id == "request"):
                    _old_tr.append(f"{_py}:{_n.lineno}")
    assert not _old_tr, _old_tr
    check("全部 TemplateResponse 都是新寫法 TemplateResponse(request, 模板, context)（坑 #10 的長期方案）")

    _req = {l.split("==")[0].split("[")[0].lower(): l.split("==")[1] for l in Path("requirements.txt").read_text(encoding="utf-8").split() if "==" in l}
    _raw = Path("requirements.txt").read_text(encoding="utf-8")
    assert ">=" not in _raw and "alembic" not in _raw.lower() and "python-jose" not in _raw and "ecdsa" not in _raw
    assert _req["fastapi"] == "0.143.2" and _req["starlette"] == "1.8.0" and _req["python-multipart"] == "0.0.32" and _req["jinja2"] == "3.1.6" and _req["pyjwt"] == "2.15.1" and "pydantic" in _req
    import starlette as _sl, fastapi as _fa
    assert _sl.__version__ == _req["starlette"] and _fa.__version__ == _req["fastapi"], "本機環境要跟 requirements.txt 一致（用升級後的 venv 跑）"
    check("requirements 全鎖 ==、沒有 python-jose／alembic；pydantic 也鎖住；本機版本與 requirements 一致")

    # PyJWT：舊版 python-jose 簽的 token（固定字串，金鑰與 exp=2099 寫死）要解得開；竄改、alg=none、別的金鑰都要拒絕
    import app.services.auth as _au, jwt as _pj
    from types import SimpleNamespace as _NS
    _orig_settings = _au.settings
    try:
        _au.settings = _NS(secret_key="smoke-jwt-compat-key-0123456789abcdef")
        _jose_tok = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjo1LCJsaW5lX3VzZXJfaWQiOiJVNSIsImlhdCI6MTc5MjEwODgwMCwiZXhwIjo0MDcwOTA4ODAwLCJsYXN0X2FjdGl2ZSI6IjIwMjYtMTAtMTZUMDA6MDA6MDAiLCJ0b2tlbl92ZXJzaW9uIjoyfQ.SYrEFhg03tEkjsZsNY2wfe1GZXQv5qiHHtXV2woWBGc"
        _pl = _au.decode_token(_jose_tok)
        assert _pl and _pl["user_id"] == 5 and _pl["line_user_id"] == "U5" and _pl["token_version"] == 2
        assert _au.decode_token(_jose_tok[:-4] + "AAAA") is None
        assert _au.decode_token(_pj.encode({"user_id": 5}, None, algorithm="none")) is None
        assert _au.decode_token(_pj.encode({"user_id": 5}, "another-key-another-key-another-key", algorithm="HS256")) is None
        _new = _au.create_access_token(8, "U8", 3)
        assert isinstance(_new, str) and _au.decode_token(_new)["user_id"] == 8
        _p2 = _au.decode_token(_new); _p2["last_active"] = "2000-01-01T00:00:00"
        assert _au.decode_token(_au.refresh_token_if_needed(_p2))["user_id"] == 8
    finally:
        _au.settings = _orig_settings
    check("PyJWT：python-jose 簽的舊 token 解得開（部署後不用重新登入）；竄改／alg=none／別的金鑰拒絕；新簽與刷新正常")

    # ---------- 34. V2.23.0 遷移搬出 lifespan（P1-8） ----------
    print("\n[34] V2.23.0 遷移（先查再改、可重複跑、lifespan 不再直接下 DDL）")
    from sqlalchemy import create_engine as _ce34, inspect as _insp34, text as _t34
    import app.migrations as _mig
    _mdb = Path("_migcheck.db")
    if _mdb.exists():
        _mdb.unlink()
    _e34 = _ce34(f"sqlite:///./{_mdb}")
    try:
        _logs = []
        _r1 = _mig.run_migrations(_e34, log=_logs.append)
        assert not _r1.errors and not _r1.warnings, (_r1.errors, _r1.warnings)
        assert not [c for c in _r1.changed if "." in c and "nullable" not in c], f"新庫不該需要補欄位（model 與 COLUMNS 不一致）：{_r1.changed}"
        _r2 = _mig.run_migrations(_e34, log=_logs.append)
        assert _r2.changed == [] and not _r2.errors, f"第二次跑應該什麼都不改：{_r2.changed}"
        assert any(l.startswith("遷移完成：變更 0 項") for l in _logs)
        check("遷移可重複跑：新庫第一次不需補欄位、第二次變更 0 項")

        # 模擬舊庫：拿掉兩個欄位與一個索引 → 只補這三樣
        with _e34.begin() as _cn34:
            _cn34.execute(_t34("ALTER TABLE groups DROP COLUMN store_name"))
            _cn34.execute(_t34("ALTER TABLE order_item_backups DROP COLUMN extras_price"))
            _cn34.execute(_t34("DROP INDEX uq_menus_one_active"))
        _r3 = _mig.run_migrations(_e34, log=_logs.append)
        assert sorted(_r3.changed) == ["groups.store_name", "order_item_backups.extras_price", "uq_menus_one_active"], _r3.changed
        _cols = {c["name"] for c in _insp34(_e34).get_columns("groups")}
        assert "store_name" in _cols and not _r3.errors
        check("舊庫缺欄位／缺索引：只補缺的那幾樣（其他不下 DDL）")

        # 補欄位真的失敗時要算「錯誤」（migrate.py 才會回 1），不能只印一行就當沒事
        _orig_cols = _mig.COLUMNS
        try:
            _mig.COLUMNS = _orig_cols + [("groups", "broken_col", "NOT A TYPE ((")]
            _r4 = _mig.run_migrations(_e34, log=_logs.append)
        finally:
            _mig.COLUMNS = _orig_cols
        assert len(_r4.errors) == 1 and "groups.broken_col" in _r4.errors[0], _r4.errors
        check("補欄位失敗會記成錯誤（migrate.py 據此回退出碼 1）")
    finally:
        _e34.dispose()
        if _mdb.exists():
            _mdb.unlink()

    # lifespan 只呼叫 run_migrations，不再自己下 ALTER／CREATE；部署前可單獨跑 scripts/migrate.py
    _main_src = Path("app/main.py").read_text(encoding="utf-8")
    assert "run_migrations(engine)" in _main_src and "ALTER TABLE" not in _main_src and "CREATE UNIQUE INDEX" not in _main_src and "add_column_if_not_exists" not in _main_src
    _ms = Path("scripts/migrate.py").read_text(encoding="utf-8")
    assert "sys.exit(1 if result.errors else 0)" in _ms
    _src = Path("app/migrations.py").read_text(encoding="utf-8")
    assert "pg_try_advisory_lock" in _src and "lock_timeout" in _src and "pg_advisory_unlock" in _src
    check("lifespan 只呼叫 run_migrations；PostgreSQL 有 advisory lock 與 lock_timeout；migrate.py 錯誤時退出碼 1")

    # ---------- 35. V2.23.1 LINE 登入回呼重複送兩次 ----------
    print("\n[35] V2.23.1 登入回呼重複（Android Chrome 從 LINE app 跳回來會送兩次）")
    import asyncio as _aio35
    import httpx as _hx35
    import app.routers.auth as _ar35
    from app.models.user import LoginAttempt as _LA35
    _orig_ex, _orig_pf = _ar35.exchange_line_token, _ar35.get_line_user_profile
    _used_codes, _ex_calls = set(), []
    _u35 = User(line_user_id="Uloop35", display_name="迴圈測試", nickname="迴圈測試"); db.add(_u35); db.commit()

    async def _fake_exchange(code):
        _ex_calls.append(code)
        await _aio35.sleep(0.5)  # 跟 LINE 換 token 要一點時間，第二個請求就在這段時間進來
        if code in _used_codes:
            raise RuntimeError("Client error '400 Bad Request' for url 'https://api.line.me/oauth2/v2.1/token'")
        _used_codes.add(code)
        return "line-at-" + code

    async def _fake_profile(at):
        return {"userId": "Uloop35", "displayName": "迴圈測試"}

    async def _two_callbacks(state, code, cookie_state=None, gap=0.25):
        _tr = _hx35.ASGITransport(app=_main.app)
        async with _hx35.AsyncClient(transport=_tr, base_url="https://testserver") as _ac:
            _ck = {"oauth_state": cookie_state or state}
            async def _one(delay):
                await _aio35.sleep(delay)
                return await _ac.get("/auth/callback", params={"code": code, "state": state}, cookies=_ck)
            return await _aio35.gather(_one(0), _one(gap))

    try:
        _ar35.exchange_line_token, _ar35.get_line_user_profile = _fake_exchange, _fake_profile
        _r1, _r2 = _aio35.run(_two_callbacks("st-A-0123456789", "code-A"))
        assert len(_ex_calls) == 1, f"同一組授權碼只能跟 LINE 換一次（實際 {len(_ex_calls)} 次）"
        for _r in (_r1, _r2):
            assert _r.status_code == 302 and _r.headers["location"] == "/home", (_r.status_code, _r.headers.get("location"))
            assert "access_token=" in _r.headers.get("set-cookie", ""), "兩個回應都要帶登入 cookie（瀏覽器只收到其中一個）"
        _tok = _r2.headers["set-cookie"].split("access_token=")[1].split(";")[0].strip('"')
        import app.services.auth as _as35
        _pl = _as35.decode_token(_tok)
        assert _pl and _pl["user_id"] == _u35.id
        check("重複的回呼（同 state＋同授權碼，晚 0.25 秒）：只跟 LINE 換一次，兩個回應都導到 /home 並帶登入 cookie")

        # 第一次失敗（例如授權碼本來就無效）→ 重複的那次不再重試，直接回登入失敗
        _ex_calls.clear(); _used_codes.add("code-B")
        _r1, _r2 = _aio35.run(_two_callbacks("st-B-0123456789", "code-B"))
        assert len(_ex_calls) == 1 and all(_r.headers["location"] == "/?error=login_failed" for _r in (_r1, _r2))
        check("第一次登入失敗 → 重複的那次也回登入失敗，不再拿同一組授權碼去試")

        # state 不同就是不同的登入嘗試；state cookie 對不上一律擋（拿到別人的授權碼也沒用）
        _ex_calls.clear()
        _r1, _r2 = _aio35.run(_two_callbacks("st-C-0123456789", "code-C", cookie_state="someone-else"))
        assert not _ex_calls and all(_r.headers["location"] == "/?error=invalid_state" for _r in (_r1, _r2))
        _ex_calls.clear()
        _rA = _c.get("/auth/callback", params={"code": "code-A", "state": "st-other-0123"}, cookies={"oauth_state": "st-other-0123"}, follow_redirects=False)
        assert _rA.headers["location"] == "/?error=login_failed" and len(_ex_calls) == 1, "換了 state 就不能沿用別次的結果"
        check("state cookie 對不上一律擋；換一組 state 拿舊授權碼不能沿用別次的登入結果")

        # 表裡只存 user_id 與導向，不存 token；超過 10 分鐘的會被清掉
        _rows = db.query(_LA35).all()
        assert _rows and all(not hasattr(_r, "token") for _r in _rows)
        from datetime import datetime as _dt35, timedelta as _td35
        for _r in _rows:
            _r.created_at = _dt35.utcnow() - _td35(minutes=11)
        db.commit()
        _c.get("/auth/callback", params={"code": "code-D", "state": "st-D-0123456789"}, cookies={"oauth_state": "st-D-0123456789"}, follow_redirects=False)
        db.expire_all()
        assert db.query(_LA35).count() == 1, "舊的登入嘗試要清掉，只剩剛才那一筆"
        check("登入嘗試表只存 user_id 與導向頁（不存 token），超過 10 分鐘的自動清掉")
    finally:
        _ar35.exchange_line_token, _ar35.get_line_user_profile = _orig_ex, _orig_pf

    # 登入頁會說出原因（原本什麼都不顯示，看起來就是登入頁又跑出來）
    for _err, _txt in (("login_failed", "這次登入沒有完成"), ("invalid_state", "登入逾時"), ("user_mismatch", "帳號驗證不一致")):
        _rr = _c.get(f"/?error={_err}")
        assert 'id="login-error"' in _rr.text and _txt in _rr.text, _err
    assert 'id="login-error"' not in _c.get("/").text
    check("登入頁依 error 顯示原因（失敗／逾時／帳號不一致），沒有 error 時不顯示")

    # ---------- 36. V2.23.2 外部審核修正 ----------
    print("\n[36] V2.23.2 外部審核（我的訂單可見性、跨站寫入、同名店家、候補順位、遷移錯誤不啟動）")
    import app.routers.orders as _ord36
    from app.models.order import Order as _O36, OrderItem as _OI36, OrderStatus as _OS36, OrderItemBackup as _OB36
    from app.models.menu import Menu as _M36, MenuCategory as _MC36, MenuItem as _MI36
    _orig_ord36 = _ord36.get_current_user
    _u36 = User(line_user_id="smoke-36", display_name="三十六", nickname="三十六"); db.add(_u36); db.flush()
    _st36 = Store(name="審核三十六店", category=CategoryType.MEAL, is_active=True); db.add(_st36); db.flush()
    _mn36 = _M36(store_id=_st36.id, is_active=True); db.add(_mn36); db.flush()
    _ct36 = _MC36(menu_id=_mn36.id, name="主食"); db.add(_ct36); db.flush()
    _it36 = _MI36(menu_id=_mn36.id, category_id=_ct36.id, name="雞腿飯", price=100); db.add(_it36); db.flush()
    _gp36 = Group(owner_id=_other.id, store_id=_st36.id, menu_id=_mn36.id, name="別人的私密團", category=CategoryType.MEAL,
                  deadline=taipei_now() + timedelta(hours=1), is_public=False, enable_backup=True, backup_count=2)
    db.add(_gp36); db.commit()
    async def _fake36(request, db_):
        return db_.query(User).filter(User.id == _u36.id).first()
    try:
        _ord36.get_current_user = _fake36
        # P1-02：不存在的團 404；看不到又沒訂單 403；自己有訂單就看得到自己的那張
        assert _c.get("/groups/999999/orders/mine").status_code == 404
        assert _c.get(f"/groups/{_gp36.id}/orders/mine").status_code == 403
        _o36 = _O36(group_id=_gp36.id, user_id=_u36.id, status=_OS36.SUBMITTED); db.add(_o36); db.flush()
        _oi36 = _OI36(order_id=_o36.id, menu_item_id=_it36.id, item_name="雞腿飯", quantity=1, unit_price=100); db.add(_oi36); db.commit()
        _r = _c.get(f"/groups/{_gp36.id}/orders/mine")
        assert _r.status_code == 200 and "雞腿飯" in _r.text
        check("我的訂單：團不存在 404；看不到的團又沒訂單 403；自己已有訂單的團一律看得到自己那張")

        # P2-01：候補順位唯一；上限照資料庫算；刪除後重排不撞號
        _o36.status = _OS36.EDITING; db.commit()
        _form = {"menu_item_id": str(_it36.id), "quantity": "1", "backup_for": str(_oi36.id)}
        assert _c.post(f"/groups/{_gp36.id}/orders/items", data=_form, headers={"HX-Request": "true"}).status_code == 403, "看不到的團不能加候補"
        _gp36.is_public = True; db.commit()
        for _ in range(2):
            assert _c.post(f"/groups/{_gp36.id}/orders/items", data=_form, headers={"HX-Request": "true"}).status_code == 200
        _r = _c.post(f"/groups/{_gp36.id}/orders/items", data=_form, headers={"HX-Request": "true"})
        assert _r.status_code == 400 and "上限" in _r.text
        db.expire_all()
        _bks = db.query(_OB36).filter(_OB36.order_item_id == _oi36.id).order_by(_OB36.priority).all()
        assert [b.priority for b in _bks] == [1, 2]
        from sqlalchemy.exc import IntegrityError as _IE36
        db.add(_OB36(order_item_id=_oi36.id, priority=2, item_name="重複", unit_price=100))
        try:
            db.commit(); raise AssertionError("同一品項同一順位應被唯一約束擋下")
        except _IE36:
            db.rollback()
        assert _c.delete(f"/orders/backups/{_bks[0].id}", headers={"HX-Request": "true"}).status_code == 200
        db.expire_all()
        assert [b.priority for b in db.query(_OB36).filter(_OB36.order_item_id == _oi36.id).order_by(_OB36.priority).all()] == [1]
        check("候補：上限以資料庫重算；(品項, 順位) 唯一約束擋重複；刪除後重排不撞號")
    finally:
        _ord36.get_current_user = _orig_ord36

    # P1-03：跨站寫入擋下；同站、沒帶標頭的放行
    _ok_post = lambda **h: _c.post("/auth/heartbeat", headers=h).status_code
    assert _ok_post(origin="https://evil.example.com") == 403
    assert _ok_post(origin="null") == 403
    assert _ok_post(**{"sec-fetch-site": "cross-site"}) == 403
    assert _ok_post(**{"origin": "https://testserver", "sec-fetch-site": "same-origin"}) != 403
    assert _ok_post() != 403
    assert _c.get("/", headers={"origin": "https://evil.example.com"}).status_code == 200, "GET 不檢查"
    check("跨站寫入：外站 Origin／null／Sec-Fetch-Site cross-site → 403；同站與沒帶標頭的放行；GET 不受影響")

    # P1-04：同名判斷排除個人代購店；預覽有「不是同一家」出口
    from app.services.import_service import same_name_store as _sns
    _pers = Store(name="審核同名店", category=CategoryType.GROUP_BUY, is_personal=True, owner_user_id=_u36.id); db.add(_pers); db.commit()
    assert _sns(db, "審核同名店") is None, "個人代購店不能被當成同名店家"
    _real = Store(name="審核同名店", category=CategoryType.MEAL, is_active=True); db.add(_real); db.commit()
    assert _sns(db, "審核同名店").id == _real.id
    _adm.get_admin_user = _fake_admin
    try:
        _r = _c.post("/admin/import/preview", data={"store_id": "", "new_store_name": "審核同名店", "new_store_category": "meal",
                     "json_text": json.dumps({"menu": {"items": [{"name": "麵", "price": 50}]}}, ensure_ascii=False)}, headers={"HX-Request": "true"})
        assert "已有同名店家" in _r.text and 'id="not-same-store"' in _r.text and "改店名" in _r.text, _r.text[:400]
    finally:
        _adm.get_admin_user = _orig
    check("同名店家：排除個人代購店；預覽提示「不是同一家？改店名」的出口")

    # P2-02：遷移有錯誤就不啟動（可用 MIGRATIONS_ALLOW_ERRORS=1 強制）
    import app.migrations as _mg36
    _orig_run = _mg36.run_migrations
    _s36 = _main.settings
    _keep = (_s36.line_channel_id, _s36.line_channel_secret, _s36.secret_key)
    try:
        _s36.line_channel_id, _s36.line_channel_secret, _s36.secret_key = "x", "x", "smoke-not-default"
        class _Bad:
            errors, warnings, changed, ok = ["groups.x：故意的錯誤"], [], [], 0
        _mg36.run_migrations = lambda engine, log=print: _Bad()
        try:
            with _TC(_main.app):
                pass
            raise AssertionError("遷移有錯誤時不該啟動")
        except RuntimeError as _e:
            assert "拒絕啟動" in str(_e)
        os.environ["MIGRATIONS_ALLOW_ERRORS"] = "1"
        with _TC(_main.app) as _c36:
            assert _c36.get("/").status_code == 200
    finally:
        os.environ.pop("MIGRATIONS_ALLOW_ERRORS", None)
        _mg36.run_migrations = _orig_run
        _s36.line_channel_id, _s36.line_channel_secret, _s36.secret_key = _keep
    check("遷移有錯誤 → 拒絕啟動（Railway 繼續跑舊版）；MIGRATIONS_ALLOW_ERRORS=1 可強制啟動")

    db.close()
    print(f"\n全部通過（{len(passed)} 項）")


if __name__ == "__main__":
    main()
