# SELA Bug 修復說明

## 問題 1: 分類 Bug (admin.py)

**錯誤訊息**: 
```
psycopg2.errors.InvalidTextRepresentation: invalid input value for enum categorytype: "GROUP_BUY"
```

**原因**: 表單送的是大寫 `GROUP_BUY`，但 PostgreSQL enum 只接受小寫 `group_buy`

**修復**: 在 `admin.py` 的 `update_store` 函數中加入轉換邏輯

---

## 問題 2: 時區 Bug (admin.py)

**錯誤訊息**:
```
jinja2.exceptions.TemplateAssertionError: No filter named 'taipei'
```

**原因**: `taipei` filter 沒有在 admin router 的 templates 中註冊

**修復**: 在 `admin.py` 開頭加入 `taipei` filter

---

## 問題 3: 截止團單顯示規則

**需求**:
- 截止的團單不應該出現在飲料區/餐點區
- 截止區只放最近一週的團單
- 超過一週的放歷史區
- 歷史區只有管理員能看

**修復**: 更新 `home.py` 的查詢邏輯

---

## 部署步驟

1. 覆蓋 `app/routers/admin.py`
2. 覆蓋 `app/routers/home.py`
3. 覆蓋 `app/templates/partials/home_groups.html`
4. Git push 部署
