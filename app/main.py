from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
from sqlalchemy import text
import os
import logging

from app.config import get_settings
from app.database import engine, Base, get_db
from app.routers import auth, home, groups, orders, admin, votes
from app.routers import templates as templates_router
from app.services.auth import get_current_user_optional

settings = get_settings()

# 設定 logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables
    # Import all models to ensure tables are created
    from app.models import department  # noqa: F401
    from app.models import treat  # noqa: F401 - Phase 3 請客記錄
    from app.models import vote  # noqa: F401 - Phase 3 投票系統
    from app.models import template  # noqa: F401 - Phase 5 開團模板
    
    Base.metadata.create_all(bind=engine)
    
    # 自動新增欄位（如果不存在）
    def add_column_if_not_exists(table: str, column: str, column_type: str):
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"))
            print(f"Added column: {table}.{column}")
        except Exception as e:
            # 欄位已存在
            print(f"Column {table}.{column} check: OK")
    
    add_column_if_not_exists("order_items", "size", "VARCHAR(10)")
    add_column_if_not_exists("order_items", "created_at", "TIMESTAMP DEFAULT NOW()")
    add_column_if_not_exists("menu_items", "price_l", "NUMERIC(10,2)")
    add_column_if_not_exists("stores", "phone", "VARCHAR(50)")
    add_column_if_not_exists("stores", "branch", "VARCHAR(100)")
    add_column_if_not_exists("groups", "branch_id", "INTEGER")
    add_column_if_not_exists("groups", "note", "TEXT")
    add_column_if_not_exists("groups", "delivery_fee", "NUMERIC(10,2)")
    add_column_if_not_exists("groups", "is_public", "BOOLEAN DEFAULT TRUE")
    add_column_if_not_exists("users", "nickname", "VARCHAR(100)")
    add_column_if_not_exists("users", "last_login_at", "TIMESTAMP")
    add_column_if_not_exists("users", "last_active_at", "TIMESTAMP")
    add_column_if_not_exists("users", "is_guest", "BOOLEAN DEFAULT FALSE")
    
    # Phase 3: 趣味功能欄位
    add_column_if_not_exists("groups", "is_blind_mode", "BOOLEAN DEFAULT FALSE")
    add_column_if_not_exists("groups", "enable_lucky_draw", "BOOLEAN DEFAULT FALSE")
    add_column_if_not_exists("groups", "lucky_draw_count", "INTEGER DEFAULT 1")
    add_column_if_not_exists("groups", "lucky_winner_ids", "TEXT")
    add_column_if_not_exists("groups", "treat_user_id", "INTEGER")
    
    # Phase 3: 湊團制欄位
    add_column_if_not_exists("groups", "min_members", "INTEGER")
    add_column_if_not_exists("groups", "auto_extend", "BOOLEAN DEFAULT FALSE")
    
    # Phase 4: 店家連結欄位
    add_column_if_not_exists("stores", "website_url", "VARCHAR(500)")
    add_column_if_not_exists("stores", "ubereats_url", "VARCHAR(500)")
    add_column_if_not_exists("stores", "foodpanda_url", "VARCHAR(500)")
    add_column_if_not_exists("stores", "google_maps_url", "VARCHAR(500)")
    add_column_if_not_exists("stores", "address", "VARCHAR(300)")
    
    # Phase 5: 自動催單欄位
    add_column_if_not_exists("groups", "auto_remind_minutes", "INTEGER")
    add_column_if_not_exists("groups", "last_remind_at", "TIMESTAMP")
    
    # Phase 7: 投票可見性欄位
    add_column_if_not_exists("votes", "is_public", "BOOLEAN DEFAULT TRUE")
    
    # Phase 7: 建立 vote_departments 表（如果不存在）
    def create_table_if_not_exists(create_sql: str, table_name: str):
        try:
            with engine.begin() as conn:
                conn.execute(text(create_sql))
            print(f"Created table: {table_name}")
        except Exception as e:
            if "already exists" in str(e):
                print(f"Table {table_name} check: OK")
            else:
                print(f"Table {table_name} check: {e}")
    
    create_table_if_not_exists("""
        CREATE TABLE IF NOT EXISTS vote_departments (
            id SERIAL PRIMARY KEY,
            vote_id INTEGER REFERENCES votes(id),
            department_id INTEGER REFERENCES departments(id)
        )
    """, "vote_departments")
    
    create_table_if_not_exists("""
        CREATE TABLE IF NOT EXISTS announcements (
            id SERIAL PRIMARY KEY,
            title VARCHAR(100) NOT NULL,
            content VARCHAR(500) NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            is_pinned BOOLEAN DEFAULT FALSE,
            created_by_id INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW(),
            expires_at TIMESTAMP
        )
    """, "announcements")
    
    # 店家推薦表
    create_table_if_not_exists("""
        CREATE TABLE IF NOT EXISTS store_recommendations (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            store_name VARCHAR(100) NOT NULL,
            category VARCHAR(20) NOT NULL,
            menu_url VARCHAR(500),
            menu_image_url VARCHAR(500),
            note VARCHAR(500),
            status VARCHAR(20) DEFAULT 'pending',
            reject_reason VARCHAR(200),
            created_at TIMESTAMP DEFAULT NOW(),
            reviewed_at TIMESTAMP,
            reviewer_id INTEGER,
            created_store_id INTEGER
        )
    """, "store_recommendations")
    
    # 投票唯一約束：同一人對同一選項只能投一票
    def add_unique_constraint_if_not_exists():
        try:
            with engine.begin() as conn:
                # 先刪除重複資料（保留最早的）
                conn.execute(text("""
                    DELETE FROM vote_records a USING vote_records b
                    WHERE a.id > b.id 
                    AND a.option_id = b.option_id 
                    AND a.user_id = b.user_id
                """))
                # 嘗試建立唯一約束
                conn.execute(text("""
                    ALTER TABLE vote_records 
                    ADD CONSTRAINT vote_records_option_user_unique 
                    UNIQUE (option_id, user_id)
                """))
            print("Added unique constraint: vote_records_option_user_unique")
        except Exception as e:
            if "already exists" in str(e):
                print("Unique constraint vote_records_option_user_unique: OK")
            else:
                print(f"Unique constraint check: {e}")
    
    add_unique_constraint_if_not_exists()
    
    # 添加新的 enum 值（團購類型）
    def add_enum_value_if_not_exists(enum_name: str, new_value: str):
        try:
            with engine.begin() as conn:
                # 檢查值是否已存在
                result = conn.execute(text(f"SELECT 1 FROM pg_enum WHERE enumlabel = '{new_value}' AND enumtypid = (SELECT oid FROM pg_type WHERE typname = '{enum_name}')"))
                if result.fetchone() is None:
                    conn.execute(text(f"ALTER TYPE {enum_name} ADD VALUE '{new_value}'"))
                    print(f"Added enum value: {enum_name}.{new_value}")
                else:
                    print(f"Enum value {enum_name}.{new_value} check: OK")
        except Exception as e:
            print(f"Enum {enum_name}.{new_value} check: {e}")
    
    # 添加大寫版本（SQLAlchemy 使用 enum name）
    add_enum_value_if_not_exists("categorytype", "GROUP_BUY")
    
    # 修正舊的小寫 group_buy -> GROUP_BUY
    def fix_enum_case():
        try:
            with engine.begin() as conn:
                # 檢查是否有使用小寫 group_buy 的記錄
                result = conn.execute(text("SELECT COUNT(*) FROM stores WHERE category = 'group_buy'"))
                store_count = result.scalar()
                result = conn.execute(text("SELECT COUNT(*) FROM groups WHERE category = 'group_buy'"))
                group_count = result.scalar()
                
                if store_count > 0 or group_count > 0:
                    # 更新為大寫
                    conn.execute(text("UPDATE stores SET category = 'GROUP_BUY' WHERE category = 'group_buy'"))
                    conn.execute(text("UPDATE groups SET category = 'GROUP_BUY' WHERE category = 'group_buy'"))
                    print(f"Fixed enum case: {store_count} stores, {group_count} groups")
                else:
                    print("Enum case fix: OK (no lowercase values)")
        except Exception as e:
            print(f"Enum case fix check: {e}")
    
    fix_enum_case()
    
    # 確保 system_settings 有初始資料和 announcement 欄位
    from app.models.user import SystemSetting
    add_column_if_not_exists("system_settings", "announcement", "VARCHAR(500)")
    
    try:
        with engine.begin() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM system_settings"))
            count = result.scalar()
            if count == 0:
                conn.execute(text("INSERT INTO system_settings (id, token_version, updated_at) VALUES (1, 1, NOW())"))
                print("Created initial system_settings")
            else:
                # 修復可能的 NULL updated_at
                conn.execute(text("UPDATE system_settings SET updated_at = NOW() WHERE updated_at IS NULL"))
                print("system_settings check: OK")
    except Exception as e:
        # 表可能不存在，SQLAlchemy 會自動建立
        print(f"system_settings check: {e}")
    
    # 確保目錄存在
    os.makedirs("app/static/images", exist_ok=True)
    os.makedirs("app/static/uploads/stores", exist_ok=True)
    
    yield
    # Shutdown


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Templates
templates = Jinja2Templates(directory="app/templates")

