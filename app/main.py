from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import engine, Base, get_db
from app.routers import auth, home, groups, orders, admin
from app.services.auth import get_current_user_optional

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables
    Base.metadata.create_all(bind=engine)
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
    user = await get_current_user_optional(request, db)
    if not user:
        return templates.TemplateResponse("login.html", {"request": request})
    return RedirectResponse(url="/home", status_code=302)
