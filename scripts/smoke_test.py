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
  7. 匯入分類／品項計數

新增或改動上述邏輯時，請一併更新這支測試。
"""
import os
import sys
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

    # ---------- 7. 匯入計數 ----------
    print("\n[7] 匯入計數")
    content = MenuContent(
        categories=[{"name": "甜點", "items": [{"name": "a", "price": 1}, {"name": "b", "price": 2}]}],
        items=[{"name": "c", "price": 3}],
    )
    assert _count_import(content) == (1, 3)
    check("分類內品項與無分類品項都算進去")
    assert _count_import(MenuContent()) == (0, 0)
    check("空菜單")

    db.close()
    print(f"\n全部通過（{len(passed)} 項）")


if __name__ == "__main__":
    main()
