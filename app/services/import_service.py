"""
import_service.py - 匯入服務
"""
from sqlalchemy.orm import Session
from decimal import Decimal

from app.models.store import Store, StoreOption, StoreTopping, CategoryType, OptionType
from app.models.menu import Menu, MenuCategory, MenuItem, ItemOption
from app.schemas.menu import FullImport, MenuImport, MenuContent


def import_store_and_menu(db: Session, data: FullImport) -> Store:
    """匯入店家 + 菜單

    V1.8.0：偵測同名店家（完全比對 name）。
    - 若同名店家已存在 → 不新增重複店家，改把菜單匯入既有店家；
      既有菜單保留為舊版本（停用），新菜單啟用。
    - 若不存在 → 正常新增店家 + 菜單。
    """
    # 完全比對店名，找既有同名店家
    existing_store = db.query(Store).filter(Store.name == data.store.name).first()

    if existing_store:
        # 同名店家已存在 → 把舊菜單全部停用（保留為舊版本），建立新菜單啟用
        db.query(Menu).filter(Menu.store_id == existing_store.id).update({"is_active": False})
        db.flush()
        _create_menu(db, existing_store.id, data.menu, is_active=True)
        db.commit()
        return existing_store

    # 建立店家
    store = Store(
        name=data.store.name,
        category=CategoryType(data.store.category),
        logo_url=data.store.logo_url,
        is_active=True,
    )
    db.add(store)
    db.flush()

    # 建立店家選項（甜度）
    if data.store.sugar_options:
        for i, value in enumerate(data.store.sugar_options):
            option = StoreOption(
                store_id=store.id,
                option_type=OptionType.SUGAR,
                option_value=value,
                sort_order=i,
            )
            db.add(option)

    # 建立店家選項（冰塊）
    if data.store.ice_options:
        for i, value in enumerate(data.store.ice_options):
            option = StoreOption(
                store_id=store.id,
                option_type=OptionType.ICE,
                option_value=value,
                sort_order=i,
            )
            db.add(option)

    # 建立加料選項
    if data.store.toppings:
        for i, topping_data in enumerate(data.store.toppings):
            topping = StoreTopping(
                store_id=store.id,
                name=topping_data.name,
                price=topping_data.price,
                sort_order=i,
                is_active=True,
            )
            db.add(topping)

    # 建立菜單
    _create_menu(db, store.id, data.menu, is_active=True)

    db.commit()
    return store


def import_menu(db: Session, data: MenuImport) -> Menu:
    """單獨匯入菜單（更新現有店家的菜單）
    
    Args:
        db: 資料庫 session
        data: MenuImport schema，包含 store_id, mode, menu
    
    Returns:
        Menu: 更新後的菜單
    """
    store_id = data.store_id
    content = data.menu

    # V2.11.1 P1-04：**取消 replace 模式，一律新增版本。**
    #
    # 原本的 replace 有兩個無法修的問題：
    #   1. `db.delete(category)` 時 MenuCategory.items 沒有設 cascade，ORM 預設
    #      把子列的 category_id 設為 NULL 而不是刪除。舊品項因此變成「無分類品項」，
    #      而點餐頁會把無分類品項顯示出來 → 新舊菜單混在一起、舊價格仍可點。
    #   2. 就算修掉 cascade 也不能真的刪：舊品項被 order_items.menu_item_id 引用，
    #      刪掉會斷掉所有歷史訂單。所以 replace 在語意上本來就不成立。
    #   3. 這個 menu 正被進行中與歷史團單透過 groups.menu_id 引用，replace 會
    #      直接改變它們的菜單內容。
    #
    # 改成一律新增版本後：進行中的團仍指向舊 menu_id 不受影響，新開的團才用新菜單。
    db.query(Menu).filter(Menu.store_id == store_id).update({"is_active": False})

    menu = _create_menu(db, store_id, content, is_active=True)
    db.commit()
    return menu


def _create_menu(db: Session, store_id: int, content: MenuContent, is_active: bool) -> Menu:
    """建立菜單"""
    menu = Menu(
        store_id=store_id,
        is_active=is_active,
    )
    db.add(menu)
    db.flush()

    _populate_menu(db, menu, content)
    return menu


def _populate_menu(db: Session, menu: Menu, content: MenuContent):
    """填充菜單內容"""
    item_sort = 0

    # 有分類的項目
    if content.categories:
        for cat_idx, cat_data in enumerate(content.categories):
            category = MenuCategory(
                menu_id=menu.id,
                name=cat_data.name,
                sort_order=cat_idx,
            )
            db.add(category)
            db.flush()

            for item_data in cat_data.items:
                item = MenuItem(
                    menu_id=menu.id,
                    category_id=category.id,
                    name=item_data.name,
                    price=item_data.price,
                    price_l=item_data.price_l,
                    sort_order=item_sort,
                )
                db.add(item)
                db.flush()
                item_sort += 1

                # 項目選項
                if item_data.options:
                    for opt_idx, opt_data in enumerate(item_data.options):
                        option = ItemOption(
                            menu_item_id=item.id,
                            name=opt_data.name,
                            price_diff=opt_data.price_diff,
                            sort_order=opt_idx,
                        )
                        db.add(option)

    # 無分類的項目
    if content.items:
        for item_data in content.items:
            item = MenuItem(
                menu_id=menu.id,
                category_id=None,
                name=item_data.name,
                price=item_data.price,
                price_l=item_data.price_l,
                sort_order=item_sort,
            )
            db.add(item)
            db.flush()
            item_sort += 1

            # 項目選項
            if item_data.options:
                for opt_idx, opt_data in enumerate(item_data.options):
                    option = ItemOption(
                        menu_item_id=item.id,
                        name=opt_data.name,
                        price_diff=opt_data.price_diff,
                        sort_order=opt_idx,
                    )
                    db.add(option)


# 別名（兼容舊代碼）
import_store_from_json = import_store_and_menu
