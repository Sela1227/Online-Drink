# SELA 部署檢查清單

> 每次 `git push` 前請完成以下檢查

---

## ✅ 快速檢查 (必做)

### 1. 本地啟動測試
```bash
# 確認能正常啟動
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 2. Import 測試
```bash
python -c "from app.main import app; print('OK')"
```

### 3. 編碼檢查
```bash
# Linux/Mac
file --mime-encoding app/**/*.py

# Windows PowerShell
Get-ChildItem -Recurse -Filter *.py | ForEach-Object { 
    $encoding = [System.Text.Encoding]::UTF8
    try { [System.IO.File]::ReadAllText($_.FullName, $encoding) | Out-Null }
    catch { Write-Host "❌ $($_.FullName)" }
}
```

---

## 📋 完整檢查清單

### 設定檔
- [ ] `railway.toml` 不包含 `alembic`
- [ ] `requirements.txt` 不包含 `alembic`
- [ ] `requirements.txt` 有所有需要的套件

### 程式碼
- [ ] 所有 `.py` 檔案是 UTF-8 編碼
- [ ] 所有 Router 的 path 不是空字串（或有 prefix）
- [ ] Jinja2 templates 使用的 filter 都已註冊
- [ ] SQLAlchemy Model 有 `extend_existing=True`（如需要）

### 資料庫
- [ ] 新增的 Enum 值使用大寫（DRINK, MEAL, GROUP_BUY）
- [ ] Schema 變更使用 Raw SQL 而非 Alembic
- [ ] 欄位新增使用 `ADD COLUMN IF NOT EXISTS` 模式

### 環境變數
- [ ] DATABASE_URL
- [ ] LINE_CHANNEL_ID
- [ ] LINE_CHANNEL_SECRET
- [ ] LINE_CALLBACK_URL
- [ ] JWT_SECRET_KEY
- [ ] CLOUDINARY_* (如使用圖片上傳)

---

## 🚀 部署步驟

```bash
# 1. 執行本地測試
uvicorn app.main:app --port 8000 &
curl http://localhost:8000/
kill %1

# 2. Git 提交
git add .
git commit -m "描述你的變更"

# 3. 推送部署
git push

# 4. 檢查 Railway Logs
# 前往 Railway Dashboard 查看 Build 和 Deploy Logs
```

---

## 🆘 部署失敗緊急處理

### Build 失敗
```bash
# 通常是 UTF-8 編碼問題
# 檢查錯誤訊息中提到的檔案

# 修復後重新部署
git add .
git commit -m "Fix: encoding issue"
git push
```

### Container 啟動失敗
```bash
# 1. 本地重現問題
python -c "from app.main import app"

# 2. 查看完整錯誤
# Railway Logs → Deployment → Runtime Logs
```

### 回滾到上一版
```bash
# Railway Dashboard → Deployments → 選擇上一個成功的部署 → Redeploy
```

### Nixpacks 持續失敗
```bash
# 改用 Dockerfile
# 修改 railway.toml:
[build]
builder = "dockerfile"

# 確保有 Dockerfile 和 start.sh
git add Dockerfile start.sh railway.toml
git commit -m "Switch to Dockerfile builder"
git push
```

---

## 📝 常見問題快速解答

| 問題 | 解決方案 |
|------|----------|
| `stream did not contain valid UTF-8` | 重新存檔為 UTF-8 |
| `Table 'xxx' is already defined` | 加入 `extend_existing=True` |
| `Prefix and path cannot be both empty` | Router 加 prefix 或 path 加 `/` |
| `invalid input value for enum` | 使用大寫 Enum 值 |
| `No filter named 'taipei'` | 在 router 註冊 filter |
| `Healthcheck failed` | 先查看其他錯誤訊息 |

---

## 📊 Railway 狀態說明

| 狀態 | 說明 | 處理 |
|------|------|------|
| 🟢 Building | 正在建置 | 等待 |
| 🟢 Deploying | 正在部署 | 等待 |
| 🟢 Active | 部署成功 | ✅ |
| 🔴 Build Failed | 建置失敗 | 檢查編碼/語法 |
| 🔴 Deploy Failed | 部署失敗 | 檢查 Runtime Logs |
| 🟡 Crashed | 執行時崩潰 | 檢查 Runtime Logs |

---

*最後更新: 2024/12/24*
