# SELA 缺失檔案修復包

## ❌ 缺失的檔案

```
app/models/
├── __init__.py    ← 新增
├── store.py       ← 新增
├── menu.py        ← 新增
└── system.py      ← 新增
```

## 🚀 部署步驟

```powershell
cd C:\Users\cbrto\Documents\Python\線上訂餐

# 1. 解壓 sela-missing-models.zip（選「全部覆蓋」）

# 2. 確認檔案存在
dir app\models\

# 應該看到：
# __init__.py
# feedback.py
# group.py
# menu.py      ← 新增
# order.py
# store.py     ← 新增
# system.py    ← 新增
# user.py

# 3. 部署
git add .
git commit -m "Add missing models: store, menu, system"
git push --force
```
