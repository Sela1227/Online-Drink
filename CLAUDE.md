# CLAUDE.md — SELA 快點來點餐（線上訂餐）

> **⚠ 給同時拿到 SELA-Starter-Kit 的 Claude：**
> 這是**已對齊 Kit V2.7.0 的成熟線上專案**（V2.34.1 落差對齊；前一次 V2.30.0 對齊 V2.3.0）（30 人團隊每日使用），不是新專案。
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
> 6. **優化體檢**：V1.16.0 對照 4 條 OPT 無中招；V2.17.0 補看 OPT-5／OPT-6 當時不適用。**V2.30.0 重看**（V2.25.0 起有呼叫 LLM，OPT-6 變成技術相關）：**OPT-6「assistant 預填 `{`」刻意不做**——`claude-sonnet-5-5` 等 Claude 4.6 以後的模型會拒絕最後一則是 assistant 的請求（400），照做整個拍照轉換會壞；現有做法是 `extract_json_text()` 去圍籬＋匯入 Pydantic 驗證＋預覽，等效。OPT-4（生成後自我驗證）已等效（AI 結果照舊走自動檢查、`"?"` 擋下、人看預覽才確認）。OPT-3（outbox）不適用：AI 轉換與照片上傳都要同步拿結果。OPT-1／2／5 不適用。**6 條中 0 項可升級**，下次 Claude 不要「補上」預填。
> 7. **對齊歷程**：V1.0.0 首次對齊 Kit V1.9.0；V1.16.0 升級至 Kit V1.18.0；**V2.17.0 落差評估 Kit V1.18.0→V1.36.0（18 個 b 版，走 claude-init 二章「已對齊過但 Kit 跳版」）**——區間新坑逐條核對本專案：#61 UI 改名只改顯示文字（V2.17.0 用語統一照此做：`pending_count`／`DRAFT` 等變數不動）；#64/#65 測試 baseline（煙霧測試每版先跑原始檔）；#81 假完成訊號（jsdom 檢查「跳過」不算通過，已在 handoff 列為防線）；#86 外部輸入過 schema（匯入已走 Pydantic）；#88 舊網址永遠公開（V2.17.0 舊路由一律 302 轉址、不留裸頁）；#90 自我描述文案同步（**這次真正撿到的舊債**：README 還寫 `docs/` 有四份規範、版尾停在 V1.0.0／Kit V1.9.0，已修；自我描述清單＝README 功能段＋目錄樹＋版尾，升版 SOP 第 10 步）；#92 `async def` 裡同步 DB 呼叫——本專案全站如此（審核 P2-F3 已列），3 workers／30 人規模可承受，列為「不做，理由：改法是全站 `def` 或 threadpool，屬長工重構」。交付格式改用 Kit V1.36.0 的回報格式（✓ 已交付／技術棧／主要功能／下版第一優先／§3 鐵律逐條核對／handoff 評估）。**V2.30.0 落差評估 Kit V1.36.0→V2.3.0**：區間新坑 #93～#112 逐條核對——**#108**（相容轉址用 302）中了兩處 301（`/admin/stores/{id}/edit`、`/menus`），已改 302；**#111**（模型 ID 會過期）已集中在 `config.anthropic_model`（可用 Railway `ANTHROPIC_MODEL` 換），補坑 #52 記查證日；#112（非同步回應寫回時對象已換人）——匯入預覽有 `src_digest` 核對（坑 #41）、AI 結果只填輸入框還要人確認，等效；#95（SPA 換頁回頂）、#105（狀態 class 撞名）——SSR 多頁＋Tailwind 工具類，不適用；#93／#94／#96～#104／#106／#107／#109／#110 是 Cloudflare、外掛化、爬蟲、Web Push 情境，不適用。新鐵律「版號在 logo／app 名稱旁」→ Sela 選加回頁首小字（V2.17.0 曾拿掉）；「直接部署的專案要同步本機 source」→ 本專案走 Git Pusher→GitHub→Railway，不適用。營運 log 用 `print`（Deploy Logs 直接看、9 處都是刻意的上線紀錄）→ 不改，不算 debug print（**V2.34.1 改成 `logging`**：錯誤與稽核訊息有等級與時間，Deploy Logs 照樣看得到；只留啟動那行 `print`，煙霧第 39 節與 Sela 看部署靠它）。**V2.34.1 落差對齊 Kit V2.3.0→V2.7.0（4 個 b 版；Sela：「對齊 kit」）**——區間新坑 #113～#135 逐條核對：#132（邀請連結先要登入）中但**不做**——LINE 登入就是身分，團員都是 30 人內部同事、首次點開本來就要 LINE 授權；#123（grid 1fr 撐寬）Tailwind `grid-cols-N` 本來就是 `minmax(0,1fr)`；#128（同一句先開寫再讀）掃過 scripts 沒有；#130（data-* 拼分隔符再 split）沒有；#131／#134（hash 路由分享、SW 快取 `/`）——SSR 真路徑、沒有 Service Worker；其餘是爬蟲、canvas 分享卡、Cloudflare Tunnel、單檔 SPA 情境，不適用。新鐵律「不加標語／副標／控制項下的小字」→ Sela 選**全站掃一遍**：94 處灰色小字逐條分類，拿掉 11 處純說明（「點了帶入選項」「點了捲到品項」「點下面菜單的品項，選好就點好了」「結帳金額自動重算」「對方點開後用自己的 LINE 登入就能一起點餐」「修改團單」下的欄位清單、訂單牆「點跟單直接加進你的訂單」、開團頁「N 家可選」「代購已選卡的說明」「常開同一家？…存成範本」），**留著的都有資訊量**（改了只影響之後開的團、進行中的團用開團時的版本、每張卡片各自儲存、候補數量跟隨主品項、刪除不可復原、外送費自動分攤、上限「允許超過」說明、只有你看得到、三種匯出各自內容、「截止 HH:MM 前都能改 · 不用再按送出」——最後這句的「不用再按送出」是 S-2 過渡期提醒，上線一兩週後可拿）；**之後新畫面照這條**。新規範「介面預覽用 Fold 8 外螢幕約 412px 一張，會在內螢幕用的再補約 920px 一張」→ 之後畫面稿照做（V2.32～V2.34 的稿是 375px）；團頁與後台內容區本來就 `max-w-lg` 置中，內螢幕不會撐開。「院內封鎖 GitHub」→ 本專案網址在 railway.app、CDN 是 unpkg／jsdelivr／cdnjs／cdn.tailwindcss.com，院內照常使用中；GitHub 只在 Sela 的 Mac 推版，不受影響。優化體檢 OPT-1～7：OPT-7（介面 emoji→線條圖示）早就是 Tabler 線條圖示，等效；其餘沿用 V2.30.0 結論，**0 項要換**。舊債：Kit 回饋檔 `SELA-handoff.md` 停在 V2.30.0（V2.31～V2.34 累積坑 #53～#56 早該產，坑 #57）、README 目錄樹根寫中文「線上訂餐/」且漏列兩個檔、交班檔開頭寫「附上 V2.33.0.zip」——都補了。
> 8. **英文程式名** = Online-Drink、中文俗稱 = 快點來點餐；app logo = ORDER 奶茶版（V1.20.1，`SELA-logo-prompt.md`）；品牌仍算 SELA 個人專案（未交醫院 IT）。

> **這份文件是給下次 Claude 看的工作上下文，不是文件。**
> 判斷標準：下次 Claude 讀完，能不能直接動手？
> 維護章法見 `SELA-Starter-Kit/conventions/CLAUDE-MD-章法.md`，每次升版前複習。
> 每升一版至少更新三處：踩過的坑、版本歷程、下版候選工作。

---

## 〇、當前狀態

- **版本：** V2.36.0（點餐頁版面整理〔內部審核 R-1～R-12、G-4～G-9〕：菜單在前、我的訂單改底部抽屜、標頭兩行＋資訊 sheet、品項上標已點 ×N 與熱門火焰、結帳列三狀態、超過上限先擋、團主預設甜冰標示、價格一行、抽屜 Esc／返回鍵。前一版 V2.35.1：內部審核 V2.35.0 點餐頁的立即修：加點被擋下不再說已點好〔G-1，P0〕、倒數歸零自動重整〔G-2〕、團主列金額拆餐點＋外送〔G-3〕。前一版 V2.35.0：店家菜單照片〔管理員在工作台上傳、團頁菜單上方一排縮圖、店家頁也看得到、匯入頁可順便存〕；部門加人與人員頁標出同名帳號。前一版 V2.34.2：說明文字再精簡：32 處縮短或拿掉，只留會影響結果的提醒。前一版 V2.34.1：對齊 Kit V2.7.0：全站拿掉 11 處說明小字、錯誤訊息改 logging、補產 Kit 回饋檔；不動功能。前一版 V2.34.0：總表第四批：開團一進來就選店、首頁空狀態列常開的店、匯入頁一個貼上區、人員頁搜尋框、工作台分頁 4→3；含 V2.31.1～V2.33.0 尚未上線的修正。前一版 V2.33.0：S-2 取消草稿購物車：點了就是訂單、我的訂單就地加減、已點後再加點直接併入、上次點的一鍵點餐＋復原；含 V2.31.1～V2.32.0 尚未上線的修正。前一版 V2.32.0：總表第二批：管理員就地改價格、後台拿掉底部導航、常用區、開團鈕貼底、toast 不壓購物車；含 V2.31.1／V2.31.2 尚未上線的修正。前一版 V2.31.2：內部審核未完成事項總表第一批：拿掉送出確認框、常點文案、Excel 公式注入、Alpine 鎖版；含 V2.31.1 尚未上線的修正。前一版 V2.31.1：內部審核 V2.31.0 修正：複製上次訂單杯型對應〔別名＋同位置＋提示〕、送出後畫面更新〔B-1〕、團頁 N+1 145→22 條 SQL、匯入容錯；V2.31.0 已於 2026-11-04 上線。前一版 V2.31.0：杯型規格 variants：品項可有任意個規格〔中杯／大杯／特大杯、Solo／Doppio、L杯／瓶裝〕、標籤照菜單；舊菜單維持 M／L；品項可設不提供加料；與 V2.30.1 一起上線。前一版 V2.30.1：菜單匯入回饋 2026-11-04 小修：改價模式列出加價選項、AI 指令補「只有大杯」、坑 #9 改寫。下一版 V2.31.0 杯型規格〔variants〕重構，見第七章。前一版 V2.30.0：對齊 SELA Kit V2.3.0：頁首 app 名稱旁加回版號、相容轉址 301→302〔Kit 坑 #108〕、AI 模型 ID 查證〔坑 #52〕、Kit 反饋 handoff。前一版 V2.29.0：刪除店家改確認框〔不用再輸入店名〕；外部審稿 V2.28.0：工作台直接改價〔存成新版本〕、摘要只留三顆、切分頁保留網址 #欄位、存檔回到卡片並寫已儲存、改了沒存就離開會提醒、手機店家列表加「菜單」鈕、問題數跟著分類搜尋算。前一版 V2.28.1：PWA 名稱改「快點來點餐」；Railway develop 環境移除〔待 Sela 在網頁按套用〕。前一版 V2.28.0：內部審核 V2.27.0 全部處理：回報頁可複製並分待處理／已處理、清除測試團改「沒有已送出訂單」並以畫面清單為準、推薦改「建立店家與菜單」確認時才建店、公告原地展開編輯、拿掉訪客／重複用戶診斷／部門小組長／分店編輯、團單頁預設近 14 天、長度與部門驗證。前一版 V2.27.0：外部 UI 審稿：後台首頁改待處理／常用／管理、店家列表拿掉巢狀連結、清除測試團移到維護區並先列清單、工作台加可點摘要。前一版 V2.26.0：版本號改單一來源 app/version.py；店家縣市＋「我會訂的縣市」篩選；排序加「最新加入」。前一版 V2.25.0：新推薦提醒：管理員首頁卡＋「我的」紅點；站內拍照轉成菜單〔Claude API，只有 ADMIN_LINE_USER_ID 能用〕；新增店家一律走匯入。前一版 V2.24.0：匯入時一併建立照片上的店家電話與地址；既有店家只補空白、不覆蓋。前一版 V2.23.2：外部審核修正：我的訂單可見性、跨站寫入檢查、同名店家排除代購店、候補順位鎖＋唯一約束、遷移錯誤不啟動、PostgreSQL 並行測試腳本。前一版 V2.23.1：LINE 登入迴圈）
- **狀態：** 上線中（30 人團隊每日使用；線上 V2.35.0，2026-11-09 上線，Railway 讀回確認）
- **線上網址：** https://online-drink-production.up.railway.app
- **一句話定位：** LINE Login 認證的團體飲料／餐點/團購訂餐系統，給彰濱秀傳特定團隊每日揪團用。
- **技術棧：** Python 3.11 + FastAPI 0.143.2 + Starlette 1.8.0 + SQLAlchemy 2.0.23 + PostgreSQL + Jinja2 3.1.6 + PyJWT 2.15.1 + Tailwind（CDN）+ Alpine.js + HTMX + **Tabler Icons 3.17.0 webfont（jsDelivr CDN，V1.1.1）**
- **部署：** Railway（Dockerfile 模式，不用 Nixpacks／Railpack；**以服務設定為準**，railway.toml 2026-12-01 起不再被讀，坑 #44）
- **認證：** LINE Login
- **圖片上傳：** Cloudinary
- **入口點：** `app/main.py`（FastAPI app；lifespan 呼叫 `app/migrations.py::run_migrations`）

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
| 「三狀態訂單」（V2.33.0 起實際只用兩態：沒點／已點） | `OrderStatus` Enum：`DRAFT`＝空的、`SUBMITTED`＝已點；`EDITING` 只剩相容（坑 #55） | `app/models/order.py` |
| 「Taipei 時區顯示」 | `taipei` Jinja filter | **每個 router 自己註冊**（坑 #6） |

> 改這張表 = 動 model + Pydantic schema + 前端解析 + Raw SQL 四處，務必同步（坑 #1 三方對齊原則）。

