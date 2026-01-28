#!/usr/bin/env python3
"""
SELA 匯入流程修正
================

流程：
1. /admin/import → 新建店家（讀 store + menu）
2. /admin/stores/{id} 點「匯入菜單」→ 只讀 menu，忽略 store
3. /admin/stores/{id}/menus → 可直接編輯品項（名稱/價格）

執行：python3 fix_import_flow.py
"""

import os
import shutil
from datetime import datetime
from pathlib import Path

if not Path("app/routers/admin.py").exists():
    print("❌ 請在專案根目錄執行")
    exit(1)

BACKUP_SUFFIX = datetime.now().strftime("_%Y%m%d_%H%M%S.bak")


def backup(filepath):
    if os.path.exists(filepath):
        shutil.copy2(filepath, filepath + BACKUP_SUFFIX)
        print(f"  📦 備份: {filepath + BACKUP_SUFFIX}")


def fix_admin_py():
    """修正 admin.py"""
    filepath = "app/routers/admin.py"
    print(f"\n🔧 修正 {filepath}")
    backup(filepath)
    
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    # === 修正 imports ===
    # 移除錯誤的 import
    content = content.replace("from sqlalchemy import or_, joinedload", "from sqlalchemy import or_")
    
    # 確保正確的 imports
    if "joinedload" not in content:
        content = content.replace(
            "from sqlalchemy.orm import Session",
            "from sqlalchemy.orm import Session, joinedload"
        )
    elif "from sqlalchemy.orm import Session, joinedload" not in content and "from sqlalchemy.orm import joinedload" not in content:
        content = content.replace(
            "from sqlalchemy.orm import Session",
            "from sqlalchemy.orm import Session, joinedload"
        )
    
    if "from sqlalchemy import or_" not in content:
        content = content.replace(
            "from sqlalchemy.orm import Session",
            "from sqlalchemy.orm import Session\nfrom sqlalchemy import or_"
        )
    
    if "MenuContent" not in content and "from app.schemas.menu import" in content:
        content = content.replace(
            "from app.schemas.menu import FullImport, MenuImport",
            "from app.schemas.menu import FullImport, MenuImport, MenuContent"
        )
    
    if "from app.models.menu import Menu" in content and "MenuItem" not in content:
        content = content.replace(
            "from app.models.menu import Menu",
            "from app.models.menu import Menu, MenuItem"
        )
    
    if "from decimal import Decimal" not in content:
        # 在檔案開頭加入
        content = "from decimal import Decimal\n" + content
    
    print("  ✅ 修正 imports")
    
    # === 替換 import_preview 函數 ===
    new_import_preview = '''@router.post("/import/preview")
async def import_preview(
    request: Request,
    json_file: UploadFile = File(...),
    store_id: int = Form(None),
    db: Session = Depends(get_db),
):
    """匯入預覽
    - store_id 存在：只匯入菜單（忽略 JSON 中的 store）
    - store_id 不存在：完整匯入（新建店家 + 菜單）
    """
    user = await get_admin_user(request, db)
    
    if not json_file or not json_file.filename:
        raise HTTPException(status_code=400, detail="請上傳 JSON 檔案")
    
    file_content = await json_file.read()
    json_str = file_content.decode("utf-8")
    
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 格式錯誤: {e}")
    
    # ========== 流程 2：匯入菜單到現有店家 ==========
    if store_id:
        target_store = db.query(Store).filter(Store.id == store_id).first()
        if not target_store:
            raise HTTPException(status_code=404, detail="店家不存在")
        
        # 提取 menu（忽略 store 欄位）
        if "menu" in data:
            menu_data = data["menu"]
        elif "categories" in data or "items" in data:
            menu_data = data  # 純菜單格式
        else:
            raise HTTPException(status_code=400, detail="JSON 缺少菜單內容")
        
        import_data = {"store_id": store_id, "mode": "replace", "menu": menu_data}
        
        try:
            validated = MenuImport(**import_data)
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=f"菜單格式錯誤: {e}")
        
        return templates.TemplateResponse("admin/import_preview.html", {
            "request": request,
            "user": user,
            "data": validated,
            "is_full_import": False,
            "target_store": target_store,
            "json_str": json.dumps(import_data, ensure_ascii=False),
            "existing_stores": [],
        })
    
    # ========== 流程 1：完整匯入（新建店家）==========
    if "store" not in data:
        raise HTTPException(status_code=400, detail="JSON 缺少 store 欄位")
    if "menu" not in data:
        raise HTTPException(status_code=400, detail="JSON 缺少 menu 欄位")
    
    try:
        validated = FullImport(**data)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"格式錯誤: {e}")
    
    # 重複店家檢查
    existing_stores = []
    store_name = validated.store.name.strip()
    exact = db.query(Store).filter(Store.name == store_name, Store.is_active == True).first()
    if exact:
        existing_stores.append({"store": exact, "match_type": "exact"})
    else:
        for s in db.query(Store).filter(Store.is_active == True).all():
            if len(store_name) >= 2 and (store_name in s.name or s.name in store_name):
                existing_stores.append({"store": s, "match_type": "similar"})
    
    return templates.TemplateResponse("admin/import_preview.html", {
        "request": request,
        "user": user,
        "data": validated,
        "is_full_import": True,
        "target_store": None,
        "json_str": json_str,
        "existing_stores": existing_stores,
    })'''

    # === 替換 do_import 函數 ===
    new_do_import = '''@router.post("/import")
async def do_import(
    request: Request,
    json_str: str = Form(...),
    merge_to_store_id: int = Form(None),
    db: Session = Depends(get_db),
):
    """執行匯入"""
    user = await get_admin_user(request, db)
    
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON 格式錯誤: {e}")
    
    try:
        # 流程 2：匯入菜單到現有店家
        if "store_id" in data:
            store_id = data["store_id"]
            menu_data = data.get("menu", {})
            if not menu_data:
                raise HTTPException(status_code=400, detail="JSON 缺少 menu")
            validated = MenuImport(store_id=store_id, mode=data.get("mode", "replace"), menu=menu_data)
            import_menu(db, validated)
            return RedirectResponse(url=f"/admin/stores/{store_id}", status_code=302)
        
        # 合併到現有店家
        if merge_to_store_id:
            target = db.query(Store).filter(Store.id == merge_to_store_id).first()
            if not target:
                raise HTTPException(status_code=404, detail="店家不存在")
            
            menu_data = data.get("menu", {})
            if not menu_data:
                raise HTTPException(status_code=400, detail="JSON 缺少 menu")
            
            validated = MenuImport(store_id=merge_to_store_id, mode="replace", menu=MenuContent(**menu_data))
            import_menu(db, validated)
            
            # 更新甜冰加料
            if "store" in data:
                sd = data["store"]
                if sd.get("sugar_options"):
                    db.query(StoreOption).filter(StoreOption.store_id == merge_to_store_id, StoreOption.option_type == OptionType.SUGAR).delete()
                    for i, v in enumerate(sd["sugar_options"]):
                        db.add(StoreOption(store_id=merge_to_store_id, option_type=OptionType.SUGAR, option_value=v, sort_order=i))
                if sd.get("ice_options"):
                    db.query(StoreOption).filter(StoreOption.store_id == merge_to_store_id, StoreOption.option_type == OptionType.ICE).delete()
                    for i, v in enumerate(sd["ice_options"]):
                        db.add(StoreOption(store_id=merge_to_store_id, option_type=OptionType.ICE, option_value=v, sort_order=i))
                if sd.get("toppings"):
                    db.query(StoreTopping).filter(StoreTopping.store_id == merge_to_store_id).delete()
                    for i, t in enumerate(sd["toppings"]):
                        db.add(StoreTopping(store_id=merge_to_store_id, name=t["name"], price=t.get("price", 0), sort_order=i, is_active=True))
                db.commit()
            
            return RedirectResponse(url=f"/admin/stores/{merge_to_store_id}", status_code=302)
        
        # 流程 1：完整匯入
        if "store" in data:
            validated = FullImport(**data)
            store = import_store_and_menu(db, validated)
            return RedirectResponse(url=f"/admin/stores/{store.id}", status_code=302)
        
        raise HTTPException(status_code=400, detail="JSON 格式錯誤")
    
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"驗證錯誤: {e}")'''

    # === 新增菜單品項編輯 API ===
    new_menu_edit_api = '''

# ========== 流程 3：菜單品項編輯 ==========

@router.post("/menu/items/{item_id}/update")
async def update_menu_item(
    item_id: int,
    request: Request,
    name: str = Form(...),
    price: str = Form(...),
    price_l: str = Form(None),
    db: Session = Depends(get_db),
):
    """更新菜單品項"""
    user = await get_admin_user(request, db)
    
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="品項不存在")
    
    item.name = name.strip()
    item.price = Decimal(price)
    item.price_l = Decimal(price_l) if price_l and price_l.strip() else None
    db.commit()
    
    # 找到店家 ID
    menu = db.query(Menu).filter(Menu.id == item.menu_id).first()
    
    # HTMX 請求返回 JSON
    if request.headers.get("HX-Request"):
        return {"success": True, "name": item.name, "price": str(item.price), "price_l": str(item.price_l) if item.price_l else None}
    
    return RedirectResponse(url=f"/admin/stores/{menu.store_id}/menus", status_code=302)'''

    # 執行替換
    # 替換 import_preview
    start = content.find('@router.post("/import/preview")')
    if start != -1:
        end = content.find('\n@router.post("/import")', start)
        if end != -1:
            content = content[:start] + new_import_preview + "\n\n" + content[end+1:]
            print("  ✅ 替換 import_preview")
    
    # 替換 do_import
    start = content.find('@router.post("/import")\nasync def do_import')
    if start == -1:
        start = content.find('@router.post("/import")')
    if start != -1:
        end = content.find('\n@router.get("/groups")', start)
        if end != -1:
            content = content[:start] + new_do_import + "\n\n" + content[end+1:]
            print("  ✅ 替換 do_import")
    
    # 新增品項編輯 API
    if "/menu/items/{item_id}/update" not in content:
        pos = content.find('@router.get("/groups")')
        if pos != -1:
            content = content[:pos] + new_menu_edit_api + "\n\n" + content[pos:]
            print("  ✅ 新增品項編輯 API")
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  💾 儲存: {filepath}")


