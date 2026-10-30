"""資料庫遷移（V2.23.0，審核 P1-8）

原本整段寫在 main.py 的 lifespan 裡，有三個問題：
  1. **每次啟動都對約 60 個欄位下 ALTER TABLE**，靠「已存在就丟例外」判斷。PostgreSQL 的
     ALTER TABLE 不管成不成功都要先拿 ACCESS EXCLUSIVE 鎖；服務設了閒置休眠，每次被叫醒
     （早上第一個人打開）都要整串跑一遍，正好跟第一批請求搶鎖。
  2. **3 個 uvicorn worker 同時跑同一串**（start.sh --workers 3），沒有互斥。
  3. 失敗只 print，沒有人知道哪一步真的有問題。

現在：
  - PostgreSQL 先拿 advisory lock（同一時間只有一個行程在遷移，其他等它做完再快速檢查一遍）
  - **先查再改**：欄位、可空、資料表、索引、約束都先用 SQLAlchemy inspector 查，已經是對的就不下 DDL
  - 真正要下 DDL 時設 lock_timeout 10 秒，拿不到鎖就放棄這一步（下次啟動再補），不會把整站卡住
  - 回傳摘要；`scripts/migrate.py` 用它當退出碼，部署前也能單獨跑

刻意不自動處理的（沿用原本的決定）：orders 的重複訂單不刪（那是使用者的餐與金額），
建不起唯一索引就把排查 SQL 印出來——算「警告」不算「錯誤」，不擋啟動。
"""
import os
import time

from sqlalchemy import inspect, text

LOCK_KEY = 827_331_001  # pg_advisory_lock 的鍵；任意固定整數，只要全專案唯一
LOCK_WAIT_SECONDS = 120

# (資料表, 欄位, 型別) —— 依加入的版本順序；新欄位加在最後
COLUMNS = [
    ("order_items", "size", "VARCHAR(10)"),
    ("order_items", "created_at", "TIMESTAMP DEFAULT NOW()"),
    ("orders", "discount_amount", "NUMERIC(10,2) DEFAULT 0"),
    ("orders", "discount_note", "VARCHAR(100)"),
    ("menu_items", "price_l", "NUMERIC(10,2)"),
    ("stores", "phone", "VARCHAR(50)"),
    ("stores", "branch", "VARCHAR(100)"),
    ("groups", "branch_id", "INTEGER"),
    ("groups", "note", "TEXT"),
    ("groups", "delivery_fee", "NUMERIC(10,2)"),
    ("groups", "is_public", "BOOLEAN DEFAULT TRUE"),
    ("groups", "store_name", "VARCHAR(100)"),
    ("users", "nickname", "VARCHAR(100)"),
    ("users", "last_login_at", "TIMESTAMP"),
    ("users", "last_active_at", "TIMESTAMP"),
    ("users", "is_guest", "BOOLEAN DEFAULT FALSE"),
    ("groups", "is_blind_mode", "BOOLEAN DEFAULT FALSE"),
    ("groups", "enable_lucky_draw", "BOOLEAN DEFAULT FALSE"),
    ("groups", "lucky_draw_count", "INTEGER DEFAULT 1"),
    ("groups", "lucky_winner_ids", "TEXT"),
    ("groups", "treat_user_id", "INTEGER"),
    ("groups", "min_members", "INTEGER"),
    ("groups", "auto_extend", "BOOLEAN DEFAULT FALSE"),
    ("stores", "website_url", "VARCHAR(500)"),
    ("stores", "ubereats_url", "VARCHAR(500)"),
    ("stores", "foodpanda_url", "VARCHAR(500)"),
    ("stores", "google_maps_url", "VARCHAR(500)"),
    ("stores", "address", "VARCHAR(300)"),
    ("groups", "auto_remind_minutes", "INTEGER"),
    ("groups", "last_remind_at", "TIMESTAMP"),
    ("groups", "order_limit", "NUMERIC(10,2)"),
    ("groups", "allow_over_limit", "BOOLEAN DEFAULT FALSE"),
    ("groups", "discount_percent", "NUMERIC(5,2)"),
    ("stores", "provides_invoice", "BOOLEAN DEFAULT FALSE"),
    ("stores", "provides_receipt", "BOOLEAN DEFAULT FALSE"),
    ("groups", "enable_backup", "BOOLEAN DEFAULT FALSE"),
    ("groups", "backup_count", "INTEGER DEFAULT 2"),
    ("stores", "is_personal", "BOOLEAN DEFAULT FALSE"),
    ("stores", "owner_user_id", "INTEGER"),
    ("menu_items", "description", "VARCHAR(200)"),
    ("menu_items", "image_url", "VARCHAR(500)"),
    ("menu_items", "stock_limit", "INTEGER"),
    ("menu_items", "is_available", "BOOLEAN DEFAULT TRUE"),
    ("menu_items", "price_tbd", "BOOLEAN DEFAULT FALSE"),
    ("order_items", "fulfillment", "VARCHAR(20)"),
    ("order_items", "fulfilled_backup_id", "INTEGER"),
    ("order_items", "diff_settled", "BOOLEAN DEFAULT FALSE"),
    ("order_item_backups", "extras_price", "NUMERIC(10,2) DEFAULT 0"),
    ("votes", "is_public", "BOOLEAN DEFAULT TRUE"),
    ("store_recommendations", "menu_image_urls", "TEXT"),
    ("stores", "is_public", "BOOLEAN DEFAULT TRUE"),
    ("group_templates", "department_ids", "VARCHAR(200)"),
    ("system_settings", "announcement", "VARCHAR(500)"),
    ("stores", "city", "VARCHAR(10)"),   # V2.26.0
    ("users", "cities", "TEXT"),         # V2.26.0
]

