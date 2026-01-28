#!/usr/bin/env python3
"""
SELA 匯入功能優化 - 自動修改腳本
================================

執行方式：
    python3 apply_import_fix.py

此腳本會自動：
1. 備份原始檔案
2. 修改 app/routers/admin.py
3. 替換 app/templates/admin/import_preview.html
"""

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

# 確認在專案根目錄
if not Path("app/routers/admin.py").exists():
    print("❌ 錯誤：請在專案根目錄執行此腳本")
    print("   當前目錄：", os.getcwd())
    exit(1)

BACKUP_SUFFIX = datetime.now().strftime("_%Y%m%d_%H%M%S.bak")

def backup_file(filepath):
    """備份檔案"""
    backup_path = filepath + BACKUP_SUFFIX
    shutil.copy2(filepath, backup_path)
    print(f"  📦 已備份: {backup_path}")
    return backup_path

def patch_admin_py():
    """修改 admin.py"""
    filepath = "app/routers/admin.py"
    print(f"\n🔧 修改 {filepath}")
    
    backup_file(filepath)
    
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    # === 1. 新增 import ===
    # 新增 sqlalchemy or_
    if "from sqlalchemy import or_" not in content and "from sqlalchemy.orm import Session" in content:
        content = content.replace(
            "from sqlalchemy.orm import Session",
            "from sqlalchemy.orm import Session\nfrom sqlalchemy import or_"
        )
        print("  ✅ 新增 import: sqlalchemy or_")
    
    # 新增 MenuContent import
    if "from app.schemas.menu import MenuContent" not in content:
        if "from app.schemas.menu import FullImport, MenuImport" in content:
            content = content.replace(
                "from app.schemas.menu import FullImport, MenuImport",
                "from app.schemas.menu import FullImport, MenuImport, MenuContent"
            )
            print("  ✅ 新增 import: MenuContent")
    
    # === 2. 修改 import_preview 函數 ===
    # 找到函數並替換
    old_preview_pattern = r'''(@router\.post\("/import/preview"\)\nasync def import_preview\(\n    request: Request,\n    json_file: UploadFile = File\(\.\.\.\),\n    store_id: int = Form\(None\),\n    db: Session = Depends\(get_db\),\n\):.*?return templates\.TemplateResponse\("admin/import_preview\.html", \{[^}]+\}\))'''
    
    new_preview_func = '''@router.post("/import/preview")
async def import_preview(
    request: Request,
    json_file: UploadFile = File(...),
    store_id: int = Form(None),
    db: Session = Depends(get_db),
):
    """匯入預覽 - 含重複店家檢查"""
    user = await get_admin_user(request, db)
    
    # 取得 JSON 內容
    if not json_file or not json_file.filename:
        raise HTTPException(status_code=400, detail="請上傳 JSON 檔案")
    
    content = await json_file.read()
    json_str = content.decode("utf-8")
    
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 格式錯誤: {e}")
    
    # 判斷匯入類型
    if store_id:
        menu_data = data.get("menu", data)
        data = {
            "store_id": store_id,
            "mode": "replace",
            "menu": menu_data
        }
        json_str = json.dumps(data, ensure_ascii=False)
        is_full_import = False
    elif "store" in data:
        is_full_import = True
    else:
        raise HTTPException(status_code=400, detail="JSON 缺少 store（新增店家）或請選擇店家（更新菜單）")
    
    try:
        if is_full_import:
            validated = FullImport(**data)
        else:
            validated = MenuImport(**data)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"資料驗證錯誤: {e}")
    
    # ===== 新增：重複店家檢查 =====
    existing_stores = []
    if is_full_import:
        store_name = validated.store.name.strip()
        
        # 精確比對
        exact_match = db.query(Store).filter(
            Store.name == store_name,
            Store.is_active == True
        ).first()
        
        if exact_match:
            existing_stores.append({
                "store": exact_match,
                "match_type": "exact"
            })
        else:
            # 模糊比對
            similar = db.query(Store).filter(
                Store.is_active == True,
                or_(Store.name.contains(store_name), Store.name == store_name)
            ).all()
            for s in similar:
                if store_name in s.name or s.name in store_name:
                    existing_stores.append({"store": s, "match_type": "similar"})
    
    # 如果是菜單匯入，取得現有菜單做比較
    existing_menu = None
    if not is_full_import:
        store = db.query(Store).filter(Store.id == validated.store_id).first()
        if not store:
            raise HTTPException(status_code=404, detail="店家不存在")
        existing_menu = db.query(Menu).filter(
            Menu.store_id == validated.store_id,
            Menu.is_active == True
        ).first()
    
    return templates.TemplateResponse("admin/import_preview.html", {
        "request": request,
        "user": user,
        "data": validated,
        "is_full_import": is_full_import,
        "existing_menu": existing_menu,
        "json_str": json_str,
        "existing_stores": existing_stores,
    })'''
    
    # 使用更簡單的替換方式
    # 找到 import_preview 函數的開始和結束
    start_marker = '@router.post("/import/preview")'
    end_marker = '@router.post("/import")'
    
    start_idx = content.find(start_marker)
    end_idx = content.find(end_marker)
    
    if start_idx != -1 and end_idx != -1:
        content = content[:start_idx] + new_preview_func + "\n\n\n" + content[end_idx:]
        print("  ✅ 已替換 import_preview 函數")
    else:
        print("  ⚠️ 找不到 import_preview 函數，跳過")
    
    # === 3. 修改 do_import 函數 ===
    new_do_import_func = '''@router.post("/import")
async def do_import(
    request: Request,
    json_str: str = Form(...),
    merge_to_store_id: int = Form(None),
    db: Session = Depends(get_db),
):
    """執行匯入 - 支援合併到現有店家"""
    user = await get_admin_user(request, db)
    
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 格式錯誤: {e}")
    
    try:
        if "store_id" in data:
            # 菜單更新模式
            menu_data = data.get("menu", {})
            if not menu_data:
                raise HTTPException(status_code=400, detail="JSON 缺少 menu 內容")
            validated = MenuImport(
                store_id=data["store_id"],
                mode=data.get("mode", "replace"),
                menu=menu_data
            )
            menu = import_menu(db, validated)
            return RedirectResponse(url=f"/admin/stores/{validated.store_id}", status_code=302)
        
        elif merge_to_store_id:
            # 合併到現有店家
            if "menu" not in data:
                raise HTTPException(status_code=400, detail="JSON 缺少 menu 內容")
            
            target_store = db.query(Store).filter(Store.id == merge_to_store_id).first()
            if not target_store:
                raise HTTPException(status_code=404, detail="目標店家不存在")
            
            menu_content = MenuContent(**data["menu"])
            validated_menu = MenuImport(
                store_id=merge_to_store_id,
                mode="replace",
                menu=menu_content
            )
            menu = import_menu(db, validated_menu)
            
            # 更新甜度/冰塊/加料選項
            if "store" in data:
                store_data = data["store"]
                if store_data.get("sugar_options"):
                    db.query(StoreOption).filter(
                        StoreOption.store_id == merge_to_store_id,
                        StoreOption.option_type == OptionType.SUGAR
                    ).delete()
                    for i, v in enumerate(store_data["sugar_options"]):
                        db.add(StoreOption(store_id=merge_to_store_id, option_type=OptionType.SUGAR, option_value=v, sort_order=i))
                
                if store_data.get("ice_options"):
                    db.query(StoreOption).filter(
                        StoreOption.store_id == merge_to_store_id,
                        StoreOption.option_type == OptionType.ICE
                    ).delete()
                    for i, v in enumerate(store_data["ice_options"]):
                        db.add(StoreOption(store_id=merge_to_store_id, option_type=OptionType.ICE, option_value=v, sort_order=i))
                
                if store_data.get("toppings"):
                    db.query(StoreTopping).filter(StoreTopping.store_id == merge_to_store_id).delete()
                    for i, t in enumerate(store_data["toppings"]):
                        db.add(StoreTopping(store_id=merge_to_store_id, name=t["name"], price=t.get("price", 0), sort_order=i, is_active=True))
                
                db.commit()
            
            return RedirectResponse(url=f"/admin/stores/{merge_to_store_id}", status_code=302)
        
        elif "store" in data:
            # 完整匯入模式（新增店家 + 菜單）
            validated = FullImport(**data)
            store = import_store_and_menu(db, validated)
            return RedirectResponse(url=f"/admin/stores/{store.id}", status_code=302)
        
        else:
            raise HTTPException(status_code=400, detail="JSON 格式錯誤")
    
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"資料驗證錯誤: {e}")'''
    
    # 找到 do_import 函數
    start_marker2 = '@router.post("/import")\nasync def do_import('
    # 找下一個函數作為結束點
    end_markers = ['@router.get("/groups")', '@router.post("/stores/', '@router.get("/stores/']
    
    start_idx2 = content.find('@router.post("/import")\nasync def do_import(')
    if start_idx2 == -1:
        start_idx2 = content.find('@router.post("/import")')
    
    if start_idx2 != -1:
        # 找最近的下一個路由
        end_idx2 = len(content)
        for marker in end_markers:
            idx = content.find(marker, start_idx2 + 50)
            if idx != -1 and idx < end_idx2:
                end_idx2 = idx
        
        content = content[:start_idx2] + new_do_import_func + "\n\n\n" + content[end_idx2:]
        print("  ✅ 已替換 do_import 函數")
    else:
        print("  ⚠️ 找不到 do_import 函數，跳過")
    
    # 寫回檔案
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    
    print(f"  💾 已儲存: {filepath}")


