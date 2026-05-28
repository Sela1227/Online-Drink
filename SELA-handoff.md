# SELA-handoff.md — 線上訂餐 V1.0.0

> **產生時機：** 首次對齊 SELA-Starter-Kit V1.9.0（既有專案首次套 Kit 規範 = 重大里程碑，依 Kit 鐵律 #0 必產出）。
>
> **這份是給 Kit Claude 看的回流交接** — SELA 下次升 Kit 時，看這份就能高效判斷有什麼通用發現要進 Kit。

---

## 〇、專案速覽

- **專案名稱：** SELA 快點來點餐（GitHub repo：Online-Drink；本機資料夾：線上訂餐）
- **專案類型：** FastAPI 後端 + Jinja2 SSR（混合 HTMX/Alpine 局部更新）
- **技術棧：** Python 3.11 / FastAPI 0.104.1 / Starlette 0.27.0 / SQLAlchemy 2.0.23 / PostgreSQL / Jinja2 3.1.2 / Tailwind（CDN）/ Alpine / HTMX
- **規模：** 37 個 Python 檔（~8,127 行）、49 個 HTML 模板（~6,743 行）
- **使用 Kit 版本：** V1.9.0
- **完成版本：** V1.0.0（首次對齊里程碑 + Starlette hotfix）
- **完成日期：** 2026-05-28
- **線上狀態：** 已上線運作超過一年，30 人團隊每日使用，部署於 Railway

---

## 一、用 Kit 的整體感受

### 預期外的順利

- **Kit「對齊既有專案 SOP」（claude-init.md §二）救命**。一開始 SELA 問「會是大工程嗎」，本能會想去比對程式碼差異。讀到 SOP 才意識到 Kit 自己明確說「不要為對齊 Kit 而改既有設計」，整個對齊範圍從「可能要重寫」收斂到「純文件 + 資產對齊，零業務邏輯變更」。**這個 SOP 的存在直接避免了一次破壞性重構。**
- **四級分類法（🔴 必做／🟡 建議／🟢 順便／✗ 不做）非常實用**。讓「不對齊但有理由保留」變成可明寫的一級，而不是默默忽略。Alembic 這條尤其受益。

### 預期外的卡住

- **Kit `tech-stack-lessons.md` 1.1「FastAPI 起手必做」第 2 條「`alembic init` 第一天就跑」與本專案實況衝突**。本專案是 Kit 出現前就上線的成熟系統，「沒在第一天跑 alembic」已成事實。Kit 沒有為「既有專案已用其他遷移策略」提供退路 — 變成必須明寫「衝突仲裁」處理。
- **Kit `tech-stack-lessons.md` 1.1 第 6 條「共用 templates 模組」與本專案實況衝突**。本專案每個 router 自己註冊 `taipei` filter（坑 #6 已記）。重構成本大於收益，列「✗ 不做」。
- **「純文件對齊」過程中意外踩到一個現有的程式碼定時炸彈**（坑 #10）— 對齊期間 Railway 自行 rebuild，揭露了 `requirements.txt` 浮動版本造成 Starlette 升版破壞 27 處 `TemplateResponse` 寫法的事實。對齊版本 hotfix 鎖了版本救火成功。**詳見 §二.1**。

### 對 Kit 的整體評價

- 如果 Kit 早一年存在，本專案會更早受益。
- Kit 設計時看起來主要瞄準新專案，對「跑了一段時間的成熟專案首次對齊」這個情境，Kit 本身就有 SOP，但 `tech-stack-lessons.md` 的「起手必做」清單沒有「成熟專案如何補做或刻意不做」的對應指引。可以考慮在 §1.1 末段加一節「**FastAPI 既有專案對齊 Kit 時的取捨**」。

---

## 二、發現的「跨專案通用坑」

> 本專案絕大多數累積的坑與 Kit `cross-project-pitfalls.md` 既有編號高度重疊（坑 #1、#2、#28、#32 等都對得起來）。以下只列**可能對下個 FastAPI 專案有額外價值**的觀察。

### ⚠ 強烈建議加坑（V1.0.0 救火 → 高度通用）

#### 1. `requirements.txt` 浮動版本 + 雲端平台自動 rebuild = 套件升版隨機破壞 API

