# SELA 常見錯誤與解決方案

> 從 2024/12/24 部署 logs 整理

---

## 🔴 錯誤類型速查表

| 錯誤關鍵字 | 類型 | 嚴重度 | 參考章節 |
|-----------|------|--------|----------|
| `stream did not contain valid UTF-8` | 編碼錯誤 | 🔴 建置失敗 | #1 |
| `Table 'xxx' is already defined` | SQLAlchemy 重複定義 | 🔴 啟動失敗 | #2 |
| `Prefix and path cannot be both empty` | FastAPI Router | 🔴 啟動失敗 | #3 |
| `invalid input value for enum` | PostgreSQL Enum | 🟡 執行時錯誤 | #4 |
| `No filter named 'taipei'` | Jinja2 Filter | 🟡 頁面錯誤 | #5 |
| `Healthcheck failed` | 部署失敗 | 🔴 部署失敗 | #6 |

---

## #1 UTF-8 編碼錯誤

### 錯誤訊息
```
Nixpacks build failed
Error: Error reading app/services/import_service.py
Caused by: stream did not contain valid UTF-8
```

### 原因
- Windows 編輯器存檔時使用了非 UTF-8 編碼
- 檔案包含 BOM 或其他特殊字元
- 複製貼上時帶入了不可見字元

### 解決方案

**方法 1：PowerShell 重新編碼**
```powershell
Get-Content app/services/import_service.py | Set-Content -Encoding utf8 app/services/import_service_fixed.py
Remove-Item app/services/import_service.py
Rename-Item app/services/import_service_fixed.py import_service.py
```

**方法 2：Python 清理**
```python
import codecs

with open('app/services/import_service.py', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

with open('app/services/import_service.py', 'w', encoding='utf-8', newline='\n') as f:
    f.write(content)
```

**方法 3：VS Code 設定**
1. 開啟檔案
2. 右下角點擊編碼（如 UTF-8 with BOM）
3. 選擇「Save with Encoding」→ UTF-8

### 預防措施
- VS Code 設定 `"files.encoding": "utf8"`
- 不使用 Windows 記事本編輯
- 定期用 `file --mime-encoding *.py` 檢查編碼

---

## #2 SQLAlchemy Table 重複定義

### 錯誤訊息
```python
sqlalchemy.exc.InvalidRequestError: Table 'system_settings' is already defined 
for this MetaData instance. Specify 'extend_existing=True' to redefine options 
and columns on an existing Table object.
```

### 原因
- 同一個 Table 在多個地方被定義
- Model 被 import 多次
- `__init__.py` 中的 import 順序問題

### 解決方案

**方法 1：加入 extend_existing**
```python
class SystemSetting(Base):
    __tablename__ = "system_settings"
    __table_args__ = {'extend_existing': True}  # ← 加入這行
    
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True)
    value = Column(Text)
```

**方法 2：檢查 __init__.py**
```python
# app/models/__init__.py
# 確保每個 model 只 import 一次
from app.models.user import User
from app.models.store import Store
# 不要重複 import
```

**方法 3：使用單一 metadata**
```python
# app/database.py
from sqlalchemy.orm import declarative_base
Base = declarative_base()

# 所有 model 都使用同一個 Base
```

---

## #3 FastAPI Router 空 Path 錯誤

### 錯誤訊息
```
fastapi.exceptions.FastAPIError: Prefix and path cannot be both empty 
(path operation: home)
```

### 原因
- Router 沒有設定 prefix
- 路由裝飾器的 path 是空字串

### 解決方案

**方法 1：設定 Router prefix**
```python
# app/routers/home.py
router = APIRouter(prefix="/home")  # ← 設定 prefix

@router.get("")  # 這樣 path 可以是空的
def home_page():
    pass
```

**方法 2：設定路由 path**
```python
router = APIRouter()

@router.get("/")  # ← 使用 "/" 而不是 ""
def home_page():
    pass
```

**方法 3：include_router 時設定 prefix**
```python
# app/main.py
app.include_router(home.router, prefix="/home", tags=["home"])
```

### 檢查清單
```python
# 確保以下至少有一個不是空的：
# 1. APIRouter(prefix="...")
# 2. @router.get("/xxx")
# 3. app.include_router(..., prefix="...")
```

---

## #4 PostgreSQL Enum 大小寫錯誤

### 錯誤訊息
```
psycopg2.errors.InvalidTextRepresentation: invalid input value for enum 
categorytype: "GROUP_BUY"
```

### 原因
- Python/表單送的是大寫 `GROUP_BUY`
- PostgreSQL Enum 定義為小寫 `group_buy`
- 或反過來