def replace_import_preview_html():
    """替換 import_preview.html"""
    filepath = "app/templates/admin/import_preview.html"
    print(f"\n🔧 替換 {filepath}")
    
    backup_file(filepath)
    
    new_content = '''{% extends "base.html" %}

{% block title %}匯入預覽 - SELA 快點來點餐{% endblock %}

{% block content %}
<div class="space-y-4">
    <div class="flex items-center justify-between">
        <h1 class="text-xl font-bold text-gray-800">匯入預覽</h1>
        <a href="/admin/import" class="text-sm text-gray-500 hover:text-gray-700">返回匯入頁面 →</a>
    </div>
    
    <!-- 匯入類型 -->
    <div class="bg-white rounded-lg shadow-sm p-4">
        {% if is_full_import %}
        <div class="text-sm text-orange-600 font-medium mb-2">📦 完整匯入（新店家 + 菜單）</div>
        
        <!-- ===== 重複店家警告 ===== -->
        {% if existing_stores and existing_stores|length > 0 %}
        <div class="bg-yellow-50 border border-yellow-300 rounded-lg p-4 mb-4">
            <div class="flex items-start gap-2">
                <span class="text-yellow-600 text-xl">⚠️</span>
                <div class="flex-1">
                    <div class="font-medium text-yellow-800 mb-2">發現可能重複的店家</div>
                    <div class="text-sm text-yellow-700 space-y-2">
                        {% for item in existing_stores %}
                        <div class="flex items-center justify-between bg-white rounded p-2">
                            <div>
                                <span class="font-medium">{{ item.store.name }}</span>
                                {% if item.match_type == 'exact' %}
                                <span class="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded ml-2">完全相同</span>
                                {% else %}
                                <span class="text-xs bg-yellow-100 text-yellow-600 px-2 py-0.5 rounded ml-2">名稱相似</span>
                                {% endif %}
                                <span class="text-xs text-gray-500 ml-2">ID: {{ item.store.id }}</span>
                            </div>
                            <a href="/admin/stores/{{ item.store.id }}" target="_blank" 
                               class="text-xs text-blue-600 hover:underline">
                                查看 →
                            </a>
                        </div>
                        {% endfor %}
                    </div>
                    <p class="text-sm text-yellow-700 mt-3">
                        您可以選擇：
                    </p>
                    <ul class="text-sm text-yellow-700 list-disc list-inside ml-2">
                        <li>繼續建立新店家（會產生重複）</li>
                        <li>合併菜單到現有店家（推薦）</li>
                    </ul>
                </div>
            </div>
        </div>
        {% endif %}
        
        <!-- 店家資訊 -->
        <div class="border rounded-lg p-3 mb-4">
            <h3 class="font-medium text-gray-800">店家資訊</h3>
            <div class="mt-2 text-sm text-gray-600 space-y-1">
                <div>名稱：<span class="font-medium">{{ data.store.name }}</span></div>
                <div>類型：<span class="font-medium">{{ '飲料' if data.store.category == 'drink' else '餐點' }}</span></div>
                {% if data.store.sugar_options %}
                <div>甜度選項：{{ data.store.sugar_options | join('、') }}</div>
                {% endif %}
                {% if data.store.ice_options %}
                <div>冰塊選項：{{ data.store.ice_options | join('、') }}</div>
                {% endif %}
                {% if data.store.toppings %}
                <div>加料選項：
                    {% for t in data.store.toppings %}
                    {{ t.name }}{% if t.price > 0 %}(+${{ t.price }}){% endif %}{% if not loop.last %}、{% endif %}
                    {% endfor %}
                </div>
                {% endif %}
            </div>
        </div>
        {% else %}
        <div class="text-sm text-green-600 font-medium mb-2">📋 菜單匯入</div>
        <div class="text-sm text-gray-600 mb-4">
            店家 ID：{{ data.store_id }}
            ・模式：{{ '新增版本' if data.mode == 'new' else '覆蓋現有' }}
        </div>
        {% endif %}
        
        <!-- 菜單內容 -->
        <div class="border rounded-lg p-3">
            <h3 class="font-medium text-gray-800 mb-2">菜單內容</h3>
            
            {% if data.menu.categories %}
            {% for category in data.menu.categories %}
            <div class="mb-3">
                <div class="text-sm font-medium text-gray-700">{{ category.name }}</div>
                <div class="ml-4 text-sm text-gray-600">
                    {% for item in category.items %}
                    <div class="flex items-center gap-2 py-1">
                        <span>{{ item.name }}</span>
                        <span class="text-orange-600">${{ item.price }}{% if item.price_l %}/${{ item.price_l }}{% endif %}</span>
                        {% if item.options %}
                        <span class="text-xs text-gray-400">
                            ({% for opt in item.options %}{{ opt.name }}{% if opt.price_diff > 0 %}+${{ opt.price_diff }}{% endif %}{% if not loop.last %}、{% endif %}{% endfor %})
                        </span>
                        {% endif %}
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endfor %}
            {% endif %}
            
            {% if data.menu.items %}
            <div class="text-sm text-gray-600">
                {% for item in data.menu.items %}
                <div class="flex items-center gap-2 py-1">
                    <span>{{ item.name }}</span>
                    <span class="text-orange-600">${{ item.price }}{% if item.price_l %}/${{ item.price_l }}{% endif %}</span>
                    {% if item.options %}
                    <span class="text-xs text-gray-400">
                        ({% for opt in item.options %}{{ opt.name }}{% if opt.price_diff > 0 %}+${{ opt.price_diff }}{% endif %}{% if not loop.last %}、{% endif %}{% endfor %})
                    </span>
                    {% endif %}
                </div>
                {% endfor %}
            </div>
            {% endif %}
        </div>
    </div>
    
    <!-- 確認匯入 -->
    <form action="/admin/import" method="post" x-data="{ mergeMode: false, selectedStoreId: null }">
        <input type="hidden" name="json_str" value="{{ json_str | e }}">
        
        {% if is_full_import and existing_stores and existing_stores|length > 0 %}
        <!-- 合併選項 -->
        <div class="bg-white rounded-lg shadow-sm p-4 mb-4">
            <div class="font-medium text-gray-800 mb-3">選擇匯入方式</div>
            
            <div class="space-y-3">
                <!-- 選項 1：建立新店家 -->
                <label class="flex items-start gap-3 p-3 border rounded-lg cursor-pointer hover:bg-gray-50 transition"
                       :class="{ 'border-orange-500 bg-orange-50': !mergeMode }">
                    <input type="radio" name="import_mode" value="new" 
                           x-model="mergeMode" :value="false"
                           @change="mergeMode = false; selectedStoreId = null"
                           class="mt-1" checked>
                    <div>
                        <div class="font-medium text-gray-800">建立新店家</div>
                        <div class="text-sm text-gray-500">將建立「{{ data.store.name }}」作為新店家（可能重複）</div>
                    </div>
                </label>
                
                <!-- 選項 2：合併到現有店家 -->
                <label class="flex items-start gap-3 p-3 border rounded-lg cursor-pointer hover:bg-gray-50 transition"
                       :class="{ 'border-green-500 bg-green-50': mergeMode }">
                    <input type="radio" name="import_mode" value="merge"
                           @change="mergeMode = true"
                           class="mt-1">
                    <div class="flex-1">
                        <div class="font-medium text-gray-800">合併到現有店家 <span class="text-xs text-green-600">(推薦)</span></div>
                        <div class="text-sm text-gray-500 mb-2">將菜單匯入到已存在的店家，並更新甜冰/加料選項</div>
                        
                        <!-- 選擇目標店家 -->
                        <div x-show="mergeMode" x-transition class="mt-2">
                            <select name="merge_to_store_id" 
                                    x-model="selectedStoreId"
                                    class="w-full border rounded-lg px-3 py-2 text-sm">
                                <option value="">-- 請選擇目標店家 --</option>
                                {% for item in existing_stores %}
                                <option value="{{ item.store.id }}">
                                    {{ item.store.name }} (ID: {{ item.store.id }})
                                    {% if item.match_type == 'exact' %}[完全相同]{% endif %}
                                </option>
                                {% endfor %}
                            </select>
                        </div>
                    </div>
                </label>
            </div>
        </div>
        {% endif %}
        
        <div class="flex gap-2">
            <a href="/admin/import" class="flex-1 py-3 text-center rounded-lg border hover:bg-gray-50">
                取消
            </a>
            <button type="submit" 
                    class="flex-1 py-3 rounded-lg bg-orange-500 hover:bg-orange-600 text-white font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                    {% if is_full_import and existing_stores and existing_stores|length > 0 %}
                    :disabled="mergeMode && !selectedStoreId"
                    {% endif %}>
                {% if is_full_import and existing_stores and existing_stores|length > 0 %}
                <span x-show="!mergeMode">確認建立新店家</span>
                <span x-show="mergeMode">確認合併菜單</span>
                {% else %}
                確認匯入
                {% endif %}
            </button>
        </div>
    </form>
</div>
{% endblock %}
'''
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)
    
    print(f"  💾 已儲存: {filepath}")


def main():
    print("=" * 50)
    print("🚀 SELA 匯入功能優化")
    print("=" * 50)
    print("\n功能：")
    print("  1. 新增重複店家檢查")
    print("  2. 支援合併菜單到現有店家")
    print("  3. 匯入後導向到店家詳情頁")
    print()
    
    confirm = input("是否繼續？(y/N) ").strip().lower()
    if confirm != 'y':
        print("已取消")
        return
    
    try:
        patch_admin_py()
        replace_import_preview_html()
        
        print("\n" + "=" * 50)
        print("✅ 修改完成！")
        print("=" * 50)
        print("\n請執行以下命令測試：")
        print("  python -c \"from app.main import app; print('OK')\"")
        print("\n如需回滾，備份檔案位於原目錄（.bak 結尾）")
        
    except Exception as e:
        print(f"\n❌ 錯誤：{e}")
        print("請檢查錯誤訊息並手動修復")
        raise


if __name__ == "__main__":
    main()