# V1.10.0：刪店家改成斷開連結保留歷史，這些外鍵要可為 NULL
NULLABLE = [
    ("groups", "store_id"),
    ("groups", "menu_id"),
    ("order_items", "menu_item_id"),
    ("order_item_options", "item_option_id"),
]


class _Result:
    def __init__(self):
        self.changed, self.warnings, self.errors = [], [], []
        self.ok = 0

    def summary(self) -> str:
        return (f"遷移完成：變更 {len(self.changed)} 項、已是最新 {self.ok} 項、"
                f"警告 {len(self.warnings)} 項、錯誤 {len(self.errors)} 項")


def _ddl(engine, sql: str, params: dict | None = None):
    """執行一條 DDL；PostgreSQL 上限制等鎖 10 秒，拿不到就丟例外（不要把線上請求一起卡住）"""
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("SET LOCAL lock_timeout = '10s'"))
        conn.execute(text(sql), params or {})


def _acquire_lock(engine, log):
    if engine.dialect.name != "postgresql":
        return None
    conn = engine.connect()
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    waited = False
    while True:
        got = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar()
        conn.commit()
        if got:
            if waited:
                log("遷移鎖：等到了（另一個行程剛做完），接著只做快速檢查")
            return conn
        if time.monotonic() > deadline:
            log(f"!! 遷移鎖等了 {LOCK_WAIT_SECONDS} 秒還拿不到，不加鎖繼續（每一步都先查再改，重複跑無害）")
            conn.close()
            return None
        if not waited:
            log("遷移鎖：另一個行程正在遷移，等待中…")
            waited = True
        time.sleep(0.5)


def _release_lock(conn):
    if conn is None:
        return
    try:
        conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
        conn.commit()
    finally:
        conn.close()