### 解決方案

**方法 1：確認 PostgreSQL 中的 Enum 值**
```sql
-- 查看 enum 定義
SELECT enumlabel FROM pg_enum 
WHERE enumtypid = 'categorytype'::regtype;
```

**方法 2：表單提交時轉換大小寫**
```python
@router.post("/stores/{store_id}")
async def update_store(store_id: int, category: str = Form(...)):
    # 轉換為 PostgreSQL 需要的格式
    category_upper = category.upper()  # 或 .lower() 視情況
    
    # 使用 raw SQL 更新
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE stores SET category = :cat WHERE id = :id"
        ), {"cat": category_upper, "id": store_id})
```

**方法 3：新增 Enum 值（用大寫）**
```python
def add_enum_value():
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TYPE categorytype ADD VALUE IF NOT EXISTS 'GROUP_BUY'"
        ))
```

### SELA 專案規則
```
PostgreSQL Enum 值統一使用大寫：
- DRINK
- MEAL  
- GROUP_BUY
```

---

## #5 Jinja2 Filter 未註冊

### 錯誤訊息
```
jinja2.exceptions.TemplateAssertionError: No filter named 'taipei'
```

### 原因
- `taipei` filter 沒有在該 router 的 templates 中註冊
- 不同 router 有各自的 `Jinja2Templates` 實例

### 解決方案

**在每個 router 註冊 filter**
```python
# app/routers/admin.py
from datetime import timezone, timedelta
from fastapi.templating import Jinja2Templates

TAIPEI_TZ = timezone(timedelta(hours=8))

def taipei(dt):
    """將 UTC 時間轉換為台北時間"""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M")

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["taipei"] = taipei  # ← 註冊 filter
```

**或使用共用 templates 模組**
```python
# app/templates_config.py
from datetime import timezone, timedelta
from fastapi.templating import Jinja2Templates

TAIPEI_TZ = timezone(timedelta(hours=8))

def taipei(dt):
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M")

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["taipei"] = taipei

# 各 router 中：
from app.templates_config import templates
```

---

## #6 Healthcheck 失敗

### 錯誤訊息
```
1/1 replicas never became healthy!
Healthcheck failed!
```

### 原因
- 應用程式無法啟動（查看上面的錯誤）
- 啟動時間超過 healthcheck timeout
- healthcheck path 回傳非 200 狀態

### 排查步驟

**1. 先查看 Runtime Logs**
```
Healthcheck 失敗通常是其他錯誤的結果，
先在 logs 中找出實際的錯誤訊息。
```

**2. 檢查 healthcheck 設定**
```toml
# railway.toml
[deploy]
healthcheckPath = "/"
healthcheckTimeout = 300  # 增加 timeout
```

**3. 確認首頁路由存在**
```python
@router.get("/")
def home():
    return {"status": "ok"}  # 簡單回應
```

**4. 本地測試啟動**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
# 瀏覽器訪問 http://localhost:8000/
```

---

## 🔧 快速診斷流程

```
部署失敗
    │
    ├─ Build Failed?
    │      │
    │      └─→ 檢查 UTF-8 編碼 (#1)
    │
    ├─ Container 啟動失敗?
    │      │
    │      ├─→ Table already defined (#2)
    │      └─→ Prefix and path empty (#3)
    │
    └─ Healthcheck 失敗?
           │
           └─→ 先找出實際錯誤 (#6)

執行時錯誤
    │
    ├─ enum 錯誤 → #4
    └─ filter 錯誤 → #5
```

---

## 📋 部署前檢查腳本

```python
# check_before_deploy.py
import subprocess
import sys

def check_imports():
    """檢查 app 能否正常 import"""
    try:
        from app.main import app
        print("✅ app.main import 成功")
        return True
    except Exception as e:
        print(f"❌ Import 錯誤: {e}")
        return False

def check_encoding():
    """檢查 Python 檔案編碼"""
    import glob
    errors = []
    for f in glob.glob("app/**/*.py", recursive=True):
        try:
            with open(f, 'r', encoding='utf-8') as file:
                file.read()
        except UnicodeDecodeError:
            errors.append(f)
    
    if errors:
        print(f"❌ 編碼錯誤檔案: {errors}")
        return False
    print("✅ 所有檔案編碼正確")
    return True

if __name__ == "__main__":
    results = [check_encoding(), check_imports()]
    sys.exit(0 if all(results) else 1)
```

---

*此文件整理自 2024/12/24 部署 logs，請在遇到問題時參考*
