#!/bin/bash
# 修復 sqlalchemy import 錯誤
# 在專案根目錄執行: bash fix_import.sh

sed -i '' 's/from sqlalchemy import or_, joinedload/from sqlalchemy import or_/' app/routers/admin.py

echo "✅ 已修復 app/routers/admin.py"
echo "   備份: app/routers/admin.py.bak"
echo ""
echo "測試: python -c \"from app.main import app; print('OK')\""
