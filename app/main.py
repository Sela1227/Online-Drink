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
    # 機密設定檢查：缺少時寧可不啟動，也不要用公開預設金鑰簽 JWT
    _missing = []
    if settings.secret_key in ("", "change-me-in-production"):
        _missing.append("SECRET_KEY")
    if not settings.line_channel_id:
        _missing.append("LINE_CHANNEL_ID")
    if not settings.line_channel_secret:
        _missing.append("LINE_CHANNEL_SECRET")
    if _missing:
        raise RuntimeError(f"必要環境變數未設定，拒絕啟動：{', '.join(_missing)}")
    
    # V2.23.0（審核 P1-8）：遷移搬到 app/migrations.py——PostgreSQL advisory lock 讓 3 個 worker
    # 不會同時跑、每一步先查再改（已是最新就不下 ALTER，休眠喚醒時不再跟第一批請求搶表鎖）。
    # 也可以在部署前單獨跑：python scripts/migrate.py
    from app.migrations import run_migrations
    _mig = run_migrations(engine)
    # V2.23.2 審稿 P2-02：遷移有錯誤（缺欄位補不上之類）就不啟動——寧可讓 Railway 健康檢查失敗、
    # 繼續跑舊版，也不要讓新程式在不完整的資料表上服務。警告（重複資料建不起唯一索引）不擋。
    # 緊急時可設 MIGRATIONS_ALLOW_ERRORS=1 強制啟動
    if _mig.errors and os.environ.get("MIGRATIONS_ALLOW_ERRORS") != "1":
        raise RuntimeError(f"資料庫遷移有 {len(_mig.errors)} 項錯誤，拒絕啟動：{'；'.join(e[:120] for e in _mig.errors[:3])}")
    
    # 確保目錄存在
    os.makedirs("app/static/images", exist_ok=True)
    os.makedirs("app/static/uploads/stores", exist_ok=True)

    from app.version import APP_VERSION
    print(f"SELA 快點來點餐 {APP_VERSION} 啟動完成")  # V2.26.0：Deploy Logs 一眼看到跑的是哪一版
    yield
    # Shutdown


app = FastAPI(
    title=settings.app_name,
    version=__import__("app.version", fromlist=["APP_VERSION"]).APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.debug else None,
)

# 401 未登入處理（V1.4.1）：
# - 瀏覽器直接開需登入頁面 → 導向 /auth/login（而非顯示 JSON 錯誤）
# - htmx 背景請求 / API 呼叫 → 維持 401 JSON，交給前端 JS handler 處理
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse

@app.exception_handler(StarletteHTTPException)
async def auth_aware_exception_handler(request: Request, exc: StarletteHTTPException):
    """V2.11.3 R-03：一般表單送出失敗時，不要回一整頁 JSON。

    htmx 請求由 base.html 的 htmx:responseError 顯示 toast；但 `<form method="post">`
    送出失敗時，瀏覽器會直接把 `{"detail":"..."}` 當成頁面顯示在手機上。
    V2.11.2 新增的兩條錯誤訊息（複製上次找不到品項、範本未記錄部門）都掉進這裡，
    等於那兩項修正的「讓使用者看到訊息」從來沒有生效。

    改成導回來源頁並帶上 flash 參數，由 base.html 統一顯示 toast。
    只導回站內路徑，避免開放轉址。
    """
    is_htmx = request.headers.get("HX-Request") == "true"
    wants_html = "text/html" in request.headers.get("accept", "")

    if exc.status_code == 401 and not is_htmx and wants_html:
        # V2.12.0：原本只帶 request.url.path，`/admin/import?store_id=25` 過期重登後
        # 會落在沒有店家的 `/admin/import` —— 畫面像是從店家頁進來的，其實店家已經掉了，
        # 接著就撞上「store_id 還是 0」的訊息。查詢字串一起帶（auth.py 有做站內路徑檢查）。
        from urllib.parse import quote
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(
            url=f"/auth/login?next={quote(target, safe='/?=&%')}",
            status_code=302,
        )

    if (400 <= exc.status_code < 500 and not is_htmx and wants_html
            and request.method == "POST" and isinstance(exc.detail, str)):
        return _form_error_response(exc.detail, exc.status_code)

    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def _form_error_response(message: str, status_code: int = 400):
    """一般表單送出失敗時的回應（V2.11.4 S-02）。

    V2.11.3 用 303 導回來源頁並帶 ?flash=，有三個問題：
      - 導回是一次新的 GET，**使用者填的表單內容全部遺失** —— 開團頁選完店家、
        填完團名截止時間備註部門，因為「截止時間必須晚於現在」被擋下，整頁重填。
        V2.11.0 特地做的「換店不丟表單」在這裡被自己打掉（S-02）。
      - 訊息放在網址上，任何人都能用連結讓本站顯示假的紅色系統提示（S-03）。
      - Referer 路徑以 // 開頭時會變成協定相對網址導向外站（S-04）。

    改成回一個極小的 HTML：把訊息寫進 sessionStorage，然後 history.back()。
    多數瀏覽器返回時會保留表單內容；網址不出現訊息；外站寫不進本站的 sessionStorage。
    """
    import json
    from fastapi.responses import HTMLResponse

    safe = json.dumps(message).replace("<", "\\u003c").replace(">", "\\u003e")
    html = (
        "<!doctype html><html lang='zh-Hant'><meta charset='utf-8'>"
        "<title>返回中</title><body>"
        "<script>"
        f"try{{sessionStorage.setItem('flash',{safe});}}catch(e){{}}"
        "if(history.length>1){history.back();}else{location.replace('/home');}"
        "</script>"
        "<noscript><p>請按上一頁返回。</p></noscript>"
        "</body></html>"
    )
    return HTMLResponse(html, status_code=status_code)


