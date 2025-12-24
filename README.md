# SELA 完整修復包

## 📦 包含檔案

```
app/
├── routers/
│   ├── home.py      ← 完整覆蓋
│   └── admin.py     ← 完整覆蓋
└── templates/partials/
    ├── home_groups.html  ← 完整覆蓋
    └── group_card.html   ← 完整覆蓋
```

## 🐛 修復的問題

1. **時間到的團還在飲料區** - 加入 `deadline > now` 條件
2. **使用者管理頁面黑屏** - 註冊 `taipei` filter
3. **店家改分類黑屏** - 大小寫轉換修復
4. **FastAPI 啟動失敗** - 移除錯誤的 return type annotation

## 🚀 部署步驟

### 步驟 1：解壓到專案目錄

```powershell
cd C:\Users\cbrto\Documents\Python\線上訂餐

# 解壓 sela-complete-fix.zip
# 選擇「全部覆蓋」
```

### 步驟 2：確認檔案已覆蓋

```powershell
# 檢查 home.py 的內容
type app\routers\home.py | findstr "async def home"

# 應該顯示：
# async def home(
# 不應該有任何 -> 符號
```

### 步驟 3：部署

```powershell
git add .
git commit -m "Fix: complete bugfix for deadline, taipei filter, category"
git push
```

## ✅ 預期結果

部署成功後：
- 首頁正常顯示
- 時間到的團自動移到「已截止」區
- `/admin/users` 正常顯示
- 修改店家分類正常運作
