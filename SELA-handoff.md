# SELA-handoff.md — 線上訂餐 V1.0.0

> **產生時機：** 首次對齊 SELA-Starter-Kit V1.9.0（既有專案首次套 Kit 規範 = 重大里程碑，依 Kit 鐵律 #0 必產出）。
>
> **這份是給 Kit Claude 看的回流交接** — SELA 下次升 Kit 時，看這份就能高效判斷有什麼通用發現要進 Kit。

---

## 〇、專案速覽

- **專案名稱：** SELA 快點來點餐（GitHub repo：Online-Drink；本機資料夾：線上訂餐）
- **專案類型：** FastAPI 後端 + Jinja2 SSR（混合 HTMX/Alpine 局部更新）
- **技術棧：** Python 3.11 / FastAPI / SQLAlchemy 2.0 / PostgreSQL / Jinja2 / Tailwind（CDN）/ Alpine / HTMX
- **規模：** 37 個 Python 檔（~8,127 行）、49 個 HTML 模板（~6,743 行）
- **使用 Kit 版本：** V1.9.0
- **完成版本：** V1.0.0（首次對齊里程碑）
- **完成日期：** 2026-05-26
- **線上狀態：** 已上線運作超過一年，30 人團隊每日使用，部署於 Railway

---

## 一、用 Kit 的整體感受

### 預期外的順利

- **Kit「對齊既有專案 SOP」（claude-init.md §二）救命**。一開始 SELA 問「會是大工程嗎」，本能會想去比對程式碼差異。讀到 SOP 才意識到 Kit 自己明確說「不要為對齊 Kit 而改既有設計」，整個對齊範圍從「可能要重寫」收斂到「純文件 + 資產對齊，零程式碼變更」。**這個 SOP 的存在直接避免了一次破壞性重構。**
- **四級分類法（🔴 必做／🟡 建議／🟢 順便／✗ 不做）非常實用**。讓「不對齊但有理由保留」變成可明寫的一級，而不是默默忽略。Alembic 這條尤其受益。

### 預期外的卡住

- **Kit `tech-stack-lessons.md` 1.1「FastAPI 起手必做」第 2 條「`alembic init` 第一天就跑」與本專案實況衝突**。本專案是 Kit 出現前就上線的成熟系統，「沒在第一天跑 alembic」已成事實。Kit 沒有為「既有專案已用其他遷移策略」提供退路 — 變成必須明寫「衝突仲裁」處理。
- **Kit `tech-stack-lessons.md` 1.1 第 6 條「共用 templates 模組」與本專案實況衝突**。本專案每個 router 自己註冊 `taipei` filter（坑 #6 已記）。重構成本大於收益，列「✗ 不做」。

### 對 Kit 的整體評價

- **如果 Kit 早一年存在，本專案會更早受益**。但 Kit 設計時看起來主要瞄準新專案，對「跑了一段時間的成熟專案首次對齊」這個情境，Kit 本身就有 SOP，但 `tech-stack-lessons.md` 的「起手必做」清單沒有「成熟專案如何補做或刻意不做」的對應指引。可以考慮在 §1.1 末段加一節「**FastAPI 既有專案對齊 Kit 時的取捨**」。

---

## 二、發現的「跨專案通用坑」

> 本專案絕大多數累積在「踩過的坑」的內容，與 Kit `cross-project-pitfalls.md` 既有編號高度重疊（坑 #1、#2、#28、#32 等都對得起來）。以下只列**可能對下個 FastAPI 專案有額外價值**的觀察。

### 強烈建議加坑

#### 1. Railway Dockerfile vs Nixpacks 何時切換的「切換閾值」沒寫明

- **症狀：** Nixpacks 對某些依賴組合不穩定，但 Kit 沒提供「累積幾次失敗就該切 Dockerfile」的判斷
- **本專案經驗：** 兩次 Nixpacks 建置失敗後直接切 Dockerfile，從此穩定。**建議切換閾值：「累積 ≥ 2 次 Nixpacks 建置失敗且非依賴版本問題，直接切 Dockerfile」**
- **與 Kit 既有坑的關係：** 補強 Kit `cross-project-pitfalls.md` 既有 Railway 相關條目（如果有 #38 提到 Railway start script，這條是「更前一步：build 階段就該切」）

### 可加但等更多證據確認

#### 2. `app/main.py` startup 事件做 raw SQL 遷移的可行性

- **N=1 證據：** 本專案運作超過一年沒問題，30 人線上
- **但需要思考的對立面：** 大型團隊 / 高並發場景下，startup 事件做 schema 變更可能不安全（多 worker 同時跑、長時間 ALTER 鎖表）
- **建議：** 等再一個小規模 FastAPI 專案重現這個模式後，再考慮回流為 Kit 通用建議。**雛型 / 小團隊 OK，大規模不適用**。

