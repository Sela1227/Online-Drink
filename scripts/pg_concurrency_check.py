# -*- coding: utf-8 -*-
"""PostgreSQL 並行測試（V2.23.2，回應外部審核 P1-01／P2-01／P2-03）

煙霧測試用 SQLite，看不到「兩個人同一瞬間」的情況（SQLite 只有一個寫入者、FOR UPDATE 不作用）。
這支連到一個**拋棄式**的 PostgreSQL，用多個行程真的同時打，驗：

  A. 搶最後一份：庫存 1，兩人同時送出各 1 份 → 每一輪恰好 1 人成功，另一人收到「只剩 0 份」
  B. 候補連點：同一品項候補上限 1，兩個請求同時新增 → 只留 1 筆，順位不重複
  C. LINE 登入回呼重複：兩個行程同時搶同一組 state＋code → 只有一個去跟 LINE 換，另一個等到結果沿用
  D. 遷移：新庫 3 個行程同時跑 → 全部 0 錯誤；之後再跑一次 → 變更 0 項

用法（資料庫名稱必須含 test 或 check，會整個清空）：
    PG_TEST_URL="postgresql://postgres@/race_check?host=/tmp&port=55432" PYTHONPATH=. python scripts/pg_concurrency_check.py [輪數]

退出碼 0＝全部通過。**不要指到正式資料庫**——偵測到 railway／rlwy 主機會直接拒絕。
"""
import multiprocessing as mp
import os
import sys
import time
from urllib.parse import urlparse

URL = os.environ.get("PG_TEST_URL", "")


def _guard():
    if not URL.startswith("postgresql"):
        sys.exit("請設 PG_TEST_URL=postgresql://…（拋棄式測試庫）")
    u = urlparse(URL)
    dbname = u.path.lstrip("/")
    host = (u.hostname or "") + " " + (u.query or "")
    if "railway" in host or "rlwy" in host or "proxy" in host:
        sys.exit("PG_TEST_URL 看起來是 Railway 的資料庫，拒絕執行（這支會清空資料庫）")
    if "test" not in dbname and "check" not in dbname:
        sys.exit(f"資料庫名稱「{dbname}」不含 test 或 check，拒絕執行（這支會清空資料庫）")


def _env():
    os.environ["DATABASE_URL"] = URL
    os.environ.setdefault("SECRET_KEY", "pg-concurrency-check")
    os.environ.setdefault("LINE_CHANNEL_ID", "x")
    os.environ.setdefault("LINE_CHANNEL_SECRET", "x")


def _wait(start_at):
    while time.time() < start_at:
        time.sleep(0.001)


# ── 子行程 ──
def _child_submit(gid, line_id, start_at, q):
    _env()
    import app.routers.orders as orders
    from app.models.user import User
    from fastapi.testclient import TestClient

    async def fake(request, db):
        return db.query(User).filter(User.line_user_id == line_id).first()
    orders.get_current_user = fake
    from app.main import app
    c = TestClient(app)
    _wait(start_at)
    r = c.post(f"/groups/{gid}/orders/submit", headers={"HX-Request": "true"})
    q.put((line_id, r.status_code, r.text[:120]))


def _child_backup(gid, item_id, menu_item_id, start_at, q):
    _env()
    import app.routers.orders as orders
    from app.models.user import User
    from fastapi.testclient import TestClient

    async def fake(request, db):
        return db.query(User).filter(User.line_user_id == "bk-user").first()
    orders.get_current_user = fake
    from app.main import app
    c = TestClient(app)
    _wait(start_at)
    r = c.post(f"/groups/{gid}/orders/items", data={"menu_item_id": str(menu_item_id), "quantity": "1", "backup_for": str(item_id)},
               headers={"HX-Request": "true"})
    q.put(r.status_code)


def _child_claim(role, start_at, q):
    _env()
    from app.database import SessionLocal
    from app.routers.auth import _claim_attempt, _finish_attempt
    from app.models.user import LoginAttempt
    db = SessionLocal()
    _wait(start_at + (0 if role == "first" else 0.2))
    row = _claim_attempt(db, "pg-check-key")
    if row is None:
        time.sleep(0.6)  # 假裝正在跟 LINE 換 token
        _finish_attempt(db, "pg-check-key", "done", 1, "/home")
        q.put((role, "換 token"))
        return
    for _ in range(40):
        if row.status != "pending":
            break
        time.sleep(0.2)
        db.expire_all()
        row = db.query(LoginAttempt).filter_by(attempt_key="pg-check-key").first()
    q.put((role, f"沿用 {row.status}"))


def _child_migrate(start_at, q):
    _env()
    from app.database import engine
    from app.migrations import run_migrations
    _wait(start_at)
    r = run_migrations(engine, log=lambda *_: None)
    q.put((len(r.errors), len(r.changed)))


# ── 主程式 ──
def _reset_and_seed():
    _env()
    from datetime import timedelta
    from app.database import Base, SessionLocal, engine
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    return Base, SessionLocal, engine, timedelta


