# SELA-handoff.md ｜ Online-Drink V2.36.0

> 給 Kit 維護 Project 的 Claude 看：這個專案從上次回流（V2.34.1／Kit V2.7.0）到 V2.36.0 學到什麼、哪些該進 Kit、哪些不要收。
> V2.34.1 那份已交出，這份只寫 V2.34.2～V2.36.0 新增的。

## 〇、專案速覽

- **專案名稱：** Online-Drink（快點來點餐）
- **專案類型：** FastAPI + Jinja2 SSR（HTMX／Alpine 局部更新）+ Railway
- **技術棧：** Python 3.11 / FastAPI 0.143.2 / Starlette 1.8.0 / SQLAlchemy 2.0.23 / PostgreSQL / Tailwind CDN / Alpine 3.17.4 / HTMX 1.9.10
- **部署路徑：** A Git Pusher 推 main → Railway（Dockerfile，服務設定）
- **使用 Kit 版本：** V2.7.0
- **完成版本：** V2.36.0
- **完成日期：** 2026-11-09

## 二、本次新增（建議進 Kit）

**[坑] htmx 的 `htmx:after-request` 失敗時也會觸發，成功後才做的事要先看 `detail.successful`**
- 症狀：加點被後端擋下（400：已截止、售完、超過上限），全站 toast 先秀出原因，緊接著 `@htmx:after-request` 的處理關掉彈窗、toast「已點好」蓋掉錯誤——使用者以為點到了。後端測試全綠。
- 原因：htmx 4xx 依序觸發 `htmx:responseError` → `htmx:afterRequest`；after-request 本身不代表成功。
- 做法：`@htmx:after-request="done($event)"`，開頭 `if (!ev?.detail?.successful) return;`；jsdom 假 XHR 可指定某個請求回 400 來測「彈窗還在、沒有成功訊息、狀態沒變」。
- 影響範圍：所有 htmx 專案。證據：專案坑 #59（V2.35.1，內部審核 P0）。查重：上一份 handoff 提的是「after-request 裡從被換掉的元素發事件」（同一個鉤子、不同坑），可合成一條「after-request 兩個陷阱」。

**[坑] Alpine 外掛的指令沒載外掛時靜默不動作**
- 症狀：四個模板寫了 `x-collapse` 以為有展開動畫；base 只載 Alpine 核心，沒有動畫、也沒有任何 console 錯誤，存在好幾版沒人發現。
- 做法：不載外掛就不寫外掛指令；要用就在 base 載外掛並鎖同一版。靜態檢查掃模板裡的外掛指令（`x-collapse`、`x-intersect`、`x-mask`、`x-trap`…）對照已載的外掛。
- 影響範圍：所有 Alpine 專案。證據：專案坑 #60（V2.36.0，內部審核 G-5）。查重：grep「Alpine」「x-collapse」→ 無。

**[坑 #56 補強] 使用者點開的底部 sheet：返回鍵、Esc、背景捲動、focus 要一起做，而且「關掉時 history.back」會觸發自己的 popstate**
- 現狀：#56（上一份提的）只講「一進來就開的覆蓋層不 pushState」。
- 補充：點開的 sheet `pushState({sheet:1})` 讓 Android 返回鍵先關 sheet；用 Esc／✕ 關掉時要 `history.back()` 把那筆吃掉，**這會再觸發一次 popstate**——用一個 `_expectPop` 旗標略過，不然會把下一個剛打開的 sheet 關掉。開著時 body `overflow-hidden`；打開 focus 進第一個控制項、關掉 focus 回原按鈕。多個 sheet 共用一份 watch（`a || b || c`）就不會互相打架。jsdom 可以測（`history.back()` 會發 popstate）。
- 證據：V2.36.0（內部審核 G-9），jsdom 團頁測 Esc／返回鍵／背景鎖／focus 回來，四項改壞都會紅。

**[坑] 測「一般使用者看不到 X」，測試帳號是管理員就永遠看得到**
- 症狀：QR 彈窗已搬進「團主或管理員」區塊，斷言「團員頁沒有 QR」還是紅；煙霧測試共用的帳號是管理員。
- 做法：測權限的視角一律另建對應身份的帳號，不沿用共用測試帳號。反過來更危險：「管理員才看得到 X」用管理員帳號測，綠了不代表一般人看不到。
- 影響範圍：所有有角色的專案。證據：專案坑 #61。查重：grep「管理員」「權限」「測試帳號」→ 無。

**[Kit #28 補強] 改壞驗證：同一段標記在模板裡有兩份時，要改到測試實際在測的那份**
- 症狀：「我的訂單整頁已 include，拿掉 load 重拿」——改壞時用 replace 第一個符合的字串，改到的是截止後那份，煙霧照樣綠；開放中抽屜那份沒動。
- 做法：改壞的錨點帶上下文（縮排、外層 id）確保改到測試路徑上那份；或兩份都改、分別驗。
- 證據：V2.36.0 改壞驗證第一輪 16 處中 1 處沒紅，改錨點後才紅。

## 可加但等更多證據

- 同一個人兩個身份提供者帳號（換 LINE 帳號）→ 管理員加人時只看名字會拉錯；做法是標「同名 N 個」＋頭像＋最近活動（專案坑 #58）。N=1，業務味重。
- 片段已在整頁 include 的區塊，不要再 `hx-trigger="load"` 重拿（多一次請求，網路慢時還會閃一下舊內容）。跟上一份「片段改整頁 include 時變數名對不上」同一族，可合併。
- 多規格價格一行顯示時，每個「標籤＋價格」整段 `white-space: nowrap`、只在分隔點之間換行；右欄別用 `flex-shrink-0`（會把左邊名稱擠成一字一行）。真瀏覽器 320px 截圖抓到。

## 五、留在這個專案、不要回流 Kit 的東西

- 點餐頁版面的具體決定：菜單在前、我的訂單抽屜、標頭兩行＋資訊 sheet、已點 ×N、熱門火焰、結帳列三狀態、候補提示、團主預設甜冰（Q-3）、價格一行（Q-2）、縮圖列（Q-1）——本專案畫面。
- `Group.food_amount`（團主列餐點不含外送）、每單上限前端先擋的規則（有折扣、時價、候補交給後端）——業務規則。
- 店家菜單照片（Cloudinary、最多 8 張、只收自家 cloud 網址）、同名帳號標示的比對規則（暱稱或 LINE 名、NFKC）——本專案功能。
- 本專案刻意不對齊 Kit 的：不用 Alembic、每個 router 自己的 Jinja 實例、內嵌 6MB 字型、奶茶配色、#132（邀請連結先要 LINE 登入）。

## 六、Kit 維護 Claude 的行動清單

- **建議升 Kit 版本：** 併進上一份（V2.34.1）的待辦一起升，新坑 3 條＋兩處補強。
- **必做：**
  - [ ] 新坑：htmx after-request 失敗也會觸發（可與上一份「after-request 從被換掉元素發事件」合成一條）
  - [ ] 新坑：Alpine 外掛指令沒載外掛靜默不動
  - [ ] 新坑：權限測試用錯身份的帳號
  - [ ] #56 補強：點開的 sheet 的返回鍵／Esc／捲動鎖／focus 與 `_expectPop`
  - [ ] #28 補強：改壞要改到測試路徑上那份
- **暫緩：**
  - [ ] 「可加但等更多證據」三條
- **不做：**
  - [ ] 本檔第五節全部
