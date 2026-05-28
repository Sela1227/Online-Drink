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
| 後端 | FastAPI 0.104.1 + SQLAlchemy 2.0.23 |
| Web 框架核心 | Starlette 0.27.0（鎖版本，見 CLAUDE.md 坑 #10） |
| 資料庫 | PostgreSQL |
| 前端 | Jinja2 3.1.2 + Tailwind CSS（CDN）+ Alpine.js + HTMX |
| 認證 | LINE Login |
| 圖片 | Cloudinary |
| 部署 | Railway（Dockerfile 模式） |

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
```

---

## 目錄結構

```
線上訂餐/
├── app/
│   ├── main.py              FastAPI 入口 + 自動遷移
│   ├── config.py            Pydantic Settings
│   ├── database.py          SQLAlchemy 連線
│   ├── models/              SQLAlchemy Model（User/Store/Menu/Group/Order/...）
│   ├── routers/             API 路由（auth/admin/groups/orders/votes/...）
│   ├── services/            業務邏輯（auth/import/export）
│   ├── schemas/             Pydantic Schema
│   ├── templates/           Jinja2 模板（含 partials、admin、votes）
│   └── static/              CSS / JS / images / sela.svg / favicon/
├── docs/                    歷史開發文件（架構、踩坑、部署、匯入規範）
├── examples/                範例 JSON
├── menu/                    各店家菜單 JSON 範本
├── scripts/                 種子資料、SQL 工具
├── requirements.txt         依賴（== 鎖版本，坑 #10）
├── railway.toml             Railway 部署設定（Dockerfile 模式）
├── Dockerfile
├── start.sh
├── .gitignore
├── CLAUDE.md                ← 給 AI 看的工作上下文（最重要）
├── SELA-handoff.md          ← Kit 回流交接
└── README.md                ← 本檔
```

---

## 主要功能

- **LINE Login** 認證 + 暱稱自訂
- **店家／菜單管理**（後台）：飲料／餐點／團購三類分流，飲料含甜冰／加料選項
- **團單**：開團、設截止時間、QR Code 分享、盲訂模式、抽幸運獎
- **訂單**：草稿／已送出／編輯中三狀態、複製功能、即時訂單牆
- **部門系統**：使用者可歸屬部門
- **公告／投票／回報**
- **個人消費統計**
- **JSON 匯入**：店家 + 菜單批次建立（見 `docs/SELA-菜單匯入格式規範.md`）

---

## 部署

走 Railway Dockerfile 模式。詳細部署檢查清單見 `docs/SELA-部署檢查清單.md`。

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
- 本專案刻意不用 Alembic，schema 演進走 `app/main.py` startup 內的 raw SQL（見 CLAUDE.md 坑 #1）
- `requirements.txt` 必須維持 `==` 精確版本鎖死，否則 Railway rebuild 時會抓到不相容的 Starlette 新版（見 CLAUDE.md 坑 #10）

---

## 開發注意事項

更詳細的踩坑與規範見：

- `CLAUDE.md` — 給 AI 看的工作上下文（含 10 條已驗證踩坑紀錄）
- `docs/SELA-開發指導手冊.md` — 完整開發規範
- `docs/SELA-常見錯誤與解決方案.md` — 錯誤對應表
- `docs/SELA-部署檢查清單.md` — 部署前必跑檢查
- `docs/SELA-菜單匯入格式規範.md` — JSON 匯入格式
- `docs/SELA-專案架構精簡.md` — 資料模型快速查閱

---

> Made by **SELA** · V1.0.0 · 對齊 SELA-Starter-Kit V1.9.0