def _run(target, args_list):
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    start_at = time.time() + 4  # 給子行程載入 app 的時間
    ps = [ctx.Process(target=target, args=(*a, start_at, q)) for a in args_list]
    for p in ps:
        p.start()
    out = [q.get(timeout=60) for _ in ps]
    for p in ps:
        p.join(timeout=30)
    return out


def main():
    _guard()
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    failures = []

    # D. 遷移（先做：它負責建表）
    Base, SessionLocal, engine, timedelta = _reset_and_seed()
    res = _run(_child_migrate, [(), (), ()])
    errs = sum(e for e, _ in res)
    from app.migrations import run_migrations
    again = run_migrations(engine, log=lambda *_: None)
    ok = errs == 0 and not again.errors and again.changed == []
    print(f"[D] 遷移：3 個行程同時跑，錯誤合計 {errs}；之後再跑一次變更 {len(again.changed)} 項 → {'通過' if ok else '失敗'}")
    if not ok:
        failures.append("D")

    from app.models.user import User
    from app.models.store import Store, CategoryType
    from app.models.menu import Menu, MenuCategory, MenuItem
    from app.models.group import Group, taipei_now
    from app.models.order import Order, OrderItem, OrderStatus, OrderItemBackup
    db = SessionLocal()
    st = Store(name="並行測試店", category=CategoryType.MEAL, is_active=True); db.add(st); db.flush()
    mn = Menu(store_id=st.id, is_active=True); db.add(mn); db.flush()
    ct = MenuCategory(menu_id=mn.id, name="限量"); db.add(ct); db.flush()
    it = MenuItem(menu_id=mn.id, category_id=ct.id, name="最後一份便當", price=100, stock_limit=1); db.add(it); db.flush()
    owner = User(line_user_id="owner", display_name="團主", nickname="團主"); db.add(owner); db.flush()
    g = Group(owner_id=owner.id, store_id=st.id, menu_id=mn.id, name="搶", category=CategoryType.MEAL,
              deadline=taipei_now() + timedelta(hours=1), enable_backup=True, backup_count=1)
    db.add(g); db.flush()
    orders_ = []
    for n in (1, 2):
        u = User(line_user_id=f"racer{n}", display_name=f"搶{n}", nickname=f"搶{n}"); db.add(u); db.flush()
        o = Order(group_id=g.id, user_id=u.id, status=OrderStatus.DRAFT); db.add(o); db.flush()
        db.add(OrderItem(order_id=o.id, menu_item_id=it.id, item_name=it.name, quantity=1, unit_price=100))
        orders_.append(o.id)
    bu = User(line_user_id="bk-user", display_name="候補", nickname="候補"); db.add(bu); db.flush()
    bo = Order(group_id=g.id, user_id=bu.id, status=OrderStatus.DRAFT); db.add(bo); db.flush()
    bi = OrderItem(order_id=bo.id, menu_item_id=None, item_name="候補用", quantity=1, unit_price=100); db.add(bi)
    db.commit()

    # A. 搶最後一份
    exact = 0
    for i in range(rounds):
        db.query(Order).filter(Order.id.in_(orders_)).update({Order.status: OrderStatus.DRAFT}, synchronize_session=False)
        db.commit()
        _run(_child_submit, [(g.id, "racer1"), (g.id, "racer2")])
        db.expire_all()
        n = db.query(Order).filter(Order.id.in_(orders_), Order.status == OrderStatus.SUBMITTED).count()
        exact += (n == 1)
        if n != 1:
            print(f"    第 {i + 1} 輪：{n} 人送出成功")
    ok = exact == rounds
    print(f"[A] 搶最後一份：{rounds} 輪中 {exact} 輪恰好 1 人成功 → {'通過' if ok else '失敗（有超賣或兩人都失敗）'}")
    if not ok:
        failures.append("A")

    # B. 候補連點（上限 1）
    exact = 0
    for i in range(rounds):
        db.query(OrderItemBackup).filter(OrderItemBackup.order_item_id == bi.id).delete(synchronize_session=False)
        db.commit()
        codes = _run(_child_backup, [(g.id, bi.id, it.id), (g.id, bi.id, it.id)])
        db.expire_all()
        prios = [b.priority for b in db.query(OrderItemBackup).filter(OrderItemBackup.order_item_id == bi.id).all()]
        exact += (prios == [1])
        if prios != [1]:
            print(f"    第 {i + 1} 輪：候補順位 {prios}，回應 {codes}")
    ok = exact == rounds
    print(f"[B] 候補連點（上限 1）：{rounds} 輪中 {exact} 輪恰好留 1 筆 → {'通過' if ok else '失敗'}")
    if not ok:
        failures.append("B")

    # C. 登入回呼重複（跨行程）
    res = dict(_run(_child_claim, [("first",), ("second",)]))
    ok = res.get("first") == "換 token" and res.get("second") == "沿用 done"
    print(f"[C] 登入回呼重複：第一個 {res.get('first')}、第二個 {res.get('second')} → {'通過' if ok else '失敗'}")
    if not ok:
        failures.append("C")

    db.close()
    print("\n全部通過" if not failures else f"\n失敗：{', '.join(failures)}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
