# CLAUDE.md — SELA 快點來點餐（線上訂餐）

> **⚠ 給同時拿到 SELA-Starter-Kit 的 Claude：**
> 這是**已對齊 Kit V1.18.0 的成熟線上專案**（30 人團隊每日使用），不是新專案。
>
> 衝突仲裁規則：
> 1. **以本專案 CLAUDE.md 為主、Kit 為輔**
> 2. 本專案刻意不對齊 Kit 的部分：
>    - **不使用 Alembic**（Kit `tech-stack-lessons.md` 1.1 建議第一天就 `alembic init`） — 本專案已用「SQLAlchemy `create_all` + 手動 raw SQL 遷移 + `ADD COLUMN IF NOT EXISTS` 模式」運作超過一年，30 人線上穩定。改用 Alembic = 風險大於收益，且過去引入 Alembic 造成過部署失敗（坑 #1）。
>    - **PostgreSQL Enum 值固定大寫**（坑 #2 持續警戒）
>    - **logo 同時用兩套**：`app/static/images/sela-logo.jpg|svg`（4 個現有模板沿用中）與 `app/static/sela.svg` + `favicon/` 套組（Kit 標準，V1.1.0 已串接到 base.html `<head>`）。既有引用不動。
>    - **打包嵌入式中文字型** `app/static/fonts/cjk-font.ttf`（6MB，V1.14.1）— 核對單 PDF/PNG 需要嵌入字型才能 render 出中文，reportlab 內建 CID 字型不嵌入會導致 PNG 空白。這是必要資產，不是可移除的肥檔。
> 3. **不要為對齊 Kit 而動既有設計** — 已驗證的就是事實標準
> 4. 版號規則照 Kit（部署版無後綴、備份版 -source）
> 5. **下次完成版本時記得評估 SELA-handoff.md**（鐵律 #0 — 完整見 Kit master CLAUDE.md）
> 6. **優化體檢（對齊 Kit V1.18.0 時做）**：對照 `optimizations.md` 4 條 OPT，本專案無中招值得改項 — OPT-1（threading.Timer 排程）不適用（自動催單是前端提示+手動催單，非後端定時任務）；OPT-2/3/4（種子 JSON、outbox、自我驗證迴圈）情境不符。體檢通過，無需改 code。
> 7. **對齊歷程**：V1.0.0 首次對齊 Kit V1.9.0；V1.16.0 對齊升級至 Kit V1.18.0（更新此區塊 + 補回漏更新的開頭版本號 V1.13.3→V1.16.0 + 優化體檢 + app logo）。

> **這份文件是給下次 Claude 看的工作上下文，不是文件。**
> 判斷標準：下次 Claude 讀完，能不能直接動手？
> 維護章法見 `SELA-Starter-Kit/conventions/CLAUDE-MD-章法.md`，每次升版前複習。
> 每升一版至少更新三處：踩過的坑、版本歷程、下版候選工作。

---

## 〇、當前狀態

- **版本：** V2.8.0（審稿二修：超賣三路徑封堵＋部門權限＋收款最終應收）
- **狀態：** 上線中（30 人團隊每日使用）
- **線上網址：** https://online-drink-production.up.railway.app
- **一句話定位：** LINE Login 認證的團體飲料／餐點/團購訂餐系統，給彰濱秀傳特定團隊每日揪團用。
- **技術棧：** Python 3.11 + FastAPI 0.104.1 + Starlette 0.27.0 + SQLAlchemy 2.0.23 + PostgreSQL + Jinja2 3.1.2 + Tailwind（CDN）+ Alpine.js + HTMX + **Tabler Icons 3.17.0 webfont（jsDelivr CDN，V1.1.1）**
- **部署：** Railway（Dockerfile 模式，不用 Nixpacks）
- **認證：** LINE Login
- **圖片上傳：** Cloudinary
- **入口點：** `app/main.py`（FastAPI app + startup 事件處理 raw SQL 遷移）

---

## 一、技術棧決策（為什麼這樣選）

| 選擇 | 替代品 | 選這個的理由 |
|------|--------|------------|
| FastAPI | Flask、Django | 型別提示、自動 docs、async 友善、SELA 過去 6 個專案累積經驗 |
| Jinja2 + Tailwind CDN + Alpine + HTMX | React / Next.js | 30 人小規模、不需 SPA、SSR + 局部更新已夠用；零 build step |
| PostgreSQL | SQLite、MySQL | Railway 原生支援、Enum 型別、JSONB |
| **SQLAlchemy `create_all` + 手動 raw SQL 遷移** | Alembic | 已穩定運作超過一年；過去引入 Alembic 造成部署失敗，回滾後決定不再嘗試（坑 #1）。**這條與 Kit `tech-stack-lessons.md` 1.1 衝突，已在衝突仲裁區塊明寫理由。** |
| Railway（Dockerfile 模式） | Nixpacks、Heroku、自架 | Nixpacks 曾多次建置失敗，改 Dockerfile 後穩定（坑 #3） |
| LINE Login | Google OAuth、自家帳密 | 使用者已是 LINE 重度用戶、認證流程最短 |
| Cloudinary | S3、本地 + nginx | 免費額度足夠、Railway 不需設置 |
| **`requirements.txt` 用 `==` 鎖死版本** | `>=` 浮動版本 | 2026-05-28 因浮動版本 + Railway 自動 rebuild 抓到 starlette 新版而炸過（坑 #10），改為鎖死 |

> 改技術棧 = 大版本升級。改了記得回頭更新這張表，並在「八、升版必讀」開 ⚠ 章節。

---

## 二、業務對映表

| 業務概念 | 程式實作 | 改這個動哪 |
|---------|---------|-----------|
| 「店家」 | `Store`、`StoreBranch`、`StoreOption`、`StoreTopping` | `app/models/store.py` + `routers/admin.py` |
| 「菜單」 | `Menu`、`MenuCategory`、`MenuItem` | `app/models/menu.py` + import 流程 `services/import_service.py` |
| 「團單」（核心業務概念） | `Group` | `app/models/group.py`、`routers/groups.py`、`templates/group_*.html` |
| 「訂單」 | `Order`、`OrderItem` | `app/models/order.py`、`routers/orders.py` |
| 「飲料／餐點／團購」分類 | `CategoryType` Enum（**PostgreSQL 大寫**：`DRINK`/`MEAL`/`GROUP_BUY`） | `app/models/store.py` 的 Enum 定義；**改動要連改三處**：model、Pydantic schema、PostgreSQL `ALTER TYPE` |
| 「三狀態訂單」 | `OrderStatus` Enum：`DRAFT`／`SUBMITTED`／`EDITING` | `app/models/order.py` |
| 「Taipei 時區顯示」 | `taipei` Jinja filter | **每個 router 自己註冊**（坑 #6） |

> 改這張表 = 動 model + Pydantic schema + 前端解析 + Raw SQL 四處，務必同步（坑 #1 三方對齊原則）。

---

## 三、關鍵檔案路徑

| 想改什麼 | 動哪些檔 |
|---------|---------|
| 啟動順序 / 自動遷移邏輯 | `app/main.py` startup 事件 |
| 環境變數 / 設定 | `app/config.py`（Pydantic Settings） |
| 資料庫連線 | `app/database.py` |
| LINE Login 流程 | `app/routers/auth.py` + `app/services/auth.py`（JWT） |
| 後台店家／菜單管理 | `app/routers/admin.py` + `templates/admin/*.html` |
| 團單建立／詳情／關團 | `app/routers/groups.py` + `templates/group_*.html` |
| 訂單 CRUD | `app/routers/orders.py` + `routers/orders_extra.py` |
| JSON 匯入 | `app/services/import_service.py` |
| Cloudinary 上傳 | `app/routers/admin.py`（圖片相關端點） |
| 首頁 / 訂單牆 | `app/routers/home.py` + `templates/home.html` + `templates/partials/order_wall.html` |
| Railway 設定 | `railway.toml`（builder=dockerfile）、`Dockerfile`、`start.sh` |
| 依賴版本（**鎖死**，坑 #10） | `requirements.txt` |
| 部署排除清單 | `.gitignore`（V1.0.0 對齊 Kit 模板） |

---

## 四、踩過的坑（編號累積，永不重排）

> **三段式**：症狀 → 原因 → 做法。
> 環境/語法類放前面，業務邏輯類放後面。

1. **Alembic 在 Railway 部署造成失敗**
   - 症狀：`railway.toml` startCommand 包含 `alembic upgrade head` 時，部署多次 timeout 或 schema 衝突；引入 alembic 套件導致 build 變慢且偶發失敗
   - 原因：本專案 schema 演進量小、SELA 一人開發、Railway cold start 對額外指令敏感
   - 做法：**完全不用 Alembic**；`requirements.txt` 不裝 alembic；schema 變更走 `app/main.py` startup 事件內的 raw SQL（`ADD COLUMN IF NOT EXISTS` / `ALTER TYPE ... ADD VALUE IF NOT EXISTS`）。**與 Kit FastAPI 預設衝突，已在衝突仲裁區塊明寫。**

2. **PostgreSQL Enum 大小寫陷阱**
   - 症狀：`invalid input value for enum categorytype: "drink"`
   - 原因：PostgreSQL Enum 值是大寫（`DRINK`/`MEAL`/`GROUP_BUY`），但表單常送小寫
   - 做法：**永遠用大寫值**；新增 Enum 值用 raw SQL：`ALTER TYPE categorytype ADD VALUE IF NOT EXISTS 'GROUP_BUY'`；後端收到表單值要先 `.upper()`

3. **Railway Nixpacks 建置失敗**
   - 症狀：部署時 Nixpacks 階段卡住或失敗
   - 原因：Nixpacks 偵測機制對本專案某些依賴不穩定
   - 做法：`railway.toml` 設 `builder = "dockerfile"`、移除 `startCommand`；提供 `Dockerfile` + `start.sh`（已就位）

4. **檔案 UTF-8 編碼問題造成 JSON 匯入失敗 / build 失敗**
   - 症狀：`stream did not contain valid UTF-8` 或 `Expecting value: line 1 column 1`
   - 原因：菜單 JSON 檔被某些編輯器存成 BOM 或非 UTF-8；Python 檔案有 BOM
   - 做法：**不要手動編輯菜單 JSON**，用程式產生；所有 `.py` 確認 UTF-8 無 BOM

5. **SQLAlchemy Model 重複定義錯誤**
   - 症狀：`Table 'xxx' is already defined for this MetaData instance`
   - 原因：某些情境下 Model 會被載入兩次
   - 做法：必要時 model 加 `__table_args__ = {'extend_existing': True}`

6. **Jinja2 filter `taipei` 找不到**
   - 症狀：`No filter named 'taipei'`
   - 原因：filter 註冊在某個 router 的 Jinja2Templates 實例上，其他 router 的實例沒註冊
   - 做法：**每個 router 自己 import 並註冊 taipei filter**（不要共用 templates 實例 — 與 Kit `tech-stack-lessons.md` 1.1 第 6 條建議相反，但本專案歷史已成形，重構成本大於收益）

7. **FastAPI Router prefix 與 path 同時為空**
   - 症狀：`Prefix and path cannot be both empty`
   - 原因：`router = APIRouter()` + `@router.get("")` + `include_router(router)` 三個都空
   - 做法：至少一個要有值，通常 path 用 `/`

8. **patch 把 `joinedload` 從錯的模組 import**
   - 症狀：執行時 `AttributeError`（已被記錄在 Kit `cross-project-pitfalls.md` 第 142 行）
   - 原因：曾從 `sqlalchemy.ext` 誤匯入，正確是 `sqlalchemy.orm`
   - 做法：`from sqlalchemy.orm import joinedload`

9. **菜單分類目前不支援 `group_buy`**
   - 症狀：JSON 匯入時 `Input should be 'drink' or 'meal'`
   - 原因：Pydantic schema 還沒開放 `group_buy` 給匯入端點
   - 做法：團購店家先用 `meal` 匯入，再到後台手動改 category；下版可考慮放開

10. **`requirements.txt` 浮動版本造成 Starlette 新版破壞 API**（⚠ **強烈建議回流 Kit**）
    - 症狀：2026-05-28 Railway 自行 rebuild 時，所有 HTTP 請求 500；log 顯示 `TypeError: unhashable type: 'dict'`，發生在 jinja2 `_load_template`，呼叫處是 `templates.TemplateResponse("login.html", {"request": request})`
    - 原因：`requirements.txt` 全部用 `>=` 沒鎖版本。Starlette 在 0.32+ 改了 `TemplateResponse` 位置參數順序（request 變第一個），舊寫法 `TemplateResponse("name.html", {"request": request})` 失效 — 新版把字串當 request、把 dict 當 template name；jinja2 拿 dict 當快取 key 就拋 unhashable
    - 影響範圍：全專案 27 處 `TemplateResponse` 都是舊寫法
    - 做法（已套用）：**`requirements.txt` 全部改 `==` 精確版本**，鎖在 2023 年版（starlette==0.27.0 + fastapi==0.104.1 + jinja2==3.1.2 等）。Railway fallback 機制保留舊 container，所以 rebuild 失敗時服務沒中斷，但下次重啟若沒 fallback 就會真壞
    - 長期方案：下版改 27 處為新 API `templates.TemplateResponse(request, "name.html", {...})`，再放寬版本鎖

