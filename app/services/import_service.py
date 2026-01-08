"""
import_service.py - 匯入服務
"""
from sqlalchemy.orm import Session
from decimal import Decimal

from app.models.store import Store, StoreOption, StoreTopping, CategoryType, OptionType
from app.models.menu import Menu, MenuCategory, MenuItem, ItemOption
from app.schemas.menu import FullImport, MenuImport, MenuContent


def import_store_and_menu(db: Session, data: FullImport) -> Store:
    """匯入店家 + 菜單"""

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
    mode = data.mode

    if mode == "replace":
        # 替換模式：找到現有菜單並更新
        existing_menu = db.query(Menu).filter(
            Menu.store_id == store_id,
            Menu.is_active == True
        ).first()

        if existing_menu:
            # 刪除舊的分類和項目
            for category in existing_menu.categories:
                db.delete(category)
            db.flush()

            # 重新填充菜單
            _populate_menu(db, existing_menu, content)
            db.commit()
            return existing_menu

    # 新增模式：停用舊菜單，建立新菜單
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