---

## 三、關鍵檔案路徑

| 想改什麼 | 動哪些檔 |
|---------|---------|
| 啟動順序 / 自動遷移邏輯 | `app/main.py` lifespan → `app/migrations.py`（新欄位加進 `COLUMNS` 清單最後；手動跑 `scripts/migrate.py`） |
| 環境變數 / 設定 | `app/config.py`（Pydantic Settings） |
| 資料庫連線 | `app/database.py` |
| LINE Login 流程 | `app/routers/auth.py` + `app/services/auth.py`（JWT） |
| 後台店家／菜單管理 | `app/routers/admin.py` + `templates/admin/*.html`；店家工作台 `admin/store_workbench.html`（V2.29.0 菜單分頁可直接改價 `#price-editor` → `POST /stores/{id}/menu/prices`；刪店確認框 `#del-store-dialog`；分頁：菜單／甜冰加料 `#tab-options`（甜冰 `tagEditor()`、加料 `toppingEditor()` → `POST /stores/{id}/toppings/batch`）／店家資料 `#tab-settings`／停用／刪除；頂部摘要 `#wb-summary`）；公告 `admin/announcements.html`（V2.28.0 原地展開，`?open=id`）；回報 `admin/feedbacks.html`；推薦 → `/admin/import?rec_id=`（確認匯入時 `_mark_recommendation_approved` 才建店核准） |
| 團單建立／詳情／關團 | `app/routers/groups.py` + `templates/group_*.html`；團頁 `group.html`（V2.36.0 起）開放中：標頭 `#group-header`（兩行＋右上「資訊」→ `#info-sheet`：電話地圖平台、收藏 `#fav-btn`、我請客、詳細表、菜單更新日）→ 團主列 `#owner-bar`（「名單 ›」`openWall()`）→ 上次點的 → 菜單 `#menu-section`（導覽 `#menu-nav` 常點＋分類＋骰子；`#quick-mine` 你的常點；品項 `partials/menu_item.html`：熱門 `data-hot` 火焰、已點 ×N 讀 `orderedQty`）→ 訂單牆 `#order-wall`（`partials/order_wall.html`，折扣工具截止後才有）→ 結帳列 `#checkout-bar`（三狀態；候補 `#backup-bar`）→ 抽屜 `#mine-sheet`（`#my-order-content` 放 `partials/my_order.html`，`data-cart-count/total/ordered`）→ 加點 sheet `#add-item-sheet`（`overLimit()`、`sizeSummary()`、團主預設 `data-owner-default`）→ 分享／更多 sheet、QR（團主區）。sheet 共通行為在 orderPage `sheetKeys`／`init()`（Esc、背景鎖、pushState、focus）。已截止：標頭 → `#next-steps` → 我的訂單卡 → 訂單牆 |
| 訂單 CRUD | `app/routers/orders.py` + `routers/orders_extra.py` |
| JSON 匯入 | `app/services/import_service.py` |
| Cloudinary 上傳 | `app/routers/admin.py`（圖片相關端點） |
| 首頁 / 店家分頁 / 紀錄分頁 / 我的 | `app/routers/home.py`（`_home_context`／`split_home_groups`／`store_catalog_context`／`records_page`）+ `templates/partials/home_groups.html`、`stores.html`、`records.html`（＋`partials/records_tabs.html`）、`profile.html` |
| 底部導航 / 頁首 | `app/templates/base.html`（`nav_items` 五格、active 規則；`{% block bottom_nav %}` 讓團頁覆寫成空） |
| 訂單牆 | `templates/partials/order_wall.html` |
| Railway 設定 | **Railway 服務 Settings（準）**、`Dockerfile`、`start.sh`；`railway.toml` 只剩對照用（坑 #44） |
| 依賴版本（**鎖死**，坑 #10） | `requirements.txt` |
| 部署排除清單 | `.gitignore`（V1.0.0 對齊 Kit 模板） |

---

## 四、踩過的坑（編號累積，永不重排）

> **三段式**：症狀 → 原因 → 做法。
> 環境/語法類放前面，業務邏輯類放後面。

1. **Alembic 在 Railway 部署造成失敗**
   - 症狀：`railway.toml` startCommand 包含 `alembic upgrade head` 時，部署多次 timeout 或 schema 衝突；引入 alembic 套件導致 build 變慢且偶發失敗
   - 原因：本專案 schema 演進量小、SELA 一人開發、Railway cold start 對額外指令敏感
   - 做法：**完全不用 Alembic**；`requirements.txt` 不裝 alembic；schema 變更走 raw SQL：V2.23.0 起集中在 `app/migrations.py`（先查 inspector 再 `ADD COLUMN`、`ALTER TYPE ... ADD VALUE IF NOT EXISTS`，PostgreSQL advisory lock 互斥）。**與 Kit FastAPI 預設衝突，已在衝突仲裁區塊明寫。**

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

9. **~~菜單分類不支援 `group_buy`~~（V1.10.2 已解；V2.30.1 依菜單匯入回饋改寫，避免下次 Claude 照舊條目叫人先用 meal 匯入）**
   - 當時症狀：JSON 匯入 `Input should be 'drink' or 'meal'`；原因是 `StoreImport.category` 的 Literal 漏了 `group_buy`
   - 現況：三種分類都能直接匯入，`group_buy` 不用再繞 meal（煙霧第 45 節守這行不再寫成現況）

10. **`requirements.txt` 浮動版本造成 Starlette 新版破壞 API**（⚠ **強烈建議回流 Kit**）
    - 症狀：2026-05-28 Railway 自行 rebuild 時，所有 HTTP 請求 500；log 顯示 `TypeError: unhashable type: 'dict'`，發生在 jinja2 `_load_template`，呼叫處是 `templates.TemplateResponse("login.html", {"request": request})`
    - 原因：`requirements.txt` 全部用 `>=` 沒鎖版本。Starlette 在 0.32+ 改了 `TemplateResponse` 位置參數順序（request 變第一個），舊寫法 `TemplateResponse("name.html", {"request": request})` 失效 — 新版把字串當 request、把 dict 當 template name；jinja2 拿 dict 當快取 key 就拋 unhashable
    - 影響範圍：全專案 27 處 `TemplateResponse` 都是舊寫法
    - 做法（已套用）：**`requirements.txt` 全部改 `==` 精確版本**，鎖在 2023 年版（starlette==0.27.0 + fastapi==0.104.1 + jinja2==3.1.2 等）。Railway fallback 機制保留舊 container，所以 rebuild 失敗時服務沒中斷，但下次重啟若沒 fallback 就會真壞
    - 長期方案：下版改 27 處為新 API `templates.TemplateResponse(request, "name.html", {...})`，再放寬版本鎖
    - **✅ V2.22.0 完成**：實數 54 處全改新寫法，升到 fastapi 0.143.2／starlette 1.8.0 並照樣全部 `==` 鎖死（鎖版本的原則不變，只是鎖在新版）；煙霧測試第 33 節用 AST 守「第一參數是 request」

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

24. **批次刪行的錨點若是縮排較深那行的子字串，assert 會假性通過**（V2.10.0 踩到）
    - 症狀：移除 `_sync_announcement_from_active(db)` 五個呼叫點後，`py_compile` 報 `IndentationError: unexpected indent`
    - 根因：錨點寫 `"    _sync_announcement_from_active(db)\n"`（4 空格），但其中四處實際是 8 空格縮排（在 `if ann:` 區塊內）。4 空格版是 8 空格版的**子字串**，`str.replace` 從第 5 個字元起匹配成功，只削掉後半段，留下孤兒的 4 個空格黏上下一行，害 `db.commit()` 變成 12 空格。`assert count == 5` 因此通過——它數到的是「1 個真 4 空格 + 4 個假匹配」
    - 做法：**縮排敏感的整行刪除，錨點一律連同前一行（或後一行）一起寫**，例如 `"        ann.is_active = not ann.is_active\n        _sync...(db)\n"`。只靠單行內容當錨點時，若該行可能出現在不同縮排層級，assert 完全不保護。收尾一定要 `py_compile`，光看 assert 全過不代表沒事
    - 延伸：這是 V2.8「多行替換注意 try 縮排」的同一族問題，但更陰險——那次是縮排沒補上，這次是 assert 說謊

25. **`deadline` 是台北牆上時間，不是 UTC — 拿 `utcnow()` 比會差 8 小時**（V2.10.1 修正，外部增補審稿抓到）
    - 症狀一：「清除測試團」對當天剛截止的團完全沒反應，要等 8 小時後才清得掉，管理員會以為功能壞了
    - 症狀二：飲料選項的「有 N 個進行中的團」警告高估，已截止 8 小時內的團仍被算成進行中
    - 根因：`groups.deadline` 存的是**台北牆上時間的 naive datetime**（見 `Group.is_expired` 的原始寫法），但 `announcements.expires_at`、`orders.created_at` 等欄位存的是 **UTC**。同一個 codebase 兩套慣例並存，寫新查詢時選錯只是機率問題——V2.10.0 就是在修完公告時區問題的**同一批程式碼裡**又犯了一次
    - 做法：`app/models/group.py` 新增模組級 `taipei_now()`，`Group.is_expired` 也改用它成為單一來源。**凡是比對 `deadline` 一律用 `taipei_now()`，永遠不要用 `utcnow()`**；反過來，比對 `expires_at` / `created_at` 這類 UTC 欄位時要用 `utcnow()`，不要用 `taipei_now()`
    - 自我檢查：改完 grep 一次 `deadline` 與 `utcnow` 同行的殘留
    - **鏡像案例（V2.10.2 清掉）**：反過來拿台北時間去比對 UTC 欄位也一樣錯。
      (a) `groups.py` 店家熱門品項的 30 天窗從台北時間起算，比對 UTC 的 `Order.created_at`，窗口實際變成 29 天 16 小時（`home.py::get_hot_items` 做同一件事卻是對的，兩支幾乎相同的函式一對一錯）。
      (b) 統計頁 `home.py` 的 `date_start/date_end` 全從台北推算，卻比對 UTC 的 `Order/Group.created_at`，「本月」會漏掉每月前 8 小時（台北 9/1 00:00-08:00 開的團不算進本月），「今年」同理漏 1/1 前 8 小時。
    - **修法有陷阱**：增補審稿建議「兩處都改用 `utcnow()`」，這對**滾動窗**（近 30/90 天）是對的，但對**日曆邊界**（本月/今年）是錯的——改成 `datetime(utcnow.year, utcnow.month, 1)` 會變成「UTC 的九月」＝台北 9/1 08:00 起，只是換個方向漏同樣 8 小時。日曆邊界仍要用台北算（那才是使用者要的月份），算完用 `taipei_to_utc()` 轉；而且統計頁的 `date_start/date_end` 還要顯示在模板的「統計期間」，所以**顯示用台北值、查詢用轉換值，必須拆成兩組**。這正是 `taipei_now()` docstring 那句反向規則想防的矯枉過正
    - **統計頁的殘餘（V2.10.3 清掉）**：V2.10.2 修了 `query_start/query_end`，但同一個函式裡還有三處沒改到——`extract('hour'/'dow', Order.created_at)` 取的是 UTC 小時與星期（午餐團在台北 09:00-12:00＝UTC 01:00-04:00，畫面會顯示「最常下單 2:00」），以及月度趨勢迴圈的 `month_start/month_end`。**修一個函式時要把整個函式的時間運算掃一遍，不要只改當下看到的那幾行。**
    - 根治：這只是緩解。兩套慣例並存是結構問題，V2.11「時間單一真相」處理。增補審稿的判斷值得記下——**時間處理是目前唯一一個「已證實會持續產生新缺陷」的結構問題**，所以它在 V2.11 裡排第一，優先於授權 dependency 與 Alembic（那兩項解決的是潛在風險與維護成本，還沒造成實際錯誤）



26. **測試腳本用 `os.environ.setdefault("DATABASE_URL", ...)` 等於沒有防護**（V2.10.2 修正，外部審稿抓到）
    - 症狀：`scripts/smoke_test.py` 開頭會 `db.query(model).delete()` 清四張表。若執行時 shell 裡已匯出過正式的 `DATABASE_URL`（剛操作完 Railway、或在 Railway console 裡跑），`setdefault` **不會覆寫**它，四道 DELETE 直接打到正式資料庫
    - 為什麼「沒出事」不算安全：外鍵約束**可能**在刪 `Group` 時中斷並回滾，但 `announcements` 沒有被任何東西參照，順序剛好就會真的被清掉。這是靠運氣不是靠設計
    - 做法：偵測到非 SQLite 的 `DATABASE_URL` 直接 `SystemExit` 中止，並用**指派**而非 `setdefault` 覆寫；`SECRET_KEY` 同理。錯誤訊息只印 scheme，不印完整連線字串
    - 通用原則：**任何會寫入或刪除的腳本，都要主動拒絕非預期的目標，而不是預設一個安全值就當作防住了。** `setdefault` 表達的是「偏好」，不是「限制」

27. **用「固定 30 天」近似月份，會讓月份重複並跳過月份**（V2.10.3 修正，外部審稿抓到）
    - 症狀：統計頁「最近六個月」的長條圖，某個月出現兩根一模一樣的長條，另一個月整個消失，而且消失那個月的資料不會出現在任何一根裡
    - 根因：`today.replace(day=1) - timedelta(days=i*30)` 往回推。月份長度是 28-31 天，30 天只是近似，累積誤差會踩過月界。實測 2026-03-01/03-15/04-10/05-20 推出來都只有 **5 個唯一月份**（二月被跳過、另一個月重複）；2026-09 剛好正確，所以平常看不出來
    - **這種 bug 有季節性**：因為二月只有 28 天，跨過二月的推算必錯，也就是**每年 3 月到 5 月一定出現**，其他月份可能正常。不要因為「現在看起來是對的」就以為沒事
    - 做法：月份要用月份運算（`month -= 1`，遇 0 則 `year -= 1; month = 12`），不要用天數近似。已抽成 `home.py::month_buckets()`
    - 通用原則：**凡是「往回推 N 個月/年」的需求，都不要用 timedelta 天數換算。** 日/週可以，月/年不行

