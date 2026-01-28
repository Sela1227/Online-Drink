#!/usr/bin/env python3
"""修復 joinedload import"""
import re

filepath = "app/routers/admin.py"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# 把 from sqlalchemy import or_ 改成加上 joinedload
if "from sqlalchemy.orm import joinedload" not in content:
    content = content.replace(
        "from sqlalchemy import or_",
        "from sqlalchemy import or_\nfrom sqlalchemy.orm import joinedload"
    )
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    
    print("✅ 已新增 joinedload import")
else:
    print("ℹ️  joinedload import 已存在")

print("\n測試: python -c \"from app.main import app; print('OK')\"")