11. **cdnjs 的 `tabler-icons` 是 2020 年舊 package（不是 webfont），同名 package 跨 CDN 不等價**
    - 症狀：V1.1.0 部署後底部導航 5 個 `<i class="ti ti-xxx">` 全部空白，但中央橘色圓圈與文字標籤都還在
    - 原因：V1.1.0 我把 CDN URL 寫成 `cdnjs.cloudflare.com/ajax/libs/tabler-icons/3.7.0/tabler-icons.min.css`，但 cdnjs 上的 `tabler-icons` 是 2020 年舊 package（500 圖示，純 SVG 不是 webfont），且 3.7.0 這個版本號根本不存在於 cdnjs。CSS 404 → 字體未載 → `<i>` 是空 inline 元素就看不到
    - 做法（V1.1.1 hotfix）：改用 jsDelivr 官方 webfont package — **`https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.17.0/dist/tabler-icons.min.css`**。**URL 必須含 `/dist/`**（這是 tabler-icons GitHub issue #1225 的官方確認），少了會 404
    - 教訓 1：**同名 package 跨 CDN 可能是完全不同的東西**。`cdnjs/tabler-icons` ≠ `jsDelivr/@tabler/icons-webfont`
    - 教訓 2：**用第三方 webfont CDN 前 web_fetch 驗證一次再貼**
    - **建議回流 Kit：** 「webfont / icon library 起手必做：用 jsDelivr 不要 cdnjs，URL 先 fetch 驗證」

12. **base.html 401 redirect 寫死錯誤 endpoint `/login`，但實際是 `/auth/login`**（潛伏 bug，V1.1.2 hotfix）
    - 症狀：使用者用無痕視窗 / 新瀏覽器 / 過期 session 訪問 `/home` 等需登入頁面 → 401 → htmx error handler redirect 到 `/login?next=...` → 404 Not Found（FastAPI 預設 JSON 錯誤頁）
    - 原因：base.html 第 57/157/164 行 hardcode 寫 `'/login?next=' + ...`，但 main.py 第 270 行：`app.include_router(auth.router, prefix="/auth", ...)`，auth.py 第 20 行 `@router.get("/login")` → 真實 endpoint 是 `/auth/login`
    - 為什麼長期沒被發現：30 人都用已登入的 cookie 持續 heartbeat，從來沒被 401 踢過。一般訪客流程是直接訪問 `/` → `main.py @app.get("/")` 直接 render `login.html`，不走 `/login` 這個路由
    - 觸發條件：無痕視窗、清 cookie、session 過期、JWT 失效
    - 做法（V1.1.2 hotfix）：把 base.html 3 處 `'/login?next=` 全改成 `'/auth/login?next=`
    - 教訓：**hardcode 的 URL 字串要與 `main.py` 的 `include_router(prefix=...)` 對齊**。可考慮用 FastAPI `request.url_for("login")` 反查 endpoint，避免字串對不上

13. **flex 排版中子元素高度不一致 → flex items-center 把它們各自垂直置中後，文字底線錯位**（V1.2.0 修正）
    - 症狀：底部導航 5 個項目視覺上「圖示對齊但文字高低不一」
    - 原因：「首頁」圖示有 `w-9 h-9 bg-sela-50` 容器（36px 高），其他 4 個是裸 `<i>`（24px 高）。`<nav class="h-14 flex items-center justify-around">` 把每個 `<a>` 區塊垂直置中 — 區塊高度不同 → 各自置中後文字 y 位置就不同
    - 做法：所有圖示都包在相同尺寸的 `w-9 h-9 flex items-center justify-center` 容器內，active 才填底色（`bg-sela-50`）。所有 `<a>` 區塊等高 → 文字底線一致
    - 通用原則：**flex 排版中要求子元素「視覺對齊」時，務必讓所有子元素總高度一致**，不能靠 padding 或 margin 補。差別在容器級別，不在內容級別

14. **未登入直接開需登入頁面 → 顯示 401 JSON 而非導向登入頁**（坑 #12 的後端版，V1.4.1 修正）
    - 症狀：新使用者用沒登入過的手機/瀏覽器直接訪問 `/home`（或任何需登入頁）→ 看到 `{"detail":"請先登入"}` JSON，無法進到 LINE 登入畫面
    - 原因：`services/auth.py` 的 `get_current_user` 未登入時 `raise HTTPException(401, "請先登入")`。瀏覽器 GET 請求時 FastAPI 把它轉成 JSON 回應，不會 redirect
    - 與坑 #12 的關係：坑 #12 修的是「htmx 背景請求 401」（base.html JS handler），這條修的是「瀏覽器直接 GET 需登入頁」（後端例外處理）。兩條是同一問題的前端 / 後端兩面
    - 做法（V1.4.1）：在 `main.py` 加全域 `@app.exception_handler(StarletteHTTPException)`：401 + 非 htmx + `Accept: text/html` → `RedirectResponse('/auth/login?next=...')`；其他維持 JSON
    - 判斷依據：`HX-Request` header 區分 htmx，`Accept` header 區分瀏覽器 vs API
    - 教訓：**SSR 應用的「需登入」保護要區分請求來源** — 瀏覽器要 redirect、API/htmx 要 JSON。單純 raise 401 只對 API 友善，對直接開頁面的使用者是死路

15. **底部導航 active 狀態 hardcode 寫死「首頁」恆亮**（V1.5.0 修正）
    - 症狀：不論在哪一頁（投票 / 回報 / 我的），底部導航都只有「首頁」是橘色 active 樣式
    - 原因：base.html 底部導航的「首頁」永遠帶 `text-sela-600` + `bg-sela-50`，其他永遠 `text-gray-400`，沒有依當前頁判斷
    - 做法（V1.5.0）：在 nav 開頭 `{% set path = request.url.path %}`，4 個項目各設 active 布林（`path == '/home'` / `path.startswith('/votes')` 等），class 用 `{{ 'xxx' if active else 'yyy' }}` 三元判斷。子頁用 `startswith` 一併涵蓋（如 /votes/123 也算投票 active）
    - 注意：`request` 在 template 內必須可用 — SELA 所有頁面都經 `TemplateResponse(request, ...)` 傳入，所以 `request.url.path` 全頁可用

16. **換主色只改色階定義不夠 — 全站 hardcode 的 Tailwind 內建色 class 不會跟著變**（V1.6.1 修正）
    - 症狀：V1.6.0 把 `sela-*` 色階從橘換藍紫後，仍有大量按鈕 / 數字 / 標籤是橘色（個人資料儲存鈕、發布公告、發起投票、標記已處理、部門新增、店家篩選等）
    - 原因：開發歷程中部分元件用 `sela-*`（自訂色階，會變），部分直接用 Tailwind 內建 `orange-*`（固定橘，不受色階定義影響）。改色階只影響前者
    - 範圍：40 檔 237 處 `orange-*`
    - 做法（V1.6.1）：regex `-orange-(\d+)` → `-sela-\1` 全站替換；色階補 800/900 對應 orange 深階；保留 `amber-*`（分類語義色）
    - 教訓：**換主題色前先全站 grep `orange-` `amber-` `red-` 等內建色 class**，確認哪些是「該跟主色變的主視覺」、哪些是「語義色該保留」。只改自訂色階會漏掉所有 hardcode 內建色的地方
    - 預防：理想上整個專案的主視覺色都該走同一個自訂色階（`sela-*`），不要混用 Tailwind 內建 `orange-*`

17. **菜單「版本號」誤用全域主鍵 `Menu.id`**（V1.8.1 修正）
    - 症狀：新建店家的第一份菜單顯示「版本 #29」之類的大數字；同店多版本跳號（#5 / #18 / #29）
    - 原因：menus.html 顯示 `版本 #{{ menu.id }}`，但 `Menu.id` 是全資料表自增主鍵（跨所有店家累加），不是「這家店的第幾版」
    - 做法（V1.8.1）：menu_list 路由算店內序號 `menu_versions = [(menu, total - idx) for idx, menu in enumerate(menus)]`（menus 是 created_at desc，所以最新序號=總數、最舊=1），template 顯示「第 N 版」
    - 教訓：**呈現給使用者的「序號 / 編號」不要直接用 DB 主鍵** — 主鍵是全域的、會跳號、洩漏其他資料量。要的是「在這個範圍內的第幾個」就現場 enumerate

18. **刪父資料時，子資料的多個外鍵都要一起斷，否則 flush 撞 NOT NULL**（V1.10.0 經驗）
    - 情境：刪店家改成「斷開團單連結但保留團單」。原本只斷 `group.store_id=None`，但團單還有 `menu_id` 指向該店菜單；刪 menu 時 SQLAlchemy 想把 `group.menu_id` 設 NULL，撞上 menu_id NOT NULL → IntegrityError
    - 解法：(1) `store_id` 和 `menu_id` 都改 nullable；(2) 斷開時兩個都設 None；(3) 用 `with db.no_autoflush:` 包整段，並在斷開後手動 `db.flush()`，再刪 menu/store，避免自動 flush 在錯的時間點觸發
    - 通用原則：**改「保留子資料、刪父資料」的軟參照前，先列出子資料所有指向父資料樹的外鍵**，每一條都要 nullable + 斷開。漏一條就會在 flush 時爆
    - 顯示層配套：加 `xxx_display_name` property（關聯在用關聯、不在用快照欄位），模板全改用它，且 `if obj.relation and obj.relation.field` 防 None
    - **完整關聯鏈（V1.10.0 實際踩到三層）**：刪 store 牽動的不只 group，還有整條 store→menu→menu_item→order_item（NOT NULL）、menu_item→item_option→order_item_option（NOT NULL）。第一次只處理 group→store/menu，部署後 PostgreSQL 才爆 `order_items.menu_item_id NOT NULL`（SQLite 本地測試較寬鬆沒抓到，PostgreSQL 才嚴格）。**教訓：本地 SQLite 測過 ≠ PostgreSQL 安全，NOT NULL/FK 約束 PostgreSQL 更嚴**
    - **最終解法**：放棄 ORM 逐層 delete（cascade flush 時序難控），改用 **raw SQL 依「子→父」順序** UPDATE 斷開所有 FK（order_items.menu_item_id、order_item_options.item_option_id、order_item_toppings.store_topping_id、groups.store_id/menu_id）再 DELETE 菜單樹與店家。訂單明細靠既有「冗餘存儲」快照欄位（item_name/unit_price/option_name/price_diff/topping_name/price）保留完整可讀的歷史
    - 需改 nullable 的欄位總清單：groups.store_id、groups.menu_id、order_items.menu_item_id、order_item_options.item_option_id（order_item_toppings.store_topping_id 原本就 nullable）

19. **`<i>` 圖示標籤塞進「會被當純文字的位置」→ 畫面顯示原始 HTML 字串亂碼**（V1.11.0 修正）
    - 症狀：emoji 換 Tabler `<i class="ti ...">` 後，某些地方畫面直接顯示 `<i class="ti ti-alarm"></i>` 這串文字而非圖示（如團單頁倒數計時旁）
    - 原因：這些位置會把內容當純文字、不渲染 HTML：(a) Alpine `x-text`（安全機制只填文字）、(b) JS `element.textContent`（同理）、(c) JS `confirm('...')` 對話框（純文字視窗）、(d) Jinja2 `{{ }}` autoescape（HTML 被轉義成 `&lt;i&gt;`）
    - 修法對照：
      - `x-text="display"`（display 含 `<i>`）→ HTML 固定放 `<i>` + 旁邊 `<span x-text="display">`，JS 字串只留文字
      - `el.textContent = '<i>'` → `el.innerHTML = '<i>'`（程式控制的固定字串無 XSS 風險才可）
      - `confirm('<i> 確定…')` → `confirm('確定…')`（純文字視窗，圖示無意義，直接拿掉）
      - Jinja2 `{{ ['<i>'][x] }}` → 直接寫 `<i>` 標籤（autoescape 只作用在 `{{ }}` 內的值）
    - 教訓：**全站 emoji→`<i>` 替換時，凡是 emoji 原本在 JS 字串、x-text、confirm、或會 autoescape 的 `{{ }}` 內，不能直接換成 `<i>` 標籤** — 要改該位置的渲染方式。批次替換後務必 grep `\`<i class` / `"<i class` / `textContent.*<i` / `x-text.*<i` 複查
    - **另注意純文字匯出**：`export_service.py` 產生的是給店家複製到 LINE 的純文字訊息，裡面的 emoji（💰🚗👥⚠️）**要保留**，不可換 Tabler `<i>`（純文字訊息裡會變字面亂碼）