28. **測試複製一份被測邏輯來驗，等於沒測**（V2.10.3 自省）
    - 症狀：`smoke_test.py` 一開始把 `month_buckets` 與 `taipei_slot` 的實作**複製**進測試檔來驗。這樣真正的 `home.py` 改壞了，測試照樣全綠
    - 做法：把邏輯抽成 `home.py` 的模組級函式，測試 `import` 它。抽函式的成本很低，而且順便讓路由主體變短
    - 驗證手法：**寫完測試後故意把被測的那行改壞，確認測試會紅、再還原。** V2.10.3 對 `taipei_slot` 做過這個動作（改壞後退出碼 1）。沒做過這個動作的測試，不知道它到底有沒有在保護東西
    - 同族：V2.10.1 那條「確認舊寫法仍會錯」的 assert 是同一個精神——防止測試隨時間退化成恆真

29. **模板 `<script>` 裡被引號包住的插值，會因為資料含引號而讓整頁 JS 掛掉**（V2.11.0 修正，做選店覆蓋層時順手發現）
    - 症狀：`name: "{{ item.name }}"` 這種寫法只靠外層雙引號包住值。只要那筆資料含有雙引號，整段 `<script>` 就語法錯誤，該頁的 **Alpine 全部失效**——分類按鈕、選單、快捷鍵全部按了沒反應，而且**畫面上不會有任何錯誤訊息**，只有 console 看得到
    - 觸發面：`group.html:1091/1096` 的 `item.name` 是**菜單品項名**，來自 JSON 匯入，出現引號的機率不低；那是團員每天在用的點餐頁。`group_new.html` 的 `store.name` 同理
    - 做法：**`<script>` 內的插值一律過 `| tojson`**，由 Jinja 負責逸出（連 enum 這種「現在很安全」的也要，否則下次照抄旁邊那行就破功），寫成零容忍規則才不用維護白名單
    - 守護：`scripts/check_template_js.py`——(一) 掃全部模板的 `<script>`，被引號包住又沒 tojson 的插值一律失敗；(二) 用假資料渲染登記過的模板、抽出函式跑 `node --check`。假資料刻意放了含引號與反斜線的店名
    - 為什麼既有檢查抓不到：`py_compile` 不看模板，Jinja `Environment().parse()` 只驗 Jinja 語法、不管產出的 JS 合不合法。這是三件套之間的縫

30. **批次改碼的錨點：淺縮排版本是深縮排版本的子字串，assert 會假性通過**（坑 #24 的再犯，V2.11.1 又踩兩次）
    - 這是**同一個坑的第三、四次**。V2.10.0 是 `_sync_announcement_from_active(db)`，V2.11.1 是
      `    order.status = OrderStatus.DRAFT`（另一處是 8 空格）與 `{"sid": store_id})`
    - 為什麼一再發生：寫錨點時只看「我要改的那一行長什麼樣」，沒看「這一行還會不會以別的縮排出現在別處」。
      `s.count(old) == 1` 在子字串情境下**會回傳 2 而不是 1**，看起來像是保護，實際上兩次都是假匹配
    - **硬規則：整行替換的錨點一律連前一行或後一行一起寫。** 例如不要用
      `"    order.status = OrderStatus.DRAFT\n"`，要用
      `"    order.status = OrderStatus.DRAFT\n    db.commit()\n    \n    return ..."`。
      單行錨點只在該行內容全域唯一（含完整縮排且不可能是他行子字串）時才可用
    - 收尾一定 `py_compile`。V2.10.0 那次 assert 全過但檔案壞掉；V2.11.1 這兩次 assert 有擋下來（因為數到 2），
      差別只在運氣

31. **測試用錯前提，會綠得很安心卻什麼都沒驗到**（V2.11.1 自省）
    - 症狀：寫「非法甜度應被擋下」的測試時，用的團單設了 `lock_sugar=True`。鎖定時甜度會先被團單預設
      覆寫，根本走不到驗證那行。測試通過，但驗證邏輯壞掉也一樣通過
    - 做法：寫完測試先確認**它測的路徑真的會被走到**。最快的檢查是把被測的那行改壞，看測試會不會紅（坑 #28）
    - 同族：坑 #28（測試複製被測邏輯）。共同點是「測試看起來在測某件事，實際上沒有」

32. **`autoflush=False` 下，`db.refresh()` / `db.expire()` 會無聲丟棄尚未 flush 的變更**（V2.11.2 修正，P0 回歸）
    - 症狀：團主按「提前截止」→ 回到團頁，團**照樣開放點餐**。而且只在「本團沒有修改中訂單」時發生，也就是最常見的情況
    - 根因：`close_group` 寫成
      `group.is_closed = True` → `_settle_editing(db, group)` → `db.refresh(group)`。
      本專案 `SessionLocal(autoflush=False)`，第一行只改記憶體；`settle_editing_orders` 在沒有 EDITING 訂單時直接 `return 0` 不 commit；
      接著 `db.refresh(group)` 從資料庫重讀，**未 flush 的變更就沒了**，最後的 `db.commit()` 沒有任何 dirty 屬性可寫
    - 有 EDITING 訂單時之所以正常，只是因為 settle 內部剛好 commit 了 —— 這種「有時候會動」最難查
    - 做法：**先改屬性、後呼叫任何會查詢或 refresh 的函式時，中間一定要 `db.flush()` 或 `db.commit()`。**
      `close_group` 改成 `is_closed = True` → `db.commit()` → 結算 → refresh
    - 同族：`with_for_update()` 也有類似陷阱 —— 它會等到鎖、資料庫也回傳最新列，但 identity map **不會覆蓋同 session 已載入的物件**，
      要加 `.populate_existing()`（V2.11.2 的抽獎鎖就是這樣失效的）
    - 通用原則：ORM 的「讀」與「寫」在同一個 session 裡不是各自獨立的，任何 refresh/expire/rollback 都可能把還沒落地的改動吃掉

33. **只修新資料、不處理既有資料，等於沒修**（V2.11.2 修正）
    - 症狀：V2.11.1 為範本加了 `department_ids` 欄位並在存檔時寫入，但**既有範本的欄位是 NULL**，
      判斷式 `if not tpl.is_public and tpl.department_ids` 整段不成立 → 舊範本開出來的團仍是「非公開且零個部門」，只有團主看得到
    - 同一版還有另一個相同形狀的：`clean_http_url` 擋下無協定網址，但資料庫裡早就存著一堆 `maps.app.goo.gl/abc`，
      結果管理員一編輯店家就整頁存不了，而且訊息不說是哪個欄位
    - 做法：**每次加欄位或加驗證，都要同時回答「既有資料長什麼樣、會怎麼樣」**，三個選項擇一並寫進交班文件：
      (a) 遷移時一併補值 (b) 程式對舊資料給明確的錯誤或降級 (c) 上線前的清查 SQL
    - V2.11.2 的處理：舊範本**擋下**並提示重存（Sela 決定 —— 可見性放寬就收不回來，重存是一次性成本）；
      無協定網址**自動補 https://**（危險協定仍擋），並在交班文件保留清查 SQL

34. **用 `except` 做流程控制，等於把剛擋下的限制又放回去**（V2.11.3 修正）
    - 症狀：庫存 5 份的品項，團員已送出 5 份、按修改、複製上次（上次點 3 份）→ 本團合計變成 **8 份**，超賣
    - 根因：V2.11.2 的寫法是
      `try: _reserve_stock(...)` / `except HTTPException: _rem = _stock_remaining(..., exclude_order_id=order.id); _copy_qty = min(_copy_qty, _rem)`。
      `_reserve_stock` 正確判斷 5+3>5 並拋出例外，但 except 分支重算的剩餘量**排除了自己**，
      於是把剛被擋下的 5 份又當成可用，複製量被封頂為 min(3,5)=3
    - 做法：不要用例外做流程控制。要「還能再加幾份」就寫一個回答這件事的函式（`_available_for`），
      讓呼叫端拿數字做決定；例外留給真正的錯誤
    - **另一半的根因**：`_reserve_stock` 原本用
      `sum(i.quantity for i in order.items if ...)` 算自有量，讀的是記憶體 collection。
      迴圈內新建的 `OrderItem(order_id=...)` **不會**自動進入 `order.items`；
      而刪除並 flush 後，被刪的物件**仍留在** collection 裡直到 expire。兩個方向都會錯。
      改用 `_own_qty()` 查資料庫（呼叫前確保已 flush）
    - 通用原則：**牽涉配額、餘額、庫存的計算，一律以資料庫為準，不要相信 ORM collection 的當下狀態**（與坑 #32 同源）

35. **「頁面載入時就要顯示的提示」是後端測試看不見的一類，必須用瀏覽器環境驗**（V2.11.4，S-01）
    - 症狀：V2.11.3 的 toast 在兩個情境下**永遠不顯示**——複製上次的「已複製 N 項」與所有表單錯誤的 flash。
      後端 51 項煙霧測試、Jinja parse、`node --check` 全綠。使用者按下去頁面重載，什麼提示都沒有，比整頁 JSON 更難察覺
    - 根因一（載入順序）：`window.toast` 定義在 body 尾端，但 group.html 的 `<script>` 在 `<main>` 裡、比它先執行，
      `if (window.toast)` 不成立直接略過。V2.11.2 的 `setTimeout(300)` 剛好掩蓋了這個順序問題，V2.11.3 拿掉後必定失效
    - 根因二（Alpine 指令順序）：Alpine v3 在同一元素上**固定先跑 `x-init` 再掛 `x-on`（@）**。
      V2.11.3 在 x-init 裡倒佇列發 `apptoast` 事件，但 `@apptoast.window` 監聽器那時還沒掛上，事件發給了不存在的人
    - 根因三（求值方式）：Alpine 把 x-init **第一個陳述式的結果**當回傳值，若是函式就會呼叫一次。
      `x-init="window._toastShow = (p) => {...}; ..."` 的結果是那個箭頭函式 → `_toastShow(undefined)` 噴 console 錯誤。要用 `x-data` 的 `init()`
    - 做法：`window.toast` 移到 `<head>`（任何位置的 script 都呼叫得到）；元件在 `x-data.init()` 直接把顯示函式交給
      `window._toastShow` 並同步倒出佇列，不再依賴事件與指令順序
    - **驗證工具**：新增 `scripts/check_frontend_toast.py` + `jsdom_toast_check.js`——渲染 HTML、載入 jsdom、把 Alpine 放 body 最後
      模擬 defer、讀 toast 文字。實測用 V2.11.3 的舊 base.html 跑會抓到（`text` 為空、退出碼 1）。沒有 node/jsdom 時自動跳過
    - 通用原則：**只要一個修正的價值在「使用者會看到什麼」，就不能只靠後端測試說它修好了**

36. **編輯工具會修掉錨點裡的尾隨空白，原檔的「空白行」常帶縮排**（V2.13.0 踩到，坑 #30 的鏡像）
    - 症狀：`assert s.count(old) == 1` 失敗，但肉眼比對兩段完全一樣
    - 根因：原檔的空行是 `"    \n"`（4 個空格），寫腳本時工具（或編輯器的 trim trailing whitespace）把它修成 `"\n"`。
      坑 #30 是錨點太寬（子字串假匹配），這次是錨點太窄（空白行對不上）——同一個「錨點與實文不一致」的家族
    - 做法：錨點中跨越空白行時，用 `re.escape` 後把 `\n\n` 換成 `\n[ \t]*\n` 再 `re.search`（`_loose()` helper）。
      注意 Python 3.12 的 `re.escape` 會把換行逸出成 `\\\n`，替換要兩種寫法都處理
    - 更根本的：先 grep 實文再寫錨點（交班文件早就寫了），這次就是沒照做

37. **屬性裡的 JS 字串：autoescape 完全沒用、tojson 只能放單引號屬性**（V2.14.1，內部審核 P0-1/P0-2/P1-2，兩條可提權的儲存型 XSS）
    - 症狀一：`onsubmit="return confirm('刪除「{{ group.name }}」')"`、`@click="openAddItem({ name: '{{ item.name }}' })"`。
      Jinja 把 `'` 轉成 `&#39;`，但**瀏覽器解析屬性時會先把 `&#39;` 還原成 `'`，再把屬性值交給 JS**，
      所以 autoescape 在 `on*`、`@*`、`x-*`、`:*` 屬性裡等於沒有。品名含撇號（`McDonald's`）按鈕沒反應；
      品名是 `a',b:fetch('/admin/users/42/toggle-admin',{method:'POST'}),c:'` 就是以點擊者身分執行——代購團任何人都能寫品名，管理員點到就被提權
    - 症狀二（V2.13.0 自己造成的）：`x-data="{ tab: {{ tab | tojson }} }"` 渲染成 `x-data="{ tab: "menu" }"`。
      **`tojson` 逸出 `<>&'` 但不逸出 `"`**，雙引號屬性在 `{ tab: ` 就被截斷，工作台分頁切換、歷史收合、刪店家 `:disabled` 全部失效。
      五項檢查全綠（`check_template_js` 只掃 `<script>`，煙霧測試只看文字），還好還沒部署
    - 做法：**屬性裡的 JS 插值一律 `{{ x | tojson }}`，而且該屬性外層必須是單引號**，屬性內的 JS 字串字面值改用雙引號；
      `onsubmit` 這類要拼使用者文字的，改放 `data-name="{{ name }}"` 再用 `this.dataset.name` 讀（data-* 只是字串，autoescape 在那裡才有效）。
      `x-html` 拼 `${opt.name}` 改 `x-for` + `x-text`
    - 守護：`check_template_js.py` 第三道檢查掃所有 `on*=` / `@*=` / `x-*=` / `:*=` 屬性——
      有 `'{{ … }}'` 沒 tojson → 紅；有 tojson 但外層雙引號 → 紅。實測改壞一處會退出碼 1。
      煙霧測試用 `HTMLParser` 解析渲染結果，驗 `@click` 屬性值裡的品名是 JSON 字串、`x-data` 屬性值完整
    - 與坑 #29 的關係：#29 是 `<script>` 內的插值，這條是屬性內的。兩條合起來的規則是**「Jinja 值進 JS 語境，只有 tojson 一條路；在屬性裡還要加上單引號」**

