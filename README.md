# SELA Bug 修復 - 2024/12/24 v2

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

## 🚀 部署步驟

### ⚠️ 重要：請完整覆蓋檔案

```powershell
cd C:\Users\cbrto\Documents\Python\線上訂餐

# 1. 備份現有檔案
copy app\routers\home.py app\routers\home.py.bak
copy app\routers\admin.py app\routers\admin.py.bak

# 2. 解壓 sela-bugfix2.zip
# 3. 確認完整覆蓋這些檔案：
#    - app/routers/home.py
#    - app/routers/admin.py
#    - app/templates/partials/home_groups.html
#    - app/templates/partials/group_card.html

# 4. 部署
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
