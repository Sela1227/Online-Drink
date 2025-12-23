# SELA 快點來點餐

一個輕量級的團購訂餐系統，專為辦公室揪團訂飲料、訂餐設計。

![SELA Logo](app/static/images/sela-logo.svg)

---

## 📋 目錄

- [功能特色](#-功能特色)
- [技術架構](#-技術架構)
- [快速開始](#-快速開始)
- [環境變數設定](#-環境變數設定)
- [LINE Login 設定](#-line-login-設定)
- [Railway 部署](#-railway-部署)
- [菜單匯入格式](#-菜單匯入格式)
- [專案結構](#-專案結構)
- [使用說明](#-使用說明)
- [常見問題](#-常見問題)

---

## ✨ 功能特色

### 👥 團購功能
| 功能 | 說明 |
|-----|------|
| 快速開團 | 選擇店家、設定截止時間即可開團 |
| QR Code 分享 | 一鍵產生 QR Code，方便同事掃碼加入 |
| 即時訂單牆 | 所有人的訂單即時顯示 |
| 跟點功能 | 看到別人點的喜歡？一鍵跟點 |
| 修改訂單 | 結單後還能修改，不怕點錯 |
| 複製開團 | 從歷史團單快速複製設定開新團 |

### 🧋 飲料團專屬
| 功能 | 說明 |
|-----|------|
| 甜度/冰塊設定 | 團主可設定預設值或鎖定選項 |
| M/L 尺寸選擇 | 支援不同杯型價格 |
| 客製化備註 | 特殊需求都能寫 |

### 🍱 餐點團支援
| 功能 | 說明 |
|-----|------|
| 加購選項 | 配料、升級套餐等 |
| 多品項訂購 | 一次訂多樣沒問題 |

### 📝 匯出功能
| 功能 | 說明 |
|-----|------|
| 點餐文字 | 一鍵匯出給店家的訂單格式 |
| 收款文字 | 自動計算每人金額，方便收錢 |

### 🔐 管理後台
| 功能 | 說明 |
|-----|------|
| 店家管理 | 新增/編輯店家資訊、上傳 Logo |
| 菜單管理 | JSON 匯入菜單，支援 AI 輔助整理 |
| 使用者管理 | 查看所有使用者 |
| 團單管理 | 管理所有團單 |

---

## 🛠 技術架構

### 後端
| 技術 | 說明 |
|-----|------|
| [FastAPI](https://fastapi.tiangolo.com/) | 高效能 Python Web 框架 |
| [SQLAlchemy](https://www.sqlalchemy.org/) | ORM 資料庫操作 |
| [PostgreSQL](https://www.postgresql.org/) | 生產環境資料庫 |
| [Pydantic](https://docs.pydantic.dev/) | 資料驗證 |

### 前端
| 技術 | 說明 |
|-----|------|
| [Jinja2](https://jinja.palletsprojects.com/) | 模板引擎 |
| [HTMX](https://htmx.org/) | 無需寫 JS 的動態互動 |
| [Alpine.js](https://alpinejs.dev/) | 輕量級響應式框架 |
| [Tailwind CSS](https://tailwindcss.com/) | 原子化 CSS 框架 |

### 第三方服務
| 服務 | 說明 |
|-----|------|
| [LINE Login](https://developers.line.biz/) | 使用者身份驗證 |
| [Cloudinary](https://cloudinary.com/) | 店家 Logo 圖片託管（選用） |
| [Railway](https://railway.app/) | 部署平台 |

---

## 🚀 快速開始

### 環境需求
- Python 3.11+
- PostgreSQL（生產環境）或 SQLite（開發環境）

### 本地開發

#### 1. 複製專案
```bash
git clone https://github.com/你的帳號/Online-Drink.git
cd Online-Drink
```

#### 2. 建立虛擬環境
```bash
# Linux / Mac
python -m venv venv
source venv/bin/activate

# Windows PowerShell
python -m venv venv
venv\Scripts\activate
```

#### 3. 安裝依賴
```bash
pip install -r requirements.txt
```

#### 4. 設定環境變數
```bash
# Linux / Mac
cp .env.example .env

# Windows PowerShell
Copy-Item .env.example .env
```

編輯 `.env` 檔案，填入必要設定（見下方環境變數說明）。

#### 5. 啟動服務
```bash
uvicorn app.main:app --reload
```

#### 6. 開啟瀏覽器
```
http://localhost:8000
```

---

## 🔧 環境變數設定

建立 `.env` 檔案，設定以下變數：

### 必要設定

```env
# 資料庫連接字串
# 本地開發可使用 SQLite: sqlite:///./app.db
# 生產環境使用 PostgreSQL: postgresql://user:pass@host:5432/dbname
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# JWT 密鑰（請使用隨機字串，至少 32 字元）
SECRET_KEY=your-super-secret-key-change-this-in-production

# LINE Login 設定
LINE_CHANNEL_ID=1234567890
LINE_CHANNEL_SECRET=abcdef1234567890abcdef1234567890
LINE_REDIRECT_URI=https://your-domain.com/auth/callback

# 管理員的 LINE User ID（登入後從 Log 取得）
ADMIN_LINE_USER_ID=Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 網站網址（用於產生 QR Code）
BASE_URL=https://your-domain.com
```

### 選用設定

```env
# Cloudinary 圖片上傳（不設定則無法上傳店家 Logo）
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=123456789012345
CLOUDINARY_API_SECRET=abcdefghijklmnopqrstuvwxyz

# 開啟除錯模式
DEBUG=false
```

### 環境變數說明

| 變數名稱 | 必要 | 說明 | 範例 |
|---------|:----:|------|------|
| `DATABASE_URL` | ✅ | 資料庫連接字串 | `postgresql://user:pass@host:5432/db` |
| `SECRET_KEY` | ✅ | JWT 密鑰 | `your-secret-key-at-least-32-chars` |
| `LINE_CHANNEL_ID` | ✅ | LINE Login Channel ID | `1234567890` |
| `LINE_CHANNEL_SECRET` | ✅ | LINE Login Channel Secret | `abcdef123456...` |
| `LINE_REDIRECT_URI` | ✅ | LINE Login 回調網址 | `https://domain.com/auth/callback` |
| `ADMIN_LINE_USER_ID` | ✅ | 管理員 LINE User ID | `Uxxxxxxxx...` |
| `BASE_URL` | ✅ | 網站網址 | `https://your-domain.com` |
| `CLOUDINARY_CLOUD_NAME` | ❌ | Cloudinary 名稱 | `my-cloud` |
| `CLOUDINARY_API_KEY` | ❌ | Cloudinary API Key | `123456789` |
| `CLOUDINARY_API_SECRET` | ❌ | Cloudinary Secret | `abcdefg...` |
| `DEBUG` | ❌ | 除錯模式 | `true` 或 `false` |

---

## 🔐 LINE Login 設定

### 步驟 1：建立 LINE Login Channel

1. 前往 [LINE Developers Console](https://developers.line.biz/console/)
2. 登入你的 LINE 帳號
3. 點擊 **Create** 建立新的 Provider（或選擇現有的）
4. 在 Provider 中點擊 **Create a new channel**
5. 選擇 **LINE Login**
6. 填寫 Channel 資訊：
   - **Channel name**: SELA 快點來點餐（或你想要的名稱）
   - **Channel description**: 團購訂餐系統
   - **App types**: 勾選 **Web app**
7. 建立完成後，記下：
   - **Channel ID**
   - **Channel Secret**

### 步驟 2：設定 Callback URL

1. 在 Channel 頁面，點擊 **LINE Login** 標籤
2. 找到 **Callback URL** 設定
3. 點擊 **Edit** 新增：
   ```
   https://your-domain.up.railway.app/auth/callback
   ```
   - 本地開發可加：`http://localhost:8000/auth/callback`

### 步驟 3：發布 Channel

1. 在 Channel 頁面上方，找到 **Developing** 標籤
2. 點擊旁邊的 **Publish** 按鈕
3. 確認發布

> ⚠️ **重要**：Channel 必須發布（Published）才能讓所有人登入，否則只有 Channel 管理員能登入。

### 步驟 4：取得管理員 LINE User ID

1. 完成上述設定後，先部署應用程式
2. 用你的 LINE 帳號登入系統
3. 查看 Railway 的 **Deploy Logs**
4. 找到類似這樣的訊息：
   ```
   User logged in: LINE User ID = Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```
5. 複製這個 ID，設為 `ADMIN_LINE_USER_ID` 環境變數
6. 重新部署後，你就能進入管理後台

---

## 🚂 Railway 部署

### 步驟 1：建立專案

1. 前往 [Railway](https://railway.app/)
2. 點擊 **New Project**
3. 選擇 **Deploy from GitHub repo**
4. 授權並選擇你的專案 repository

### 步驟 2：新增 PostgreSQL 資料庫

1. 在專案畫面中，點擊 **New**
2. 選擇 **Database** → **PostgreSQL**
3. Railway 會自動建立資料庫並設定 `DATABASE_URL`

### 步驟 3：設定環境變數

1. 點擊你的應用程式服務（不是資料庫）
2. 選擇 **Variables** 標籤
3. 點擊 **New Variable** 逐一新增：

| 變數名稱 | 值 |
|---------|-----|
| `SECRET_KEY` | （自己產生的隨機字串） |
| `LINE_CHANNEL_ID` | （你的 LINE Channel ID） |
| `LINE_CHANNEL_SECRET` | （你的 LINE Channel Secret） |
| `LINE_REDIRECT_URI` | `https://你的網域.up.railway.app/auth/callback` |
| `ADMIN_LINE_USER_ID` | （登入後從 Log 取得） |
| `BASE_URL` | `https://你的網域.up.railway.app` |

### 步驟 4：取得網域

1. 點擊你的應用程式服務
2. 選擇 **Settings** 標籤
3. 找到 **Domains** 區塊
4. 點擊 **Generate Domain** 取得免費網域
5. 將網域更新到 `LINE_REDIRECT_URI` 和 `BASE_URL`

### 步驟 5：重新部署

1. 更新環境變數後，點擊 **Deployments** 標籤
2. 點擊最新的 deployment 旁的 **⋮**
3. 選擇 **Redeploy**

---

## 📦 菜單匯入格式

### 完整匯入（店家 + 菜單）

適用於新增全新的店家：

```json
{
  "store": {
    "name": "五十嵐",
    "category": "drink",
    "sugar_options": ["正常糖", "少糖", "半糖", "微糖", "無糖"],
    "ice_options": ["正常冰", "少冰", "微冰", "去冰", "熱"]
  },
  "menu": {
    "categories": [
      {
        "name": "找好茶",
        "items": [
          {"name": "四季春茶", "price": 25, "price_l": 30},
          {"name": "阿薩姆紅茶", "price": 25, "price_l": 30},
          {"name": "日式煎茶", "price": 30, "price_l": 35}
        ]
      },
      {
        "name": "找奶茶",
        "items": [
          {"name": "奶茶", "price": 35, "price_l": 45},
          {"name": "珍珠奶茶", "price": 40, "price_l": 50},
          {"name": "波霸奶茶", "price": 40, "price_l": 50}
        ]
      },
      {
        "name": "找新鮮",
        "items": [
          {"name": "檸檬汁", "price": 45, "price_l": 55},
          {"name": "金桔檸檬", "price": 50, "price_l": 60}
        ]
      }
    ]
  }
}
```

### 僅匯入菜單

適用於更新現有店家的菜單：

```json
{
  "store_id": 1,
  "mode": "replace",
  "menu": {
    "categories": [
      {
        "name": "主餐",
        "items": [
          {"name": "雞腿便當", "price": 85},
          {"name": "排骨便當", "price": 80}
        ]
      }
    ]
  }
}
```

### 欄位說明

#### 店家欄位

| 欄位 | 類型 | 必要 | 說明 |
|-----|------|:----:|------|
| `name` | string | ✅ | 店家名稱 |
| `category` | string | ✅ | `drink`（飲料）或 `meal`（餐點） |
| `sugar_options` | array | ❌ | 甜度選項（飲料店用） |
| `ice_options` | array | ❌ | 冰塊選項（飲料店用） |
| `logo_url` | string | ❌ | Logo 圖片網址 |

#### 菜單項目欄位

| 欄位 | 類型 | 必要 | 說明 |
|-----|------|:----:|------|
| `name` | string | ✅ | 品項名稱 |
| `price` | number | ✅ | M 杯價格（或單一價格） |
| `price_l` | number | ❌ | L 杯價格（有填才顯示尺寸選擇） |
| `options` | array | ❌ | 加購選項 |

#### 加購選項欄位

| 欄位 | 類型 | 必要 | 說明 |
|-----|------|:----:|------|
| `name` | string | ✅ | 選項名稱 |
| `price_diff` | number | ❌ | 加價金額（預設 0） |

### 餐點店範例

```json
{
  "store": {
    "name": "正忠排骨飯",
    "category": "meal"
  },
  "menu": {
    "categories": [
      {
        "name": "便當",
        "items": [
          {
            "name": "雞腿便當",
            "price": 85,
            "options": [
              {"name": "加滷蛋", "price_diff": 10},
              {"name": "飯加大", "price_diff": 10},
              {"name": "換五穀飯", "price_diff": 15}
            ]
          },
          {
            "name": "排骨便當",
            "price": 80,
            "options": [
              {"name": "加滷蛋", "price_diff": 10},
              {"name": "飯加大", "price_diff": 10}
            ]
          }
        ]
      },
      {
        "name": "湯品",
        "items": [
          {"name": "味噌湯", "price": 20},
          {"name": "貢丸湯", "price": 25}
        ]
      }
    ]
  }
}
```

---

## 📁 專案結構

```
Online-Drink/
├── app/
│   ├── __init__.py
│   ├── config.py              # 環境設定
│   ├── database.py            # 資料庫連接
│   ├── main.py                # FastAPI 應用程式入口
│   │
│   ├── models/                # SQLAlchemy 資料模型
│   │   ├── __init__.py
│   │   ├── group.py           # 團單模型
│   │   ├── menu.py            # 菜單模型
│   │   ├── order.py           # 訂單模型
│   │   ├── store.py           # 店家模型
│   │   └── user.py            # 使用者模型
│   │
│   ├── routers/               # API 路由
│   │   ├── __init__.py
│   │   ├── admin.py           # 管理後台 API
│   │   ├── auth.py            # 身份驗證 API
│   │   ├── dev.py             # 開發工具 API
│   │   ├── groups.py          # 團單 API
│   │   ├── home.py            # 首頁 API
│   │   └── orders.py          # 訂單 API
│   │
│   ├── schemas/               # Pydantic 資料驗證
│   │   ├── __init__.py
│   │   ├── menu.py            # 菜單匯入格式
│   │   └── store.py           # 店家匯入格式
│   │
│   ├── services/              # 業務邏輯服務
│   │   ├── __init__.py
│   │   ├── auth.py            # 身份驗證服務
│   │   ├── export_service.py  # 匯出服務
│   │   ├── import_service.py  # 匯入服務
│   │   └── upload_service.py  # 圖片上傳服務
│   │
│   ├── static/                # 靜態檔案
│   │   ├── css/
│   │   ├── js/
│   │   └── images/
│   │       └── sela-logo.svg  # SELA Logo
│   │
│   └── templates/             # Jinja2 HTML 模板
│       ├── admin/             # 管理後台頁面
│       │   ├── groups.html
│       │   ├── import.html
│       │   ├── import_preview.html
│       │   ├── index.html
│       │   ├── menus.html
│       │   ├── store_edit.html
│       │   ├── stores.html
│       │   └── users.html
│       ├── partials/          # HTMX 片段模板
│       │   ├── group_card.html
│       │   ├── menu_item.html
│       │   ├── my_order.html
│       │   └── order_wall.html
│       ├── base.html          # 基礎模板
│       ├── export.html        # 匯出頁面
│       ├── group.html         # 團單頁面
│       ├── group_new.html     # 開團頁面
│       ├── home.html          # 首頁
│       ├── login.html         # 登入頁
│       └── my_groups.html     # 我的團單頁面
│
├── migrations/                # Alembic 資料庫遷移
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
├── scripts/
│   ├── __init__.py
│   └── seed.py                # 種子資料腳本
│
├── .env.example               # 環境變數範例
├── .gitignore                 # Git 忽略檔案
├── Procfile                   # Railway 啟動指令
├── railway.toml               # Railway 設定檔
├── requirements.txt           # Python 依賴套件
└── README.md                  # 本文件
```

---

## 📖 使用說明

### 開團流程

1. **登入系統**
   - 點擊「使用 LINE 登入」
   - 授權 LINE Login

2. **開新團**
   - 點擊「開新團」按鈕
   - 選擇店家
   - 輸入團名
   - **點擊時間預設按鈕**（如「1小時後」）設定截止時間
   - 如果是飲料團，可設定預設甜度/冰塊
   - 點擊「開團！」

3. **分享連結**
   - 複製網址分享給同事
   - 或產生 QR Code 讓大家掃碼

### 點餐流程

1. **加入團單**
   - 點擊分享連結或掃描 QR Code
   - 登入 LINE

2. **選擇品項**
   - 瀏覽菜單
   - 點擊想要的品項
   - 選擇尺寸（如果有）
   - 選擇甜度/冰塊（飲料團）
   - 選擇加購選項（如果有）
   - 填寫數量和備註
   - 點擊「加入購物車」

3. **確認結單**
   - 確認訂單內容
   - 點擊「確定結單」

4. **修改訂單**
   - 如果需要修改，點擊「修改訂單」
   - 修改完成後再次「確定結單」

### 團主操作

1. **提前截止**
   - 在團單頁面點擊「提前截止」
   - 確認後團單立即截止

2. **匯出訂單**
   - 點擊「點餐文字」取得給店家的訂單
   - 點擊「收款文字」取得收款清單

### 管理後台

1. **進入後台**
   - 登入後，點擊右上角「管理」
   - 必須是管理員才能看到此選項

2. **新增店家**
   - 進入「店家管理」
   - 點擊「匯入店家」
   - 貼上 JSON 格式的店家資料
   - 點擊「預覽」確認無誤
   - 點擊「確認匯入」

3. **更新菜單**
   - 進入「菜單管理」
   - 選擇要更新的店家
   - 點擊「匯入菜單」
   - 貼上新的菜單 JSON
   - 選擇「覆蓋現有菜單」或「新增版本」

---

## ❓ 常見問題

### 登入相關

#### Q: 點擊 LINE 登入後沒反應？
**A:** 檢查以下項目：
1. LINE Login Channel 是否已建立
2. `LINE_CHANNEL_ID` 和 `LINE_CHANNEL_SECRET` 是否正確
3. 瀏覽器是否有阻擋彈出視窗

#### Q: 登入後又跳回登入頁？
**A:** 檢查以下項目：
1. LINE Login Channel 是否已發布（Published）
2. Callback URL 是否正確設定為 `https://你的網域/auth/callback`
3. `SECRET_KEY` 環境變數是否有設定

#### Q: 如何成為管理員？
**A:** 
1. 先用你的 LINE 帳號登入系統一次
2. 查看 Railway 的 **Deploy Logs**
3. 找到 `User logged in: LINE User ID = Uxxxx...` 訊息
4. 複製該 ID，設為 `ADMIN_LINE_USER_ID` 環境變數
5. 重新部署應用程式

### 開團相關

#### Q: 開團按鈕沒反應？
**A:** 確認以下項目都已填寫：
1. ✅ 已選擇店家
2. ✅ 已輸入團名
3. ✅ 已**點擊時間預設按鈕**設定截止時間
   - 必須點擊「30分鐘後」「1小時後」等按鈕
   - 直接用日期選擇器可能無法正確提交

#### Q: 找不到店家？
**A:** 
1. 確認已在管理後台新增店家
2. 確認店家狀態為「啟用」
3. 確認店家有設定菜單

### 菜單匯入相關

#### Q: 菜單匯入失敗？
**A:** 確認 JSON 格式正確：
- ✅ 使用雙引號 `"` 而非單引號 `'`
- ✅ 數字不要加引號（`"price": 50` 而非 `"price": "50"`）
- ✅ 最後一個項目後面不要有逗號
- ✅ 使用 [JSON 驗證工具](https://jsonlint.com/) 檢查格式

#### Q: 如何用 AI 整理菜單？
**A:** 你可以將店家菜單圖片給 AI（如 ChatGPT、Claude），請它轉換成指定的 JSON 格式。提示詞範例：

```
請將這份菜單轉換成以下 JSON 格式：
{
  "store": {
    "name": "店家名稱",
    "category": "drink 或 meal",
    "sugar_options": ["甜度選項"],
    "ice_options": ["冰塊選項"]
  },
  "menu": {
    "categories": [
      {
        "name": "分類名稱",
        "items": [
          {"name": "品項名稱", "price": M價格, "price_l": L價格}
        ]
      }
    ]
  }
}
```

### 部署相關

#### Q: Railway 部署失敗？
**A:** 查看 Build Logs 和 Deploy Logs 找錯誤訊息。常見問題：
1. `requirements.txt` 缺少套件
2. 環境變數未設定
3. 資料庫連接失敗

#### Q: 圖片上傳失敗？
**A:** 確認 Cloudinary 設定：
1. 已建立 Cloudinary 帳號
2. 三個環境變數都有正確設定
3. API Key 和 Secret 沒有多餘空格

---

## 📄 授權

MIT License

---

## 🤝 貢獻

歡迎提交 Issue 和 Pull Request！

---

## 📧 聯絡

如有問題或建議，歡迎提出 [Issue](https://github.com/你的帳號/Online-Drink/issues)。
