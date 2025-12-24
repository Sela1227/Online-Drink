# SELA Bug 修復 - 2024/12/24 (第二批)

## 🐛 修復的問題

| # | 問題 | 原因 | 狀態 |
|---|------|------|------|
| 1 | 時間到的團還在飲料區 | 查詢條件沒有檢查 deadline | ✅ 已修復 |
| 2 | 使用者管理頁面黑屏 | taipei filter 未註冊 | ✅ 已修復 |
| 3 | 店家改分類黑屏 | CategoryType 大小寫轉換失敗 | ✅ 已修復 |

---

## 📁 修改的檔案

```
app/
├── routers/
│   ├── admin.py          # taipei filter + 分類大小寫修復
│   └── home.py           # 截止團單查詢邏輯修復
└── templates/partials/
    ├── home_groups.html  # 首頁團單列表
    └── group_card.html   # 團單卡片模板
```

---

## 🔍 修復詳情

### 1. 截止團單邏輯修復 (home.py)

**修復前（錯誤）：**
```python
# 開放區只檢查 is_closed，沒檢查 deadline
drink_groups = db.query(Group).filter(
    Group.category == CategoryType.DRINK,
    Group.is_closed == False,  # ❌ 只檢查這個
)
```

**修復後（正確）：**
```python
# 必須同時檢查 is_closed 和 deadline
drink_groups = db.query(Group).filter(
    Group.category == CategoryType.DRINK,
    Group.is_closed == False,
    Group.deadline > now,  # ✅ 加入時間檢查
)
```

### 2. taipei filter 註冊 (admin.py)

**加入程式碼：**
```python
def to_taipei_time(dt):
    if dt is None:
        return None
    taipei_tz = timezone(timedelta(hours=8))
    if dt.tzinfo is None:
        utc_dt = dt.replace(tzinfo=timezone.utc)
    else:
        utc_dt = dt
    return utc_dt.astimezone(taipei_tz)

templates.env.filters['taipei'] = to_taipei_time
```

### 3. 分類大小寫轉換 (admin.py)

**修復程式碼：**
```python
try:
    category_lower = category.lower()
    store.category = CategoryType(category_lower)
except ValueError:
    try:
        store.category = CategoryType[category.upper()]
    except KeyError:
        pass  # 保持原值
```

---

## 🚀 部署步驟

```powershell
cd C:\Users\cbrto\Documents\Python\線上訂餐

# 解壓 sela-bugfix2.zip 覆蓋

git add .
git commit -m "Fix: deadline check, taipei filter, category case"
git push
```

---

## ✅ 團單顯示規則

| 區域 | 條件 | 可見對象 |
|------|------|----------|
| 飲料/餐點/團購 | `is_closed == False` AND `deadline > now` | 所有人 |
| 已截止 | `is_closed == True` OR `deadline <= now`，且最近 7 天內 | 所有人 |
| 歷史紀錄 | `is_closed == True` OR `deadline <= now`，且超過 7 天 | 管理員 |