38. **「每份總價」快照回寫時要保留它的組成**（V2.14.1，審核 P1-3）
    - 症狀：候補的 `unit_price` 是「基本價＋加購＋加料」。時價定價回寫用基本價整個蓋掉：候補「時價魚＋加飯 10」定價 380 後變 380 而不是 390；
      代購路徑（只改 0 元的）則因為 10 ≠ 0 永遠不回寫
    - 做法：`order_item_backups` 加 `extras_price` 分開存，回寫 = 新基本價 + extras_price；「基本價仍為 0」的判斷改成 `unit_price == extras_price`。
      快照與還原都要帶這個欄位（坑 #18/#24 那句「快照要涵蓋品項的所有子結構」的延伸：也要涵蓋金額的組成）
    - 通用原則：任何「合計快照」在部分重算時，都要能拆回組成；拆不回就得先把組成存下來

39. **htmx 的 `changed` 修飾掛在 `<form>` 上永遠不觸發；`from:find <選擇器>` 找不到元素會直接拋錯**（V2.15.0，jsdom 實測抓到）
    - 症狀一：`<form hx-trigger="input changed delay:700ms">` 貼上文字後什麼都沒發生。`changed` 比對的是**掛 hx-trigger 那個元素**的 `value`——form 沒有 value，`undefined !== undefined` 永遠 false
    - 症狀二：`hx-trigger="…, change from:find select"` 在沒有 `<select>` 的頁面（選定店家時）htmx 初始化就 `Cannot read properties of null (reading 'addEventListener')`，而且是 uncaught，後面的 trigger 不會掛
    - 做法：debounce 只靠 `delay:`，不用 `changed`（重送一次無害）；條件性的觸發器用 Jinja 分開寫，元素不存在就不要寫進 hx-trigger
    - 守護：`scripts/check_frontend_import.py` + `jsdom_import_check.js`——渲染匯入頁、載入 htmx 與 Alpine、攔 XHR，驗貼上會發、清空不發、拖檔去 BOM、換店家重查，**頁面初始化有 uncaught 錯誤也算失敗**。兩種改壞都實測會紅
    - 同族：坑 #35（頁面載入後的行為後端測試看不見）。**凡是靠 htmx 觸發器或 Alpine 事件串起來的互動，都要有 jsdom 那一層**
    - jsdom 注意：(a) htmx 掃 `hx-on` 用 `document.evaluate`，jsdom 的實作不合，載入前設 `document.evaluate = undefined` 讓它走 fallback；
      (b) 整份文件直接餵 jsdom 時 Alpine 的 `$el`/`$refs` 魔法變數會失效（原因未查明），只重組 body 就正常；
      (c) FileReader 回呼裡 `this.$refs` 拿不到，要用的元素由呼叫端用 `$el`/`$refs.x` 傳進方法

40. **relationship 的列表一律寫 `order_by`——模板直接迭代 relationship 時，順序只靠它**（V2.15.1，審核 P2-1）
    - 症狀：匯入時明明寫了 `sort_order`，團頁、工作台、差異比對的分類卻都直接迭代 `menu.categories` / `category.items`，**從來沒用到**。
      PostgreSQL 沒有 `ORDER BY` 時回的是實體儲存順序——代購團主一改價（UPDATE 寫新 tuple），那個品項就跳到最後；VACUUM 後分類順序也可能被打亂。
      SQLite 碰巧照插入順序回，所以本地測試永遠看不到
    - 做法：`relationship(..., order_by=lambda: (Model.sort_order, Model.id))`，六個列表關聯全部補上；有了之後呼叫端的手動 `sort()` 可以拿掉
    - 連帶：差異比對也要看順序（P2-3）——「把招牌移到最前面」原本被判成「沒有變更」擋下來

41. **兩段式表單（預覽→確認）的確認請求，要帶「預覽時的輸入原文雜湊」**（V2.15.1，審核 P1-1，jsdom 實測）
    - 症狀：貼上→自動檢查→出現確認鈕；使用者改了輸入框，在 0.7 秒的 debounce 加一次往返之間按確認，送出的是**改之前**的 `json_str`，
      伺服器照樣寫入並顯示「菜單已更新」。重新檢查若失敗（斷網、500），舊鈕更是一直留在畫面上
    - 做法（兩邊都做）：前端 `@input` 立刻把結果區變灰、按鈕停用（`markStale`）；後端預覽時算原文 `sha256[:16]` 放進片段，
      確認用 `hx-include` 把輸入框原文一起送，雜湊不符就不寫入、改用目前內容重新預覽
    - 守護：`jsdom_import_check.js` 的 XHR 假回應改用 TestClient 產生的**真實片段**——上一版回的是 `<div>ok</div>`，根本測不到確認鈕。
      這條與坑 #28 同族：測試的假資料太假，就測不到真東西
    - 順帶：`#import-result` 原本在外層 `<form>` 裡面，片段再放一個 `<form>` 是巢狀表單（htmx 用 DOM API 插入所以能動，但不合法）。移到外層表單之外，值用 `hx-include` 帶

42. **被 `x-show` 藏起來的表單欄位照樣會送出；「選項清單」不能寫死在開團頁**（V2.16.3，UI 審核 P0-1／P0-2，實機重現）
    - 症狀一：開團頁不勾「湊團制」「自動催單」，DB 裡每個團都是 `min_members=5`、`auto_remind_minutes=15`，團頁多兩行假資訊（「湊團 0/5」「截止前 15 分鐘提醒」）。勾選框沒有 `name`，只是用 `x-show` 把帶預設值的 `<input name="min_members" value="5">` 藏起來——`display:none` 的欄位仍在表單裡，後端「有值就寫」
    - 症狀二：開團頁預設甜度寫死「正常糖／少糖／半糖／微糖／無糖」，店家匯入的是「全糖／半糖…」；選「正常糖」＋鎖定 → 團員加任何品項都 400「甜度選項不存在」，整團沒人能點。鎖定時 hidden 還會把 `None` 渲染成字串 `"None"` 送出
    - 做法：(一) 條件顯示的欄位用 `:disabled="!enabled"`——disabled 的欄位不會送出（`x-show` 只是藏）；(二) 任何「從清單選一個」的表單，清單要從資料來（`selectedStore.sugar_options`），不要在模板寫死；(三) 後端再守一次：`sanitize_drink_defaults()` 不在店家清單的預設一律不指定也不鎖，開團與範本開團共用（範本存的預設可能已過期）；`{{ x or '' }}` 防 None 字串
    - 守護：`jsdom_store_sort_check.js` 用 `FormData` 讀真正會送出的欄位（不勾→沒有、勾→有），並驗選店後 `<select>` 的 options 等於店家的 `store_options`；兩者改壞都會紅
    - 同族：坑 #33（既有資料怎麼辦）——上線後已被寫入 5／15 的舊團，handoff 附清查 SQL 由 Sela 決定是否清

43. **框架升級後，靠「數 app.routes」的檢查會無聲變瞎**（V2.22.0 踩到，Kit 坑 #81 假完成訊號的實例）
    - 症狀：升到 FastAPI 0.143／Starlette 1.8 後，`check_routes.py` 照樣印「路由檢查通過」，但數字從 137 變成 **1**；煙霧測試 187 項全綠，所以第一眼看不出問題
    - 原因：新版 `include_router` 不再把子路由攤平進 `app.routes`，而是包成 `_IncludedRouter`（`original_router` ＋ `include_context.prefix`）。舊腳本只挑 `hasattr(r, "methods")` 的，七個 router 全被略過——重複路由檢查形同關閉，而 V2.9.1 那次就是靠它才抓到 `copy_last_order` 重複
    - 做法：遞迴走 `original_router.routes` 並累加 prefix（舊的攤平形狀也照走）；**加數量下限防線**（少於 100 條直接失敗），下次攤平方式再變就會紅而不是說謊
    - 通用原則：**升級框架後，所有「自己去讀框架內部結構」的檢查腳本都要看一次它數到幾個**，不能只看最後一行有沒有寫通過。檢查的輸出要包含一個你知道正確值的數字

44. **部署設定以為在 `railway.toml`，實際上服務自己存的是另一套**（V2.23.0 查線上時發現）
    - 症狀：CLAUDE.md、README、部署檢查清單都寫「Dockerfile 模式（railway.toml）」，但 Railway 服務設定讀出來是 **Railpack、沒有健康檢查、沒有重啟策略**
    - 原因：`railway.toml` 在每次部署時覆蓋服務設定，所以一直能用；Railway 已把 Config as Code 停用，**2026-12-01 起不再讀這個檔**——之後下一次部署就會照服務自己的設定（Railpack，Python 版本不受控）建，整站可能起不來，而且沒有任何警告
    - 做法：2026-10-17 已把 production 服務設定改成跟 `railway.toml` 一樣（Dockerfile、健康檢查 `/` 100 秒、ON_FAILURE ×3）並讀回確認。之後改部署設定**到服務 Settings 改**（或改用 `.railway/railway.ts`），不要只改 `railway.toml`。develop 環境 V2.28.1 決定移除（Sela：不需要了）
    - 通用原則：**平台設定要讀線上實際值，不要相信 repo 裡的設定檔就是真相**；部署檢查清單加一條「部署設定以 Railway 服務設定為準」。另外 develop 環境沒動（只改 production）

45. **煙霧測試是一支 2000 多行的 `main()`，後面的節拿共用變數名去裝別的東西，會蓋掉前面建立的物件**（V2.23.1 踩到）
    - 症狀：第 35 節要用 `_c`（TestClient）與 `_main`（app 模組）時噴 `'Connection' object has no attribute 'app'`、`'str' object has no attribute 'app'`
    - 原因：第 34 節寫了 `with _e34.begin() as _c:` 和 `_main = Path("app/main.py").read_text()`——同一個函式作用域，直接覆蓋了第 17 節建立的 `_c` 與第 16 節 import 的 `_main`。第 34 節當時是最後一節所以沒事
    - 做法：每節自己的暫存變數一律帶節號後綴（`_cn34`、`_main_src`、`_r35`…）；**不要重用 `_c`、`_main`、`db`、`user`、`_grp`、`_ord`、`_adm` 這些全檔共用的名字**
    - 長期：把煙霧測試拆成多個函式（每節一個），作用域分開就不會互相蓋——列入「大重構」
46. **在 base.html 加「每頁都會發的請求」，會讓 jsdom 檢查的請求計數全部錯位**（V2.25.0 踩到）
    - 症狀：只是在底部導航加了新推薦紅點（`hx-get="/admin/recommendations/badge" hx-trigger="load"`），`check_frontend_import` 兩頁都報「貼上後沒有自動檢查」；實際上預覽有發，只是 `posts.length !== 1`
    - 原因：jsdom 檢查用「攔到幾個 XHR」判斷行為，base 每頁多一個 GET，計數就多 1
    - 做法：`jsdom_import_check.js` 的 XHR 模擬略過 `/recommendations/badge`；**以後 base.html 再加全站請求，同一處要一起略過**，並把失敗訊息改成印出實際請求清單再查
47. **版本號寫死在模板裡，兩版都忘了改**（V2.26.0 Sela 回報「不然我不知道成功沒有」）
    - 症狀：V2.24.0、V2.25.0 部署後，「我的」頁最下面仍顯示 V2.23.2；Sela 靠它判斷新版上線沒
    - 原因：`base.html` 一行 `{% set app_version = 'V2.23.2' %}`，升版 SOP 沒列這一處
    - 做法：唯一來源 `app/version.py`（`register_filters` 掛成 Jinja global；啟動 log 印「SELA 快點來點餐 VX.Y.Z 啟動完成」）。**煙霧第 39 節核對 CLAUDE.md 狀態行、README 版尾、handoff 跟它同一版**——只改一處就紅
48. **FastAPI 0.14x 把空白的表單值當成「沒送」（None），用空字串表示「自動」會無聲失效**（V2.26.0 踩到）
    - 症狀：工作台縣市下拉選「依地址自動判斷」（value=""）存檔，縣市沒變
    - 原因：`city: str = Form(None)` 收到空字串時給的是預設值 None，程式走「沒送就不動」
    - 做法：有意義的選項一律給非空值（`value="auto"`）；空白只用在「真的沒填」
49. **模板裡 `tojson` ORM 物件，平常沒資料不會爆，有資料才 500**（V2.26.0 測縣市時順便抓到，屬既有 bug）
    - 症狀：任何一家店有分店，開團頁 `/groups/new` 整頁 500（`Object of type StoreBranch is not JSON serializable`）
    - 原因：`branches: {{ store.branches | tojson if store.branches else "[]" }}`——沒分店時走 `"[]"`，有分店才真的序列化 ORM 物件
    - 做法：路由先轉成純資料（`branch_map`：id／name／phone／address，停用的不給）；**tojson 只餵 dict／list／字串數字**。煙霧第 39 節在有分店的情況下開開團頁
50. **「不能有巢狀連結」要檢查原始 HTML，jsdom／瀏覽器的 DOM 看不到**（V2.27.0 改壞驗證時發現）
    - 症狀：故意把連結包回店名連結裡，jsdom 的 `querySelector("a a")` 照樣找不到、檢查通過
    - 原因：HTML 解析器碰到 `<a>` 裡又開 `<a>` 會自動先關掉外層——DOM 裡永遠不會有巢狀 a，但手機瀏覽器的點擊範圍與鍵盤焦點已經亂了，原始碼也不合法
    - 做法：煙霧第 40 節用 `html.parser.HTMLParser` 數原始回應裡的 `<a>` 深度（不經瀏覽器修正）；jsdom 那條只當第二道