# V2.11.4 S-07：表單缺必填欄位時 FastAPI 拋的是 RequestValidationError（422），
# 不會進上面的 StarletteHTTPException 處理器，一般 UI 幾乎不會觸發，但瀏覽器
# 自動填入異常或舊頁面快取時仍可能整頁 JSON。
from fastapi.exceptions import RequestValidationError


@app.exception_handler(RequestValidationError)
async def form_validation_handler(request: Request, exc: RequestValidationError):
    is_htmx = request.headers.get("HX-Request") == "true"
    wants_html = "text/html" in request.headers.get("accept", "")
    if not is_htmx and wants_html and request.method == "POST":
        return _form_error_response("輸入格式有誤，請重新確認", 422)
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Templates
templates = Jinja2Templates(directory="app/templates")
from app.templating import register_filters as _register_filters  # V2.15.1：money/taipei 共用
_register_filters(templates.env)

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
# V2.23.2 審稿 P1-03：會改資料的請求（POST/PUT/PATCH/DELETE）擋跨站來源。
# 主防線是 cookie 的 SameSite=Lax（up.railway.app 在公開後綴清單上，別的 Railway 網站算跨站）；
# 這裡是第二道：瀏覽器標明 Sec-Fetch-Site: cross-site、或 Origin 不是本站，就直接 403。
# 沒帶這兩個標頭的（很舊的瀏覽器、伺服器對伺服器）放行——那種情況 SameSite 仍在
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _allowed_hosts(request: Request) -> set:
    from urllib.parse import urlparse
    hosts = {request.headers.get("host", ""), request.headers.get("x-forwarded-host", ""), request.url.netloc,
             os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")}  # Railway 自動提供的正式網域
    try:
        hosts.add(urlparse(settings.base_url).netloc)
    except Exception:
        pass
    return {h.lower() for h in hosts if h}


@app.middleware("http")
async def reject_cross_site_writes(request: Request, call_next):
    if request.method in _UNSAFE_METHODS:
        from urllib.parse import urlparse
        from fastapi.responses import JSONResponse as _JR
        site = (request.headers.get("sec-fetch-site") or "").lower()
        origin = request.headers.get("origin")
        bad = site == "cross-site"
        if origin is not None and not bad:
            netloc = urlparse(origin).netloc.lower() if origin != "null" else ""
            bad = netloc not in _allowed_hosts(request)
        if bad:
            logger.warning(f"擋下跨站寫入：{request.method} {request.url.path} origin={origin} sec-fetch-site={site or '-'}")
            return _JR({"detail": "請求來源不符，已拒絕"}, status_code=403)
    return await call_next(request)


app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(home.router, tags=["home"])
app.include_router(groups.router, prefix="/groups", tags=["groups"])
app.include_router(orders.router, tags=["orders"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(votes.router, tags=["votes"])
app.include_router(templates_router.router, tags=["templates"])

# 開發模式路由


@app.get("/")
async def root(request: Request, db: Session = Depends(get_db)):
    user, new_token = await get_current_user_optional(request, db)
    if not user:
        return templates.TemplateResponse(request, "login.html", {"request": request})
    
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
