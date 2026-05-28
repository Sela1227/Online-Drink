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

- **版本：** V1.2.0（三大分類圖示全站 Tabler 化 + 底部導航文字對齊）
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

1. **V1.3.0：剩餘高頻 emoji → Tabler**（📋 19 檔 / 👥 11 檔 / 👤 9 檔 / ✅ 8 檔 / 🎉 7 檔 / 📝 6 檔 / 🌐 6 檔 / 🏪 6 檔 等）。同樣 1:1 替換策略，每個 emoji 自動繼承外層字級
2. **V1.4.0：admin 後台系統圖示**（管理用：⚙ ✏ 💾 🗑 ➕ 📁 等）— 你自己後台用，順序排在用戶可見之後
3. **V1.5.0：其餘 emoji 全清**（投票 🗳 / 慶祝 🎊 🎉 / 警告 ⚠ / 鎖 🔒 等收尾）
4. **27 處 `TemplateResponse` 改新 API**（解坑 #10 的長期方案）— 改完才能放寬 `requirements.txt` 版本鎖
5. 訂單匯出 Excel — 原本 backlog
6. 外送費分攤功能 — 原本 backlog；`scripts/DELIVERY_FEE_CHANGES.py` 已有設計稿
7. 多尺寸定價 — 之前因 bug 回滾過，重做注意 schema 三方對齊
8. 菜單匯入開放 `group_buy` category（解坑 #9）
9. 動態判斷底部導航 active 頁面（V1.1.0 仍 hardcode「首頁」恆亮）— 改要用 `request.url.path` 判斷
10. 評估是否要把 `taipei` filter 抽到共用 templates 模組（解坑 #6，但要評估重構成本）
11. V1.1.2 的 `/auth/login` 修正尚未實機驗證 — 等下次自然踩到再確認

---

## 八、升版必讀

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

V1.1.0 開始視覺風格升級 — base.html 底部導航 5 個 emoji 換成 Tabler 北歐風細線圖示 + 順手串接 V1.0.0 留下的 favicon 套組。**只動 1 個檔（base.html），所有業務邏輯零變更**。下版第一優先：**V1.1.1 改三大分類圖示（🧋 🛒 🍱）**，整站視覺風格就會統一八成。