51. **Jinja 值放進 JS 反引號字串（template literal），tojson 也救不了**（V2.28.0，內部審核 P0-1）
    - 症狀：回報頁「複製」鈕寫成 `` @click="navigator.clipboard.writeText(`{{ f.content }}`)" ``。回報內容含反引號或 `${...}`，整個 Alpine 表達式壞掉或被當程式執行——回報是任何團員都能寫的
    - 原因：反引號字串裡 `${}` 會求值，autoescape 不處理反引號；坑 #37 的規則（tojson＋單引號屬性）只管引號字串，這裡根本不該插值
    - 做法：使用者文字一律放 `data-*`（`data-copy="{{ ... }}"`），JS 讀 `$root.dataset.copy`／`this.dataset.x`。`check_template_js.py` 新增 `check_backtick()`：依序配對反引號（先把 Markdown 的 ``` 換掉，略過 Jinja 註解），反引號字串內出現 `{{` 就紅
    - 第一版用正則 `` `[^`]*\{\{[^`]*` `` 會跨段配對（前一段的結尾反引號配到下一段的開頭），在 group.html 誤報；改成依序配對才準

52. **呼叫 LLM 的模型 ID 會過期；「預填 `{`」在新模型會 400**（V2.30.0 對齊 Kit 坑 #111／OPT-6 時查證）
    - 症狀（別的專案踩過）：模型退役後 API 回 `model not found`，程式沒動過、沒有任何建置期警告；照 Kit OPT-6 在請求最後加 assistant `{` 預填，Claude 4.6 以後的模型直接 400（`does not support assistant message prefill`）
    - 本專案現況：模型 ID 只在 `app/config.py::anthropic_model`（預設 `claude-sonnet-5-5`，Railway `ANTHROPIC_MODEL` 可覆蓋）；`ai_menu.py` 不寫死（煙霧第 44 節守）；不用預填，靠 `extract_json_text()`＋Pydantic 驗證＋預覽
    - **查證紀錄**：2026-11-09（前次 2026-11-02）Anthropic 模型淘汰頁——`claude-sonnet-5-5` Active，最早 2027-09-28 退役（同頁 `claude-sonnet-4-5-20250929` 2026-11-30 退役）。預填限制出自第三方整理文（官方頁未逐條列），標「待官方確認」
    - 做法：**升版 SOP 第 13 步每次查淘汰頁並更新這行日期**；查不到第一手證據的寫「未確認」，不寫「仍可用」

53. **規格標籤由菜單決定之後，所有「size == 'L'」的寫法都要改查規格清單**（V2.31.0）
    - 症狀（改之前盤點出來的）：計價、複製上次訂單、改價、菜單呈現、差異比對、匯入預覽各自寫死 M／L；只改其中幾處，特大杯會被當成 M 價、跨版本複製會把 Doppio 記成 L
    - 做法：規格一律走 `app/services/variants.py`（`item_choices`／`resolve`／`carry_over`）或 `item.size_choices`／Jinja `size_choices()`；**不要再新增讀 `price_l` 的程式**（只有 variants.py 與匯入相容層可以）。`grep -rn "price_l" app` 只該剩 schema、匯入、variants.py、遷移、`_menu_to_import_json`
    - 新增指向 `menu_items` 的表（這次的 `menu_item_variants`）要回頭改刪店家流程——煙霧第 7 節會紅（坑 #6 系列）
    - `order_items.size` 是規格標籤字串，長度 30；舊訂單仍是 M／L，統計與核對單照字串分組即可

54. **htmx 回應後才發的事件，不能從「會被換掉的元素」身上 `$dispatch`**（V2.31.1，內部審核 B-1）
    - 症狀：購物車按 ＋、送出訂單後，訂單牆、我的訂單、結帳列都沒更新，要重新整理才對；後端與煙霧測試都正常
    - 原因：按鈕在 `#cart-content` 裡、`hx-target="#cart-content"`；`htmx:after-request` 觸發時按鈕已被新內容換掉、離開 DOM，Alpine 的 `$dispatch` 從它身上冒泡，到不了 `body`，`hx-trigger="orderUpdated from:body"` 收不到
    - 做法：一律 `document.body.dispatchEvent(new CustomEvent('orderUpdated'))`；煙霧第 47 節靜態檢查 `@htmx:after-*` 裡不准 `$dispatch(`；jsdom 團頁測試實際按 ＋ 與送出，數訂單牆／我的訂單的 GET 有沒有增加
    - 原 jsdom 團頁測試沒抓到：只測了 sheet 開關，從沒按過購物車裡的按鈕（坑 #35 同族：要真的操作一次）

55. **訂單不再有「草稿」：DRAFT＝空的，每個增減都要過 `_settle_after_change`**（V2.33.0，S-2）
    - 規則：`get_or_create_order` 仍建 DRAFT（空殼，避免後面步驟失敗時訂單牆出現空的已點訂單）；加了品項才 `_activate` 成 SUBMITTED。新增任何會改品項的路由，都要在 commit 前呼叫 `_settle_after_change(db, order, group)`——它負責刪光回 DRAFT、每單上限檢查（超過 rollback＋400）
    - 庫存在加點當下就鎖行預留（`_reserve_stock` 不再看狀態）；不要再寫「送出時才檢查庫存」，PG 並行 A2 會紅
    - `/orders/edit`、`/orders/cancel`、`/orders/submit` 是相容路由（舊分頁、舊快取的頁面還會打），**不要刪**；EDITING 只剩遷移前留下的，遷移第 7 步會轉掉
    - include 片段時變數名要對：團頁傳 `my_order`、片段讀 `order`，要 `{% with order = my_order %}`；之前購物車片段是 htmx 載的所以沒人發現，S-2 讓卡片常駐才露出來（真瀏覽器截圖抓到，煙霧第 50 節補檢查）

56. **「一進來就開」的全螢幕覆蓋層，返回行為要跟「點開的」分開**（V2.34.0，S-5）
    - 開團頁一進來就是選店覆蓋層：這次 `openPicker(true)` **不** `pushState`、左上 ← 在沒選店時直接回 `/home`；否則按手機返回鍵只會關掉覆蓋層、露出一張空表單，使用者要按兩次才離開
    - 之後從「換一家」打開的照舊 pushState（返回＝關覆蓋層、回表單，不丟已填的設定）
    - 原本放在頁首的東西（投票入口、快速開團範本）會被一進來就開的覆蓋層蓋住，要搬進覆蓋層——搬之前先查煙霧有沒有在數個數（第 45 節數 `/use"` 剛好 4 個，留兩份會紅）

57. **專案有兩份 handoff，只更新交班檔，Kit 回饋就斷了**（V2.34.1 對齊時發現）
    - 症狀：`SELA-handoff-快點來點餐.md`（專案交班，新對話先讀）每版都更新；`SELA-handoff.md`（給 Kit 維護的回饋）停在 V2.30.0，V2.31～V2.34 累積坑 #53～#56 早就達「≥3 條坑」門檻卻沒產
    - 原因：升版 SOP 第 14 步寫「達標就產」，但每版都只檢查交班檔版號（煙霧第 39 節），沒人回頭看回饋檔停在哪一版
    - 做法：煙霧第 52 節讀 `SELA-handoff.md` 檔頭版號，**距 `APP_VERSION` 超過 5 個小版就紅**；達標的那版照 Kit 範本只寫本次新增、另存 Mac `~/Downloads/Kit反饋/Online-Drink VX.Y.Z-handoff.md`

58. **同一個人用兩個 LINE 帳號登入，系統就是兩個同名使用者；管理員只看名字會拉錯**（V2.35.0）
    - 症狀：先開部門限定團，再把她拉進部門，她還是看不到；可見性程式沒問題（每次都用當下的部門比對）
    - 原因：她有兩個帳號（換過 LINE 帳號登入），部門頁加人是只列名字的下拉選單，選到她沒在用的那個
    - 做法：`user_names.dup_name_counts` 標「同名 N 個」（暱稱或 LINE 名稱、NFKC 不分大小寫）；部門加人改清單、依最近活動排並顯示頭像與最近活動；人員頁也標。沒做合併帳號（Sela 選），遇到就把兩個帳號都加進部門、或請她固定用一個 LINE
    - 查「某人看不到某團」時先問：團勾了哪些部門／她在不在（同名要對頭像與最近活動）／拉她時團截止了沒

59. **htmx 的 `htmx:after-request` 失敗時也會觸發——成功後才做的事要先看 `event.detail.successful`**（V2.35.1，內部審核 G-1，P0）
    - 症狀：加點被後端擋下（團單已截止、只剩 N 份、超過上限），base.html 先 toast 出原因，緊接著 `afterAddItem()` 關彈窗、toast「已點好」把錯誤蓋掉——使用者以為點到了，店家不會做
    - 原因：htmx 4xx 依序觸發 `htmx:responseError`、`htmx:afterRequest`；`@htmx:after-request` 拿不到成功與否就照做
    - 做法：`@htmx:after-request="afterAddItem($event)"`，開頭 `if (!ev?.detail?.successful) return;`。**新寫 `@htmx:after-request` 時一律先判斷成功**；jsdom 的假 XHR 可用 `w.__xhrOverride` 指定回 400 來測
    - 同族：坑 #54（after-request 裡從被換掉的元素發事件）——after-request 這個鉤子兩次都出事

60. **Alpine 外掛的指令沒載外掛時不會報錯，只是什麼都不做**（V2.36.0，內部審核 G-5）
    - 症狀：訂單牆、首頁「更多團」、開團頁進階設定、投票「已結束」四處寫了 `x-collapse`，以為有展開動畫；實際上 base.html 只載 Alpine 核心，`x-collapse` 是 `@alpinejs/collapse` 外掛的指令——沒有動畫，也沒有任何 console 錯誤
    - 做法：不載外掛就不要寫外掛指令（這版全部拿掉，`x-show` 照常開合）；要動畫就在 base.html 載外掛並鎖版本（坑：P2-F6 Alpine 鎖 3.17.4，外掛也要同版）。煙霧第 55 節：模板不准出現 `x-collapse`
    - 通用：Alpine 的 `x-<名字>` 拼錯或沒註冊都會被靜默略過；新寫指令時確認它是核心指令（x-data／show／bind／on／text／html／model／if／for／transition／effect／ref／cloak／ignore／init／teleport／id）

61. **管理員看得到團主區——測「團員看不到 X」要用非管理員的測試帳號**（V2.36.0 煙霧第 55 節踩到）
    - 症狀：斷言「團員頁不產 QR」失敗；QR 彈窗確實已搬進 `{% if is_owner or is_admin %}`，但煙霧共用的 `_uid` 是管理員
    - 做法：測「團員視角」一律另建一個一般帳號（`User(line_user_id="sXX_member")`），不要拿共用的 `_uid`；同理測「團主視角」用真的團主

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
| V2.36.0 | **點餐頁版面整理（內部審核《V2.35.0 開團後點餐頁》R-1～R-12、G-4～G-9；Sela：「照稿做」，畫面稿 `v2_36_0_mockup.png`；Q-1 維持縮圖列、Q-2 價格一行、Q-3 預選團主預設並標示）**。**R-1 標頭兩行**：團名＋「店 · 誰開的」＋右上「資訊」；第二行倒數（剩 X（HH:MM 截止），最後 15 分鐘紅字）、上限、外送均分、全單折扣、請客；備註一行。原本收合的「詳細資訊」、電話／地圖／外送平台、收藏、我請客、菜單更新日都搬進 `#info-sheet`。**R-2 我的訂單改底部抽屜** `#mine-sheet`（`#my-order-content` 的 id 與 hx 目標不變），結帳列「我的訂單 ⌃」打開。**R-3** 開放中訂單牆移到菜單下面，團主列「名單 ›」`openWall()` 捲過去並展開（展開狀態 `window.__wallOpen` 跨刷新保留）；按人折扣工具截止後才出現。**R-4／R-10** 推薦只留「一樣再來」與「你的常點」；「你點過的」「大家常點」兩段拿掉，熱門改成品項名旁的火焰（`data-hot`）；導覽列拿掉「熱門」chip、分類不帶數量。**R-5** 品項列 48px、右側白框 ＋；點過的加框＋「已點 ×N」（`my_order.html` 的 `data-ordered` → `orderedQty`）。**R-6** 結帳列三狀態：沒點「HH:MM 截止 · 不用再按送出」／已點「你點了 N 件 · $X／已點好 · HH:MM 前都能改」／選候補「選候補 N：「X」缺貨時改買」＋取消（G-4：原本在標頭的候補提示捲到菜單就看不到）。**R-8** 不可超過上限的團，加點前先算（已點＋這次 > 上限 → 主鈕停用「超過上限 $N」；有折扣、時價、候補交給後端）。**R-11** 單一規格標題下寫「大杯 $45」；團主設的預設甜冰預選並標「團主預設」，帶入上次時不標（Q-3）。**R-12** 我的訂單寫「外送均分約 $X（目前 N 人）」。**Q-2** 多規格價格一行「M $25 · L $30」，價格不拆行（店家頁共用 `item_price`）。**G-5** 拿掉 4 個模板的 `x-collapse`（沒載 collapse 外掛）。**G-6** QR 彈窗移進團主區、`intersect once` 打開才載（原本每個團員進頁就產一張）。**G-7** 我的訂單整頁已 include，拿掉 `load` 重拿；加點成功只發 `wallUpdated` 刷訂單牆（原本 `orderUpdated` 會再拿一次我的訂單）。**G-8** base.html 購物車 sheet 的 CSS 死碼拿掉。**G-9** 抽屜／加點／資訊／分享／更多共通：Esc 關、開著背景不捲、`pushState({sheet:1})` 讓 Android 返回鍵先關 sheet、打開 focus 進去、關掉 focus 回原按鈕。**測試**：煙霧 277 → **281 項**（第 55 節四項；第 24、29、46、P2-6 節改期待：熱門改 `data-hot`、chip 不帶數量、資訊 sheet、價格一行）；jsdom 團頁 member 重寫前半（不重拿片段、已點 ×1、抽屜 Esc／返回鍵／背景鎖／focus 回來、資訊 sheet、訂單牆在菜單下、火焰、上限先擋與減回恢復、單一規格摘要、候補關抽屜與結帳列提示、加點後只刷訂單牆）。真瀏覽器截圖（412／320px，本機編 Tailwind）抓到兩處：320px「特大杯 $155」標籤跟價格拆行（改成每個規格整段不拆、在 · 之間換）、店家頁價格欄 `flex-shrink-0` 把「那堤」擠成一字一行；捲到底時「返回頂端」蓋住訂單牆的「看大家點什麼」（訂單牆下留 3.5rem）。**改壞驗證十六處都會紅**（data-ordered 空／團主預設不標／我的訂單又 load／不先擋上限／不 pushState／Esc 不關／開放中也有折扣／QR 一進頁就載／加點後又發 orderUpdated／候補不關抽屜／價格回多行／熱門沒標／x-collapse 加回／背景不鎖／返回鍵不關／訂單牆回菜單上面）；第一輪「我的訂單又 load」只改到截止後那份、煙霧沒紅，改成改抽屜裡那份才紅——同一段標記在模板裡有兩份時，改壞要改到實際在測的那份。 |
| V2.35.1 | **內部審核《V2.35.0 開團後點餐頁（整合外部 UI 審稿）》立即修（報告第七章 V2.35.1 批次；Sela：G-2 選 A）**。報告存進 Project `claude/Online-Drink_V2.35.0_點餐頁審核.md`，版面整理 R-1～R-12 與 G-4～G-9 排 V2.36.0。逐條對程式碼查證屬實。**G-1（P0）**：加點被後端擋下（截止、售完、超過上限、甜冰不在清單…）時，htmx 先 `responseError`（base.html toast 出原因）、再 `afterRequest`——`afterAddItem()` 沒看成功與否，照樣關彈窗、記偏好、`orderStatus='submitted'`、toast「已點好」蓋掉錯誤；改 `afterAddItem($event)`，`ev.detail.successful` 不成立就返回（彈窗留著讓人改）。**G-2**：倒數歸零後 `isClosed` 沒人讀，菜單、跟單、＋／− 都還能按；歸零 1.5 秒後 `location.reload()` 換成截止後的畫面。每個團只自動重整一次（`sessionStorage` 記 `closedReload_<id>`）：手機時鐘比伺服器快時，重整回來還是開放中，不能一直重整。**G-3**：團主列與標頭用 `group.total_amount`（含外送 $330），訂單牆用訂單合計（$270）——同一頁兩個總額；新增 `Group.food_amount`（不含外送），團主列與截止後標頭改「N 人已點 · 餐點 $270 ＋外送 $60」，沒外送就不寫。**測試**：煙霧 275 → **277 項**（第 54 節）；jsdom 團頁 member 加 G-1（XHR 可指定回 400：彈窗留著、toast 有「團單已截止」、沒有「已點好」、狀態不變；成功照舊關彈窗）與 G-2（歸零排一次重整、同團第二次不排）。**改壞驗證都會紅**（拿掉成功檢查／拿掉 sessionStorage 防重複／團主列改回 total_amount）。 |
| V2.35.0 | **店家菜單照片＋同名帳號標示（Sela 2026-11-09：同事想放菜單圖檔；另回報「先開部門限定團、後拉人進部門，她看不到」）**。**先查可見性**：程式每次都用當下的部門比對（`visibility.py`），沒有開團時的名單快照——後拉進部門的人重新整理就看得到；Sela 後台查出是**她有兩個帳號**、拉錯那個（坑 #58）。**同名標示**（Sela 選「加人時標出同名」，不做合併）：`services/user_names.dup_name_counts` 暱稱或 LINE 名稱撞名（NFKC＋不分大小寫）就算；部門頁加人從下拉改成清單（頭像＋最近活動＋搜尋，依最近活動排，最上面通常是她現在用的）、成員列表與人員頁都標「同名 N 個」。**菜單照片**（Sela 選：店家附照片、只有管理員上傳、團頁一排縮圖〔B〕、匯入頁可順便存但預設不勾）：`stores.menu_photo_urls`（JSON）＋`menu_photos_updated_at`，最多 8 張（`MENU_PHOTO_MAX`）；工作台「菜單」分頁最上面 `#menu-photos` 卡（縮圖、× 刪、加照片多選直接上傳；長邊 1600 存 Cloudinary `sela/menus`）；`POST /admin/stores/{id}/menu-photos`（超過上限整批擋、代購個人店 404）與 `/menu-photos/delete`；團頁菜單上方、前台店家頁、店家菜單頁共用 `partials/menu_photos.html`（縮圖列＋全螢幕看圖：左右鍵／滑動／循環、Esc 關、原圖連結、開著時背景不捲；網址放 `data-photos` 用 `tojson | forceescape`，坑 #37）；匯入頁 AI 區「轉完把照片存成這家店的菜單照片」——勾了轉換時才上傳（推薦的照片直接沿用網址）、確認匯入才寫進店家並**換掉**舊照片，`_clean_menu_photo_urls` 只收 `https://res.cloudinary.com/<我們的 cloud>/` 開頭、最多 8 張；沒勾或沒帶照片的匯入不動原照片。`upload_service.upload_bytes` 給已讀過的位元組用。路由 133 → **135**；遷移加兩欄。**測試**：煙霧 271 → **275 項**（第 53 節四項）；jsdom 團頁加看圖（點第 2 張、循環、上一張、Esc 關、背景捲動恢復）。**改壞驗證九處都會紅**（看圖不循環／團頁不放縮圖／外站網址也收／同名不依活動排——第一版測試資料的 LINE ID 剛好跟活動順序一樣，改了資料才紅／不擋 8 張／匯入不存照片／關掉不恢復捲動／同名不看暱稱／網址 tojson 沒 forceescape）。真瀏覽器截圖看過團頁縮圖、看圖、工作台照片卡、部門加人清單。 |
| V2.34.2 | **說明文字再精簡（Sela：「儘量優化簡化說明，不要造成干擾」）**。V2.34.1 只拿掉 11 處純說明，這版把留下來的長句也縮：掃所有淡色、12 字以上帶標點的句子共 37 處，**縮短 29 處、拿掉 3 處**（推薦頁標語「發現好吃的店家？推薦給大家一起訂！」、範本頁副標「儲存常用設定，一鍵快速開團」、個人資料暱稱說明的後半），5 處本來就短或是問句沒動。原則：**一句話只留「會發生什麼」**，拿掉操作步驟的重述與舉例（例：「停用後團員看不到這家店，但資料都在；刪除則不可復原。」→「停用：團員看不到、資料都在。刪除：不能復原。」；開團頁「允許超過上限」的說明 → 「勾了可以點超過，超過的自付」）。順手修開團頁甜冰提示還寫舊分頁名「營運設定」（V2.21.0 起叫甜冰加料，這次整句縮成「這家店沒有甜冰選項，點餐不會問甜冰。」）。**測試**：煙霧第 52 節加「縮短後的長句不再出現」，第 1581 行匯入頁照片說明改新字。 |
| V2.34.1 | **落差對齊 Kit V2.3.0 → V2.7.0（Sela：「對齊 kit」；不動功能）**。細節在仲裁區塊第 7 點。**小字**：Sela 選全站掃——94 處灰色小字分類，拿掉 11 處純說明（團頁 8、開團頁 3），有資訊量的留著；結帳列沒點時不再顯示第二行。**用語**：後台團單頁「N 人已點」、紀錄頁「N 人已點」（S-2 留下的）。**logging**：upload_service、ai_menu 的錯誤與後台三處稽核訊息從 `print` 改 `logging`（`upload`／`ai_menu`／`admin`），只留啟動那行 print。**舊債**：補產 Kit 回饋檔 `SELA-handoff.md`（V2.30.0 → V2.34.1，坑 #53～#57），另存 Mac `~/Downloads/Kit反饋/`；README 目錄樹根改 `Online-Drink/`、補列 `SELA-handoff.md`（Kit 回饋）與 `SELA-logo-prompt.md`；交班檔開頭 zip 版號；升版 SOP 第 14 步改成每版看 Kit 回饋檔檔頭版本。**測試**：煙霧 268 → **271 項**（第 52 節三項：拿掉的 11 處不再出現且有資訊量的提醒還在、Kit 回饋檔檔頭版本距今 ≤ 5 版、後端只剩啟動那行 print；第 29 節訂單牆說明、第 40 節稽核訊息改接 logging）。**改壞驗證四處都會紅**（小字加回／回饋檔停在 V2.30.0／加回 print／拿掉有資訊量的提醒）。 |
| V2.34.0 | **總表第四批（Sela：「下一版」；畫面稿 `v2_34_0_mockup.png`，S-5 選 A、S-6 選 A、M-3／M-4／M-5 照稿）**。**S-5**：開團頁拿掉「類型」這一步，一進來就是選店覆蓋層（`openPicker(true)`，這次不 pushState，← 與返回鍵＝離開開團頁）；覆蓋層有類別 chip（`#picker-cats`，只列有店的類別，`pickerCat` 取代原本依類型篩的 `pool`）、第一格代購（`#pick-proxy`）；投票入口與快速開團（範本）從頁首搬進覆蓋層（不然會被蓋住）；選好店後卡片「換一家」、代購也有一張已選卡（`#picked-proxy`）。從店家頁（`?store_id=`）與複製開團進來照舊直接是表單。**S-6**：首頁沒有任何團時列「你常開的店」三家（`home.often_stores_for`：自己開過的依次數、同次數看最近，只留看得到的店；一家都沒開過退回全站熱門，標「大家常開的店」），每列「開團」連 `/groups/new?store_id=`；下面「開別家」。**M-3**：匯入頁從「新增店家」進來只看到貼上區與拍照轉換；「匯入至」收成一行「要更新已經有的店？選店 ›」，店名／類別欄收起來，預覽「將新增店家…」旁有「改」（`edit-new-store` 事件展開並聚焦）；從工作台「更新菜單」進來照舊一行店名。**M-4**：人員頁四個排序分頁換成搜尋框（名字、暱稱，前端篩），預設依最近活動、副標顯示最近活動；`?sort=` 舊網址照用。**M-5**（含 B-6）：工作台分頁 4→3，停用／刪除併到店家資料最下面的「危險區」（`#danger`）；`?tab=more` 與停用後都 302 到 `?tab=settings#danger`。**順手**：S-2 留下的團員用語——首頁「N 人已點」「已點」標籤、紀錄頁「已點」、開團頁自動催單「提醒還沒點的人」。**測試**：煙霧 263 → **268 項**（第 51 節五項；舊工作台斷言原本靠 HTML 註解裡的「停用／刪除」字樣才綠，改成查 `#danger`，註解改 Jinja）；jsdom 開團頁改成覆蓋層一進來就開、類別 chip、代購格、換一家；工作台三分頁＋危險區。**改壞驗證九處都會紅**（不自動開／代購格／常開排序／停用店也列／店名欄不收／人員預設排序／tab=more 不轉址／分頁加回／代購不清店家）。真瀏覽器截圖看過五頁。 |
| V2.33.0 | **S-2 取消草稿購物車（Sela 選「S-2 取消購物車」；總表排程第三批，連帶 S-3、S-4、B-2、B-3）**。**模型**：DRAFT 只代表「空的、沒點」；加品項就把訂單轉成 SUBMITTED（`_activate`），每次增減後 `_settle_after_change`：刪光回 DRAFT、否則 SUBMITTED 並檢查每單上限（超過 rollback＋400）。庫存一律在加點當下鎖行預留（`_reserve_stock` 拿掉「只有 EDITING 才查」）。`/orders/edit`、`/orders/cancel`、`/orders/submit` 留著當相容（舊分頁按了不會壞）。**畫面**：沒有購物車 sheet、沒有「查看並送出」；「我的訂單」卡一直在頁面上、就地 ＋／−／垃圾桶，底下小字「全部取消」；結帳列「你點了 N 件 · $X／截止 HH:MM 前都能改 · 不用再按送出」＋「我的訂單」捲過去；加點鈕「點這杯・$」（餐點團「點這份」）；菜單不再收合；訂單牆「已點 N 人」；團主列「N 人已點」，催單不再數「點了沒送出」。**S-4**：沒點的時候菜單上方「上次點的：X　一樣再來」一鍵照點，toast 帶「復原」（6 秒，按了整單刪掉）；明細彈窗改「照這樣點」、「換成上次點的／一起點」。toast 加 action 按鈕（`toast(msg, kind, {label, run})`）。**遷移第 7 步**：開放中團裡有品項的 DRAFT／EDITING 轉 SUBMITTED、丟快照；已截止與空的不動，再跑 0 筆。**真瀏覽器截圖抓到一個 bug**：團頁 include `my_order.html` 時變數叫 `my_order`、片段讀 `order`，整頁首次渲染卡片是空的（靠 htmx load 才補上，結帳列已經寫 2 件、卡片寫「還沒點東西」）；改成 `{% with order = my_order %}`，煙霧加檢查。**測試**：煙霧 254 → **263 項**（第 50 節九項；27／29／31／48 節改期待）；jsdom 團頁 member 改寫；PostgreSQL 並行加 **A2**（兩人同時點最後一份，恰好一人拿到）。**改壞驗證**：煙霧／jsdom 九處＋全部取消鈕＋首次渲染＋拿掉加點鎖（PG A2 超賣）都會紅。 |
| V2.32.0 | **內部審核未完成事項總表第二批（Sela：「繼續下一步，排定後續沒有完成的改版」；M-1 畫面稿選 A）**。排程寫進 Project 總表（V2.32.0 後台小改 → V2.33.0 點餐流程 S-2 → V2.34.0 開團與後台 → V2.35.0 安全與穩定）。**M-1**：團頁菜單標題，管理員的「價格跟店裡不一樣？回報」換成「改價格」直進 `/admin/stores/{id}?tab=menu&edit=price`，下面一行「改了只影響之後開的團，這團照舊」；團員照舊回報；代購個人店不顯示。前台店家頁右上多「管理」進工作台。**M-2**：後台 12 個模板都覆寫 `bottom_nav` 為空（返回靠頁首 ←），工作台改價存檔列從 `bottom: 4.5rem` 改貼底。**B-4**：開團頁也不顯示底部導航（從 ＋ 進來的任務頁），開團鈕所在列 sticky 貼底。**M-6**：後台首頁「常用」只留新增店家、店家與菜單；團單、公告移到「管理」。**B-5**：打開購物車／加點／更多／分享 sheet 時收掉「之前」的 toast（團頁根元素 `x-effect` 呼叫 `window.hideStaleToast`）；400ms 內剛跳的留著——候補流程是先開購物車、緊接著 toast「已設定候補」，不留會被自己收掉。真瀏覽器截圖（本機編 Tailwind）看過團頁、店家頁、後台首頁、改價頁。**測試**：煙霧 252 → **254 項**（第 49 節：管理員／團員兩種身份看團頁與店家頁、後台 11 頁沒有 `<nav`、前台照舊有、開團頁無導航且開團鈕 sticky、常用區內容）；jsdom 團頁 member 加 toast 兩情境。**改壞驗證六處都會紅**：團頁沒改價格／人員頁留導航／開團鈕不貼底／團單回到常用／開購物車不收 toast／剛跳的也收掉（第一版測試先 toast 再開購物車，跟實際順序相反，拿掉 400ms 保護也是綠的；改成實際順序才紅）。 |
| V2.31.2 | **內部審核《未完成事項總表（以 V2.31.0 為準）》第一批（Sela：「小的＋安全先做」）**。總表整合 V2.29.0（沒交到這個對話的那份）與 V2.31.0 兩份審核共 30 項，逐條對 V2.31.1 查證：V2.31.1 已做 8 項，其餘仍在；總表存進 Project `claude/Online-Drink_未完成事項總表_V2.31.0.md`、開頭寫處理狀態，第七章改指向它（單一來源）。V2.31.1 已交 zip 但沒上線，為免同版號兩份內容，出 c+1。**S-1**：拿掉「送出訂單」確認框（截止前隨時能改，確認框只是重講購物車底部的件數金額；7→6 下），toast 改「已送出 · 截止前都能改」；刪品項的確認保留。**B-7**：常點「點了直接加」→「點了帶入選項」（實際會開彈窗）。**P2-17（V2.14.0 審核，安全）**：openpyxl 遇到「=」開頭的字串會存成公式，團員在備註／名字寫 `=HYPERLINK(...)`，團主開 Excel 就會執行；`excel_service._no_formulas()` 存檔前把所有字串格強制存成文字（顯示不變、不加 '）。**P2-F6（安全）**：Alpine 從 `@3.x.x` 浮動改鎖 `3.17.4`（跟 jsdom 測試同一版）；**SRI 沒加**——這個環境連不到 unpkg，算不出、也驗證不了線上檔案的雜湊，填錯會讓整站 JS 被瀏覽器擋掉，留待能實際驗證時做。第七章劃掉已完成的「item.variants」「多尺寸定價」「拍照轉 JSON」。**測試**：煙霧 251 → **252 項**（第 48 節：送出鈕沒有 hx-confirm、沒有「點了直接加」、模板 CDN 不准 `@latest／@3.x.x／@3`、Excel 用「=1+1」「=HYPERLINK」「=cmd」當名字品名備註匯出後沒有公式格且內容原樣）。**改壞驗證三處都會紅**：拿掉 `_no_formulas`／Alpine 改回 `@3.x.x`／送出鈕加回 hx-confirm。jsdom 用的 Alpine 就是 3.17.4，前端檢查全過。 |
| V2.31.1 | **內部審核《V2.31.0 杯型規格上線前》修正（V2.31.0 已於 2026-11-04 12:28 上線，Railway 讀回確認遷移變更 3 項、錯誤 0；審核在上線後才到，所以出 c+1）**。逐條對程式碼查證全部屬實。**V-1（P1）**：複製上次訂單跨版本時規格對不上就默默退第一個（最小杯、較低價）——舊 M／L 店照新 AI 指令重匯成「中杯／大杯」後，點 L 的人被改成中杯少 $5，而且第 46 節把「Doppio 改名退回 Solo」寫成了預期結果（測試鎖住錯誤行為）。`variants.carry_over` 改成 同名（NFKC＋不分大小寫）→ 別名（M＝中杯、L＝大杯）→ 同位置（帶舊版本品項的規格清單，新舊規格數相同時照位置）→ 才退第一個並回 `exact=False`；複製上次轉址帶 `resized=N`，團頁提示「N 項的杯型新菜單沒有，已改成第一個，請確認」；順手把算了沒帶出去的 `_skipped_opt` 也帶成 `optreset=1`。前端「記住上次」也用同一套別名。**B-1（V2.29.0 內部審核 P1，那份報告沒有交到這個對話，照本報告的描述修）**：購物車按鈕的 `@htmx:after-request="$dispatch('orderUpdated')"`——按鈕回應後已被 hx-swap 換掉，從離開 DOM 的元素發的事件傳不到 body，訂單牆、我的訂單、結帳列都不更新；全部 10 處（my_order 7、group／order_wall／fulfillment_panel 各 1）改 `document.body.dispatchEvent(new CustomEvent('orderUpdated'))`。**V-2（P2）**：`MenuItem.options`／`variants` 與 `MenuCategory.items` 改 `lazy="selectin"`——60 個品項的團頁 145 → **22** 條 SQL、工作台 135 → **14** 條（審核只提前兩個，實測剩 37 條，查出逐分類讀品項也是 N+1，一起改）。**V-3**：只有一種杯型的品項存「記住上次」時不再把上次的杯型蓋成空的。**V-4**：`allow_toppings: ""` 當沒給（原本變不加料）、規格名不分全半形大小寫查重、規格最多 8 個（AI 指令同步）、variants 與 price_l 同給時提醒 price_l 被忽略。**V-5／V-6**：交班檔開頭的部署狀態從 9 月更新成實際線上版本並寫回退注意；版本歷程瘦身——V2.24.0 以前 100 列搬到 `docs/CHANGELOG.md`（CLAUDE.md 248KB，每個新對話整份讀）；第七章補 V2.29.0 內部審核待辦。**測試**：煙霧 248 → **251 項**（第 46 節複製上次改成斷言 雙份／大杯／對不上帶 resized=1；第 47 節：after-request 不准 `$dispatch` 的靜態檢查、60 品項 SQL ≤ 30 條、匯入四縫）；jsdom 團頁 member 加「按 ＋ 與送出後訂單牆／我的訂單有重新載入」、杯型加「單一杯型不蓋掉上次」「上次 L 帶入大杯」。**每一條新測試都先在 V2.31.0 程式上跑過、確認會紅**（坑 #28）。**改壞驗證十一處都會紅**：拿掉別名／拿掉同位置／不帶 resized／variants 或分類品項拿掉 selectin／空字串變不加料／拿掉規格上限／改回 `$dispatch`／購物車按鈕不發事件／單一杯型蓋掉上次／記住上次不看別名；第一輪有兩處沒紅，都是測試沒蓋到——「拿掉別名」被「同位置」接住（補了舊 M／L 重匯成三杯型、規格數不同的奶茶）、「按鈕不發事件」只改到垃圾桶鈕而測試按的是 ＋（改成全部按鈕與只拿掉送出鈕兩種都驗）。PostgreSQL 並行 A～E 通過。 |

> 規則：超過 10 版砍最舊的，搬到 `docs/CHANGELOG.md`（V2.31.1 起；原本寫搬到 README.md，但 README 是給人看的說明，改放專用檔）。V2.25.0 以前的完整歷程在那裡。

---

## 七、下版候選工作（按優先序）

> **內部審核未完成事項——單一來源是 Project 文件 `claude/Online-Drink_未完成事項總表_V2.31.0.md`**（2026-11-04 內部審核整理 V2.29.0＋V2.31.0 兩份報告，每項都寫完整；原 V2.29.0 報告沒交到這個對話，以總表為準）。開頭有處理狀態，**每做完一項就回去更新那段**。
> - 已做：V-1～V-6、B-1（V2.31.1）；S-1、B-7、P2-17、P2-F6（V2.31.2）；M-1、M-2、B-4、M-6、B-5（V2.32.0）；S-2、S-3、S-4、B-2、B-3（V2.33.0，Sela 選 S-2）；S-5、S-6、M-3、M-4、M-5、B-6（V2.34.0）。總表第一～五章全部做完。
> - **排程**（總表開頭）：~~V2.33.0 點餐流程~~、~~V2.34.0 開團與後台~~（✅）；V2.35.0 菜單照片與同名標示；V2.35.1 點餐頁審核立即修（G-1～G-3）；V2.36.0 點餐頁版面（R-1～R-12、G-4～G-9）。
> - **點餐頁審核（2026-11-09，Project 文件 `claude/Online-Drink_V2.35.0_點餐頁審核.md`）**：✅ 全部做完——G-1～G-3（V2.35.1）、R-1～R-12＋G-4～G-9（V2.36.0，照畫面稿 `v2_36_0_mockup.png`）。審核另提的「之後再說」：菜單搜尋（Sela 之前決定不做 A-4）、品項圖片大圖。
> - **下一版第一優先：安全與穩定**（V2.14.0 審核剩餘 P2、CDN SRI）——點餐頁已整理完，Sela 原排在它之後。P2-13（收款文字沒讀 `lucky_winner_ids`）先問 Sela 是不是刻意的。
> - 附錄 V2.14.0 審核的 P2／P3 仍在下面「V2.14.0 內部審核未做」。
> - **D-1**：Railway develop 環境刪除等 Sela 在網頁按套用（2026-12-01 前）。

> **V2.31.0 杯型規格（variants）——已完成**（見版本歷程）。**後續候選**（來源 Project 文件 `claude/SELA-菜單匯入待辦-杯型規格.md`）：3-1 區間價（`price_min`／`price_max`，比照時價由團主定價）、3-3 `store.currency`（只顯示不換匯）；工作台「改價格」目前只能改價、不能增減規格（增減走「更新菜單」），若常用再加。

> **V2.28.0 內部審核延伸（未做）**：部門 `role` 欄位與 `DeptRole.LEADER` 值仍在資料表（畫面不用了，要真的刪得動 enum，坑 #2，不划算）；`SystemSetting.token_version` 仍在用（登出所有人靠它），只是畫面不顯示；~~PWA 名稱~~（✅ V2.28.1 改「快點來點餐」）；Railway develop 環境的刪除已 staged，待 Sela 在網頁套用（API 不能過兩步驟驗證）。
> **V2.27.0 外部 UI 審稿未做**：首頁頂部跨類別搜尋（沒有 API，審稿也說可延後）；桌機左側導覽；後台其他頁（人員、部門、公告、回報、匯入頁）的字級與點擊範圍統一（這版只做首頁、店家列表、團單、工作台）；成功／錯誤訊息逐一寫明作用對象。
> **V2.26.0 延伸（未做）**：後台店家列表加縣市篩選（目前只顯示＋可搜尋）；首頁「今天」的開放中團不依縣市篩（團是人開的，不是店）。
> **V2.25.0 延伸（未做）**：AI 轉完若有看不清的價格，在預覽直接給輸入框補（畫面稿方案 A 第二張），現在仍是回輸入框改；推薦送出時 LINE 推播給管理員（需另開 Messaging API 頻道）；~~PWA 名稱~~（✅ V2.28.1）。

> **V2.35.0 延伸（未做）**：菜單照片換順序（目前照上傳順序，要換就刪了重傳）；合併重複帳號（Sela 這次選只標示）；刪店家時一併刪 Cloudinary 上的菜單照片（目前留著，跟 logo 一樣）。

> **V2.24.0 延伸（未做）**：匯入時一併建分店（`store.branches: [{name, phone, address}]` → `store_branches`）。目前照片列多家分店時 AI 指令要求 phone／address 填 null，分店要手動加。

> **與 Sela 議定的三包規劃**（依序做，審稿 md 各自對應）：
> - **V2.10.0 管理後台流程第一包 — 已完成**（公告二合一＋提案 1/3/7＋清除測試團安全性）
> - **V2.11 管理後台流程第二包＋危險操作**（V2.13.0 做了提案 2／6／刪店家確認，V2.13.1 做了菜單差異預覽；剩提案 4／5；儀表板分區 V2.27.0、清除測試團先列清單 V2.27.0／V2.28.0、全體登出影響說明與下架訪客工具 V2.28.0 已做）：提案 2（手動新增店家表單）、提案 4（部門成員批次加入）、提案 5（使用者列表顯部門＋指派入口）、提案 6（店家列表快捷操作與搜尋）、儀表板重整（修 `/admin/users` 重複連結、分「今天要處理的／管理入口」兩區）、危險操作三項（清除測試團兩段式預覽、刪店家改輸入店名確認、全體登出顯示在線人數影響）、下架兩處訪客清理工具
> - **V2.12 防再犯基礎設施**：Alembic 評估（注意坑 #1，本專案刻意不用）、授權 dependency 取代 handler 各自檢查、時間單一真相（坑 #24 那類時區問題的根治）、表單輸入 schema — 見「程式碼優化與維護建議」md 的 H/A/G/J 節
> - **獨立長工 大重構**：巨型 router 拆分（`admin.py` 已 1700+ 行）、`group.html` 1359 行拆 JS、Jinja 環境統一（解坑 #6）、函式內 import 清理 — 功能穩定期再動，需全站回歸
>
> **V2.14.0 審核未做清單（依優先）**：~~P1-7 套件升級鏈~~（✅ V2.22.0，目標改為 fastapi 0.143／starlette 1.8，pip-audit 0 條）；~~P1-8 啟動遷移~~（✅ V2.23.0：advisory lock＋先查再改＋lock_timeout；Sela 選不放 preDeployCommand）；P2-5 匯入預覽→確認的版本檢查（409）；P2-7/8/11 時價生命週期配套（未定價時送出提示上限、禁折扣、禁重開團）；P2-13 收款文字沒讀 `lucky_winner_ids`（待確認是否刻意）；~~P2-14 刪加料硬刪 FK~~（✅ V2.21.0 批次儲存先斷外鍵）；~~P2-15 清除訪客子表與 aborted 交易~~（✅ V2.28.0 清理訪客整個拿掉）；P2-16 清除測試團加 7 天條件；~~P2-17 Excel 公式注入~~（✅ V2.31.2）；P2-F1 倒數計時器不清除；P2-F2 點餐彈窗不重設；P2-F3 async 路由含同步 IO；P2-F4 開團不檢查店家可用；~~P2-F5 推薦上傳不走 upload_service~~（✅ V2.16.2）；~~P2-F6 CDN 鎖版＋SRI~~（✅ V2.31.2 Alpine 鎖 3.17.4；SRI 未加，見 V2.31.2 歷程）；P2-F7 LINE 取消授權 422；P3 ×13（`quote` safe、GET logout（V2.23.2 外部審核也點到，風險＝被騙點一下登出，未改）、安全標頭、last_active 節流、QR 端點未登入、README 變數名、close_group 抽獎無鎖、中獎 contains、投票雙送、複製上次排序不一致、`int()` 截斷、範本邊界、死碼）。
>
> **兩份 UI 審核（2026-10-16，《UI／UX 全面精簡建議》＋《內部審核 V2.16.1 UI 優化與簡化建議》）— hotfix 已做（V2.16.3），其餘待 Sela 排序**。內部審核建議的順序：**用語統一**（「結單」一詞三義——截止時間／團員送出／團主關團，建議全站改「截止／送出訂單／提前截止」，草稿一律「未送出」）＋**底部常駐結帳列**取代購物車 FAB、團單頁隱藏底部導航（解「以為點了其實沒送出」）→ **團單頁依身分×階段重排**（團員：精簡標頭→菜單→結帳列；已送出後菜單收合成「再加點」；已截止團主看「下一步卡」傳給店家／核對單／收款明細；拿掉「快速點餐」卡——常點與熱門併入菜單導覽、看別人點什麼併入訂單牆「跟單」、隨機收進導覽列；訂單牆改一行摘要；團主工具 7 格→分享／催單／更多）→ **開團頁只問店家＋截止**（團名自動帶「店名＋時段」、截止預設 1 小時、其他收進進階設定；「開團」改 `.btn-primary`；可見範圍 radio 改 chip）＋**首頁去重**（同一團不出現兩次、店家清單移到底部、團列表不分段依截止排序、頁首只留 logo）＋**底部導航三格**（首頁｜＋開團｜我的；投票進首頁、回報進我的）。加點彈窗：✕＋拖曳條、「加入購物車・$25」帶金額、備註收起、「上次」標籤。購物車 sheet：去雙標題、整單刪除收進 ⋯、減到 0 即移除。全站：主要按鈕統一 `.btn-primary`、圓角統一、手機一律底部 sheet、`alert()` 改 toast、透明度收成三階。《UI／UX 全面精簡》另提：後台首頁先待處理事項、個人頁分「資料／活動」、統計先總覽。**不照做**：匯入改「上傳照片→辨識狀態」（辨識是外部 AI 做的，系統沒有 OCR）；桌機寬版佈局（30 人幾乎全手機）。
>
> **IA 重整（Sela 2026-10-16 兩輪意見）— ✅ V2.17.0 導航／首頁／店家／紀錄／我的／開團頁頂列；✅ V2.18.0 團頁重排；✅ V2.19.0 開團頁只問店家＋截止；✅ V2.20.0 加點彈窗與購物車 sheet 內部；✅ V2.21.0 工作台分頁重組；✅ V2.22.0 P1-7 套件升級鏈。**排定的系列到此全部完成**；之後從下面幾段的待辦再挑（Sela 排序）。V2.23.0 做了 P1-8。**期限**：Railway 2026-12-01 停讀 `railway.toml`——production 服務設定已改好（坑 #44），develop 環境沒動。**不做**（Sela 決定）：A-4 菜單搜尋、A-6 停售灰字列出、A-7 時價提示文。
>
> **審稿《菜單管理優化》＋內部審核 V2.15.0**：✅ V2.16.0 A-1/A-2/A-5/A-8 → ✅ V2.16.1 B-3/5/6/7/8/9/10 → ✅ V2.21.0 工作台分頁重組。
>
> **匯入 P2 後半（仍要動資料表）**：~~`item.variants` 取代 price/price_l~~（✅ V2.31.0）、~~後台上傳照片直接轉 JSON~~（✅ V2.25.0 拍照轉菜單）、店家層級加料匯入、`store.currency`。
>
> **零星待辦**：核對單 PDF/Excel 改用 actual 出貨鏈（兩輪審稿點名，現以「原始品項」標示過渡）；候補列進核對單 PDF（分頁高度計算是已知重疊坑，見坑 #23）

> **emoji 全站清除已完成（V1.1.0~V1.5.0）。** 以下為更早的功能性 backlog。

1. ~~匯入價格容錯~~（✅ V2.14.0 做掉：`parse_price_input()`，時價轉 `price_tbd`）
2. ~~**27 處 `TemplateResponse` 改新 API**~~（✅ V2.22.0：實數 54 處）（解坑 #10 的長期方案）— 把 `TemplateResponse("name.html", {"request": request, ...})` 改成 `TemplateResponse(request, "name.html", {...})`，改完才能放寬 `requirements.txt` 版本鎖，享受套件安全更新
2. 訂單匯出 Excel — 原本 backlog（見 `docs/SELA-開發指導手冊.md`「待開發」）
3. 外送費分攤功能 — `scripts/DELIVERY_FEE_CHANGES.py` 已有設計稿
4. ~~多尺寸定價~~（✅ V2.31.0 杯型規格 variants）
5. ~~菜單匯入開放 group_buy category~~（✅ V1.10.2 已解坑 #9）
6. 評估把 `taipei` filter 抽到共用 templates 模組（解坑 #6，評估重構成本）
7. 整體視覺巡檢 — (a) emoji 換 Tabler 後檢查圖示大小 / 對齊 / 顏色語義；(b) **V1.6.0 換主色後巡檢**：原本搭配橘色設計的局部（如分類篩選按鈕 amber/green/blue、各種 hardcode 顏色）在藍紫主色下是否協調；admin 統計數字色（橘/紫/綠/藍）是否需重新搭配

## 八、升版必讀

### 版本號管理（V2.26.0 起改單一來源）

- 版本號定義在 **`app/version.py` 的 `APP_VERSION`**（V2.26.0 前寫死在 `base.html`，V2.24／V2.25 都忘了改，坑 #47）
- 顯示在頁首 app 名稱旁（V2.30.0 對齊 Kit 鐵律加回）與「我的」頁最下面；啟動 log 印「SELA 快點來點餐 VX.Y.Z 啟動完成」——Sela 靠這幾處確認部署成功
- 煙霧第 39 節核對 CLAUDE.md 狀態行、README 版尾、handoff「目前版本」跟它一致，漏改就紅
- **升版 SOP：**
  1. 改 `app/version.py` 的 `APP_VERSION`（**取代**舊的「改 base.html」）
  2. 改 `CLAUDE.md` 第〇章「當前狀態」的版本字串
  3. `CLAUDE.md` 第六章「版本歷程」加新一列
  4. 打包 zip 命名 `Online-Drink VX.Y.Z.zip`
  5. **跑 `scripts/check_frontend_toast.py`**（V2.11.4 起）：`PYTHONPATH=. python scripts/check_frontend_toast.py`。
     靜態檢查一定跑；jsdom 實測需要 node_modules 有 jsdom 與 alpinejs（`npm i jsdom@24 alpinejs@3` 或設 `NODE_PATH`），沒有就跳過。
     **打包前記得清掉 node_modules。** 改到 base.html 的 toast、或任何「頁面載入時就要顯示」的提示時必跑
  6. **跑 `scripts/check_template_js.py`**（V2.11.0 起）：`PYTHONPATH=. python scripts/check_template_js.py`，沒有 node 時第二道檢查會自動跳過
  7. **跑 `scripts/smoke_test.py`**（V2.10.1 起）：`pip install -q --break-system-packages -r requirements.txt` 後
     `SECRET_KEY=x DATABASE_URL="sqlite:///./_smoke.db" PYTHONPATH=. python scripts/smoke_test.py`，
     跑完 `rm -f _smoke.db` 並清 `__pycache__` 再打包。改到公告／飲料選項／匯入／deadline 邏輯時要一併更新這支測試
  8. **跑 `scripts/check_frontend_import.py`**（V2.15.0 起）：`PYTHONPATH=. python scripts/check_frontend_import.py`。
     需要 node_modules 有 jsdom、alpinejs、htmx.org（`npm i jsdom@24 alpinejs@3 htmx.org@1.9.10` 或設 NODE_PATH），沒有就跳過。
     改到匯入頁的 htmx 觸發器或拖檔邏輯時必跑；它也一起跑店家排序（`jsdom_store_sort_check.js`）、團頁（`jsdom_group_check.js`，V2.18.0）與店家工作台（`jsdom_workbench_check.js`，V2.21.0）
  9. **更新 Claude Project「快點來點餐」的背景文件**（V2.16.1 起，Sela 指示：改程式若背景需要更新就一併更新）。Project 裡有五份 md ＋ 一份程式碼快照：
     - 《SELA-菜單匯入格式規範》改到匯入就同步；《專案架構精簡》改到資料表／路由／套件就同步；《部署檢查清單》改到檢查流程就同步；《常見錯誤與解決方案》新坑值得速查就加；《開發指導手冊》業務規則或排程變了就同步。都是 `project_write` 原地覆蓋同檔名。
     - 程式碼快照 `線上訂餐_bundle_VX.Y.Z.txt`：每版用 `python scripts/匯整專案.py "Online-Drink VX.Y.Z" 線上訂餐_bundle_VX.Y.Z.txt` 產生（約 1.4MB，含 CLAUDE.md），**先 `project_delete` 舊版號的那份再寫新的**（檔名帶版號，不會自動覆蓋；用 `local_path` 上傳時會落在 `claude/` 命名空間，路徑是 `claude/線上訂餐_bundle_VX.Y.Z.txt`）。
     - 這四份背景 md **不再放在 zip 的 `docs/`**（V2.16.1 移除，避免兩邊漂移）；zip 裡只留 CLAUDE.md 與 handoff。
  12. **動到庫存、候補、登入、遷移時跑 `scripts/pg_concurrency_check.py`**（V2.23.2 起；需要拋棄式 PostgreSQL：`PG_TEST_URL=postgresql://…/xxx_check`，名稱要含 test／check）。本機沙盒有 `/usr/lib/postgresql/16/bin`，用非 root 帳號 `initdb` 起一個即可（見 handoff）
  11. **跑 `pip-audit -r requirements.txt`**（V2.22.0 起；要網路，會查 PyPI 的漏洞資料庫）。有新漏洞且有修正版就升到修正版並全跑一次；沒有修正版的寫進交班文件說明為什麼不影響本專案。動到 requirements 後也要看 `check_routes.py` 數到的條數還對不對（坑 #43）
  13. **查 Anthropic 模型淘汰頁**（V2.30.0 起，Kit 坑 #111）：platform.claude.com/docs/en/about-claude/model-deprecations，確認 `config.anthropic_model` 還是 Active，並更新坑 #52 的查證日期；快退役就改預設值並提醒 Sela 改 Railway `ANTHROPIC_MODEL`
  14. **完成版本評估 `SELA-handoff.md`**（Kit 反饋檔，Kit 鐵律 #0）：達標（≥3 條坑／≥2 條選型決策／距上次 ≥5 版／對齊 Kit）就照 Kit 範本只寫本次新增；連著 Sela 的 Mac 時另存 `~/Downloads/Kit反饋/Online-Drink VX.Y.Z-handoff.md`。**每版都看 `SELA-handoff.md` 檔頭停在哪一版**（不是交班檔 `SELA-handoff-快點來點餐.md`——那份每版都改，坑 #57）；煙霧第 52 節距今超過 5 版就紅
  15. **菜單 AI 轉換指令全文**（V2.33.0 起，Sela 指示）：Project 文件 `claude/SELA-菜單AI轉換指令.md` 是 `app/services/menu_prompt.py` 的全文鏡像；改到 prompt 就同一輪更新那份
  10. **自我描述文案同步**（Kit 坑 #90，V2.17.0 起）：README 的「主要功能」「專案結構」目錄樹、版尾「Made by … 對齊 Kit Vx」、本檔第三章路徑表——動到導航／頁面／目錄就一併改。V2.17.0 對齊時發現 README 版尾停在 V1.0.0、`docs/` 說明是 V2.16.1 之前的，沒有任何測試抓得到這種腐化。
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

V2.x 把一個 30 人每天在用的訂餐站從「功能堆疊」整理成「物件各歸其頁」（V2.17～V2.21 IA 與團頁重排），再用四輪內外部審核把可提權的 XSS、超賣、時區、並行與遷移風險一條條補上，並為每一類建了會紅的檢查（煙霧 281 項、十支 jsdom、PostgreSQL 並行 A～E＋A2）。V2.30.0 對齊 Kit V2.3.0、V2.34.1 對齊 V2.7.0；V2.31.0 把「兩個價格欄位」換成照菜單的規格（variants）；V2.33.0 拿掉草稿購物車，點了就是訂單。V2.34.0 開團一進來就選店、後台三頁精簡，總表第一～五章做完；V2.35.0 加店家菜單照片與同名帳號標示，V2.35.1 修點餐頁審核的 P0（加點失敗還說已點好），V2.36.0 照審核把點餐頁整理成菜單在前、我的訂單收進底部抽屜；下一步是安全與穩定，見第七章。