# 加入台北時區過濾器
from datetime import timezone, timedelta

def to_taipei_time(dt):
    """將 UTC 時間轉換為台北時間 (UTC+8)"""
    if dt is None:
        return None
    taipei_tz = timezone(timedelta(hours=8))
    # 假設 dt 是 naive UTC 時間
    utc_dt = dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(taipei_tz)

templates.env.filters['taipei'] = to_taipei_time

# Routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(home.router, tags=["home"])
app.include_router(groups.router, prefix="/groups", tags=["groups"])
app.include_router(orders.router, tags=["orders"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(votes.router, tags=["votes"])
app.include_router(templates_router.router, tags=["templates"])

# 開發模式路由
if settings.debug:
    from app.routers import dev
    app.include_router(dev.router, tags=["dev"])


@app.get("/")
async def root(request: Request, db: Session = Depends(get_db)):
    user, new_token = await get_current_user_optional(request, db)
    if not user:
        return templates.TemplateResponse("login.html", {"request": request})
    
    response = RedirectResponse(url="/home", status_code=302)
    # 如果需要刷新 token
    if new_token:
        response.set_cookie(
            key="access_token",
            value=new_token,
            httponly=True,
            max_age=7 * 24 * 60 * 60,
            samesite="lax",
            secure=True,
        )
    return response
