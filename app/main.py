from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
from sqlalchemy import text
import os

from app.config import get_settings
from app.database import engine, Base, get_db
from app.routers import auth, home, groups, orders, admin
from app.services.auth import get_current_user_optional

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables
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

# Routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(home.router, tags=["home"])
app.include_router(groups.router, prefix="/groups", tags=["groups"])
app.include_router(orders.router, tags=["orders"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])

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