- **症狀：** 平台（Railway / Render / Fly.io 等）自行觸發 rebuild，重新從 PyPI 抓最新版套件，舊程式碼遇上新版套件的 API 變更後整站 500
- **本專案具體事例：** 2026-05-28 Railway 自行重啟，抓最新 Starlette（≥ 0.32），舊寫法 `TemplateResponse("name.html", {"request": request})` 被新版位置參數重排後當成 `TemplateResponse(name=string, request=dict)`，jinja2 拿 dict 當快取 key → `TypeError: unhashable type: 'dict'`
- **影響範圍：** 全專案 27 處用舊 API
- **原因：** `requirements.txt` 用 `>=` 沒鎖上限，每次 build 都拉最新
- **做法：** **`requirements.txt` 一律用 `==` 精確鎖版本**；新增依賴時鎖；定期人工檢視解鎖更新（而非讓 build 系統替你決定）
- **特別注意：** 雲端平台的 fallback 機制可能讓你「以為沒事」 — Railway 在 rebuild 失敗時會保留舊 container 繼續服務，但 Railway log 仍會狂噴 500，下次平台維護時就會真壞。**有 log 異常一定要追**
- **N=1 嗎？** N=1 但這是「所有用浮動版本 + 自動 build 的雲端部署」共通陷阱，連 Kit `tech-stack-lessons.md` §1.1「FastAPI 起手必做」都該加。**強烈建議升 Kit V1.9.1 直接收**

### 強烈建議加坑（會直接幫下個同類型專案省時間）

#### 2. Railway Dockerfile vs Nixpacks 切換的「閾值」沒寫明

- **症狀：** Nixpacks 對某些依賴組合不穩定，但 Kit 沒提供「累積幾次失敗就該切 Dockerfile」的判斷
- **本專案經驗：** 兩次 Nixpacks 建置失敗後直接切 Dockerfile，從此穩定。**建議切換閾值：「累積 ≥ 2 次 Nixpacks 建置失敗且非依賴版本問題，直接切 Dockerfile」**
- **與 Kit 既有坑的關係：** 補強 Kit `cross-project-pitfalls.md` 既有 Railway 相關條目（如果有 #38 提到 Railway start script，這條是「更前一步：build 階段就該切」）

### 可加但等更多證據確認

#### 3. `app/main.py` startup 事件做 raw SQL 遷移的可行性

- **N=1 證據：** 本專案運作超過一年沒問題，30 人線上
- **但需要思考的對立面：** 大型團隊 / 高並發場景下，startup 事件做 schema 變更可能不安全（多 worker 同時跑、長時間 ALTER 鎖表）
- **建議：** 等再一個小規模 FastAPI 專案重現這個模式後，再考慮回流為 Kit 通用建議。**雛型 / 小團隊 OK，大規模不適用**

---

## 三、發現的「跨專案設計模式」

### 1. 「衝突仲裁區塊」對既有專案是命門

- 本專案最痛的點是「Alembic 該不該補」。Kit 默認建議用，但本專案運作良好。如果沒有「Kit 衝突仲裁開頭區塊」這個機制，未來 Claude 拿到專案 + Kit 一起，會很自然地想「修正」這個「不對齊」，造成破壞。
- **建議：** Kit `templates/claude-init.md` §二的「Kit 衝突仲裁開頭區塊」模板很好，可以更突出（在 master CLAUDE.md「對既有專案的 SOP」開頭就引用，現在是在第二章後段才出現）

### 2. 「踩坑紀錄與 Kit 通用坑庫的雙向引用」需要明確規範

- 本專案坑 #8 已被 Kit `cross-project-pitfalls.md` 第 142 行收錄。應該在專案 CLAUDE.md 寫法上鼓勵「**這條坑已進 Kit #N**」的雙向標記，方便將來 Kit 升版時知道哪些已回流
- **建議：** Kit `conventions/CLAUDE-MD-章法.md` 加一節：「踩坑紀錄若已回流 Kit，標『（已進 Kit pitfalls #N）』」

### 3. 「對齊過程中順便接到 hotfix」應該被預期、不該被排斥

- V1.0.0 原本設計成「純文件對齊、零程式碼變更」。對齊過程中卻揭露了坑 #10 — 一個跟對齊無關但很嚴重的 bug。如果嚴守「純對齊」原則就會放著 bug 不修，等下次再炸
- **本專案處理方式：** 順便鎖版本（不改業務邏輯，只動 1 個依賴設定檔），CLAUDE.md 標註「對齊 + hotfix」
- **建議：** Kit `templates/claude-init.md` §二可以加一段：「**對齊過程意外揭露的非業務 bug（依賴、配置、部署層級），允許納入該版本一起 hotfix，但業務邏輯 bug 留下版**」

---

## 四、Kit 該瘦身或調整的地方

### Kit 規範修改建議

#### 1. `tech-stack-lessons.md` §1.1 FastAPI 起手必做 — **加「鎖依賴版本」一條**

- **觀察：** 「起手必做」沒有「鎖 `requirements.txt` 版本」這條，這次坑 #10 直接損失 1 個小時排查
- **建議新增條目：** 「**`requirements.txt` 一律用 `==` 精確鎖版本**。雲端平台會自動 rebuild 拉最新套件，浮動版本 = 隨機 API 破壞。新增依賴時用 `pip show` 看當下版本鎖死，定期人工解鎖更新而非交給 build 系統決定」
- **位置：** §1.1 第 2 條（在 Alembic 之後）

#### 2. `tech-stack-lessons.md` §1.1 第 2 條 Alembic 建議

