<div align="center">
  <img src="app/static/sela.svg" width="120" alt="SELA"/>
  <h1>SELA 快點來點餐</h1>
  <p>LINE Login 認證的團體飲料／餐點／團購訂餐系統</p>
  <p><strong>V1.0.0</strong></p>
</div>

---

## 簡介

給約 30 人團隊每日揪團訂餐用。支援三大類採購：飲料（含甜度／冰塊客製）、餐點（含加購選項）、團購；提供即時訂單牆、三狀態訂單管理、訂單複製、QR Code 分享、部門系統、公告、投票、消費統計、JSON 菜單匯入。

線上網址：[online-drink-production.up.railway.app](https://online-drink-production.up.railway.app)

---

## 技術棧

| 層 | 技術 |
|----|------|
| 後端 | FastAPI 0.143.2 + SQLAlchemy 2.0.23 |
| Web 框架核心 | Starlette 1.8.0（全部 `==` 鎖版本，見 CLAUDE.md 坑 #10；V2.22.0 升級，pip-audit 0 條） |
| 資料庫 | PostgreSQL |
| 前端 | Jinja2 3.1.6 + Tailwind CSS（CDN）+ Alpine.js + HTMX |
| 認證 | LINE Login（JWT：PyJWT） |
| 圖片 | Cloudinary |
| 部署 | Railway（Dockerfile 模式；設定在 Railway 服務上，見 CLAUDE.md 坑 #44） |

---

## 本地啟動

```bash
# 1. 建虛擬環境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. 裝依賴（鎖版本）
pip install -r requirements.txt

# 3. 準備環境變數（建立 .env，內容見下）
# 編輯 .env 填入機密

# 4. 啟動
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

開瀏覽器到 http://localhost:8000。

---

## 環境變數

```env
# 資料庫（Railway 自動提供）
DATABASE_URL=postgresql://...

# LINE Login（LINE Developers Console 取得）
LINE_CHANNEL_ID=xxx
LINE_CHANNEL_SECRET=xxx
LINE_CALLBACK_URL=https://xxx.up.railway.app/auth/callback

# JWT 簽章
JWT_SECRET_KEY=xxx

# Cloudinary（圖片上傳，可選）
CLOUDINARY_CLOUD_NAME=xxx
CLOUDINARY_API_KEY=xxx
CLOUDINARY_API_SECRET=xxx

# 管理員（LINE userId；也是唯一能用「拍照轉成菜單」的人）
ADMIN_LINE_USER_ID=Uxxxx

# 站內拍照轉成菜單（V2.25.0，可選；沒設就只能複製指令到 ChatGPT／Claude）
ANTHROPIC_API_KEY=sk-ant-xxx
# ANTHROPIC_MODEL=claude-sonnet-5-5   # 預設值，要換模型才設
```

---

## 目錄結構

```
線上訂餐/
├── app/
│   ├── main.py              FastAPI 入口（啟動時呼叫遷移）
│   ├── migrations.py        資料庫遷移（advisory lock、先查再改；V2.23.0）
│   ├── config.py            Pydantic Settings
│   ├── database.py          SQLAlchemy 連線
│   ├── models/              SQLAlchemy Model（User/Store/Menu/Group/Order/...）
│   ├── routers/             API 路由（auth/admin/groups/orders/votes/...）
│   ├── services/            業務邏輯（auth/import/export）
│   ├── schemas/             Pydantic Schema
│   ├── templates/           Jinja2 模板（含 partials、admin、votes）
│   └── static/              CSS / JS / images / sela.svg / favicon/
├── docs/                    預設 Logo 功能說明（架構／部署／匯入規範等背景文件在 Claude Project「快點來點餐」，V2.16.1 起不再放 zip）
├── examples/                範例 JSON
├── menu/                    各店家菜單 JSON 範本
├── scripts/                 煙霧測試與七支檢查（smoke_test／check_*／jsdom_*）、種子資料、專案匯整
├── requirements.txt         依賴（== 鎖版本，坑 #10）
├── railway.toml             舊的 Railway 設定檔（對照用；2026-12-01 起不再被讀，以服務設定為準）
├── Dockerfile
├── start.sh
├── .gitignore
├── CLAUDE.md                ← 給 AI 看的工作上下文（最重要）
├── SELA-handoff-快點來點餐.md ← 交班文件（新對話先讀）
└── README.md                ← 本檔
```

---

## 主要功能

- **LINE Login** 認證 + 暱稱自訂
- **店家／菜單管理**（後台）：飲料／餐點／團購三類分流，飲料含甜冰／加料選項；店家工作台分「菜單／共用選項／店家設定／更多」，甜冰點選標籤＋預設組、加料一次改完一次儲存（V2.21.0）
- **團單**：開團、設截止時間、QR Code 分享、盲訂模式、抽幸運獎
- **訂單**：草稿／已送出／編輯中三狀態、複製功能、即時訂單牆
- **部門系統**：使用者可歸屬部門
- **前台導覽（V2.17.0）**：底部五格 今天｜店家｜＋開團｜紀錄｜我的——首頁只放公告、投票卡（有才出現）、要你處理的、開放中；店家分頁搜尋／分類／只看收藏／排序；紀錄分頁合併我點的／我開的／統計；投票入口在首頁卡與開團頁
- **團頁（V2.18.0）**：身分 × 階段——團員點餐時標頭精簡、菜單直達、底部常駐結帳列；送出後菜單收合成「再加點」、訂單牆一行摘要可「跟單」；團主有團主列（分享／催單／更多）、截止後「下一步」卡（傳店家／核對／收錢）
- **開團（V2.19.0）**：選店、選截止（預設 1 小時後）就能開，團名自動帶「店名 · 時段」，其他設定收在「進階設定」
- **加點與購物車（V2.20.0）**：加點是底部 sheet，按鈕直接帶金額、會顯示帶入了上次的甜冰；購物車數量減到 0 即移除、清空收在右上 ⋯
- **公告／投票／回報**
- **JSON 匯入**：店家 + 菜單批次建立（匯入格式規範在 Claude Project「快點來點餐」的《SELA-菜單匯入格式規範》）

---

## 部署

走 Railway Dockerfile 模式。**部署設定以 Railway 服務的 Settings 為準**（V2.23.0 已設：Dockerfile、健康檢查 `/` 100 秒、失敗重啟 3 次）；下面的 `railway.toml` 只是對照，2026-12-01 起 Railway 不再讀它。詳細部署檢查清單見 Claude Project「快點來點餐」的《SELA-部署檢查清單》。

```toml
# railway.toml
[build]
builder = "dockerfile"
dockerfilePath = "Dockerfile"

[deploy]
healthcheckPath = "/"
healthcheckTimeout = 100
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 3
```

⚠ **重要**：
- 本專案刻意不用 Alembic，schema 演進走 `app/migrations.py` 的 raw SQL（見 CLAUDE.md 坑 #1；可手動 `python scripts/migrate.py`）
- `requirements.txt` 必須維持 `==` 精確版本鎖死，否則 Railway rebuild 時會抓到不相容的 Starlette 新版（見 CLAUDE.md 坑 #10）

---

## 開發注意事項

更詳細的踩坑與規範見：

- `CLAUDE.md` — 給 AI 看的工作上下文（42 條踩坑紀錄、版本歷程、升版 SOP）
- `SELA-handoff-快點來點餐.md` — 交班文件（部署注意、實測點）
- Claude Project「快點來點餐」背景文件（V2.16.1 起隨版本同步，不再放 zip）：《SELA-開發指導手冊》《SELA-常見錯誤與解決方案》《SELA-部署檢查清單》《SELA-菜單匯入格式規範》《SELA-專案架構精簡》＋程式碼快照 `線上訂餐_bundle_VX.Y.Z.txt`

---

> Made by **SELA** · V2.25.0 · 對齊 SELA-Starter-Kit V1.36.0