def create_import_preview_html():
    """建立 import_preview.html"""
    filepath = "app/templates/admin/import_preview.html"
    print(f"\n🔧 更新 {filepath}")
    backup(filepath)
    
    content = '''{% extends "base.html" %}
{% block title %}匯入預覽{% endblock %}

{% block content %}
<div class="space-y-4">
    <div class="flex items-center justify-between">
        <h1 class="text-xl font-bold text-gray-800">匯入預覽</h1>
        {% if target_store %}
        <a href="/admin/stores/{{ target_store.id }}" class="text-sm text-gray-500">← 返回 {{ target_store.name }}</a>
        {% else %}
        <a href="/admin/import" class="text-sm text-gray-500">← 返回</a>
        {% endif %}
    </div>
    
    <div class="bg-white rounded-lg shadow-sm p-4">
        {% if is_full_import %}
        <!-- 流程 1：新建店家 -->
        <div class="text-sm text-orange-600 font-medium mb-3">📦 新建店家 + 菜單</div>
        
        {% if existing_stores|length > 0 %}
        <div class="bg-yellow-50 border border-yellow-300 rounded-lg p-3 mb-4">
            <div class="font-medium text-yellow-800 mb-2">⚠️ 發現重複店家</div>
            {% for item in existing_stores %}
            <div class="flex items-center justify-between bg-white rounded p-2 mb-1">
                <span>{{ item.store.name }} 
                    {% if item.match_type == 'exact' %}<span class="text-xs bg-red-100 text-red-600 px-1 rounded">完全相同</span>{% endif %}
                </span>
                <a href="/admin/stores/{{ item.store.id }}" target="_blank" class="text-xs text-blue-600">查看 →</a>
            </div>
            {% endfor %}
        </div>
        {% endif %}
        
        <div class="border rounded p-3 mb-4 text-sm">
            <div class="font-medium text-gray-800">{{ data.store.name }}</div>
            <div class="text-gray-500">{{ '🧋 飲料' if data.store.category == 'drink' else '🍱 餐點' }}</div>
            {% if data.store.sugar_options %}<div class="text-gray-400">甜度：{{ data.store.sugar_options|join(' / ') }}</div>{% endif %}
            {% if data.store.ice_options %}<div class="text-gray-400">冰塊：{{ data.store.ice_options|join(' / ') }}</div>{% endif %}
        </div>
        
        {% else %}
        <!-- 流程 2：匯入菜單 -->
        <div class="text-sm text-green-600 font-medium mb-3">📋 匯入菜單到現有店家</div>
        {% if target_store %}
        <div class="bg-green-50 border border-green-200 rounded p-3 mb-4 flex items-center gap-3">
            <div class="w-10 h-10 bg-white rounded flex items-center justify-center">
                {% if target_store.logo_url %}<img src="{{ target_store.logo_url }}" class="w-8 h-8 object-contain">
                {% else %}<span class="text-xl">{% if target_store.category.value == 'drink' %}🧋{% else %}🍱{% endif %}</span>{% endif %}
            </div>
            <div>
                <div class="font-medium">{{ target_store.name }}</div>
                <div class="text-sm text-green-600">菜單將覆蓋現有菜單</div>
            </div>
        </div>
        {% endif %}
        {% endif %}
        
        <!-- 菜單預覽 -->
        <div class="border rounded p-3 max-h-72 overflow-y-auto">
            <div class="font-medium text-gray-800 mb-2">菜單內容</div>
            {% if data.menu.categories %}
            {% for cat in data.menu.categories %}
            <div class="mb-2">
                <div class="text-xs bg-gray-600 text-white px-2 py-0.5 rounded inline-block">{{ cat.name }}</div>
                <div class="ml-2 text-sm text-gray-600">
                    {% for item in cat.items %}
                    <div class="py-0.5">{{ item.name }} <span class="text-orange-600">${{ item.price }}{% if item.price_l %}/${{ item.price_l }}{% endif %}</span></div>
                    {% endfor %}
                </div>
            </div>
            {% endfor %}
            {% endif %}
            {% if data.menu.items %}
            <div class="text-sm text-gray-600">
                {% for item in data.menu.items %}
                <div class="py-0.5">{{ item.name }} <span class="text-orange-600">${{ item.price }}</span></div>
                {% endfor %}
            </div>
            {% endif %}
        </div>
    </div>
    
    <!-- 表單 -->
    <form action="/admin/import" method="post" x-data="{ mergeMode: false, selectedId: '' }">
        <input type="hidden" name="json_str" value="{{ json_str | e }}">
        
        {% if is_full_import and existing_stores|length > 0 %}
        <div class="bg-white rounded-lg shadow-sm p-4 mb-4 space-y-3">
            <label class="flex items-start gap-3 p-3 border rounded cursor-pointer" :class="{ 'border-orange-500 bg-orange-50': !mergeMode }">
                <input type="radio" name="mode" value="new" @change="mergeMode = false" checked class="mt-1">
                <div><div class="font-medium">建立新店家</div><div class="text-sm text-gray-500">（會有重複）</div></div>
            </label>
            <label class="flex items-start gap-3 p-3 border rounded cursor-pointer" :class="{ 'border-green-500 bg-green-50': mergeMode }">
                <input type="radio" name="mode" value="merge" @change="mergeMode = true" class="mt-1">
                <div class="flex-1">
                    <div class="font-medium">合併到現有店家 <span class="text-xs text-green-600">(推薦)</span></div>
                    <select name="merge_to_store_id" x-model="selectedId" x-show="mergeMode" class="mt-2 w-full border rounded px-3 py-2 text-sm">
                        <option value="">-- 選擇 --</option>
                        {% for item in existing_stores %}<option value="{{ item.store.id }}">{{ item.store.name }}</option>{% endfor %}
                    </select>
                </div>
            </label>
        </div>
        {% endif %}
        
        <div class="flex gap-2">
            {% if target_store %}
            <a href="/admin/stores/{{ target_store.id }}" class="flex-1 py-3 text-center rounded-lg border hover:bg-gray-50">取消</a>
            {% else %}
            <a href="/admin/import" class="flex-1 py-3 text-center rounded-lg border hover:bg-gray-50">取消</a>
            {% endif %}
            <button type="submit" class="flex-1 py-3 rounded-lg bg-orange-500 text-white font-medium hover:bg-orange-600 disabled:opacity-50"
                    {% if is_full_import and existing_stores|length > 0 %}:disabled="mergeMode && !selectedId"{% endif %}>
                確認匯入
            </button>
        </div>
    </form>
</div>
{% endblock %}
'''
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  💾 儲存: {filepath}")


