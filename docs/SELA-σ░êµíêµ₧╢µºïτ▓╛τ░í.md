# SELA 專案架構精簡文檔

> 快速了解專案結構與資料模型

---

## 📁 目錄結構

```
線上訂餐/
├── app/
│   ├── main.py              # FastAPI 入口 + 遷移邏輯
│   ├── config.py            # Pydantic Settings
│   ├── database.py          # SQLAlchemy 連線
│   │
│   ├── models/
│   │   ├── user.py          # User, Feedback, StoreRecommendation
│   │   ├── store.py         # Store, StoreBranch, StoreOption, StoreTopping
│   │   ├── menu.py          # Menu, MenuItem, MenuCategory
│   │   ├── group.py         # Group (團單)
│   │   ├── order.py         # Order, OrderItem
│   │   ├── department.py    # Department 相關
│   │   └── vote.py          # Vote, VoteOption, VoteRecord
│   │
│   ├── routers/
│   │   ├── auth.py          # LINE Login
│   │   ├── home.py          # 首頁
│   │   ├── groups.py        # 團單操作
│   │   ├── orders.py        # 訂單操作
│   │   ├── admin.py         # 後台管理
│   │   └── votes.py         # 投票系統
│   │
│   ├── services/
│   │   ├── auth.py          # JWT 認證
│   │   ├── import_service.py # JSON 匯入
│   │   └── export_service.py # 匯出
│   │
│   └── templates/
│       ├── base.html
│       ├── home.html
│       ├── partials/        # 可重用組件
│       └── admin/           # 後台模板
│
├── requirements.txt
├── railway.toml
├── Dockerfile              # 備用
└── start.sh                # 備用
```

---

## 🗄️ 核心資料表

### users
```sql
id              SERIAL PRIMARY KEY
line_user_id    VARCHAR(100)     -- LINE ID
display_name    VARCHAR(100)     -- LINE 名稱
nickname        VARCHAR(100)     -- 自訂暱稱
picture_url     VARCHAR(500)
is_admin        BOOLEAN DEFAULT FALSE
is_guest        BOOLEAN DEFAULT FALSE
last_login_at   TIMESTAMP
last_active_at  TIMESTAMP
```

### stores
```sql
id              SERIAL PRIMARY KEY
name            VARCHAR(100)
category        ENUM('DRINK','MEAL','GROUP_BUY')
logo_url        VARCHAR(500)
phone           VARCHAR(50)
is_active       BOOLEAN DEFAULT TRUE
is_public       BOOLEAN DEFAULT TRUE
```

### groups (團單)
```sql
id              SERIAL PRIMARY KEY
store_id        INTEGER REFERENCES stores(id)
menu_id         INTEGER REFERENCES menus(id)
owner_id        INTEGER REFERENCES users(id)
name            VARCHAR(100)
note            TEXT
category        ENUM
deadline        TIMESTAMP
is_closed       BOOLEAN DEFAULT FALSE
share_code      VARCHAR(20)
-- 飲料特化
default_sugar   VARCHAR(50)
default_ice     VARCHAR(50)
lock_sugar      BOOLEAN
lock_ice        BOOLEAN
-- 功能開關
is_blind_mode   BOOLEAN
enable_lucky_draw BOOLEAN
```

### orders
```sql
id              SERIAL PRIMARY KEY
group_id        INTEGER REFERENCES groups(id)
user_id         INTEGER REFERENCES users(id)
status          ENUM('DRAFT','SUBMITTED','EDITING')
total_amount    NUMERIC(10,2)
note            TEXT
created_at      TIMESTAMP
```

### order_items
```sql
id              SERIAL PRIMARY KEY
order_id        INTEGER REFERENCES orders(id)
menu_item_id    INTEGER
item_name       VARCHAR(100)
quantity        INTEGER
unit_price      NUMERIC(10,2)
size            VARCHAR(20)
sugar           VARCHAR(50)
ice             VARCHAR(50)
note            TEXT
```

---

## 🔗 資料關係

```
User ─┬─< Order >─ Group ─< Store
      │              │
      │              └─< Menu >─< MenuCategory >─< MenuItem
      │
      ├─< Feedback
      ├─< StoreRecommendation
      └─< UserDepartment >─ Department
```

---

## 📱 主要頁面路由

| 路徑 | 說明 | 權限 |
|------|------|------|
| `/` | 首頁 | 登入 |
| `/auth/login` | 登入 | 公開 |
| `/auth/callback` | LINE 回調 | 公開 |
| `/groups/new` | 開新團 | 登入 |
| `/groups/{id}` | 團單詳情 | 登入 |
| `/profile` | 個人資料 | 登入 |
| `/admin` | 後台 | 管理員 |
| `/admin/stores` | 店家管理 | 管理員 |
| `/admin/import` | JSON 匯入 | 管理員 |

---

## 🎯 Enum 定義

```python
# 店家/團單分類 (PostgreSQL 用大寫)
CategoryType: DRINK, MEAL, GROUP_BUY

# 訂單狀態
OrderStatus: DRAFT, SUBMITTED, EDITING

# 回報類型
FeedbackType: BUG, SUGGESTION, OTHER

# 回報狀態
FeedbackStatus: OPEN, IN_PROGRESS, RESOLVED, CLOSED
```

---

## 🔧 關鍵設定

### railway.toml
```toml
[build]
builder = "nixpacks"

[deploy]
startCommand = "uvicorn app.main:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/"
healthcheckTimeout = 300
```

### requirements.txt (精簡版)
```
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
sqlalchemy>=2.0.0
pydantic-settings>=2.0.0
python-multipart>=0.0.6
jinja2>=3.1.2
httpx>=0.25.0
python-jose[cryptography]>=3.3.0
qrcode[pil]>=7.4
psycopg2-binary>=2.9.9
cloudinary>=1.36.0
```

---

## 🎨 前端技術

- **Tailwind CSS**: CDN 引入
- **Alpine.js**: 輕量互動
- **HTMX**: 局部更新
- **主色**: orange-500 (#F97316)
- **風格**: 便利貼卡片

---

*精簡版架構文檔，詳細內容請參考完整開發指導手冊*