- **觀察：** 「`alembic init` 第一天就跑」太絕對。對 1 人開發、小團隊、雛型階段，create_all + raw SQL 完全夠用，引入 Alembic 反而增加複雜度
- **建議改寫：** 「**`alembic init` 第一天就跑**（**團隊規模 ≥ 2 人 或 預期 schema 演進頻率 ≥ 每月 1 次** 才必做；個人雛型專案可暫緩，但要明寫『暫不用 Alembic 的理由』）」
- **理由：** Kit 自己 `sela-philosophy.md` 有「不過度工程」原則，這條起手必做違反該原則

#### 3. `tech-stack-lessons.md` 缺「既有 FastAPI 專案對齊 Kit」一節

- **觀察：** §1.1 全部以「新專案起手」角度寫，對「跑了一段時間、現在要對齊 Kit」沒指引
- **建議新增節：** §1.1.5「既有 FastAPI 專案對齊 Kit 的取捨」，列「已用 create_all 不用切 Alembic 的判準」「已用各 router 自註冊 Jinja filter 何時值得重構」「鎖版本是首要補做項」等對立面

### Kit 結構性建議

無 — 整體結構（conventions / templates / references / deployment / logo 五大資料夾）對首次接觸的 Claude 很清楚。

---

## 五、留在這個專案、**不要回流 Kit** 的東西

> ⚠ 這節是回流防呆 — 以下都是「線上訂餐」業務專屬，**Kit Claude 看到請不要誤收**：

- **LINE Login 流程細節**（`app/routers/auth.py`、`app/services/auth.py`）— 業務認證實作
- **「團單」概念與三狀態訂單**（`Group` model、`OrderStatus` Enum）— 業務領域模型
- **甜度／冰塊／加料選項結構**（`StoreOption`、`StoreTopping`）— 飲料店業務
- **菜單 JSON 匯入格式**（`services/import_service.py`、`docs/SELA-菜單匯入格式規範.md`）— 業務資料規範
- **QR Code 分享、盲訂模式、幸運獎**（`Group` 的 `share_code`、`is_blind_mode`、`enable_lucky_draw` 欄位）— 業務功能
- **部門系統**（`Department`、`UserDepartment`）— 該組織專屬
- **Cloudinary 整合方式**（`routers/admin.py` 的圖片端點）— 該專案選型
- **Tailwind orange-500 配色 / 便利貼卡片風格** — 該專案視覺風格
- **所有 `templates/*.html`** — 業務 UI
- **本專案 27 處 `TemplateResponse` 舊 API 寫法**（V1.0.0 用鎖版本擋住，下版才改）— 業務程式碼層的事

> Kit Claude 萃取通用坑時要避開以上這些，只看「踩過的坑」中環境／語法／工具鏈層級的條目（坑 #1～#8、#10 屬通用、坑 #9 屬業務不要收）。

---

## 六、Kit Claude 的建議行動清單

### 強烈建議升 Kit 版本（V1.9.1）

收坑 #10 與相關建議：
- `tech-stack-lessons.md` §1.1 加「鎖依賴版本」起手必做
- `cross-project-pitfalls.md` 加「浮動版本 + 自動 rebuild = 隨機破壞」通用坑

### 建議

- §四.2「Alembic 第一天就跑」改為條件式（≥ 2 人團隊或 ≥ 月變 schema 才必做）
- §四.3 新增「既有 FastAPI 專案對齊 Kit」一節

### 暫緩

- 「main.py startup 事件做 raw SQL 遷移」回流為 Kit 通用建議 — N=1 證據不足，等下一個小規模 FastAPI 專案重現再說

### 不做

- 「預期外的卡住」中關於 Jinja filter 共用 templates 模組的衝突 — 不要為了「對齊 Kit」反過來修改本專案的既有結構

---

## 七、給 Kit Claude 的最後備註

本專案 V1.0.0 是「**對齊版本 + 順手 hotfix**」：
- ✅ 加：根目錄 `CLAUDE.md`、`README.md`、`SELA-handoff.md`、Kit 標準 `.gitignore`、`app/static/sela.svg`、`app/static/favicon/` 完整套組
- ✅ 改：`requirements.txt` 從 `>=` 浮動改為 `==` 精確鎖（救坑 #10）
- ✅ 刪：commit 進去的 `.DS_Store`、重複的 `gitignore`（無點）
- ❌ **完全沒動程式碼、模板、資料表結構、Dockerfile、railway.toml、start.sh**

「base.html 串接 favicon」與「27 處 TemplateResponse 改新 API」刻意留到 V1.0.1 / V1.1.0 — 為了讓 V1.0.0 名實相符：**零業務邏輯變更**。萬一 Railway 部署出問題，可以 100% 確定是依賴鎖造成的、不是程式邏輯造成的，排查極快。

下次 Kit 升版時，**重點看 §二.1 + §四.1 兩條** — 「鎖依賴版本」這條解決的不只本專案，是所有用浮動版本 + 雲端自動 build 的 Python 專案共通陷阱。