def update_menus_html():
    """更新 menus.html 加入編輯功能"""
    filepath = "app/templates/admin/menus.html"
    print(f"\n🔧 更新 {filepath}")
    backup(filepath)
    
    content = '''{% extends "base.html" %}
{% block title %}菜單管理 - {{ store.name }}{% endblock %}

{% block content %}
<div class="space-y-4">
    <div class="flex items-center justify-between">
        <h1 class="text-xl font-bold text-gray-800">菜單管理</h1>
        <div class="flex items-center gap-3">
            <a href="/admin/import?store_id={{ store.id }}" class="text-sm bg-orange-500 hover:bg-orange-600 text-white px-3 py-1.5 rounded-lg">+ 匯入菜單</a>
            <a href="/admin/stores/{{ store.id }}" class="text-sm text-gray-500 hover:text-gray-700">返回 {{ store.name }} →</a>
        </div>
    </div>
    
    <!-- 操作說明 -->
    <div class="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800">
        💡 點擊品項可直接編輯名稱和價格
    </div>
    
    {% if menus %}
    {% for menu in menus %}
    {% if menu.is_active %}
    <div class="bg-white rounded-lg shadow-sm">
        <div class="p-4 border-b flex items-center justify-between">
            <div>
                <span class="font-medium text-gray-800">目前使用中的菜單</span>
                <span class="text-xs text-gray-400 ml-2">{{ menu.items|length }} 個品項</span>
            </div>
        </div>
        
        <div class="divide-y">
            {% for category in menu.categories %}
            <div class="p-4">
                <div class="text-sm font-medium text-white bg-gray-600 px-2 py-1 rounded inline-block mb-2">{{ category.name }}</div>
                
                <div class="space-y-1">
                    {% for item in category.items %}
                    <div class="flex items-center gap-2 p-2 rounded hover:bg-gray-50 group"
                         x-data="{ 
                             editing: false, 
                             name: '{{ item.name|replace("'", "\\'")|e }}', 
                             price: '{{ item.price }}', 
                             priceL: '{{ item.price_l or '' }}',
                             saving: false,
                             async save() {
                                 this.saving = true;
                                 const form = new FormData();
                                 form.append('name', this.name);
                                 form.append('price', this.price);
                                 form.append('price_l', this.priceL);
                                 await fetch('/admin/menu/items/{{ item.id }}/update', {method: 'POST', body: form});
                                 this.saving = false;
                                 this.editing = false;
                             }
                         }">
                        
                        <!-- 顯示模式 -->
                        <template x-if="!editing">
                            <div class="flex-1 flex items-center gap-2 cursor-pointer" @click="editing = true">
                                <span class="flex-1" x-text="name"></span>
                                <span class="text-orange-600 font-medium">
                                    $<span x-text="price"></span>
                                    <template x-if="priceL"><span class="text-gray-400">/$<span class="text-orange-600" x-text="priceL"></span></span></template>
                                </span>
                                <span class="text-xs text-gray-300 opacity-0 group-hover:opacity-100 transition">✏️</span>
                            </div>
                        </template>
                        
                        <!-- 編輯模式 -->
                        <template x-if="editing">
                            <div class="flex-1 flex items-center gap-2">
                                <input type="text" x-model="name" @keydown.enter="save()" @keydown.escape="editing = false"
                                       class="flex-1 border rounded px-2 py-1 text-sm" autofocus>
                                <div class="flex items-center gap-1 text-sm">
                                    <span class="text-gray-400">$</span>
                                    <input type="number" x-model="price" step="1" min="0" @keydown.enter="save()"
                                           class="w-16 border rounded px-2 py-1 text-right">
                                    <span class="text-gray-300">/</span>
                                    <input type="number" x-model="priceL" step="1" min="0" placeholder="大杯" @keydown.enter="save()"
                                           class="w-16 border rounded px-2 py-1 text-right">
                                </div>
                                <button @click="save()" class="text-green-600 hover:text-green-700 px-2" :disabled="saving">
                                    <span x-show="!saving">✓</span>
                                    <span x-show="saving">...</span>
                                </button>
                                <button @click="editing = false" class="text-gray-400 hover:text-gray-600 px-1">✕</button>
                            </div>
                        </template>
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endfor %}
            
            {% set uncategorized = menu.items | selectattr('category_id', 'none') | list %}
            {% if uncategorized %}
            <div class="p-4">
                <div class="text-sm font-medium text-white bg-gray-500 px-2 py-1 rounded inline-block mb-2">未分類</div>
                <div class="space-y-1">
                    {% for item in uncategorized %}
                    <div class="flex items-center gap-2 p-2 rounded hover:bg-gray-50 group"
                         x-data="{ editing: false, name: '{{ item.name|replace("'", "\\'")|e }}', price: '{{ item.price }}', priceL: '{{ item.price_l or '' }}', saving: false,
                             async save() {
                                 this.saving = true;
                                 const form = new FormData();
                                 form.append('name', this.name);
                                 form.append('price', this.price);
                                 form.append('price_l', this.priceL);
                                 await fetch('/admin/menu/items/{{ item.id }}/update', {method: 'POST', body: form});
                                 this.saving = false;
                                 this.editing = false;
                             }
                         }">
                        <template x-if="!editing">
                            <div class="flex-1 flex items-center gap-2 cursor-pointer" @click="editing = true">
                                <span class="flex-1" x-text="name"></span>
                                <span class="text-orange-600 font-medium">$<span x-text="price"></span></span>
                                <span class="text-xs text-gray-300 opacity-0 group-hover:opacity-100">✏️</span>
                            </div>
                        </template>
                        <template x-if="editing">
                            <div class="flex-1 flex items-center gap-2">
                                <input type="text" x-model="name" @keydown.enter="save()" @keydown.escape="editing = false" class="flex-1 border rounded px-2 py-1 text-sm" autofocus>
                                <input type="number" x-model="price" step="1" @keydown.enter="save()" class="w-20 border rounded px-2 py-1 text-sm text-right">
                                <button @click="save()" class="text-green-600">✓</button>
                                <button @click="editing = false" class="text-gray-400">✕</button>
                            </div>
                        </template>
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endif %}
        </div>
    </div>
    {% endif %}
    {% endfor %}
    
    <!-- 歷史版本 -->
    {% set inactive_menus = menus | selectattr('is_active', 'false') | list %}
    {% if inactive_menus %}
    <details class="bg-white rounded-lg shadow-sm">
        <summary class="p-4 cursor-pointer text-gray-600 hover:bg-gray-50">
            📁 歷史版本 ({{ inactive_menus|length }})
        </summary>
        <div class="divide-y border-t">
            {% for menu in inactive_menus %}
            <div class="p-4 flex items-center justify-between">
                <div class="text-sm text-gray-500">
                    版本 #{{ menu.id }} ・{{ menu.created_at.strftime('%Y-%m-%d') }} ・{{ menu.items|length }} 品項
                </div>
                <form action="/admin/stores/{{ store.id }}/menus/{{ menu.id }}/activate" method="post">
                    <button type="submit" class="text-sm text-orange-600 hover:text-orange-700">啟用</button>
                </form>
            </div>
            {% endfor %}
        </div>
    </details>
    {% endif %}
    
    {% else %}
    <div class="text-center py-12 text-gray-500 bg-white rounded-lg">
        <div class="text-4xl mb-2">📋</div>
        <p>還沒有菜單</p>
        <a href="/admin/import?store_id={{ store.id }}" class="text-orange-600 hover:underline">匯入菜單</a>
    </div>
    {% endif %}
</div>
{% endblock %}
'''
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  💾 儲存: {filepath}")


def test():
    """測試"""
    print("\n🧪 測試...")
    import subprocess
    result = subprocess.run(["python3", "-c", "from app.main import app; print('OK')"], capture_output=True, text=True)
    if result.returncode == 0:
        print("  ✅ 測試通過")
        return True
    print("  ❌ 測試失敗:")
    print(result.stderr)
    return False


def main():
    print("=" * 50)
    print("🚀 SELA 匯入流程修正")
    print("=" * 50)
    print("\n流程：")
    print("  1️⃣  /admin/import → 新建店家（讀 store + menu）")
    print("  2️⃣  /admin/stores/{id} 匯入菜單 → 只讀 menu")
    print("  3️⃣  /admin/stores/{id}/menus → 點擊編輯品項")
    print()
    
    if input("繼續？(y/N) ").strip().lower() != 'y':
        print("已取消")
        return
    
    try:
        fix_admin_py()
        create_import_preview_html()
        update_menus_html()
        
        print("\n" + "=" * 50)
        if test():
            print("\n✅ 完成！執行：")
            print("  git add .")
            print('  git commit -m "Fix: import flow"')
            print("  git push")
        print("=" * 50)
    except Exception as e:
        print(f"\n❌ 錯誤：{e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