def run_migrations(engine, log=print) -> _Result:
    """建表＋補欄位＋索引＋資料修正。可重複執行；回傳結果摘要。"""
    from app.database import Base
    # 匯入所有 model，create_all 才看得到每一張表
    import app.models  # noqa: F401
    from app.models import department, treat, vote, template  # noqa: F401
    from app.models.user import SystemSetting  # noqa: F401

    r = _Result()
    t0 = time.monotonic()
    pg = engine.dialect.name == "postgresql"
    lock = _acquire_lock(engine, log)
    try:
        Base.metadata.create_all(bind=engine)

        insp = inspect(engine)
        tables = set(insp.get_table_names())
        col_cache: dict[str, dict] = {}

        def columns(table):
            if table not in col_cache:
                col_cache[table] = {c["name"]: c for c in inspect(engine).get_columns(table)} if table in tables else {}
            return col_cache[table]

        # 1. 欄位
        for table, column, ctype in COLUMNS:
            if table not in tables:
                r.errors.append(f"{table}.{column}：資料表不存在")
                log(f"!! Column {table}.{column}: 資料表 {table} 不存在")
                continue
            if column in columns(table):
                r.ok += 1
                continue
            try:
                _ddl(engine, f"ALTER TABLE {table} ADD COLUMN {column} {ctype}")
                col_cache.pop(table, None)
                r.changed.append(f"{table}.{column}")
                log(f"Added column: {table}.{column}")
            except Exception as e:
                r.errors.append(f"{table}.{column}：{e}")
                log(f"!! Column {table}.{column} 新增失敗：{e}")

        # 2. 外鍵改可空（只有 PostgreSQL 需要；SQLite 的 create_all 本來就照 model 建）
        for table, column in NULLABLE:
            info = columns(table).get(column)
            if info is None or info.get("nullable", True) or not pg:
                r.ok += 1
                continue
            try:
                _ddl(engine, f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL")
                col_cache.pop(table, None)
                r.changed.append(f"{table}.{column} nullable")
                log(f"{table}.{column} set nullable")
            except Exception as e:
                r.errors.append(f"{table}.{column} nullable：{e}")
                log(f"!! {table}.{column} 改可空失敗：{e}")

        def indexes(table):
            if table not in tables:
                return set()
            i = inspect(engine)
            names = {x["name"] for x in i.get_indexes(table)}
            try:
                names |= {x["name"] for x in i.get_unique_constraints(table) if x.get("name")}
            except NotImplementedError:
                pass
            return names

        # 3. 投票唯一約束：同一人對同一選項只能投一票（先刪重複保留最早）
        if "vote_records" in tables:
            if "vote_records_option_user_unique" in indexes("vote_records"):
                r.ok += 1
            elif pg:
                try:
                    with engine.begin() as conn:
                        conn.execute(text("SET LOCAL lock_timeout = '10s'"))
                        conn.execute(text("""
                            DELETE FROM vote_records a USING vote_records b
                            WHERE a.id > b.id AND a.option_id = b.option_id AND a.user_id = b.user_id
                        """))
                        conn.execute(text("ALTER TABLE vote_records ADD CONSTRAINT vote_records_option_user_unique UNIQUE (option_id, user_id)"))
                    r.changed.append("vote_records_option_user_unique")
                    log("Added unique constraint: vote_records_option_user_unique")
                except Exception as e:
                    r.warnings.append(f"vote_records_option_user_unique：{e}")
                    log(f"!! Unique constraint vote_records_option_user_unique：{e}")
            else:
                r.ok += 1

        # 4. 唯一索引（V2.11.1 P1-06／P1-07、V2.15.1 P2-10）
        #    收藏與請客的重複可以刪（冪等／純統計）；訂單與菜單的重複不自動刪，印排查 SQL
        idx_specs = [
            ("user_favorites", "uq_user_favorites", "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_favorites ON user_favorites (user_id, store_id)",
             "DELETE FROM user_favorites a USING user_favorites b WHERE a.id > b.id AND a.user_id = b.user_id AND a.store_id = b.store_id", None),
            ("treat_records", "uq_treat_records_group", "CREATE UNIQUE INDEX IF NOT EXISTS uq_treat_records_group ON treat_records (group_id)",
             "DELETE FROM treat_records a USING treat_records b WHERE a.id > b.id AND a.group_id = b.group_id", None),
            ("orders", "uq_orders_group_user", "CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_group_user ON orders (group_id, user_id)", None,
             ["!! 無法建立 uq_orders_group_user，很可能已有重複訂單。",
              "!! 不會自動刪除（那是使用者的餐與金額）。請手動排查：",
              "!!   SELECT group_id, user_id, COUNT(*) FROM orders GROUP BY 1,2 HAVING COUNT(*) > 1;"]),
            ("order_item_backups", "uq_backups_item_priority",
             "CREATE UNIQUE INDEX IF NOT EXISTS uq_backups_item_priority ON order_item_backups (order_item_id, priority)", None,
             ["!! 無法建立 uq_backups_item_priority，已有同一品項的候補順位重複（V2.23.2 以前連點可能造成）。不自動刪除，排查：",
              "!!   SELECT order_item_id, priority, COUNT(*) FROM order_item_backups GROUP BY 1,2 HAVING COUNT(*) > 1;",
              "!!   重新編號：UPDATE order_item_backups b SET priority = r.rn FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY order_item_id ORDER BY priority, id) rn FROM order_item_backups) r WHERE r.id = b.id;"]),
            ("menus", "uq_menus_one_active", "CREATE UNIQUE INDEX IF NOT EXISTS uq_menus_one_active ON menus (store_id) WHERE is_active", None,
             ["!! 無法建立 uq_menus_one_active，很可能有店家同時有兩份使用中菜單。排查：",
              "!!   SELECT store_id, COUNT(*) FROM menus WHERE is_active GROUP BY 1 HAVING COUNT(*) > 1;",
              "!!   保留最新的一份：UPDATE menus SET is_active = false WHERE id NOT IN (SELECT MAX(id) FROM menus WHERE is_active GROUP BY store_id) AND is_active;"]),
        ]
        for table, name, create_sql, dedupe_sql, hint in idx_specs:
            if table not in tables:
                continue
            if name in indexes(table):
                r.ok += 1
                log(f"Unique index {name}: OK")
                continue
            try:
                with engine.begin() as conn:
                    if pg:
                        conn.execute(text("SET LOCAL lock_timeout = '10s'"))
                        if dedupe_sql:
                            conn.execute(text(dedupe_sql))
                    conn.execute(text(create_sql))
                r.changed.append(name)
                log(f"Unique index {name}: OK（新建）")
            except Exception as e:
                r.warnings.append(f"{name}：{e}")
                log("=" * 70)
                for line in (hint or [f"!! Unique index {name} 建立失敗"]):
                    log(line)
                log(f"!! 原始錯誤：{e}")
                log("=" * 70)

        # 5. Enum：團購（PostgreSQL 的 enum 值固定大寫，坑 #2）
        if pg:
            try:
                with engine.begin() as conn:
                    has = conn.execute(text(
                        "SELECT 1 FROM pg_enum WHERE enumlabel = 'GROUP_BUY' "
                        "AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'categorytype')")).fetchone()
                if has:
                    r.ok += 1
                else:
                    with engine.begin() as conn:
                        conn.execute(text("ALTER TYPE categorytype ADD VALUE IF NOT EXISTS 'GROUP_BUY'"))
                    r.changed.append("categorytype.GROUP_BUY")
                    log("Added enum value: categorytype.GROUP_BUY")
            except Exception as e:
                r.errors.append(f"categorytype.GROUP_BUY：{e}")
                log(f"!! Enum categorytype.GROUP_BUY：{e}")
            # 舊資料的小寫 group_buy → GROUP_BUY（只在 PG 上 enum 才會有這種殘留）
            try:
                with engine.begin() as conn:
                    n = conn.execute(text("SELECT (SELECT COUNT(*) FROM stores WHERE category::text = 'group_buy') + (SELECT COUNT(*) FROM groups WHERE category::text = 'group_buy')")).scalar()
                    if n:
                        conn.execute(text("UPDATE stores SET category = 'GROUP_BUY' WHERE category::text = 'group_buy'"))
                        conn.execute(text("UPDATE groups SET category = 'GROUP_BUY' WHERE category::text = 'group_buy'"))
                        r.changed.append(f"小寫 group_buy × {n}")
                        log(f"Fixed enum case: {n} rows")
                    else:
                        r.ok += 1
            except Exception as e:
                r.warnings.append(f"enum case：{e}")
                log(f"Enum case fix check: {e}")

        # 6a. V2.26.0：有地址、還沒設縣市的店家，從地址開頭補縣市（判斷不出來的留空＝永遠顯示）。
        #     只動 city IS NULL 的列，管理員改過的不會被蓋；每次啟動跑一次，沒得補就 0 筆
        if "stores" in tables:
            try:
                from app.services.city import city_from_address
                with engine.begin() as conn:
                    rows = conn.execute(text("SELECT id, address FROM stores WHERE city IS NULL AND address IS NOT NULL AND address <> ''")).fetchall()
                    n = 0
                    for sid, addr in rows:
                        c = city_from_address(addr)
                        if c:
                            conn.execute(text("UPDATE stores SET city = :c WHERE id = :i AND city IS NULL"), {"c": c, "i": sid})
                            n += 1
                if n:
                    r.changed.append(f"店家縣市補值 × {n}")
                    log(f"Backfilled stores.city from address: {n}")
                else:
                    r.ok += 1
            except Exception as e:
                r.warnings.append(f"店家縣市補值：{e}")
                log(f"!! 店家縣市補值：{e}")

        # 6. system_settings 初始列
        try:
            with engine.begin() as conn:
                count = conn.execute(text("SELECT COUNT(*) FROM system_settings")).scalar()
                if count == 0:
                    conn.execute(text("INSERT INTO system_settings (id, token_version, updated_at) VALUES (1, 1, CURRENT_TIMESTAMP)"))
                    r.changed.append("system_settings 初始列")
                    log("Created initial system_settings")
                else:
                    fixed = conn.execute(text("UPDATE system_settings SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")).rowcount
                    if fixed:
                        r.changed.append("system_settings.updated_at")
                    else:
                        r.ok += 1
        except Exception as e:
            r.errors.append(f"system_settings：{e}")
            log(f"!! system_settings：{e}")
    finally:
        _release_lock(lock)

    log(r.summary() + f"（{time.monotonic() - t0:.1f} 秒）")
    for e in r.errors:
        log(f"!! 錯誤：{e}")
    return r
