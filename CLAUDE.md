# CLAUDE.md — SELA 快點來點餐（線上訂餐）

> **⚠ 給同時拿到 SELA-Starter-Kit 的 Claude：**
> 這是**已對齊 Kit V1.9.0 的成熟線上專案**（30 人團隊每日使用），不是新專案。
>
> 衝突仲裁規則：
> 1. **以本專案 CLAUDE.md 為主、Kit 為輔**
> 2. 本專案刻意不對齊 Kit 的部分：
>    - **不使用 Alembic**（Kit `tech-stack-lessons.md` 1.1 建議第一天就 `alembic init`） — 本專案已用「SQLAlchemy `create_all` + 手動 raw SQL 遷移 + `ADD COLUMN IF NOT EXISTS` 模式」運作超過一年，30 人線上穩定。改用 Alembic = 風險大於收益，且過去引入 Alembic 造成過部署失敗（坑 #1）。
>    - **PostgreSQL Enum 值固定大寫**（坑 #2 持續警戒）
>    - **logo 同時用兩套**：`app/static/images/sela-logo.jpg|svg`（4 個現有模板沿用中）與 `app/static/sela.svg` + `favicon/` 套組（Kit 標準，V1.1.0 已串接到 base.html `<head>`）。既有引用不動。
> 3. **不要為對齊 Kit 而動既有設計** — 已驗證的就是事實標準
> 4. 版號規則照 Kit（部署版無後綴、備份版 -source）
> 5. **下次完成版本時記得評估 SELA-handoff.md**（鐵律 #0 — 完整見 Kit master CLAUDE.md）

> **這份文件是給下次 Claude 看的工作上下文，不是文件。**
> 判斷標準：下次 Claude 讀完，能不能直接動手？
> 維護章法見 `SELA-Starter-Kit/conventions/CLAUDE-MD-章法.md`，每次升版前複習。
> 每升一版至少更新三處：踩過的坑、版本歷程、下版候選工作。

---

## 〇、當前狀態

- **版本：** V1.13.3（主題色換 #7528d4 低彩度紫）
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