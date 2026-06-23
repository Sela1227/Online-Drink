# SELA 快點來點餐 - 開發指導手冊

> 最後更新: 2024/12/24 | 適用版本: Railway 部署

---

## 📋 專案概覽

| 項目 | 說明 |
|------|------|
| **專案名稱** | SELA 快點來點餐 |
| **線上網址** | https://online-drink-production.up.railway.app |
| **目標使用者** | 約 30 人團隊 |
| **主要功能** | 飲料/餐點/團購訂餐系統 |
| **認證方式** | LINE Login |

---

## 🛠️ 技術架構

```
後端: FastAPI + SQLAlchemy 2.0 + PostgreSQL
前端: Jinja2 + Tailwind CSS + Alpine.js + HTMX
部署: Railway (Nixpacks)
圖片: Cloudinary
```

### 專案結構
```
線上訂餐/
├── app/
│   ├── main.py              # 應用入口 + 資料庫遷移
│   ├── config.py            # 環境設定
│   ├── database.py          # 資料庫連線
│   ├── models/              # SQLAlchemy Models
│   ├── routers/             # API 路由
│   ├── services/            # 業務邏輯
│   └── templates/           # Jinja2 模板
├── requirements.txt
├── railway.toml
└── Dockerfile (備用)
```

---

## ⚠️ Railway 部署黃金法則

### 1. 不要使用 Alembic
```python
# ❌ 錯誤
# railway.toml:
startCommand = "alembic upgrade head && uvicorn..."
# requirements.txt:
alembic==1.x.x

# ✅ 正確：使用 SQLAlchemy 自動建表 + 手動遷移
# 在 main.py 的 startup 事件中處理
```

### 2. PostgreSQL Enum 必須用大寫
```python
# ❌ 錯誤：表單送小寫
category = "group_buy"

# ✅ 正確：PostgreSQL Enum 值是大寫
# 新增 Enum 值：
ALTER TYPE categorytype ADD VALUE IF NOT EXISTS 'GROUP_BUY';

# 修改欄位時用 Raw SQL + 大寫值
with engine.begin() as conn:
    conn.execute(text("UPDATE stores SET category = 'DRINK' WHERE ..."))
```

### 3. railway.toml 設定
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

### 4. Nixpacks 建置失敗時的備案
```toml
# railway.toml
[build]
builder = "dockerfile"
# 移除 startCommand
```

```dockerfile
# Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["sh", "start.sh"]
```

```bash
# start.sh
#!/bin/bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

---

## 🗄️ 資料庫操作指南

### 安全新增欄位
```python
def add_column_if_not_exists(table: str, column: str, definition: str):
    try:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
            print(f"✅ Added column {column} to {table}")
    except Exception as e:
        if "already exists" not in str(e):
            raise
        print(f"ℹ️ Column {column} already exists in {table}")
```

### 安全新增 Enum 值
```python
def add_enum_value_if_not_exists(enum_name: str, new_value: str):
    """新增 Enum 值（必須用大寫）"""
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{new_value}'"))
```

### SQLAlchemy Table 重複定義修復
```python
# 在 Model 類別加入 extend_existing
class SystemSetting(Base):
    __tablename__ = "system_settings"
    __table_args__ = {'extend_existing': True}  # ← 加入這行
    
    id = Column(Integer, primary_key=True)
    # ...
```

---

## 🎨 Jinja2 Filter 註冊

### taipei 時區 Filter
```python
# 在每個 router 檔案開頭（如 admin.py, home.py）
from datetime import timezone, timedelta

TAIPEI_TZ = timezone(timedelta(hours=8))

def taipei(dt):
    """將 UTC 時間轉換為台北時間"""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M")

# 建立 templates 時註冊
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["taipei"] = taipei
```

---

## 🔧 FastAPI Router 設定

### 避免空 prefix 錯誤
```python
# ❌ 錯誤：prefix 和 path 都是空的
router = APIRouter()

@router.get("")  # 空 path
def home():
    pass

app.include_router(router)  # 沒有 prefix

# ✅ 正確：至少要有 prefix 或 path
router = APIRouter()

@router.get("/")  # 有 path
def home():
    pass

# 或者
app.include_router(router, prefix="/home")  # 有 prefix
```

---

## 📁 檔案編碼問題

### UTF-8 編碼錯誤修復
```bash
# 錯誤訊息：stream did not contain valid UTF-8

# 解決方法 1：重新建立檔案
# Windows PowerShell:
Get-Content app/services/import_service.py | Set-Content -Encoding utf8 app/services/import_service_new.py
Move-Item app/services/import_service_new.py app/services/import_service.py -Force

# 解決方法 2：用 Python 重新寫入
with open('file.py', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()
with open('file.py', 'w', encoding='utf-8') as f:
    f.write(content)
```

---

## 🧪 本地測試檢查清單

部署前請確認：

- [ ] `python -c "from app.main import app"` 無錯誤
- [ ] 所有 router 的 `@router.get/post` 有正確的 path
- [ ] Jinja2 templates 中使用的 filter 都已註冊
- [ ] 檔案都是 UTF-8 編碼
- [ ] `requirements.txt` 不包含 alembic
- [ ] `railway.toml` startCommand 不包含 alembic

---

## 📊 功能狀態

### ✅ 已完成 (Phase 0-9)
- LINE Login 認證
- 店家/菜單/團單/訂單 CRUD
- 甜冰選項 + 加料系統
- QR Code 分享
- 部門系統
- 公告系統
- 投票系統
- 個人消費統計
- JSON 匯入

### 🔜 待開發
- 外送費分攤
- 訂單匯出 Excel
- 多尺寸定價（之前因 bug 回滾）

---

## 🌐 環境變數

```env
# 資料庫（Railway 自動提供）
DATABASE_URL=postgresql://...

# LINE Login
LINE_CHANNEL_ID=xxx
LINE_CHANNEL_SECRET=xxx
LINE_CALLBACK_URL=https://xxx.up.railway.app/auth/callback

# JWT
JWT_SECRET_KEY=xxx

# Cloudinary
CLOUDINARY_CLOUD_NAME=xxx
CLOUDINARY_API_KEY=xxx
CLOUDINARY_API_SECRET=xxx
```

---

## 📝 開發原則

1. **穩定優先**：遇到複雜問題，優先回滾到穩定版本
2. **手動遷移**：不使用 Alembic，用 Raw SQL 處理 schema 變更
3. **大寫 Enum**：PostgreSQL Enum 永遠用大寫值
4. **UTF-8 編碼**：所有檔案確保 UTF-8 編碼
5. **Filter 註冊**：每個 router 自己註冊需要的 Jinja2 filter

---

*此文件為 SELA 專案的核心開發指導，請在開發時參考*
