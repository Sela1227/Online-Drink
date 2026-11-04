# SELA-handoff.md ｜ Online-Drink V2.30.0

> 給 Kit 維護 Project 的 Claude 看：這個專案從上次回流（V1.16.0／Kit V1.18.0；V2.17.0 落差評估只寫進專案 CLAUDE.md、沒產 handoff）到 V2.30.0 學到什麼、哪些該進 Kit、哪些不要收。
> 舊版 handoff（V1.0.0 首次對齊＋V1.16.0 增補）已被 Kit 整合過，這份不重搬。

## 〇、專案速覽

- **專案名稱：** Online-Drink（快點來點餐）
- **專案類型：** FastAPI + Jinja2 SSR（HTMX／Alpine 局部更新）+ Railway
- **技術棧：** Python 3.11 / FastAPI 0.143.2 / Starlette 1.8.0 / SQLAlchemy 2.0.23 / PostgreSQL / PyJWT / Tailwind CDN / Alpine 3 / HTMX 1.9.10；站內呼叫 Claude Messages API（httpx）
- **部署路徑：** A Git Pusher 推 main → Railway（Dockerfile，服務設定）
- **使用 Kit 版本：** V2.3.0（從 V1.36.0 落差對齊）
- **完成版本：** V2.30.0
- **完成日期：** 2026-11-02

## 二、本次新增（建議進 Kit）

**[Kit 修改建議] sela-deploy `references/railway.md`「Railpack 時代的慣例」第 2 條**
- 現狀：教用 `railway.json` 的 `deploy.startCommand`。
- 建議改成：Railway 已停用 Config as Code，**2026-12-01 起 `railway.toml`／`railway.json` 不再被讀**；建置器、Dockerfile 路徑、啟動指令、健康檢查、重啟策略一律設在服務 Settings（或用連接器 `update-service` 設定後讀回確認）。部署動作清單加一行「讀線上服務設定，不信 repo 裡的設定檔」。
- 理由：本專案 V2.23.0 用連接器讀 production 服務設定，發現服務自己存的是 **Railpack、無健康檢查、無重啟策略**，一直能跑只因 `railway.toml` 每次部署蓋過去；12/01 後下一次部署會掉回 Railpack，Python 版本不受控（SQLAlchemy 2.0.23 不相容 3.13）。專案坑 #44。查重：grep「railway.toml」「Config as Code」→ Kit 無。

**[Kit 修改建議] optimizations.md OPT-6「取捨」補一句**
- 現狀：「不該換：API 不支援 assistant prefill 的模型」——沒說哪些。
- 建議改成：**Claude 4.6 以後的模型（Opus 4.6～5.5、Sonnet 4.6～5.5、Fable 5／5.1、Mythos）拒絕最後一則是 assistant 的請求**（400 `does not support assistant message prefill`）；只有 Sonnet 4.5／Haiku 4.5／Opus 4.5 以前可用。新專案預設用不到，改用「去圍籬容錯解析＋schema 驗證」或結構化輸出。
- 理由：本專案 V2.25.0 站內拍照轉菜單用 `claude-sonnet-5-5`，對齊時照 OPT-6 評估才查到；照做會整個功能 400。查證日 2026-11-02（第三方整理文，官方模型頁未逐條列，標「待官方確認」）。

**[坑] 版本號寫死在模板，連續兩版忘了改（坑 #1 補強）**
- 症狀：部署後 UI 版號停在舊版，使用者靠它判斷「新版上了沒」→ 以為部署失敗。
- 原因：`{% set app_version = 'V2.23.2' %}` 寫在 base.html，升版 SOP 沒列這處。
- 做法：版號單一來源（`app/version.py`），模板走 Jinja global、啟動 log 印版號；**煙霧測試核對 CLAUDE.md 狀態行、README 版尾、handoff 跟它同一版**——只改一處就紅。
- 影響範圍：所有有 UI 版號的專案。證據：專案坑 #47（V2.26.0）。

**[坑] 使用者文字進 JS 反引號字串，tojson 也擋不住（坑 #18 補強）**
- 症狀：`` @click="copy(`{{ f.content }}`)" ``，內容含 `` ` `` 或 `${…}` 時整個 Alpine 表達式壞掉或被執行。
- 原因：template literal 裡 `${}` 會求值，autoescape 不處理反引號；「tojson＋單引號屬性」的規則只管引號字串。
- 做法：使用者文字一律放 `data-*`，JS 讀 `dataset`；靜態檢查依序配對反引號（先換掉 Markdown 的 ```、略過模板註解），反引號字串內出現 `{{` 就紅。第一版用正則會跨段配對誤報。
- 影響範圍：Jinja／任何伺服端模板＋Alpine／inline JS。證據：專案坑 #51（V2.28.0 內部審核 P0-1）。