20. **同一筆金額有兩條計算路徑，改了一條沒同步另一條 → 對帳不符**（使用者回報，V1.11.2）
    - 症狀：使用者回報「個人明細金額與店家明細金額不同」
    - 根因：金額有兩個產生函數。`OrderItem.subtotal`（個人明細用）= `(unit_price + options_total + toppings_total) * quantity` 含加料；但 `generate_order_text`（店家明細）自己重算成 `unit_price + options_total`，**漏了 toppings_total**。有人點加料時兩邊就差加料費
    - 修：店家明細補 toppings_total，並把加料納入彙總 key
    - 通用原則：**同一個金額概念只該有一個 single source of truth**。OrderItem.subtotal 已是權威算法，匯出 / 統計 / 顯示都應呼叫它，而非各自重算。各自重算遲早因為新增欄位（如後加的 toppings）而不同步。未來若再有金額計算，先找有沒有現成 property 可用

21. **用 HSL 重組生成色階會讓主色偏色**（V1.13.2 修正）
    - 症狀：使用者指定主色 #710ced，但實際生成的 500 階是 #662ab0（偏暗偏濁），色票一比就看出落差
    - 原因：生成色階時用 colorsys 把指定色拆成 HSL，只保留 hue，明度/飽和度用自訂的 scale_config 數值重算 500 階 → 等於「重新調過」使用者的顏色，而非直接用
    - 修法：**500 階（主色）必須是使用者指定的 hex 原值，不經任何轉換**。其餘深淺階用「原色 ↔ 白 / 黑 線性混合」（`mix(target, white, t)` / `mix(target, black, t)`）生成，這樣同色相、只變明暗，不會偏色
    - 通用原則：換主題色時，使用者給的那個 hex 必須在成品裡一字不差地出現（500 階）。要驗證就 grep `500: '#XXXXXX'` 確認 == 指定值。淡濃階可以算，主色不能算

23. **reportlab 畫色塊要算「往哪個方向長」；render PNG 別只抓第一頁**（V1.19.4 修正，使用者截圖回報）
    - 症狀一：核對單店家總項有店家優惠時，「店家優惠 -$X」那行被底下「實收」紫色塊蓋掉一半
    - 根因一：reportlab y 軸向上為正。實收紫條用 `c.rect(x, y-1mm, w, 8mm)`（從 `y-1mm` 往**上**長到 `y+7mm`），但畫完折扣文字只 `y -= 6mm`。6mm < 7mm，紫條上緣就吃進折扣文字。修：`y -= 10mm`（間距須 > 紫條上探的 7mm）
    - 症狀二：人多時核對單 PNG 只剩第一頁，每人明細整段不見
    - 根因二：`generate_receipt_png` 寫死 `pdf[0]`，多頁 PDF 只 render 首頁。修：迴圈 render `len(pdf)` 頁、白底等寬置中直向拼成一張長圖（團主貼 LINE 用，單張最方便）
    - 通用原則：(a) 用 `c.rect` 畫底色塊前，先想清楚它是從錨點往上還往下長、會佔到 baseline 上方多少，間距要 > 那個量才不蓋字。(b) 凡是「PDF → 圖」的轉檔，預設 PDF 可能多頁，一律掃 `len(pdf)` 全頁，別假設只有一頁

---

## 五、煙霧測試（可貼上執行）

> 每次升版前必跑。**打包成 zip 前所有指令必須全綠**。

```bash
# === 語法檢查（所有 router）===
python -c "import ast; [ast.parse(open(f).read()) for f in __import__('glob').glob('app/**/*.py', recursive=True)]"

# === Import 測試（含路由註冊驗證）===
python -c "from app.main import app; print(len(app.routes), 'routes')"

# === 啟動測試（5 秒後自動結束）===
timeout 5 uvicorn app.main:app --host 0.0.0.0 --port 8001 || true

# === 找漏掉的 debug / TODO ===
grep -rn "console.log\|print(\|TODO\|FIXME" app/ || true

# === 確認 .gitignore 涵蓋機密 ===
git check-ignore .env 2>/dev/null && echo "✅ .env 已忽略" || echo "❌ .env 未忽略"

# === 確認 requirements.txt 不含 alembic（坑 #1）===
grep -i "alembic" requirements.txt && echo "❌ 不該有 alembic！" || echo "✅ 沒 alembic"

# === 確認 railway.toml startCommand 不含 alembic（坑 #1）===
grep -i "alembic" railway.toml && echo "❌ 不該有 alembic！" || echo "✅ 沒 alembic"

# === 確認 requirements.txt 全部鎖版本（坑 #10）===
grep -E "^[a-zA-Z].*>=" requirements.txt && echo "❌ 有 >= 沒鎖版本！" || echo "✅ 全部鎖版本"
```

---

## 六、版本歷程（最近 6-10 版）

