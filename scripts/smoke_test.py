# -*- coding: utf-8 -*-
"""煙霧測試 — 用 SQLite 驗核心邏輯，不需要 live app 也不碰正式資料庫。

跑法（先 pip install -r requirements.txt）：
    SECRET_KEY=x DATABASE_URL="sqlite:///./_smoke.db" PYTHONPATH=. python scripts/smoke_test.py
跑完記得 `rm -f _smoke.db`，打包前不要把它一起裝進去。

涵蓋範圍（V2.10.3）：
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
  18. 匯入分類／品項計數

新增或改動上述邏輯時，請一併更新這支測試。
"""
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
            assert f"匯入到店家「{store.name}」" in _T(r), f"{label}：應以 UI 選的店家為準"
        check("選了店家時，JSON 的 store_id / mode 一律忽略（四種形狀）")

        r = _c.post("/admin/import/preview", data={"store_id": str(store.id),
                    "json_text": _J({"store": {"name": "別家", "category": "meal"}, "menu": _menu})}, headers=_H)
        assert f"匯入到店家「{store.name}」" in _T(r) and "已忽略" in _T(r)
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
        assert r.status_code == 200 and "基本資料" in r.text and "營運設定" in r.text
        check("工作台 200，四個分頁")

        r = _c.get(f"/admin/stores/{store.id}/edit", follow_redirects=False)
        assert r.status_code == 301 and r.headers["location"].endswith("?tab=info")
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
        assert "與使用中版本（第 1 版" in t and "新增 1" in t and "變更 3" in t and "移除 1" in t and "不變 3" in t, t
        assert "確認匯入（新增 1・變更 3・移除 1）" in t
        assert "只貼了部分菜單" not in t
        check("預覽片段顯示差異卡與帶數字的確認鈕")

        r = _c.post("/admin/import/preview", data={"store_id": str(_ds.id),
                    "json_text": _J({"menu": {"categories": [{"name": "滷味", "items": [{"name": "滷蛋", "price": 15}]}]}})}, headers=_H)
        t = _T(r)
        assert "看起來只貼了部分菜單" in t and "仍要匯入（移除 6 個品項）" in t, t
        check("部分菜單 → 醒目提醒，按鈕改「仍要匯入」但不擋")

        r = _c.post("/admin/import/preview", data={"store_id": "",
                    "json_text": _J({"store": {"name": "差異測試店", "category": "meal"}, "menu": _new.model_dump(mode="json")})}, headers=_H)
        t = _T(r)
        assert "同名店家" in t and "與使用中版本" in t, t
        check("同名店家匯入也跟它的使用中版本比")

        r = _c.post("/admin/import/preview", data={"store_id": "",
                    "json_text": _J({"store": {"name": "全新的店", "category": "meal"}, "menu": _new.model_dump(mode="json")})}, headers=_H)
        t = _T(r)
        assert "與使用中版本" not in t and "確認匯入" in t and "新增 1" not in t
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
    assert _chg["滷肉飯"]["note_changed"] and "說明改了" in _chg["滷肉飯"]["note"]
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

    db.close()
    print(f"\n全部通過（{len(passed)} 項）")


if __name__ == "__main__":
    main()