**[坑] 框架升級後，自己寫的結構檢查無聲變瞎（坑 #78 補強）**
- 症狀：FastAPI 0.13x 起 `include_router` 不再把子路由攤平進 `app.routes`；重複路由檢查照樣印「通過」，實際只數到 1 條。
- 做法：遞迴走新結構；**檢查輸出要包含一個知道正確值的數字，並設下限**（少於 100 條就失敗）。升框架後所有「讀框架內部結構」的腳本都看一次數字。
- 證據：專案坑 #43（V2.22.0）。

**[坑] Android Chrome 從 LINE app 授權跳回時，OAuth 回呼送兩次**
- 症狀：只有 Android Chrome 使用者無限回到登入頁；log 同秒兩次回呼，一次 499（瀏覽器取消）、一次拿用過的授權碼被 LINE 400。
- 做法：以 `sha256(state:code)` 唯一鍵做去重表——第一個請求去換 token，重複的輪詢等結果、沿用同一人；**不再拿同一組授權碼重試**；表裡不存 token。
- 影響範圍：LINE Login（可能所有「跳出 app 再跳回瀏覽器」的 OAuth）。證據：專案坑 V2.23.1（PostgreSQL 雙行程實測）。查重：grep「授權碼」→ 無；#16 是 callback URL 設定，不同。

**[設計模式] 危險操作「畫面列清單 → 送 id → 後端取交集」＋「確認時才建立」**
- 本案情境：清除測試團原本按下去刪的是「那一刻」的候選，可能比畫面多；推薦店家原本一按就建空殼店，匯入沒做完就留一家沒菜單的店。
- 可推廣的原則：批次刪除送出畫面上的 id，後端只刪 `id ∩ 候選`、沒帶 id 一個都不刪；「建立 A 再補 B」的流程改成 B 確認成功那一刻才建 A（同一交易、鎖來源列、只處理 pending）。
- 代價：多一個 hidden 欄位／參數；並行要有 PostgreSQL 測試（本案 E 項：同一推薦同時確認兩次只建一家）。

### 可加但等更多證據

- FastAPI 0.14x 把空字串表單值當成沒送（`Form(None)` 收到 None）——「自動」選項要用非空值（專案坑 #48）。
- Jinja `tojson` 餵 ORM 物件，平常沒資料不爆、有資料才 500（專案坑 #49）。
- 「不能有巢狀 `<a>`」要檢查原始 HTML，jsdom／瀏覽器 DOM 會自動修正看不到（專案坑 #50）。
- Kit 鐵律 #108（相容轉址用 302）在本專案找到兩處 301，已改；屬既有坑的實例，不另立。

## 五、留在這個專案、不要回流 Kit 的東西

- 菜單匯入格式（price 容錯、時價、`"?"` 看不清、差異比對、分類改名偵測、版本核對）——業務規則。
- 時價定價、代購個人店家、缺貨候補與換貨結算、每單上限與補助、整單折扣——業務模型。
- 部門可見性、縣市篩選、推薦→匯入流程的具體欄位與畫面——業務流程。
- 本專案刻意不對齊 Kit 的：不用 Alembic（raw SQL 遷移）、每個 router 自己的 Jinja 實例、`async def` 內同步 DB、內嵌 6MB 字型、營運 log 用 `print`（Railway Deploy Logs 直接看）——理由都在專案 CLAUDE.md 仲裁區塊。
- 奶茶配色、ORDER app logo、用語統一（截止／送出訂單／提前截止）。

## 六、Kit 維護 Claude 的行動清單

- **建議升 Kit 版本：** V2.4.0（railway.md 慣例改寫屬新內容）。
- **必做：**
  - [ ] railway.md：Config as Code 停讀（2026-12-01）、以服務設定為準、讀回確認；Railpack 預設 Python 版本風險
  - [ ] OPT-6 取捨補「Claude 4.6 起拒絕 prefill」，查官方文件確認後寫查證日
  - [ ] 坑 #1、#18、#78 各補一段（本檔第二節）
- **暫緩：**
  - [ ] LINE 回呼送兩次：N=1，等第二個 LINE Login 專案
  - [ ] 危險操作取交集／確認時才建立：N=1 設計模式
- **不做：**
  - [ ] 本檔第五節全部
