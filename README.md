# SELA 快點來點餐 🧋

> 一個為 30 人左右團隊設計的群組訂餐系統，支援飲料、餐點、團購三種類型。

**線上版本**: https://online-drink-production.up.railway.app

---

## 📋 目錄

- [功能總覽](#功能總覽)
- [技術架構](#技術架構)
- [資料庫設計](#資料庫設計)
- [部署指南](#部署指南)
- [開發注意事項](#開發注意事項)
- [問題與解決方案](#問題與解決方案)
- [功能開發歷程](#功能開發歷程)

---

## 功能總覽

### 🎯 核心功能 (66 項)

#### Phase 0-2: 基礎建設
- LINE Login 認證系統
- 店家管理（CRUD、Logo 上傳）
- 菜單管理（品項、分類、價格）
- 團單系統（開團、下單、結單）
- 訂單管理（草稿、已提交、編輯中三狀態）
- QR Code 分享功能

#### Phase 3: 飲料店特化
- 甜度/冰塊選項管理
- 加料系統（珍珠、椰果等）
- 預設甜冰鎖定功能
- 隨機免單抽獎
- 盲點模式（截止前隱藏他人訂單）

#### Phase 4: 店家資訊強化
- 多分店管理（名稱、電話、地址）
- 外部連結整合（官網、Uber Eats、foodpanda、Google Maps）
- 店家收藏功能
- 菜單圖片（Cloudinary 雲端存儲）

#### Phase 5: 使用者體驗
- 部門/群組系統
- 團單可見範圍控制（公開/限定部門）
- 自動催單提醒
- 湊團制（最低成團人數）
- 訂單複製（複製上次訂單）
- 跟單功能（複製他人訂單）

#### Phase 6: 進階功能
- 請客功能（團主請客標記）
- RWD 響應式設計
- 統一返回按鈕
- 問題回報系統
- JSON 匯入菜單
- 首頁店家名單（快速開團）

#### Phase 7: 社群互動
- 公告系統（置頂、過期、編輯）
- 快速點餐（常點/熱門品項）
- 投票系統（多選項、可見性控制）
- 投票小卡（首頁紫色便利貼）

#### Phase 8: 營運工具
- 使用者推薦店家（含圖片上傳）
- 管理員審核流程
- 店家部門綁定（限定可見範圍）
- 分店系統完善

#### Phase 9: 個人統計
- 消費金額統計（總額、平均）
- 分類統計（飲料、餐點、團購）
- 時間篩選（這個月、過去30天、3個月、今年、自訂區間）
- 月度消費趨勢圖
- 最愛店家 TOP 5
- 最常點品項 TOP 10
- 最常跟團的團主
- 下單習慣分析（時段、星期）
- 飲料偏好（甜度、冰塊、加料）
- 趣味統計（開團數、中獎數、請客/被請客次數）
- 店家部門綁定（限定可見範圍）
- 分店系統完善

---

## 技術架構

### 後端
```
Python 3.11+
├── FastAPI          # Web 框架
├── SQLAlchemy       # ORM
├── Jinja2           # 模板引擎
├── python-jose      # JWT 處理
├── httpx            # HTTP 客戶端
└── qrcode           # QR Code 生成
```

### 前端
```
HTML + Tailwind CSS
├── Alpine.js        # 輕量互動框架
├── HTMX             # 局部更新
└── Tailwind CSS     # 樣式框架（CDN）
```

### 資料庫
```
PostgreSQL (Railway 提供)
```

### 雲端服務
```
├── Railway          # 部署平台
├── Cloudinary       # 圖片存儲
└── LINE Login       # 第三方認證
```

### 專案結構
```
線上訂餐/
├── app/
│   ├── main.py              # 應用入口 + 資料庫遷移
│   ├── config.py            # 環境設定
│   ├── database.py          # 資料庫連線
│   ├── models/              # SQLAlchemy Models
│   │   ├── user.py          # User, Feedback, StoreRecommendation
│   │   ├── store.py         # Store, StoreBranch, StoreOption, StoreTopping
│   │   ├── menu.py          # Menu, MenuItem, MenuCategory
│   │   ├── group.py         # Group
│   │   ├── order.py         # Order, OrderItem
│   │   ├── department.py    # Department, UserDepartment, GroupDepartment, StoreDepartment
│   │   ├── vote.py          # Vote, VoteOption, VoteRecord
│   │   └── template.py      # GroupTemplate
│   ├── routers/             # API 路由
│   │   ├── auth.py          # LINE Login 認證
│   │   ├── home.py          # 首頁、個人資料
│   │   ├── groups.py        # 團單操作
│   │   ├── orders.py        # 訂單操作
│   │   ├── admin.py         # 後台管理
│   │   └── votes.py         # 投票系統
│   ├── services/            # 業務邏輯
│   │   ├── auth.py          # 認證服務
│   │   └── export_service.py # 匯出服務
│   └── templates/           # Jinja2 模板
│       ├── base.html        # 基礎模板
│       ├── home.html        # 首頁
│       ├── group.html       # 團單頁
│       ├── group_new.html   # 開團頁
│       ├── partials/        # 可重用組件
│       │   ├── home_groups.html
│       │   └── group_card.html
│       └── admin/           # 後台模板
├── static/                  # 靜態資源
├── requirements.txt         # Python 依賴
├── railway.toml             # Railway 設定
├── Dockerfile               # Docker 設定（備用）
└── start.sh                 # 啟動腳本（備用）
```

---

## 資料庫設計

### ER 關係圖

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│    User     │────<│   Order     │>────│    Group    │
└─────────────┘     └─────────────┘     └─────────────┘
       │                   │                   │
       │            ┌──────┴──────┐            │
       │            │  OrderItem  │            │
       │            └─────────────┘            │
       │                                       │
       ├──< UserDepartment >──┬────────────────┤
       │                      │                │
       │              ┌───────┴───────┐        │
       │              │  Department   │        │
       │              └───────────────┘        │
       │                      │                │
       │              GroupDepartment >────────┤
       │              StoreDepartment >────────┼───< Store
       │                                       │        │
       │                                       │   StoreBranch
       │                                       │   StoreOption
       │                                       │   StoreTopping
       │                                       │        │
       │                               ┌───────┴────────┤
       │                               │     Menu       │
       │                               └────────────────┤
       │                                       │        │
       │                               MenuCategory  MenuItem
       │
       ├──< Vote >──< VoteOption >──< VoteRecord
       │
       ├──< Feedback
       │
       └──< StoreRecommendation
```

### 主要資料表

#### users
| 欄位 | 類型 | 說明 |
|------|------|------|
| id | SERIAL | 主鍵 |
| line_user_id | VARCHAR(100) | LINE 用戶 ID |
| display_name | VARCHAR(100) | LINE 顯示名稱 |
| nickname | VARCHAR(100) | 自訂暱稱 |
| picture_url | VARCHAR(500) | 大頭貼 |
| is_admin | BOOLEAN | 管理員 |
| is_guest | BOOLEAN | 訪客模式 |
| last_login_at | TIMESTAMP | 最後登入 |
| last_active_at | TIMESTAMP | 最後活動 |

#### stores
| 欄位 | 類型 | 說明 |
|------|------|------|
| id | SERIAL | 主鍵 |
| name | VARCHAR(100) | 店名 |
| category | ENUM | DRINK/MEAL/GROUP_BUY |
| logo_url | VARCHAR(500) | Logo 圖片 |
| phone | VARCHAR(50) | 電話 |
| address | VARCHAR(300) | 地址 |
| website_url | VARCHAR(500) | 官網 |
| ubereats_url | VARCHAR(500) | Uber Eats |
| foodpanda_url | VARCHAR(500) | foodpanda |
| google_maps_url | VARCHAR(500) | Google Maps |
| is_active | BOOLEAN | 啟用狀態 |
| is_public | BOOLEAN | 公開/限定部門 |

#### groups
| 欄位 | 類型 | 說明 |
|------|------|------|
| id | SERIAL | 主鍵 |
| store_id | INTEGER | 店家 FK |
| menu_id | INTEGER | 菜單 FK |
| owner_id | INTEGER | 團主 FK |
| branch_id | INTEGER | 分店 FK |
| name | VARCHAR(100) | 團名 |
| note | TEXT | 備註 |
| category | ENUM | 分類 |
| deadline | TIMESTAMP | 截止時間 |
| is_closed | BOOLEAN | 手動截止 |
| is_public | BOOLEAN | 公開/限定部門 |
| delivery_fee | NUMERIC | 外送費 |
| default_sugar | VARCHAR(50) | 預設甜度 |
| default_ice | VARCHAR(50) | 預設冰塊 |
| lock_sugar | BOOLEAN | 鎖定甜度 |
| lock_ice | BOOLEAN | 鎖定冰塊 |
| is_blind_mode | BOOLEAN | 盲點模式 |
| enable_lucky_draw | BOOLEAN | 啟用抽獎 |
| lucky_draw_count | INTEGER | 免單人數 |
| lucky_winner_ids | TEXT | 中獎者 |
| treat_user_id | INTEGER | 請客者 |
| min_members | INTEGER | 最低成團人數 |
| auto_extend | BOOLEAN | 自動延長 |

#### orders
| 欄位 | 類型 | 說明 |
|------|------|------|
| id | SERIAL | 主鍵 |
| group_id | INTEGER | 團單 FK |
| user_id | INTEGER | 用戶 FK |
| status | ENUM | DRAFT/SUBMITTED/EDITING |
| total_amount | NUMERIC | 總金額 |
| created_at | TIMESTAMP | 建立時間 |

#### order_items
| 欄位 | 類型 | 說明 |
|------|------|------|
| id | SERIAL | 主鍵 |
| order_id | INTEGER | 訂單 FK |
| menu_item_id | INTEGER | 品項 FK |
| item_name | VARCHAR(100) | 品項名稱 |
| quantity | INTEGER | 數量 |
| unit_price | NUMERIC | 單價 |
| size | VARCHAR(20) | 尺寸 |
| sugar | VARCHAR(50) | 甜度 |
| ice | VARCHAR(50) | 冰塊 |
| note | TEXT | 備註 |

---

## 部署指南

### Railway 部署

#### 1. 環境變數設定
```env
# 資料庫（Railway 自動提供）
DATABASE_URL=postgresql://...

# LINE Login
LINE_CHANNEL_ID=your_channel_id
LINE_CHANNEL_SECRET=your_channel_secret
LINE_CALLBACK_URL=https://your-app.up.railway.app/auth/callback

# JWT
JWT_SECRET_KEY=your_secret_key

# Cloudinary（圖片上傳）
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret
```

#### 2. railway.toml
```toml
[build]
builder = "nixpacks"

[deploy]
startCommand = "uvicorn app.main:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/"
healthcheckTimeout = 300
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 3
```

#### 3. requirements.txt
```txt
fastapi==0.109.0
uvicorn==0.27.0
sqlalchemy==2.0.25
psycopg2-binary==2.9.9
python-jose==3.3.0
httpx==0.26.0
python-multipart==0.0.6
jinja2==3.1.3
qrcode==7.4.2
pillow==10.2.0
cloudinary==1.38.0
```

### LINE Login 設定

1. 到 [LINE Developers Console](https://developers.line.biz/)
2. 建立 Provider 和 Channel (LINE Login)
3. 設定 Callback URL: `https://your-app.up.railway.app/auth/callback`
4. 取得 Channel ID 和 Channel Secret

---

## 開發注意事項

### ⚠️ Railway 部署重點

#### 1. 不要使用 Alembic
```python
# ❌ 錯誤：不要在 railway.toml 或 requirements.txt 包含 alembic
startCommand = "alembic upgrade head && uvicorn..."

# ✅ 正確：使用 SQLAlchemy 自動建表 + 手動遷移
# 在 app/main.py 的 startup 事件中處理
```

#### 2. PostgreSQL Enum 處理
```python
# ❌ 錯誤：直接修改 Python Enum 定義
class CategoryType(str, Enum):
    DRINK = "drink"
    MEAL = "meal"
    GROUP_BUY = "group_buy"  # 新增值

# ✅ 正確：使用 Raw SQL 新增 Enum 值（大寫）
def add_enum_value_if_not_exists(enum_name: str, new_value: str):
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{new_value}'"))
```

#### 3. 新增欄位的安全方式
```python
def add_column_if_not_exists(table: str, column: str, definition: str):
    try:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
    except Exception as e:
        if "already exists" not in str(e):
            raise
```

#### 4. Nixpacks 建置失敗時的備案
```toml
# railway.toml
[build]
builder = "dockerfile"

# Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["sh", "start.sh"]
```

### 🔧 常見問題檢查清單

1. **部署後 500 錯誤**
   - 檢查 Railway Logs
   - 確認環境變數設定正確
   - 確認資料庫遷移完成

2. **LINE Login 失敗**
   - 確認 Callback URL 完全一致
   - 確認 Channel ID/Secret 正確
   - 檢查 LINE Developers Console 設定

3. **圖片上傳失敗**
   - 確認 Cloudinary 設定正確
   - 檢查檔案大小限制

4. **表單提交失敗**
   - 檢查 Form 欄位名稱是否匹配
   - 確認 enctype="multipart/form-data"（上傳檔案時）

---

## 問題與解決方案

### 問題 1: taipei_tz 未定義
**錯誤訊息**: `NameError: name 'taipei_tz' is not defined`

**原因**: 在 groups.py 中使用了未定義的變數

**解決方案**:
```python
# 在檔案開頭定義全局常數
from datetime import timezone, timedelta
TAIPEI_TZ = timezone(timedelta(hours=8))

# 使用時
thirty_days_ago = datetime.now(TAIPEI_TZ).replace(tzinfo=None) - timedelta(days=30)
```

### 問題 2: Enum 值新增失敗
**錯誤訊息**: `invalid input value for enum categorytype: "GROUP_BUY"`

**原因**: PostgreSQL Enum 使用大寫，但程式傳入小寫

**解決方案**:
```python
# PostgreSQL 中 Enum 值是大寫
# 新增時用大寫
ALTER TYPE categorytype ADD VALUE IF NOT EXISTS 'GROUP_BUY';

# 查詢時 SQLAlchemy 會自動轉換
```

### 問題 3: 重複投票
**錯誤訊息**: 使用者可以對同一選項重複投票

**解決方案**:
```python
# 1. 資料庫加入唯一約束
ALTER TABLE vote_records 
ADD CONSTRAINT vote_records_option_user_unique 
UNIQUE (option_id, user_id);

# 2. 程式碼檢查
existing = db.query(VoteRecord).filter(
    VoteRecord.option_id == option_id,
    VoteRecord.user_id == user.id
).first()
if existing:
    return  # 已投過
```

### 問題 4: 表單檔案上傳
**錯誤訊息**: 檔案欄位收到空值

**解決方案**:
```html
<!-- 表單必須有 enctype -->
<form method="POST" enctype="multipart/form-data">
    <input type="file" name="menu_image">
</form>
```

```python
# 路由要用 UploadFile
from fastapi import UploadFile, File

async def submit(menu_image: UploadFile = File(None)):
    if menu_image and menu_image.filename:
        contents = await menu_image.read()
```

### 問題 5: 部門過濾邏輯
**需求**: 非公開店家只對綁定部門成員顯示

**解決方案**:
```python
# 取得用戶部門
user_dept_ids = [ud.department_id for ud in db.query(UserDepartment).filter(
    UserDepartment.user_id == user.id
).all()]

# 過濾可見店家
visible_stores = []
for store in all_stores:
    if store.is_public:
        visible_stores.append(store)
    elif user.is_admin:
        visible_stores.append(store)
    else:
        store_dept_ids = {sd.department_id for sd in db.query(StoreDepartment).filter(
            StoreDepartment.store_id == store.id
        ).all()}
        if store_dept_ids & set(user_dept_ids):
            visible_stores.append(store)
```

---

## 功能開發歷程

### Phase 0-2 (基礎)
- 建立專案架構
- LINE Login 整合
- 基本 CRUD 功能
- 訂單流程

### Phase 3 (飲料特化)
- 甜冰選項系統
- 加料功能
- 趣味功能（抽獎、盲點）

### Phase 4 (店家強化)
- 分店管理
- 外部連結
- 圖片上傳

### Phase 5 (使用者體驗)
- 部門系統
- 權限控制
- 訂單複製

### Phase 6 (進階功能)
- 請客功能
- RWD 優化
- 問題回報
- JSON 匯入

### Phase 7 (社群互動)
- 公告系統
- 快速點餐
- 投票系統

### Phase 8 (營運工具)
- 推薦店家
- 審核流程
- 店家部門綁定

---

## 授權

MIT License

---

## 聯絡

如有問題，請透過系統內的「問題回報」功能反映。
