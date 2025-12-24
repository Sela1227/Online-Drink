# SELA 修復 - 只包含缺失的 Model

## ⚠️ 重要：先刪除重複檔案！

你的專案有重複定義問題。請先執行：

```powershell
cd C:\Users\cbrto\Documents\Python\線上訂餐

# 刪除我之前給你的重複檔案
del app\models\__init__.py
del app\models\system.py
```

## 📦 這個包只有

```
app/models/
├── store.py   ← CategoryType, Store, StoreOption 等
└── menu.py    ← Menu, MenuItem, MenuCategory 等
```

## 🚀 部署

```powershell
# 1. 先刪除重複檔案（上面的命令）

# 2. 解壓 sela-models-only.zip

# 3. 確認
dir app\models\

# 4. 部署
git add .
git commit -m "Add store.py and menu.py models"
git push --force
```
