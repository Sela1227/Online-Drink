# CLAUDE.md — SELA 快點來點餐（線上訂餐）

> **⚠ 給同時拿到 SELA-Starter-Kit 的 Claude：**
> 這是**已對齊 Kit V1.9.0 的成熟線上專案**（30 人團隊每日使用），不是新專案。
>
> 衝突仲裁規則：
> 1. **以本專案 CLAUDE.md 為主、Kit 為輔**
> 2. 本專案刻意不對齊 Kit 的部分：
>    - **不使用 Alembic**（Kit `tech-stack-lessons.md` 1.1 建議第一天就 `alembic init`） — 本專案已用「SQLAlchemy `create_all` + 手動 raw SQL 遷移 + `ADD COLUMN IF NOT EXISTS` 模式」運作超過一年，30 人線上穩定。改用 Alembic = 風險大於收益，且過去引入 Alembic 造成過部署失敗（坑 #1）。
>    - **PostgreSQL Enum 值固定大寫**（坑 #2 持續警戒）
>    - **logo 仍使用 `app/static/images/sela-logo.jpg|svg`**（4 個現有模板引用中） — V1.0.0 加入了 Kit 完整 favicon 套組到 `app/static/favicon/`，但 base.html 尚未串接，列為下版候選
> 3. **不要為對齊 Kit 而動既有設計** — 已驗證的就是事實標準
> 4. 版號規則照 Kit（部署版無後綴、備份版 -source）
> 5. **下次完成版本時記得評估 SELA-handoff.md**（鐵律 #0 — 完整見 Kit master CLAUDE.md）

> **這份文件是給下次 Claude 看的工作上下文，不是文件。**
> 判斷標準：下次 Claude 讀完，能不能直接動手？
> 維護章法見 `SELA-Starter-Kit/conventions/CLAUDE-MD-章法.md`，每次升版前複習。
> 每升一版至少更新三處：踩過的坑、版本歷程、下版候選工作。

---

## 〇、當前狀態

- **版本：** V1.0.0（首次對齊 Kit V1.9.0 規範 + 含 starlette hotfix）
- **狀態：** 上線中（30 人團隊每日使用）
- **線上網址：** https://online-drink-production.up.railway.app
- **一句話定位：** LINE Login 認證的團體飲料／餐點／團購訂餐系統，給彰濱秀傳特定團隊每日揪團用。
- **技術棧：** Python 3.11 + FastAPI 0.104.1 + Starlette 0.27.0 + SQLAlchemy 2.0.23 + PostgreSQL + Jinja2 3.1.2 + Tailwind（CDN）+ Alpine.js + HTMX
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
| V1.0.0 | **首次對齊 SELA-Starter-Kit V1.9.0 + Starlette hotfix**。新增根目錄 `CLAUDE.md` / `README.md` / `SELA-handoff.md`；換用 Kit 標準 `.gitignore`；加入完整 favicon 套組到 `app/static/favicon/`；移除 commit 進去的 `.DS_Store` 與重複的 `gitignore`（無點）；**`requirements.txt` 從 `>=` 改為 `==` 精確鎖版本**（坑 #10 救火）。**零業務邏輯變更** — 純文件 / 資產對齊 + 依賴鎖版本。 |
| 對齊前 | （無正式版號制度）30 人線上運作中；功能含 LINE Login、店家／菜單／團單／訂單 CRUD、甜冰選項、加料系統、QR Code 分享、部門系統、公告、投票、消費統計、JSON 匯入 |

> 規則：超過 10 版砍最舊的，搬到 README.md。

---

## 七、下版候選工作（按優先序）

1. **27 處 `TemplateResponse` 改新 API**（解坑 #10 的長期方案）— 把所有 `TemplateResponse("name.html", {"request": request, ...})` 改成 `TemplateResponse(request, "name.html", {...})`，改完就能放寬版本鎖。**為什麼是第 1 名：** 坑 #10 是定時炸彈，目前靠鎖版本擋住，但鎖版本意味著未來無法享受套件安全更新與新功能
2. **base.html 串接 Kit favicon 套組** — V1.0.0 只把資產放進 `app/static/favicon/`，但 `base.html` 還沒加 `<link rel="icon">`。串接後瀏覽器分頁會顯示 SELA logo
3. 訂單匯出 Excel — 原本就在 backlog（見 `docs/SELA-開發指導手冊.md`「待開發」）
4. 外送費分攤功能 — 原本就在 backlog；`scripts/DELIVERY_FEE_CHANGES.py` 已有設計稿
5. 多尺寸定價 — 之前因 bug 回滾過，重做時注意 schema 三方對齊
6. 菜單匯入開放 `group_buy` category（解坑 #9）
7. 評估是否要把 `taipei` filter 抽到共用 templates 模組（解坑 #6，但要評估重構成本）

---

## 八、升版必讀

V1.0.0 屬「文件對齊 + 依賴鎖版本」 → **有部署注意事項**：

### V1.0.0 部署動作

- [ ] 用 Git Pusher 匯入 `Online-Drink V1.0.0.zip` 上 GitHub
- [ ] **不需要動 Railway Variables**（沒改任何環境變數）
- [ ] **不需要動第三方 Console**（LINE / Cloudinary callback 都沒變）
- [ ] **不需要跑 migration**（沒改 schema）
- [ ] Railway 自動 redeploy 時會抓鎖版本依賴（**約 60-120 秒** — 比 cold start 慢，因為要重新解析鎖死的依賴樹）
- [ ] 部署後驗收：
    - 訪問 `/` 確認首頁正常（不再 500）
    - 用無痕視窗走一次 LINE Login
    - 進一個團單頁面確認訂單牆正常
    - Railway log 應該 0 個 `TypeError: unhashable`

### 風險提醒

- **這次部署會觸發 Railway 抓全新依賴樹（鎖版本第一次拉）**，cold start 較慢
- 如果部署失敗，Railway 會保留舊 container 繼續服務（fallback 機制），不會中斷 30 人使用
- 失敗時看 Railway deploy log，常見原因：套件版本被 PyPI 撤下（極少見）→ 改用 `==` 接近版本

---

## 九、一句話總結

V1.0.0 完成了首次對齊 SELA-Starter-Kit V1.9.0，**並順便救了一次 Starlette 升版破壞 API 的緊急 bug**（坑 #10 — `requirements.txt` 鎖版本）。**下版第一優先：27 處 `TemplateResponse` 改新 API**，徹底解決坑 #10 後就能放寬版本鎖。