---

## 三、發現的「跨專案設計模式」

### 1. 「衝突仲裁區塊」對既有專案是命門

- 本專案最痛的點是「Alembic 該不該補」。Kit 默認建議用，但本專案運作良好。如果沒有「Kit 衝突仲裁開頭區塊」這個機制，未來 Claude 拿到專案 + Kit 一起，會很自然地想「修正」這個「不對齊」，造成破壞。
- **建議：** Kit `templates/claude-init.md` §二的「Kit 衝突仲裁開頭區塊」模板很好，可以更突出（在 master CLAUDE.md「對既有專案的 SOP」開頭就引用，現在是在第二章後段才出現）

### 2. 「踩坑紀錄與 Kit 通用坑庫的雙向引用」需要明確規範

- 本專案坑 #8 已被 Kit `cross-project-pitfalls.md` 第 142 行收錄。應該在專案 CLAUDE.md 寫法上鼓勵「**這條坑已進 Kit #N**」的雙向標記，方便將來 Kit 升版時知道哪些已回流
- **建議：** Kit `conventions/CLAUDE-MD-章法.md` 加一節：「踩坑紀錄若已回流 Kit，標『（已進 Kit pitfalls #N）』」

---

## 四、Kit 該瘦身或調整的地方

### Kit 規範修改建議

#### 1. `tech-stack-lessons.md` §1.1 FastAPI 起手必做

- **觀察：** 「起手必做」第 2 條「`alembic init` 第一天就跑」太絕對。對 1 人開發、小團隊、雛型階段，create_all + raw SQL 完全夠用，引入 Alembic 反而增加複雜度
- **建議改寫：** 「**`alembic init` 第一天就跑**（**團隊規模 ≥ 2 人 或 預期 schema 演進頻率 ≥ 每月 1 次** 才必做；個人雛型專案可暫緩，但要明寫『暫不用 Alembic 的理由』）」
- **理由：** Kit 自己 `sela-philosophy.md` 有「不過度工程」原則，這條起手必做違反該原則

#### 2. `tech-stack-lessons.md` 缺「既有 FastAPI 專案對齊 Kit」一節

- **觀察：** §1.1 全部以「新專案起手」角度寫，對「跑了一段時間、現在要對齊 Kit」沒指引
- **建議新增節：** §1.1.5「既有 FastAPI 專案對齊 Kit 的取捨」，列「已用 create_all 不用切 Alembic 的判準」「已用各 router 自註冊 Jinja filter 何時值得重構」等對立面

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

> Kit Claude 萃取通用坑時要避開以上這些，只看「踩過的坑」中環境／語法／工具鏈層級的條目（坑 #1～#8 屬通用、坑 #9 屬業務不要收）。

---

## 六、Kit Claude 的建議行動清單

### 建議升 Kit 版本

無強烈必要 — 本份 handoff 的觀察以「補強建議」為主，沒有 Kit 緊急錯誤要修。SELA 下次升 Kit 時可參考下方分類。

### 必做

無。

### 暫緩

- **§ 二.2「main.py startup 事件做 raw SQL 遷移」回流為 Kit 通用建議** — N=1 證據不足，等下一個小規模 FastAPI 專案重現再說

### 不做

- **§ 一「預期外的卡住」中關於 Jinja filter 共用 templates 模組的衝突** — 不要為了「對齊 Kit」反過來修改本專案的既有結構。Kit 那條建議對新專案合理，對本專案重構成本大於收益，已列「✗ 不做」並明寫理由

---

## 七、給 Kit Claude 的最後備註

本專案 V1.0.0 是「**純對齊版本**」 —
- ✅ 加：根目錄 `CLAUDE.md`、`README.md`、`SELA-handoff.md`、Kit 標準 `.gitignore`、`app/static/sela.svg`、`app/static/favicon/` 完整套組
- ✅ 刪：commit 進去的 `.DS_Store`、重複的 `gitignore`（無點）
- ❌ **完全沒動程式碼、模板、資料表結構、Dockerfile、railway.toml、start.sh、requirements.txt**

「base.html 串接 favicon」刻意留到 V1.0.1 — 為了讓 V1.0.0 名實相符：「零程式碼變更」 = 萬一 Railway 部署出問題，可以 100% 確定不是程式邏輯造成。下版（V1.0.1）才動 base.html，問題隔離明確。

下次 Kit 升版時，**重點看 §四的兩條建議** —「`alembic init` 必做」改為條件式 + 補「既有專案對齊」一節，這兩條解決的不只本專案，是所有「已上線小規模 FastAPI 專案」都會遇到的對齊摩擦。