| 版本 | 重點 |
|------|------|
| V2.8.0 | **審稿二修（V2.7 代購審查，P0×4＋P1×4＋P2×2）**。**P0 超賣封堵**：(1) 同單多列同品項——submit 改「依 menu_item_id 彙總後比對」（原逐列各自過檢，3+3 可破上限 5）。(2) 併發超賣——submit/還原交易內 `SELECT FOR UPDATE` 鎖定涉及品項（固定依 ID 排序防死鎖；SQLite no-op 無害），資料庫層保證先送先贏。(3) 佔用口徑改**方案 A：SUBMITTED＋EDITING 皆佔**（進修改不失去已搶到的限量品；減量/刪除仍即時釋放＝「改單會回」）；`_stock_remaining` 加 `exclude_order_id` 防自身重複計算；取消修改還原前重驗庫存（修改中刪掉限量品又被搶走時 400「僅剩 N 份無法完整還原」）；顯示 stock_used 同口徑。(4) **部門限定團權限**：`is_visible_to` 落實到團詳情＋orders 全入口（`_ensure_visible` 共 8 處），不再只靠畫面隱藏。**P1**：(5) 修改快照補存 `fulfillment/fulfilled_backup_priority/diff_settled`，還原時依**順位**重連新候補 id（舊 id 會變）。(6) 缺貨處理限截止後（POST 硬擋 400＋面板鎖定提示）。(7) 收款總覽有換貨時列「原訂應收→補收/退還→**最終應收**（=Σactual_self_pay+運）」，每人頂行直接顯示換貨後金額（原額括注）。(8) 品項上限不可低於已佔量（400 提示）。**P2**：(9) `upload_image` 前置驗證——JPG/PNG/WebP 白名單＋5MB 讀取階段拒絕＋失敗明確 400（原本靜默回 None 品項照建）。(10) 品名 1-100/說明 ≤200/價格 str→Decimal 直轉且 1~100 萬/庫存 1~99999＋前端 maxlength。(11) 核對單標示「原始品項・換貨結果見收款明細」。**待辦沿用**：核對單/Excel 改用 actual 出貨鏈。教訓：**「先查再送」不是庫存機制**——彙總、鎖、排除自身、還原重驗四件缺一不可；佔用口徑改動要同步 helper/顯示/送出/還原四處。 |
| V2.7.0 | **新功能：代購（團主自訂品項）**。討論定案：品名/價格/說明/圖片（選填）＋數量上限（選填）＋團 icon；隨時可加可改（已送出吃快照）；先開團再加品項；**庫存佔用＝送出才算**。(1) **架構：重用不另起爐灶**——代購團＝自動建「個人店家」（`Store.is_personal`＋`owner_user_id`，每人一家，隱藏）＋每團一份菜單（`is_active=False` 不干擾一般邏輯，**必帶一個 MenuCategory** 否則菜單渲染不出品項）；`category=GROUP_BUY`＋`store.is_personal` 判斷代購，**避開 PostgreSQL enum 加值的坑**（不動 enum）。上限/折扣/補助/候補/缺貨處理/收款明細全部原地生效。(2) **Model**：MenuItem 加 `description/image_url/stock_limit/is_available` 四欄（通用欄位，未來正式菜單也能用）；遷移共 6 欄。(3) **開團**：類別四選一加「代購」（`is_proxy` hidden input、店家選單隱藏＋`:required` 動態解除、後續設定區 `storeId||proxy` 放行）；create_group 分支建個人店家＋菜單＋分類。(4) **管理品項**：團主工具第一顆（深色、代購團限定）→ 底部 sheet（`partials/proxy_items_panel.html`，htmx multipart 自刷新）：團 icon 上傳（＝個人店家 logo，首頁團卡/團頁自動生效）、新增表單（品名/價格/說明/上限/圖片）、品項列表 details 展開改/下架（下架有 confirm、可重新上架）；圖片走 `upload_service.upload_image`（Cloudinary，folder sela/items、sela/proxy）。路由 5 支限團主/管理員＋is_personal。(5) **庫存（推導式，不存狀態）**：`_stock_remaining` = stock_limit − Σ(已送出該品項數量)；**修改模式＝暫時釋放、重新送出＝重佔**（改單會回自動成立）；檢查點 5 處——加入（含售完/下架訊息）、改量（僅增加時檢查差額）、跟點、複製上次（**過濾非本團菜單/已下架＋數量封頂**，代購每團菜單不同、舊 menu_item_id 會漏進來的潛在洞順手補掉）、**送出權威檢查**（先送先贏）。(6) **團員端**：menu_item 全重寫——縮圖/說明/「剩 N」琥珀徽章（≤5 才顯示）/完售 disabled/已下架隱藏；客製視窗 + 鈕封頂到 remaining。(7) **個人店家過濾**：首頁店家列表×2、開團店家來源、一般店家清單、後台列表＋計數（`is_personal != True` NULL 安全）。教訓：**批次腳本任一 assert 失敗＝整段未寫入（全有或全無），錨點必須先 grep 實文**（跟點註解「已結單」沒被 V2.6 用語清掃改到、fastapi import 順序不同都踩過）；**py_compile 不驗 import 名稱**，新用 UploadFile/File 要 AST 驗證 import。 |
| V2.6.0 | **UX 收尾（審稿第三部分五項）**。(1) **團主首頁待處理狀況**：「我的進行中」中自己開的開放團加狀態列——「已送出 N・M 未送出・$總額」＋**「催單」一鍵複製**（【團名】MM/DD HH:MM 結單＋連結＋還有 N 位點了還沒送出，複製後 toast 提示貼 LINE 群；inline onclick 含 preventDefault/stopPropagation 因按鈕在 `<a>` 內，且該區無 x-data 故不用 Alpine）。(2) **結單前確認摘要**：確定結單加 `hx-confirm`「送出訂單？共 N 件、$X、M 件已填候補」（Jinja 伺服端算好，零 JS）。(3) **狀態全站統一**：人的狀態一律 **未送出（奶）／修改中（琥珀，原誤用 sela）／已送出（綠）**——修了 my_order 徽章（原「已結單」）、首頁徽章、group_card（原「點餐中」）、資訊卡狀況行（原「尚未送出」）、訂單牆標題、加點 confirm 文案、收款明細（「N 人已送出」「【未送出】」）、後台團單列表與使用者詳情；「結單」一詞保留給**團**（結單時間/提早結單）。(4) **複製上次訂單防覆蓋**：後端 copy_last 加 `mode`（replace/append）＋**已送出防護 400**（原本會靜默清空已送出訂單的品項！）；前端購物車有品項時彈三選一浮層（取代／加入保留現有／取消），空車直接複製。(5) **匯出入口依用途分組**：傳給店家（點餐彙總・含候補對照）／現場核對（核對單 PDF/圖片）／收款與留存（收款明細＝向大家收錢、Excel＝存檔），「店家明細/個人明細」等模糊名稱走入歷史。仍待辦：候補列進核對單 PDF、Excel 套折扣/自付欄。 |
| V2.5.0 | **缺貨處理模式（審稿第二部分・候補功能後半）**。原則：**原訂單完整保留，出貨結果另記**，補退金額走既有折扣＋補助鏈自動算。(1) **Model**：OrderItem 加 `fulfillment`（NULL=正常／substituted=已換候補／unavailable=缺貨未出）、`fulfilled_backup_id`、`diff_settled`（補退結清）；actual 金額鏈鏡射既有三屬性——`actual_subtotal`（換候補=候補單價×量、缺貨未出=0）→ `actual_total/final/self_pay` → **`settle_diff` = actual_self_pay − self_pay**（>0 補收、<0 退還，**含折扣與補助效果**：兩者都在上限內時補退 $0 公司吸收，與「沒用到上限不退錢」一致；驗證 170→155 上限 140 = 退 15、120→100 = $0）。(2) **團主操作**：團主工具加「缺貨處理」→ 底部 sheet（htmx 自刷新面板 `partials/fulfillment_panel.html`）：**依品項名(尺寸)分組**（店家說什麼缺貨就展開那組），每人一列，未處理→候補按鈕（含整筆價差）＋「缺貨不出」（confirm、不收費）；已處理→結果標籤＋此人補/退金額＋**未結清/已結清切換**＋還原。路由 `GET/POST /groups/{gid}/fulfillment[/{item_id}]`（限團主/管理員，動作：backup/unavailable/reset/toggle_settled，候補歸屬驗證）。(3) **團員視角**：我的訂單品項顯示「已換：青草茶」綠標／缺貨未出劃線標；合計下方顯示「換貨後實際金額 $X・需補/退 $Y」。(4) **收款明細**：每人附換貨行（✕ 原品項 → 已換候補N／缺貨未出不收費）＋「換貨後應付 $X，需補收/退還 $Y（已/未結清）」；總覽加**【換貨統計】N 人有換貨：補收合計/退還合計/未結清人數**。遷移：order_items 三欄。至此候補閉環：填候補（V2.4）→ 店裡照單換（點餐文字對照表）→ 回來逐筆記錄＋補退追蹤（V2.5），團主不用再三邊核對。 |
| V2.4.1 | **審稿修正（8 項必修）**。外部程式審查抓出的問題全數修正：(1) **修改快照不完整**（最嚴重）：進入修改模式的 snapshot 原本只存品項+選項，漏存**加料與候補**→「取消修改」還原後加料/候補憑空消失且金額變少；快照補齊 toppings/backups 兩段、還原時重建，舊快照用 `.get(,[])` 向下相容。(2) **品項菜單歸屬**：add_item 的 MenuItem 查詢加 `menu_id == group.menu_id`，防跨店/舊菜單品項注入。(3) **加購/加料歸屬**：兩個分支（一般+候補）都驗證 `ItemOption.menu_item_id == menu_item.id`、`StoreTopping.store_id == group.store_id`，不合法**明確 400** 而非靜默略過（原本會出現金額與名目不符的訂單）。(4) **跟點**：來源品項限「本團+已結單」（原本可跨團複製任意 item_id）；已結單者跟點不再靜默改 EDITING（無快照，取消修改會炸）→ 400 提示先按修改訂單。(5) **折扣文字**：「95 折」語意混淆（台灣慣用 95 折=付 95%，但顯示易誤讀）→ 全面改「95%（九五折，付原價的 95%）」：資訊卡/設定 modal（標籤改「折後百分比」）/購物車合計/收款明細。(6) **團總額一致性**：`Group.total_amount` 由 `o.total_amount` 改 `o.final_amount`（套整單折扣），**連動修正請客 TreatRecord 金額**與已結單牆總額（原本請客者被記原價）。(7) **外送費餘數分配**：收款明細改精確分配——`base=fee//n`，餘數 r 依姓名排序前 r 位 +1 元，**總和恰等於外送費**（$100/3人→34/33/33）；資訊卡顯示加「約」。(8) **輸入驗證**：quantity 後端限 1-99；`backup_for` int 轉換 try/except → 400。教訓：**快照/複製類邏輯必須涵蓋「品項的所有子結構」**（選項+加料+候補），新增子結構時要 grep 所有 snapshot/copy 點同步；**關聯 ID 一律驗證歸屬**，不能只查存在。待辦（審稿二、三部分）：缺貨處理模式（候補確認/標記）、待處理中心等 UX，另版開發。 |
| V2.4.0 | **新功能：缺貨候補（資訊型・完整客製・價差提醒）**。討論定案：資訊型（候補是給團主的換貨指示，系統金額不自動變，價差人工補退但單據算好）／單品層級／候補可完整客製（糖冰尺寸加料）。(1) **Model**：Group 加 `enable_backup BOOLEAN` + `backup_count INTEGER 1-3（預設2）`；新表 `order_item_backups`（order_item_id/priority/menu_item_id/品名尺寸糖冰快照/extras_text 加料摘要/unit_price 每份含加料總價快照），OrderItem.backups cascade delete-orphan（刪團 FK 鏈由 ORM cascade 涵蓋）；新表由 create_all 自動建、Group 兩欄走啟動遷移。(2) **零新介面的填寫流程**：購物車品項下「＋缺貨候補(n/max)」虛線鈕（enable_backup＋可編輯時）→ `startBackup()` 進候補模式（關購物車、頂端深咖啡 sticky 提示條含取消）→ 點菜單開**同一個客製視窗**（頂部多候補標示條、數量列隱藏改「跟隨主品項」、送出鈕變「設為候補 N」）→ 表單多 hidden `backup_for`，**同一個 add_item 端點分支處理**（驗證歸屬/可編輯/上限，計每份總價=尺寸價+加購+加料，存快照，回傳同 partial）；`afterAddItem` 分支：候補完成→重開購物車+toast。(3) **顯示**：購物車候補虛線標籤（順位+名稱+糖冰+**價差** +$需補琥珀/-$需退綠、× 刪除→`DELETE /orders/backups/{id}` 刪後重排順位）；已結單唯讀版標籤。(4) **單據**：收款明細每品項下縮排候補列（$單價+價差需補/退）＋整份有候補時結尾「※ 若以候補出貨，請依價差向該員補收/退還」；點餐文字（彙總結構）改用**【缺貨候補對照】區**（誰的哪杯→依順位候補什麼，數量同主品項）。(5) 設定：開團表單（上限下方，開關+1/2/3 段選）與設定 modal＋create/update 路由（clamp 1-3）；資訊卡「候補」行（全員可見）。**未動**：核對單 PDF（每人明細分頁高度計算＝已知重疊坑，候補列下版再加，店內場景由點餐文字對照表覆蓋）。 |
| V2.3.0 | **結帳自動化：補助自付計算＋整單折扣＋店家單據**。(1) **結算單一真相**（Order 三屬性）：`final_amount`＝套用整單折扣後四捨五入到元；`company_pay`＝有每單上限時 min(折後,上限)、沒設上限=0；`self_pay`＝折後−補助（**沒用到上限不退錢**：低於上限自付 0）。計算順序＝先折扣、後補助。數學驗證：170 元/95 折/上限 140 → 折後 162、公司 140、自付 22。(2) **整單折扣（滿額 95 折情境）**：Group 加 `discount_percent NUMERIC(5,2)`（95=95 折），團主在設定 modal 手動填（1-99，留空=無），資訊卡顯示「折扣：全單 95 折・結帳金額自動重算」（全員可見）；購物車合計顯示原價劃線＋折後、上限警示/貼補/送出擋單全部改用折後金額（前端 my_order＋後端 submit 同步）。(3) **收款明細（出帳單）重寫**：`generate_payment_text` 總覽列出 原價小計→折後→公司補助合計→應向個人收；每人明細列出品項＋計算過程（原價→折後→補助→應自付＋運費分攤）；順手**清除舊 emoji（💰🚗👥⚠️）**改純文字。(4) **店家單據**：Store 加 `provides_invoice/provides_receipt` 布林，後台店家編輯加「可開立單據：發票/收據」勾選，顯示於店家頁徽章、團單資訊卡「單據」行、收款明細標頭（方便報帳）。遷移：groups.discount_percent、stores.provides_invoice/receipt（啟動 add_column_if_not_exists）。**未動**：Excel 匯出與核對單 PDF 仍為原價（需要再加折扣/自付欄再說）。 |
| V2.2.0 | **去 geek 化重構：資訊卡整合＋身份分流**。使用者回饋介面「太 geek 向：功能很多但很亂、色塊太多」。設計原則確立：**一個畫面一個任務／身份決定資訊量／色塊只留語意點**。(1) **團頁頭部**：頂行倒數移除（併入資訊卡）、logo 20→14、店家 4 顆 pill（電話/地址文字/地圖/官網/外送）→ **一行圖示鈕**（地址併入地圖鈕：無 google_maps_url 時用 address 組 Google Maps 搜尋連結）。(2) **四色橫幅 → 一張資訊卡**：黃(結單)/綠(湊團大塊)/青(催單)/奶(上限/外送費) 五塊 → 單一 divide-y 卡，一行一項（結單+倒數／備註／每單上限／外送費／湊團含迷你進度條），唯一彩色＝「已成團」綠 pill 與 urgent 紅字。盲點/免單/請客三個趣味橫幅保留原樣（稀有且已安靜）。(3) **身份分流**（路由既有 is_owner/is_admin）：團員看 3 塊（團名區→資訊卡→我的訂單→菜單）；團主/管理員資訊卡多兩行——「狀況：N 人尚未送出＋查看名單」（原 pending 橫幅併入）與「催單：截止前 N 分自動提醒」（團員不再看到催單行）。(4) **團主工具收合**：原 4 格 grid＋管理 pill 列（複製連結/QR/存模板/匯出/修改/提早結單）→ 收合列「團主工具」點開 3×2 grid＋匯出展開區，**團員完全不顯示**（複製連結/QR/存模板原本全員可見，依核准設計稿收為團主限定）。(5) **我的訂單去重**：外層卡標題「我的訂單+已結單」移除（partial 內已有），「我請客」變卡上方靠右小動作。(6) **首頁**：團卡 grid-cols-2 半寬 → 單欄整寬橫排卡（logo 48/兩行截斷/人數+倒數/chevron，高度約 ⅓），備註從卡上移除（進團看資訊卡）。全模板解析通過；Alpine 綁定（copyLink/showQR/showSaveTemplate/showSettings/showReminder）健檢完整，收合列巢狀 x-data 靠 scope chain 上溯。教訓：**團員與團主需要的資訊量不同，伺服器渲染下身份分流零成本（is_owner 早就在 context），設計時應先問「這行字是誰需要的」**。 |
| V2.1.0 | **新功能：每單金額上限（公司補助情境）**。團主可設定每單上限金額，並選擇可否超過。(1) **Model+遷移**：Group 加 `order_limit NUMERIC(10,2)`（NULL=不限）、`allow_over_limit BOOLEAN DEFAULT FALSE`，用 main.py 既有 `add_column_if_not_exists` 啟動遷移（無 Alembic、PostgreSQL 安全）。(2) **開團表單**：外送費下方加「每單金額上限（選填）」＋輸入金額後浮出「允許超過上限」勾選（勾＝超過自行貼補；不勾＝不能結單超過的訂單），支援 copy_from 模板帶入。(3) **團資訊橫幅**：進團即見「每單上限 $X・可超過（自行貼補）／不可超過」。(4) **點超過提醒＋貼補計算**（my_order.html 結帳列，server-rendered 每次更新即時準確）：允許超過→琥珀警示「超過上限 $X，需自行貼補 $Y」＋合計轉琥珀；不允許→紅色警示「請調整品項」＋合計轉紅＋**確定結單 disabled**。(5) **後端雙重擋**：submit 路由檢查 `order_limit and not allow_over_limit and total > limit` → 400（前端 disabled 只是 UI，server 才是保險）。(6) **團主可改**：團單設定 modal 加上限欄位＋允許超過勾選，update_group 路由同步。教訓：加欄位一律走 main.py 啟動遷移（auto-create 不會補既有表的欄位）；金額類警示配色沿用語意色（琥珀=提醒可行、紅=阻擋）。 |
| V2.0.1 | **修：開團模板返回錨點**。使用者實機回報「我的（個人資料）」頁進入的 6 項，返回應一律回到該頁。盤點發現 5 項（消費統計／我的訂單／我參與過的團／我的部門／收藏店家）已正確返回 `/profile`，僅 **開團模板（templates/list）** 返回 `/home`（因它也可從開團頁的「管理模板」進入，當初設成首頁）；改為返回 `/profile`，與其他項一致。 |
| **V2.0.0** | **里程碑版・導覽返回鍵全站盤點**。逐頁盤點「點進去回不了上一頁」的情況：全部 41 個頁面模板檢查返回鍵，結果只有 6 個沒有——其中 `home`/`login`/`welcome`/`feedback/list`（底部 nav 根頁）/`guest_entry`（訪客外部入口）本來就不需要返回鍵；真正缺的只有 **`group_new`（開團頁，從 FAB 進入）→ 補返回 /home** 與 **`my_groups`（我的團單，從個人頁進入）→ 補返回 /profile**。另確認外部連結（外送/地圖/官網）皆有 `target="_blank"`、不會把使用者帶離 App；所有現有 `nav.back` 目的地正確。至此**全站無導覽死路**：每個子頁左上都有統一返回鍵、根頁有底部 nav。此版總結 V1.19→V2.0 的成果：收據修正、奶茶主題、結帳重做、全站視覺統一、返回鍵統一（前後台）、手機優化、加入回饋/無重載結帳/再來一杯、匯入頁重設計、清除測試團、使用者排序、我的進行中、常點一鍵、截止急迫感、SVG 空狀態插圖。 |
| V1.27.0 | **我的進行中 + 常點一鍵 + 截止急迫感 + SVG 空狀態插圖**。(1) **首頁「我的進行中」**（#3）：home.py 從已 eager-load 的開放團算出「我是團主或已下單」的團（`my_active`，狀態 submitted/draft/editing/owner），home.html 頂部新增區塊＋狀態徽章（已結單綠／待點餐琥珀／未送出 sela），一進首頁就看到自己在哪些團、點了沒。(2) **常點一鍵**（#6）：groups.py 新增個人常點查詢（`OrderItem` 依 `menu_item_id` 彙總此使用者在此店家的數量，前 8，再對應到目前菜單可點的前 4），group.html 快速點餐區頂部加「你的常點」深咖啡 chips，點一下開客製 sheet（與 V1.25 的「再來一杯」串起來＝開窗即帶上次糖冰）。(3) **截止急迫感**（#1）：`countdown()`（home.html + group.html）加 `urgent` 旗標（剩 <15 分），group_card 與 group 頭部倒數在急迫時變紅底＋`animate-pulse`＋火焰圖示，平時時鐘圖示。(4) **SVG 空狀態**（#2，絕不用 emoji）：空購物車換成奶茶杯內嵌 SVG 插圖（杯身/杯蓋/吸管/珍珠）、首頁無團換成飲料杯＋蒸氣餐碗場景 SVG，皆用品牌奶茶色階。全站確認無 emoji（一律 Tabler icon webfont 或 inline SVG）。後端 home.py/groups.py 編譯通過、全模板解析通過。 |
| V1.26.0 | **標題版本號 + 清除測試團 + 使用者排序**。(1) **版本號回到標題旁**：header logo 右側「快點來點餐」下方加小字版本號（`{{ app_version }}`，text-[10px] 暖灰），方便確認部署是否更新（Phase 1 曾移除，現依需求以低調樣式加回）。(2) **清除測試團**（admin）：`admin.py` 新增 `_delete_group_cascade()`（照抄 groups.py 既有 FK 連鎖刪除：TreatRecord→GroupDepartment→Order 的 OrderItemOption/OrderItemTopping/OrderItem→Order→Group）＋ `POST /admin/groups/cleanup-test`（刪除「所有訂單都屬團主、或無訂單」的團，條件 `all(o.user_id == g.owner_id for o in g.orders)`）＋ `POST /admin/groups/{id}/delete`（管理員刪單一團，導回 /admin/groups）。admin/groups.html 加「清除測試團」卡片＋清除數提示，每列改結構（原整列 `<a>` → 連結與操作並列，表單不能塞進 `<a>`），加「測試團」標記與刪除鈕。(3) **使用者排序**：`GET /admin/users` 加 `sort` 參數（created／last_login／last_active／name，用 `nullslast()` 處理未登入者），users.html 加分頁式排序控制。教訓：刪團 FK 連鎖務必重用既有經驗證的刪除順序，不可只 `db.delete(group)`（PostgreSQL 會因 FK 失敗）。 |
| V1.25.0 | **使用者體驗強化（toast + 無重載結帳 + 再來一杯）+ 匯入頁重設計**。(1) **加入購物車即時回饋**：base.html 加全域 toast 元件（`@apptoast.window` 監聽、底部置中、1.8s 自動消失）＋ `window.toast(msg)` helper；`afterAddItem()` 觸發「已加入購物車」。(2) **拿掉結帳整頁重載**：`my_order.html` 四顆鈕（送出/取消/修改/刪除）原 `$dispatch('orderUpdated'); location.reload()` → 改成只更新 Alpine `orderStatus`（送出→submitted＋關購物車、修改→editing、取消→submitted、刪除→none＋cartCount=0），畫面切換靠既有 x-show、內容靠既有 orderUpdated 監聽刷新，不再白閃/跳頂/失去位置；送出與刪除附 toast。(3) **再來一杯（記住上次糖/冰/尺寸）**：`orderPage()` 加 `saveLastPref()`（加入時把勾選的 sugar/ice + selectedSize 存 `localStorage['selapref_<storeId>']`）與 `applyLastPref()`（openAddItem 後 `$nextTick` 套用；找不到對應選項就回到團預設，graceful）。(4) **匯入店家/菜單頁重設計**：原本一牆並列盒子（AI prompt 藍盒＋Logo 盒＋分頁＋表單＋格式說明）看不出先做什麼；改成**編號步驟流程**（①複製 prompt 給 AI → ②貼 JSON 並預覽匯入），選用的 **Logo 生成摺疊移到最下方**（與菜單匯入無關、不再打斷主線），藍/琥珀彩虹收品牌 sela，主鈕升 `.btn btn-primary`，store_id 選擇從厚重 amber alert 簡化成一般欄位。**block scripts 的 5 段 prompt 字串原封不動**。教訓：`location.reload` 之所以能安全移除，是因為畫面切換本就綁在 Alpine `orderStatus` 的 x-show、內容刷新本就綁在 `orderUpdated` 監聽——reload 只是把這兩件事一起暴力重來；分清楚「狀態切換」與「內容刷新」兩條路徑後就能局部更新。**實機需驗**：送出/修改/刪除的平滑切換、加入 toast、再來一杯預填。 |
| V1.24.0 | **手機優化 + 移除重複開團鈕**。(1) **去重**：移除 header 右上的「開團」鈕，與底部中央 FAB 重複（每位使用者其實多半是加入點餐、非開團，開團入口留一個即可）。header 右側精簡為 管理（限管理員）+ 頭像。(2) **手機優化**：viewport 改 `viewport-fit=cover` 並放開縮放限制（無障礙）；**輸入框強制 ≥16px**（避免 iOS 聚焦時整頁自動放大，超常見痛點）；header 加 `padding-top: env(safe-area-inset-top)`（瀏海不擋內容）；底部導航 `.safe-area-pb` 補定義＋佔位高度納入安全區（home indicator 不擋）；移除點擊灰閃 `-webkit-tap-highlight-color`；`overscroll-behavior-y` 防橡皮筋外溢；加 `apple-mobile-web-app` / `theme-color #E8D9C0` meta。group.html sticky 分類列 `top` 改 `calc(3.5rem+env(safe-area-inset-top))` 配合 header 安全區。 |
| V1.23.1 | **後台管理介面返回鍵統一 + 灰字暖化**。使用者回報後台返回鍵位置仍亂。Phase 3 為控風險未掃 admin，本版補上：17 個後台頁全部套用 `nav.back()` macro（左上角、chevron + 目的地、統一樣式），移除原本散落 header 右側的 `返回XXX →`（灰、往前箭頭）；`import.html` 的條件式雙返回（有/無選定店家）改成條件式 `nav.back`。後台 18 檔灰字暖化（coffee 墨色階）、卡片圓角統一 `rounded-2xl`，後台 gray 歸零。後台的狀態色（啟用/停用/角色/審核狀態）屬語意色，保留。全模板 Jinja 解析通過。至此**前台＋後台返回鍵與文字色系全站一致**。 |
| V1.23.0 | **UI 優化 Phase 3：返回鍵全站統一 + 次要頁收尾**。使用者回報「按鍵位置跳來跳去、尤其返回鍵」。盤點發現返回鍵根本各做各的：位置有左有右、圖示 `←`／`‹`／往前的 `→` 混用、文案「返回首頁／個人頁面／店家／投票列表…」不一、顏色 gray/sela 混。**統一方案（iOS 風）**：新增 `partials/nav.html` 的 `nav.back(href, label)` macro + base.html `.back-link` 樣式（左上、chevron + 目的地、44pt 可點）；16 個頁面一律在 `{% block content %}` 後第一個元素放 `{{ nav.back(...) }}`（永遠左上角），移除原本散落的返回連結；group.html 自身返回鍵也對齊同款。**次要頁彩虹收尾**：stats（資料頁全收品牌）、votes/*（投票選擇器→深咖啡實心、進度條→sela）、feedback 列表（blue→sela，保留 green=已解決/red=緊急）、guest_entry、templates/* 的灰字暖化＋彩虹收斂。卡片圓角統一 `rounded-2xl`。至此**消費端 gray 與非語意彩虹全部歸零**（green/amber/red 僅留語意）。全模板 Jinja 解析通過。教訓：返回鍵這種全站重複元件，應一開始就做成 macro+共用 class，不要每頁各寫一份——否則位置/圖示/文案必然漂移。 |
| V1.22.0 | **UI 優化 Phase 2：全頁視覺統一**。把 Phase 1 的設計地基套到所有消費端頁面。(1) **灰字暖化**——全站 `text-gray-*` → coffee 墨色不同透明度（`text-sela-800` 系，900/800→800、700→800/80、600→800/70、500→800/60、400→800/45），`bg-gray-*`/`border-gray-*` → `sela`，`hover:bg-gray` → `active:bg-sela`（觸控回饋）。(2) **彩虹收斂**——分類三色（飲料 amber／餐廳 green／團購 blue）全收成品牌 sela；首頁篩選、團卡、快速點餐分頁、sticky 分類列的選中態統一成深咖啡實心 `bg-sela-800 text-white`；店家連結 pill（電話綠/地圖藍/UberEats emerald/foodpanda 粉）、功能橫幅（免單粉/請客紅/外送費藍）、糖冰晶片（amber/blue）全部統一 sela。**語意三色保留**：green=成功（已結單/送出數/資料已更新）、amber=提醒（備註）、red=危險（刪除/登出）。(3) **登入頁＋welcome 重做**——原本冷灰離題、掛舊 `sela-logo.svg`；改奶茶配色＋換上透明版新 ORDER logo（`images/order-logo.png`），LINE 綠鈕保留（品牌色）、加 LINE 圖示。(4) **結構細節**——`查看菜單` 升為主要 CTA、`返回首頁 →`（往前箭頭當返回）改成左 chevron `‹ 首頁`、profile 列表 `→` 改 `ti-chevron-right`、卡片圓角統一 `rounded-2xl`、group.html sticky 分類列 offset `top-12`→`top-14`。涉及約 25 個消費端模板與 partials，全數 Jinja 解析通過。**Phase 3 待辦**：stats／votes/*／feedback 列表／guest_entry 的彩虹收斂（次要頁，另版）。教訓：批次換色用 `text-sela-800/<opacity>` 做暖灰階，比硬挑 sela 中階好看且統一；語意色（成功/提醒/危險）要逐檔判斷保留，不能一律收成品牌色。 |
| V1.21.0 | **UI 優化 Phase 1：設計地基 + 結帳重做（功能優先）**。背景：以 iOS 設計師視角逐頁體檢，列出系統性問題（冷灰文字／配色失控／主鈕太弱／hover 當回饋／觸控過小／圓角不一）。本版先做地基與最痛的結帳：(1) **設計地基**——base.html `<style>` 加元件層（純 CSS hex，不依賴 Tailwind 編譯）：`.btn-primary`（深咖啡實心高對比主鈕）/`.btn-secondary`/`.btn-danger`、`.card`、`.chip`+選中態深咖啡實心、`.stepper`（44pt）、`#cart-content .order-actions` 釘底結帳列。(2) **結帳**——購物車從右抽屜改**底部 sheet**（抓握條、滑入）；`my_order.html` 重寫：**合計＋確定結單釘在底部**（捲動仍可見，用 `position:sticky` 範圍鎖在 `#cart-content` 內，頁面版顯示不受影響）、±從 24px 放大到 36/44pt、文字暖化、主鈕高對比；客製 sheet 加**本品小計即時計算**（Alpine `extraToppings`+`itemSubtotal()`，反應 size／加料／數量）、糖冰加料選中態改深咖啡實心。(3) 全域：拿掉 header 版本號、底部 nav 未選色暖化（gray-400→sela-400）＋選中態加強（sela-50→sela-100）、購物車 FAB 改深咖啡高對比。`menu_item` 暖化＋按壓態。**注意**：`location.reload()` 暫留（送出/修改要切換頁面狀態，移除需實機測 Alpine 同步，列為後續）。Phase 2/3＝首頁/店家/個人/登入頁配色收斂與灰字暖化（大面積掃，另版）。教訓：`my_order.html` 同時用於購物車與頁面顯示，sticky 須用 `#cart-content` 範圍鎖定，避免頁面版蓋到底部 nav。 |
| V1.20.1 | **換上奶茶版 ORDER logo 全套 + 修 manifest 橘色殘留**。使用者提供 AI 生成的 ORDER logo（原為紫底白圖），因主題已是奶茶，先攔下避免紫色擺回奶茶表頭。flat 雙色 logo 程式改色：flood fill 遮罩外圈白 → 方塊內 紫→奶茶 tan `#C9A977`、白圖→深咖啡 `#5B4733`、外圈透明。照規範切全套：頁首 `images/sela-logo.jpg`（壓 `#E8D9C0` 表頭底）、favicon `16/32/192/512`（透明圓角 PNG）、`apple-touch-icon`（壓 `#E8D9C0` 不透明，iOS 用）、`favicon.ico`（16/32/48）。另外發現 `site.webmanifest` 的 `theme_color`/`background_color` 還是橘色 `#F36825`（橘色時代殘留，當初換紫＋這次換奶茶都漏，且不在前次 grep 的副檔名範圍內）→ 改 `#C9A977`/`#E8D9C0`。教訓：**改主題色時 grep 範圍要含 `.webmanifest`/`.json`/`.svg`**，PWA 顏色與圖示資產容易漏。 |
| V1.20.0 | **主題色全面更換：紫 #653985 → 經典奶茶（淺底深字）**。原因：有人反映紫色影響食慾，改用偏白的奶茶暖色。`sela` 色階全部換成奶茶（500 = `#C9A977`、200 = `#E8D9C0`、800 = `#5B4733`，一字不差、淡濃階用算的）；網頁端從「深底白字」反轉成「淺底深字」（`header bg-sela-600`→`bg-sela-200` + `border-sela-300`、`text-white`→`text-sela-800`，約 40 個模板＋scrollbar 一起掃）。收尾三個缺口：(a) `receipt_service.py` 版型翻成淺底深字（表頭 `THEME_FILL #E8D9C0` 底＋底部 `DIVIDER #DCC8A6` 分隔線、店名/實收文字改深咖啡、實收條 `THEME_BAR #D8C09A`、logo 白框加 divider 描邊）；(b) `excel_service.py` 匯出表頭 紫底白字 → `#C9A977` 底深字；(c) `import.html` 生 logo 的 AI 提示詞 紫底白框 → 奶茶底深咖啡框。語意色（amber/yellow 狀態徽章、收藏星、分類 filter）**刻意保留**，非紫色殘留。全站 grep 紫色 hex 歸零；receipt render 像素取樣驗證表頭 = #E8D9C0、實收條 = #D8C09A。 |
| V1.19.4 | **Hotfix：核對單兩個顯示 bug（坑 #23）**。使用者回報截圖。(1) **折扣行被實收紫條蓋住**：店家總項有店家優惠時的「店家優惠 -$X」那行，畫完只往下移 6mm，但底下「實收」紫色塊是從 `y-1mm` 往上長 8mm（頂端在 `y+7mm`），7mm 上緣蓋過只隔 6mm 的折扣文字。改 `y -= 6mm` → `y -= 10mm`（間距須 > 7mm）。(2) **PNG 只出第一頁**：`generate_receipt_png` 寫死 `page = pdf[0]`，人多溢頁時每人明細整段不見。改為 render 全部頁面、白底等寬置中直向拼成「一張長圖」（貼 LINE 一次分享完整）。兩處皆獨立測試重現＋修復確認（折扣行與紫條分離、3 頁拼接成 6315px 長圖）。只動 `receipt_service.py`。 |
| V1.19.3 | **分享連結改走 LINE 登入 + 訪客清理**。承 V1.19.2 關閉訪客後，使用者要的「分享連結」其實是「分享團單網址、對方點了沒登入就導 LINE 登入」（用自己身分跟團）。發現**既有的「複製連結」按鈕（copyLink 複製 window.location.href = /groups/{id}）就是這個需求** —— 對方點開未登入會被坑 #14 的 401 redirect 導去 LINE 登入。只改提示文字講清楚（「分享給跟團的人，他們用自己 LINE 登入即可一起點餐」），不需新功能。訪客清理：診斷頁清理按鈕 + `/admin/users-cleanup-guests` 路由（依子→父斷鏈刪訪客訂單樹，排除有開團的訪客）已完備，使用者確認舊訪客訂單不重要、直接清。端到端測：3 訪客清光、正式用戶保留。 |
| V1.19.2 | **關閉訪客功能（只用 LINE 登入）**。承 V1.19.1：訪客功能是空殼帳號的來源，且本系統只需 LINE 登入（使用者表示忘了當初有開訪客）。關閉：(1) 移除 group.html「產生訪客連結」前端區塊（團主無入口）。(2) 後端 3 個訪客路由（`/guest-link` POST、`/guest` GET、`/guest` POST）加 `GUEST_MODE_ENABLED = False` 開關，全部回 410「訪客功能已停用」—— 防舊訪客連結被點到時建新帳號（最關鍵是 POST /guest 那個 build User 的）。路由保留不刪（將來要恢復改開關即可）。既有訪客帳號與其歷史訂單保留（V1.19.1 已從正式列表隔離）。 |
| V1.19.1 | **找到「重複用戶」根因 + 隔離訪客帳號**。診斷頁顯示那些「重複」全是 0 訂單/從未活躍/無頭像/同日註冊/暱稱=名稱、末碼都不同。追查發現兇手是 `groups.py` 訪客功能（guest_entry）：每次有人用訪客連結進來就建一個 `guest_{隨機hex}` 新帳號、display_name 用訪客自填的 guest_name → 有人填 0/測試/靜，且同人多次進來=多帳號。這些 `is_guest=True` 的臨時訪客**不該出現在正式員工列表**。修：部門可選用戶下拉、用戶管理列表、後台用戶統計、重複診斷頁全部加 `User.is_guest == False` 過濾，把訪客隔離（歷史訂單保留、不刪資料）。根因是訪客 vs 正式用戶混在同一張 users 表又沒在列表處區分。 |
| V1.19.0 | **重複用戶診斷工具**。使用者反映部門管理選用戶下拉一堆「重複」（多個 0/測試/靜）。查 root cause：`line_user_id` model 上有 `unique=True`，登入走 `get_or_create_user`（用 line_user_id 查找），**同一 LINE 帳號不可能真重複**。所以「重複」實為不同 LINE 帳號剛好同名（show_name=nickname or display_name）。做診斷頁 `/admin/users-duplicates`（放 `/users/{user_id}` 前避免 int 路徑衝突）：同名分組，顯示各自 line_user_id 末碼（不同=不同人）、訂單數、註冊/活躍時間、有無頭像，並標記 true_dup（同組內 line_user_id 真的相同才算）。用戶管理頁加入口。讓團主自行判斷哪些是不同人（不刪）、哪些可能要處理。 |
| V1.18.2 | **Hotfix：折扣送出 404 跳黑頁**。V1.18.0 把折扣路由加在 `orders_extra.py`，但該 router 掛載方式與表單 URL 對不上，且表單寫 `/{group_id}/orders/{order_id}/discount` 缺 `/groups` 前綴 → POST 404 Not Found。修：路由移到 `groups.py`（與 copy-last 同檔，groups.router 在 main.py 以 `prefix="/groups"` 註冊，自動補前綴）、改用 groups.py 慣例的 `await get_current_user(request, db)`；表單 action 改 `/groups/{group_id}/orders/{order_id}/discount`。教訓：加路由前先確認該 router 的 mount prefix，表單 URL 要跟「prefix + 路由 path」完整對齊。 |
| V1.18.1 | **折扣修正為「店家優惠」：店家總項也跟著減**。V1.18.0 原假設「折扣是團主自行吸收」→ 店家總項顯示原價。使用者指正：絕大部分是**店家給的優惠**，店家實收也該折後。修正：核對單店家總項總計改顯示「原價小計 / 店家優惠 -$X / 實收」三行（無折扣時維持單行「總計」）；店家明細純文字（generate_order_text）總額同樣加「原價/店家優惠/實收」。`_collect` 加 items_total（折前）+ total_discount（總優惠）+ total_amount（實收=折後）。**三方一致達成**：店家實收 = 團體總額 = 每人加總（端到端測 268 原價、優惠 10、三方都 258）。Excel 合計 V1.18.0 已扣折扣不需再改。教訓：折扣語意要先問清楚「誰買單」（店家優惠 vs 團主吸收），影響店家總項算不算。 |
| V1.18.0 | **新功能：團主手動按人折扣**。需求源於「搭主餐折10元」這類優惠。不做自動判斷（規則難猜易算錯），改團主/管理員手動對每個人的訂單填「折扣金額 + 說明」。**單一真相設計**：Order 加 `discount_amount`/`discount_note` 欄位，`total_amount` property 改為「品項原價總和 - 折扣」（>0 保護），所有用 order.total_amount 的地方（訂單牆、團體總額 group.total_amount、個人明細、核對單、Excel）**自動連動**。**重要概念區分**：折扣只影響「每人應付」與「團體應收」，**不影響核對單的「店家總項」總額**（店家做的餐沒少，原價結算；折扣是團主跟成員間的事）。UI：order_wall.html 加團主折扣表單（數字+說明，Alpine 展開）；折扣顯示用紅字區隔。路由 `POST /{group_id}/orders/{order_id}/discount`（團主/管理員限定、折扣不超過原價）。各匯出（核對單紅字折扣行、個人明細折扣行、Excel 折扣列扣合計）全部顯示折扣。main.py 加 2 欄遷移。 |
| V1.17.3 | **核對單每人明細色塊留白修勻**。原色塊高度計算與文字繪製位置對不齊，導致上下留白不對稱（有的緊貼姓名、有的鬆）、外框框太緊。重寫成乾淨 padding 模型：定義明確常數（上內距 5mm／姓名 6mm／品項 5mm／下內距 4mm／人間外距 3mm），色塊高度 = 上下內距 + 內容、文字從色塊頂依序往下排。每個人色塊留白一致、外框留足。 |
| V1.17.2 | **核對單 PDF 排版優化**。(1) 店家 logo 放大：header 30→36mm、logo 22→30mm、縮圖上限 300→400px（放大後解析度夠）。(2) 每人明細「一人一色區」：隔人交替整塊底色（同一人的姓名+品項共用一個色塊），核對時一眼分辨誰是誰；改用「先畫底色再畫內容」確保色塊位置精準。(3) 區塊底色 ZEBRA #F2EEF5→#ECE5F2 略加深，核對更清楚（店家總項斑馬紋同步）。 |
| V1.17.1 | **核對單 PDF 排版調整**。(1) 店家 logo 放大：header 高 22→30mm、logo 框 14→22mm、縮圖解析度 200→300px、店名字級 16→17。(2) 每人明細從「純文字列」改「一人一色區塊」：先算每人區塊高度（姓名+品項列），隔人交替淺紫底色（ZEBRA），整塊同底色，團主核對時一眼分辨同一人的幾行。換頁判斷改為「整塊放不下才換頁」避免一個人被切兩頁。 |
| V1.17.0 | **對齊 SELA-Starter-Kit V1.18.0**（從 V1.9.0 升級對齊）。🔴 更新衝突仲裁區塊 Kit 版本；🔴 修正 §〇 當前狀態版本號 V1.13.3→V1.16.0（V1.13.4 起用 git clone 改版漏更新開頭，補回）；🟡 優化體檢（Kit V1.17.0 鐵律）對照 optimizations.md 4 條 OPT 無中招值得改項，通過；🟡 app logo（Kit V1.13.0 雙軌）SELA 同意做專屬 logo，依 §17 產出 `SELA-logo-prompt.md`（範本 A、背景色 #653985、待 SELA 生圖後走 §10.2 轉檔）；更新 SELA-handoff.md 加 V1.16.0 對齊升級增補段 + 2 條 Kit 回流發現。零業務邏輯變更。 |
| V1.16.0 | **主題色換 #653985（北歐低彩度紫）**。沿用坑 #21 正解：500 階直接 #653985 原值。北歐低彩度做法：淡階往「帶紫灰的暖白 #F5F4F6」混（非純白，保留灰調、彩度壓到 17-24%）、深階往「帶紫的暖黑 #1A1620」混，整體沉穩不鮮豔。**全站同步**：base.html 色階 + 滾動條、admin/import.html 的 logo prompt 主色、excel_service 表頭色（7528D4→653985）、receipt_service 主題色 THEME/THEME_LIGHT/ZEBRA 都換。grep 確認無殘留舊主色 hex。 |
| V1.15.0 | **團單頁 UI 優化：按鈕區重整 + 購物車不被遮**。(1) 底部操作按鈕原本 10 個擠一排、文字直排凌亂（加核對單後更擠）。重新設計：主動作（複製連結/QR/存模板/匯出單據）改 4 欄網格、圖示在上文字在下；團主管理動作（催單/修改/提早結單）改膠囊按鈕橫排；5 個匯出（核對單PDF/圖、店家/個人明細、Excel）收進「匯出單據」展開區（Alpine showExport，分「給店家核對」與「其他格式」兩組）。(2) 購物車浮動按鈕 `bottom-4`→`bottom-20`，避開底部導航列遮擋。(3) 分類捲動間距 `scroll-mt-28`→`scroll-mt-32`，避免品項標題被 sticky 分類標籤蓋住。 |
| V1.14.1 | **Hotfix：核對單 PNG 中文空白 + 改斑馬紋（坑 #22）**。(1) **PNG 完全沒中文**：reportlab 內建 CID 字型 STSong-Light 只「引用」不「嵌入」PDF，pypdfium2 render 時找不到字型 → 中文變空白（PDF 在有該字型的電腦看正常，但 render 圖就缺字）。修：改用**嵌入式 TrueType 字型**（打包 `app/static/fonts/cjk-font.ttf` 進專案，6MB），嵌入後 render PNG 中文正常。(2) 店家總項原本畫分隔細線會錯位產生「奇怪的線」，改成**斑馬紋**（隔行淺紫底 #F7F4FB）對齊更清楚。 |
| V1.14.0 | **新功能：訂單核對單匯出（PDF + PNG，含店家 logo）**。給團主跟店家核對用。新 service `receipt_service.py`：上半「店家總項」（彙總相同品項，店家照此製作）、下半「每人明細」（團主對帳）、頂部店家 logo + 店名 + 截止時間。技術選型路線 B（伺服器生檔，部署穩）：**PDF 用 reportlab 內建 CID 中文字型 `STSong-Light`（零外部字型檔，避免打包肥大 TTF 或在 Docker 裝字型）**；PNG 用 pypdfium2 將 PDF render 成 2.5x 高解析圖（同源、貼 LINE 清晰）。彙總邏輯複用 export_service 規則（含加料、與 OrderItem.subtotal 一致）。logo 下載後用 Pillow 縮圖到 200px 再嵌入（避免 1.4MB 肥檔 → 降到 62KB）；logo 下載失敗 try/except fallback（不因 Cloudinary 抽風而 500）。團單頁加「核對單PDF / 核對單圖」兩連結（團主/管理員限定）。requirements 加 reportlab==4.4.10、pypdfium2==5.6.0。邊界測試：有logo/壞網址/店家已刪三情境全過。 |
| V1.13.4 | **Hotfix：Excel 匯出爆 500 + 訂單牆爆 500**。(1) `excel_service.py` 用了 OrderItem 不存在的 `item.toppings`（應為關聯 `selected_toppings`）和 `item.price`（應為 `subtotal`）→ `AttributeError`。修：規格組合改用 `selected_options`/`selected_toppings`、小計改 `item.subtotal`（與個人/店家明細一致含加料）；表頭橘 F97316→紫 7528D4；store.name 防 None。(2) `orders.py` 的 `order_wall` 路由沒傳 `group`/`is_open`，但 order_wall.html 第 8 行用到 → `UndefinedError: 'group' is undefined`。修：路由補查 group 並傳入 group + is_open。兩者端到端測試通過。 |
| V1.13.3 | **主題色換 #7528d4（低彩度紫）**。沿用坑 #21 正解：500 階直接用 #7528d4 原值，其他階原色往白/黑線性混合。滾動條→sela-300、logo prompt 主色同步更新。 |
| V1.13.2 | **Hotfix：色階生成偏色（坑 #21）**。V1.13.1 用 HSL 拆解再重組生成色階，只保留 hue、明度飽和度自訂 → 500 階算成 #662ab0（偏暗偏濁），與指定的 #710ced 有明顯落差。改法：**500 階直接寫死 #710ced 原色不經任何轉換**，其他階用「原色往白混（淡階）/往黑混（深階）」線性生成，色相零偏移。 |
| V1.13.1 | **主題色換 #710ced（紫）**。使用者覺得 #454c8c 太藍。`sela-*` 色階整組重新生成（以 #710ced 為 500，HSL 267°/90%/49%，固定 hue 調明度生成 50~900）。滾動條 hardcode #8E95CC→#B179F6（新 sela-300）；文字 logo prompt 的 #454c8c→#710ced。 |
| V1.13.0 | **提高主題色比例（A+B）**。使用者覺得白色太多。(A) `<body>` 背景 `bg-sela-50/30`→`bg-sela-50`（完整淡藍紫，卡片白色浮其上）。(B) 頂部 header 從白底改 `bg-sela-600` 藍紫底：logo 文字 / 齒輪改白、版本號 white/50、開團按鈕改白底藍紫字（在深色 header 上對比足夠）、頭像邊框改 white/60。底部導航維持白底（浮在淡藍紫背景上）。 |
| V1.12.0 | **團單頁頂部 + 首頁卡片版面重排**。(1) 團單頁頂部：原本縮圖/店名/店家/老闆/收藏/倒數全擠一排。改為「返回 + 倒數」獨立頂行（返回改 `ti-arrow-left` 左置），下方大縮圖（64→80px）+ 店名獨立大字一行、店家/老闆/收藏分行不擠。(2) 首頁開團卡片（group_card）：縮圖 56→72px、店名從 `truncate`（截斷一行）改 `line-clamp-2`（可換兩行不截）。 |
| V1.11.2 | **修金額 bug：個人明細 vs 店家明細不符（使用者回報，坑 #20）**。`export_service.generate_order_text`（店家明細）算單項價時 `unit_price + options_total` **漏了 `toppings_total`（加料費）**，而 `generate_payment_text`（個人明細）用 `OrderItem.subtotal` 含加料 → 有人點加料時兩邊金額對不上。修：店家明細補 `+ item.toppings_total`，與 subtotal 算法一致；彙總 key 也補加料（`+珍珠`）避免同品項不同加料被合併後價格被覆蓋。註：export_service 內的 💰🚗👥⚠️ emoji **刻意保留**（純文字匯出給店家貼 LINE 用，非 HTML，不可換 Tabler）。 |
| V1.11.1 | **匯入 store_id=0 友善指引 + 貼上分頁可選目標店家**。menu-only JSON 的 store_id 是 prompt 佔位值 0，直接貼會「找不到店家編號 0」。改善：(1) 偵測 store_id==0 給明確兩方法指引（回店家頁點匯入／手動改編號）；找不到其他編號時列出現有店家對照表。(2) 貼上分頁加「選填目標店家」下拉（沒從店家頁進來時顯示），選了就覆蓋 JSON 的 store_id，不用手動改 JSON。(3) preview 路由 store_id 參數改 `str` 安全轉 int（下拉「不指定」傳空字串，避免 int 轉換 422）。 |
| V1.11.0 | **修圖示亂碼 + 放大團單頁 logo（坑 #19）**。(1) 倒數計時等 6 處把 `<i class="ti ...">` 標籤塞進「會被當純文字的位置」（Alpine `x-text`、JS `textContent`、JS `confirm()`、Jinja2 autoescape 的 `{{ }}`），導致畫面顯示原始 HTML 字串亂碼。修法：`x-text` 改「固定圖示 + span」、`textContent`→`innerHTML`、`confirm()` 去掉標籤留純文字、Jinja2 字串陣列改直接寫標籤。涵蓋倒數計時/送單勾勾/收藏星星/排名獎牌/刪除確認。(2) 團單頁 store logo 容器 48→64px、圖 40→56px。(3) 順手把漏網的 `group.category_icon` emoji（model property 🧋🍱🛒）在 group.html / guest_entry.html 的 fallback 換成 Tabler 字串比較版。 |
| V1.10.2 | **修正 JSON 匯入只能兩種分類的 bug（解坑 #9）**。系統 CategoryType enum 有三種（drink/meal/group_buy）、後台手動新增店家表單也有三種 radio、import_service `CategoryType(...)` 也支援三種，**唯獨 `schemas/store.py` 的 `StoreImport.category` 與 `StoreCreate.category` 寫死 `Literal["drink","meal"]`，把 group_buy 擋在驗證階段** → JSON 匯入團購店一律失敗。修法：兩處 Literal 補上 "group_buy"。prompt 的 category 規範改回三種 + 加判斷準則（團購/預購/宅配/農場直送/箱購→group_buy）+ 補 group_buy 完整範例。三種分類匯入都實測通過。 |
| V1.10.1 | **匯入 prompt 對齊真實 schema + 完整範例**。重寫 promptNewStore / promptMenu，依實際 Pydantic schema（schemas/menu.py + store.py）逐欄位規範。**修正關鍵錯誤：原 prompt 寫 category 可填 group_buy，但 `StoreImport.category` 是 `Literal["drink","meal"]` 根本不收 group_buy（坑 #9）— 會讓 AI 產出系統拒絕的 JSON**。新 prompt：category 明確只能 drink/meal + 判斷準則、所有 price 純數字「時價」填 0、store 各欄位（logo_url 填 null、sugar/ice/toppings 規則）、item 的 price_l/options 何時填 null、附「drink 完整範例 + meal 範例」兩個可直接用的範例。promptMenu 同樣附完整範例。**三個範例都用真實 schema 驗證過能通過匯入**。 |
| V1.10.0 | **刪店家改為「軟參照」：斷開連結保留團單**。原本店家有團單就 `raise HTTPException` 擋刪（整頁噴 JSON）。改為：刪店家時把該店所有團單的店名存進新欄位 `groups.store_name`（快照）、`store_id` 與 `menu_id` 設 NULL（斷開），再刪店家 + 菜單。團單與歷史完整保留，只是不再指向店家。Model：`store_id`/`menu_id` 改 nullable + 新增 `store_name` 欄位 + `store_display_name` property（關聯優先、刪除後用快照）。6 個模板 `group.store.name`→`group.store_display_name`、`group.store.logo_url` 加 `group.store and` 防 None。main.py 加 3 條遷移（store_name 欄位 + store_id/menu_id DROP NOT NULL）。刪除用 `db.no_autoflush` 避免 flush 時序撞 NOT NULL。 |
| V1.9.0 | **Logo 生成 prompt + 店名填空**。(1) 匯入頁新增「生成店家 Logo」獨立區塊（紫色），兩顆複製 prompt 按鈕：`promptLogoRestore`（有原始 logo → 忠實還原 + 去雜訊 + 提升解析度 + 取邊緣底色補滿正方形不留白不裁切）、`promptLogoText`（無 logo → 店名生成北歐極簡文字 logo：#454c8c 底、白字、白色細外框、無襯線細體、正方形，結尾留「店名：」填空）。logo 生成後走現有店家編輯頁上傳流程（prompt 只負責生圖）。(2) 實測發現菜單照片常無店名，`promptNewStore` 結尾補「店名：」填空 + 指示 AI 不要亂猜。 |
| V1.8.1 | **Hotfix：菜單版本號顯示店內序號（坑 #17）**。原本 menus.html 顯示「版本 #{{ menu.id }}」用的是 Menu 全域自增主鍵 — 新店第一份菜單可能顯示「#29」（全系統第 29 筆），多版本也會跳號（#5/#18/#29）看不出第幾版。改為在 menu_list 路由算「店內版本序號」（最舊=第 1 版，用 `total - idx` 因 created_at desc 排序），template 顯示「第 N 版」。 |
| V1.8.0 | **抬頭文字 + AI prompt 複製 + 同名店家偵測 + 菜單時間**。(1) base.html 抬頭「SELA」→「快點來點餐」（logo 圖與版本號不變）。(2) 匯入頁「載入範例」按鈕改為「複製 AI prompt」按鈕（新增店家 / 既有店家加菜單兩種），點了把完整 prompt 複製到剪貼簿（`navigator.clipboard`）— prompt 含格式規範、欄位限制（category 只能 drink/meal/group_buy、price 純數字、時價填 0、大杯 price_l）、輸出格式範例，配合「截圖菜單貼給 AI → 拿 JSON 貼回」工作流；加「怎麼用」三步驟說明。(3) `import_store_and_menu` 加**同名店家偵測**（完全比對 `Store.name`）：偵測到同名 → 不新增重複店家，菜單匯入既有店家，舊菜單停用保留為舊版本、新菜單啟用；預覽綠框顯示提示行（不跳視窗）。(4) admin/menus.html 菜單版本時間「建立於」→「匯入於」並套 `taipei` filter（原本顯示 UTC 差 8 小時）。 |
| V1.7.0 | **匯入體驗強化：貼上 JSON + 友善中文錯誤**（功能優化首發，非視覺）。匯入頁加「貼上 JSON / 上傳檔案」分頁（預設貼上，符合「AI 轉 JSON 直接貼」工作流）；改 htmx 提交，**失敗不換頁**、中文錯誤紅框就地顯示（取代原本整頁噴 `{"detail":"..."}` JSON）；Pydantic `ValidationError` 翻成「第 N 個分類的第 M 個品項的價格：不是有效數字」這種看得懂的訊息（`humanize_validation_error` + `_translate_loc` + `_translate_error_type`）；JSONDecodeError 給行號提示；範例一鍵載入（textarea 帶入）；驗證通過後預覽摘要 + 明細就地展開。新增 partial `admin/partials/import_result.html`（錯誤/成功二擇一片段）。**保留上傳檔案舊功能**。價格容錯（「時價」「$30」自動處理）刻意留待下版單獨做。 |
| V1.6.1 | **Hotfix：hardcode `orange-*` class 全換 `sela-*`（坑 #16）**。V1.6.0 只改了 `sela-*` 色階定義，但全站有 40 檔 / 237 處用 Tailwind 內建 `orange-*` class（按鈕 / 數字 / 標籤 / active / focus ring），不受 sela 色階影響 → 仍是橘色。全部 `-orange-{N}` → `-sela-{N}`（regex 精確匹配顏色 class）。色階補 `sela-800`(#1E2248) / `sela-900`(#141734) 以對應 orange-800。**保留 56 個 `amber-*`**（飲料分類語義色 + 暖色點綴，與餐廳綠 / 團購藍成套，作為藍紫主色的對比色）。 |
| V1.6.0 | **主視覺換色 + 移除空狀態 logo**。`base.html` 的 `tailwind.config` `sela-*` 色階從橘色系整組換成 `#454c8c` 藍紫系（以 #454c8c 為 500 階，HSL 234°/34%/41%，固定 hue 調明度生成 50~700）— 全站用 `sela-*` class 的按鈕 / active / 連結 / 邊框一次全變藍紫。品牌 logo（`sela-logo.jpg` img）不受 CSS 影響保持橘色；`default-drink.svg` 預設飲料插圖刻意保留橘色（食慾暖色）。滾動條 thumb hardcode `#FDBA74`→`#8E95CC`（新 sela-300）。首頁空狀態橘色大 SELA logo 移除，換成低調 `ti-cup`（sela-400 配 sela-50 圓底）。 |
| V1.5.0 | **emoji 收尾全清 + 底部導航動態 active**。剩餘 52 種 emoji 全站 1:1 替換（33 檔 149 次）：⭐☆→`ti-star` / 📞→`ti-phone` / 💝🩷❤→`ti-heart` / 🗳→`ti-checkbox` / 🙈→`ti-eye-off` / ⏰→`ti-alarm` / 📍→`ti-map-pin` / ⚡→`ti-bolt` / 🎊🥳→`ti-confetti` / 🔥→`ti-flame` / ✓→`ti-check` / 🗺→`ti-map` / ⚠→`ti-alert-triangle` / 🎯→`ti-target` / ➕→`ti-plus` / 🎲→`ti-dice` / 🚀→`ti-rocket` / 🥤→`ti-cup` / 📭→`ti-mailbox` / ❌✕→`ti-x` / 💾→`ti-device-floppy` / 🏆→`ti-trophy` / 📊→`ti-chart-bar` / 📈→`ti-chart-line` / 📂→`ti-folder-open` / 📁→`ti-folder` / 📦→`ti-package` / 👀→`ti-eye` / ⚙→`ti-settings` / 🗑→`ti-trash` / ⏸→`ti-player-pause` / 🔒🔐→`ti-lock` / 🐛→`ti-bug` / 🔄→`ti-refresh` / 🚗→`ti-car` / 🥇🥈🥉→`ti-medal` / 📅→`ti-calendar` / 👑→`ti-crown` / 📜→`ti-scroll` / ⚫→`ti-circle-filled` / 💬→`ti-message` / 🔗→`ti-link` / 🚨→`ti-alert-octagon` / ⏱→`ti-stopwatch`。**保留 `→`（49 次）與 `↑`（1 次）純文字箭頭不換**。另外底部導航改用 `request.url.path` 動態判斷 active（坑 #15）：之前 hardcode「首頁」恆亮，現在依當前頁高亮對應項目（home/votes/feedback/profile，用 `path.startswith` 涵蓋子頁）。**全站零裝飾 emoji 達成**。 |
| V1.4.1 | **Hotfix：未登入訪問需登入頁 → 導向 LINE 登入（坑 #14）**。新使用者用沒登入過的手機直接開 `/home` 看到 `{"detail":"請先登入"}` JSON 而非登入頁。在 `main.py` 加全域 401 例外處理器：瀏覽器開頁面（Accept: text/html 且非 htmx）→ `RedirectResponse` 到 `/auth/login`；htmx/API → 維持 401 JSON。**只動 main.py（加 handler）+ base.html 版本號**。 |
| V1.4.0 | **admin 後台 9 種 emoji → Tabler**。16 檔 37 次替換：🟢→`ti-circle-filled`（保留綠色 inline style）/ 📮→`ti-mailbox` / 💡→`ti-bulb` / 📢→`ti-speakerphone` / 📥→`ti-inbox` / ⏳→`ti-hourglass` / ✨→`ti-sparkles` / ✏→`ti-pencil`（與 V1.3.0 📝 一致）/ 📌→`ti-pin`。🟢 特別處理：用 inline style `color: #22c55e` 保留綠色語義，避免 Tabler 圖示 currentColor 失去狀態色 |
| V1.3.0 | **標題列版本號 + 高頻 emoji 全站 Tabler 化**。base.html 在 `<body>` 後加 `{% set app_version = 'V1.3.0' %}`，「SELA」標題旁顯示 `{{ app_version }}` 灰色小字（10px mono）— 升版只需改 `{% set %}` 一行；標題列 ⚙️ 換 `ti-settings`；全站 37 檔 83 次替換：📋→`ti-clipboard-list`（27 次最多）、👥→`ti-users`、👤→`ti-user`、✅→`ti-check`、🎉→`ti-confetti`、📝→`ti-pencil`、🌐→`ti-world`、🏪→`ti-building-store`。 |
| V1.2.0 | **三大分類圖示全站 Tabler 化 + 底部導航文字對齊**。三大分類 emoji 全站 1:1 替換：🧋 → `<i class="ti ti-cup"></i>`（23 檔 103 次）、🍱 → `ti-bowl`、🛒 → `ti-shopping-cart`。`<i>` 自動繼承外層 span/button 的字級，不需逐處調 size。底部導航另外把 4 個圖示也包進 `w-9 h-9` 容器，所有 `<a>` 區塊高度一致，文字底線對齊。 |
| V1.1.3 | **Hotfix：中央 + 圓圈對齊**。V1.1.0 我把圓圈尺寸從原版 48px 改成 52px 並用 inline style `margin-top: -26px` 試圖配合，但實機上沒生效（圓圈貼底而不是浮出於導航條）。退回原版 `w-12 h-12 -mt-6` 經驗證能用的 Tailwind 寫法，內部 + 字體用 24px。**教訓：不要為了讓 Tabler + 看起來大 4px 就動已驗證 work 的尺寸組合**。 |
| V1.1.2 | **Hotfix：base.html 401 redirect 寫死錯誤 endpoint `/login`，改為 `/auth/login`**（坑 #12）。V1.1.1 部署後使用者用無痕視窗測試踩到 — `/login` 不存在（真實是 `/auth/login`）。base.html 第 57/157/164 行三處 hardcode 全改。**這個 bug 早於 V1.1.x，潛伏多時** — 30 人都用已登入 cookie 從沒被 401 踢過。 |
| V1.1.1 | **Hotfix：Tabler webfont CDN URL 修正**（坑 #11）。V1.1.0 寫的 `cdnjs.cloudflare.com/ajax/libs/tabler-icons/3.7.0/tabler-icons.min.css` 在 cdnjs 上根本不存在（cdnjs 的 tabler-icons 是 2020 年舊 package），改為 `cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.17.0/dist/tabler-icons.min.css`。**只動 base.html 一行**。 |
| V1.1.0 | **北歐風圖示首登場（Tabler Icons 3.17.0）+ favicon 套組串接**。在 `base.html` `<head>` 加 Tabler webfont CDN、`apple-touch-icon` / favicon / webmanifest 四個 link 標籤；底部導航 5 個 emoji（🏠 🗳️ + 📮 👤）換成 Tabler 細線圖示（`ti-home` / `ti-checkbox` / `ti-plus` / `ti-mailbox` / `ti-user`）+「首頁」加 36×36px `bg-sela-50` 圓角方塊強調 active 樣態。**只動 1 個檔案（base.html）**。⚠ 部署後發現 Tabler CDN URL 錯誤造成圖示空白（坑 #11）— V1.1.1 修正。 |
| V1.0.0 | **首次對齊 SELA-Starter-Kit V1.9.0 + Starlette hotfix**。新增根目錄 `CLAUDE.md` / `README.md` / `SELA-handoff.md`；換用 Kit 標準 `.gitignore`；加入完整 favicon 套組到 `app/static/favicon/`；移除 commit 進去的 `.DS_Store` 與重複的 `gitignore`（無點）；**`requirements.txt` 從 `>=` 改為 `==` 精確鎖版本**（坑 #10 救火）。**零業務邏輯變更** — 純文件 / 資產對齊 + 依賴鎖版本。 |
| 對齊前 | （無正式版號制度）30 人線上運作中；功能含 LINE Login、店家／菜單／團單／訂單 CRUD、甜冰選項、加料系統、QR Code 分享、部門系統、公告、投票、消費統計、JSON 匯入 |

> 規則：超過 10 版砍最舊的，搬到 README.md。

---

## 七、下版候選工作（按優先序）

> **emoji 全站清除已完成（V1.1.0~V1.5.0）。** 以下為功能性 backlog。

1. **匯入價格容錯**（V1.7.0 預告的下一步）— `schemas/menu.py` + `import_service.py` 處理「時價」「$30」「30元」「全形數字」等非純數字輸入：能解析的自動轉（$30→30），不能解析的（時價）給明確提示或存為 0 + 標記。單獨做、單獨測，不跟其他混
2. **27 處 `TemplateResponse` 改新 API**（解坑 #10 的長期方案）— 把 `TemplateResponse("name.html", {"request": request, ...})` 改成 `TemplateResponse(request, "name.html", {...})`，改完才能放寬 `requirements.txt` 版本鎖，享受套件安全更新
2. 訂單匯出 Excel — 原本 backlog（見 `docs/SELA-開發指導手冊.md`「待開發」）
3. 外送費分攤功能 — `scripts/DELIVERY_FEE_CHANGES.py` 已有設計稿
4. 多尺寸定價 — 之前因 bug 回滾過，重做注意 schema 三方對齊
5. ~~菜單匯入開放 group_buy category~~（✅ V1.10.2 已解坑 #9）
6. 評估把 `taipei` filter 抽到共用 templates 模組（解坑 #6，評估重構成本）
7. 整體視覺巡檢 — (a) emoji 換 Tabler 後檢查圖示大小 / 對齊 / 顏色語義；(b) **V1.6.0 換主色後巡檢**：原本搭配橘色設計的局部（如分類篩選按鈕 amber/green/blue、各種 hardcode 顏色）在藍紫主色下是否協調；admin 統計數字色（橘/紫/綠/藍）是否需重新搭配

## 八、升版必讀

### 版本號管理（V1.3.0 起）

- 版本號定義在 `app/templates/base.html` 的 `{% set app_version = 'VX.Y.Z' %}`（緊跟 `<body>` 標籤）
- 升版時**只需改這一行**，所有頁面標題列自動更新
- **升版 SOP：**
  1. 改 `base.html` 內 `{% set app_version = ... %}`
  2. 改 `CLAUDE.md` 第〇章「當前狀態」的版本字串
  3. `CLAUDE.md` 第六章「版本歷程」加新一列
  4. 打包 zip 命名 `Online-Drink VX.Y.Z.zip`
- 未來若要做 `/version` API endpoint，把 `APP_VERSION` 移到 `app/config.py` 並用 context_processor 注入 templates

### V1.1.0 部署動作

- [ ] 用 Git Pusher 匯入 `Online-Drink V1.1.0.zip` 上 GitHub
- [ ] **不需要動 Railway Variables**（沒改任何環境變數）
- [ ] **不需要動第三方 Console**
- [ ] **不需要跑 migration**（沒改 schema）
- [ ] **不需要重新解析依賴樹**（沒改 requirements.txt），Railway redeploy 較快（30-60 秒）
- [ ] 部署後驗收：
    - 用無痕視窗訪問 `/home`，確認底部導航顯示 5 個 Tabler 細線圖示（不是 emoji）
    - 確認「首頁」圖示底下有淡橘色 `bg-sela-50` 圓角方塊背景
    - 點中央橘色大圓圈 → 應導向開團頁
    - 瀏覽器分頁標題列／書籤應顯示 SELA logo（favicon 生效）
    - iOS 加到主畫面測試：圖示應為 Kit 標準 SELA 圖示

### 風險提醒

- 首次依賴 Tabler webfont CDN（`cdnjs.cloudflare.com`），若 CDN 故障圖示會變空白 — 不影響功能但會難看。Cloudflare CDN 全球可用性極高，風險可接受
- **底部導航 active 樣式仍 hardcode 寫死「首頁」恆亮**（V1.0.0 既有設計沿用，V1.1.0 沒動）— 在 /votes / /feedback 等頁面也會看到「首頁」是亮的。列入下版候選 #9

---

## 九、一句話總結

V1.0.0~V1.5.0 完成了從「對齊 Kit」到「全站 emoji 北歐風 Tabler 化」的完整視覺升級，途中救了多個生產 bug（Starlette 版本破壞、CDN URL 錯誤、登入路由前後端兩面、底部導航對齊與 active）。**全站零裝飾 emoji 達成**，標題列有版本號可即時辨識運行版本。下一步建議轉向功能性 backlog（#1 TemplateResponse 新 API 最優先，解除版本鎖）。