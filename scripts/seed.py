"""
建立測試用種子資料
執行方式: python -m scripts.seed
"""
import sys
sys.path.insert(0, '.')

from app.database import SessionLocal, engine, Base
from app.models import User, UserPreset, Store, StoreOption, Menu, MenuCategory, MenuItem, ItemOption
from app.models.store import CategoryType, OptionType

def seed():
    # 建立資料表
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    try:
        # 檢查是否已有資料
        if db.query(User).first():
            print("⚠️ 資料庫已有資料，跳過種子")
            return
        
        # 建立測試使用者
        admin = User(
            line_user_id="test-admin-user",
            display_name="管理員",
            picture_url=None,
            is_admin=True,
        )
        db.add(admin)
        
        user1 = User(
            line_user_id="test-user-1",
            display_name="小明",
            picture_url=None,
            is_admin=False,
        )
        db.add(user1)
        
        user2 = User(
            line_user_id="test-user-2",
            display_name="小華",
            picture_url=None,
            is_admin=False,
        )
        db.add(user2)
        
        db.flush()
        print(f"✅ 建立使用者: {admin.display_name}, {user1.display_name}, {user2.display_name}")
        
        # 建立飲料店
        drink_store = Store(
            name="可不可熟成紅茶",
            category=CategoryType.DRINK,
            logo_url=None,
            is_active=True,
        )
        db.add(drink_store)
        db.flush()
        
        # 甜度選項
        sugar_options = ["正常糖", "少糖", "半糖", "微糖", "無糖"]
        for i, value in enumerate(sugar_options):
            db.add(StoreOption(
                store_id=drink_store.id,
                option_type=OptionType.SUGAR,
                option_value=value,
                sort_order=i,
            ))
        
        # 冰塊選項
        ice_options = ["正常冰", "少冰", "微冰", "去冰", "熱"]
        for i, value in enumerate(ice_options):
            db.add(StoreOption(
                store_id=drink_store.id,
                option_type=OptionType.ICE,
                option_value=value,
                sort_order=i,
            ))
        
        # 建立菜單
        drink_menu = Menu(
            store_id=drink_store.id,
            is_active=True,
        )
        db.add(drink_menu)
        db.flush()
        
        # 分類: 熟成紅茶
        cat1 = MenuCategory(menu_id=drink_menu.id, name="熟成紅茶", sort_order=0)
        db.add(cat1)
        db.flush()
        
        items1 = [
            ("熟成紅茶", 30),
            ("熟成冷露", 35),
            ("太妃紅茶", 45),
        ]
        for i, (name, price) in enumerate(items1):
            db.add(MenuItem(
                menu_id=drink_menu.id,
                category_id=cat1.id,
                name=name,
                price=price,
                sort_order=i,
            ))
        
        # 分類: 熟成奶茶
        cat2 = MenuCategory(menu_id=drink_menu.id, name="熟成奶茶", sort_order=1)
        db.add(cat2)
        db.flush()
        
        items2 = [
            ("熟成奶茶", 50),
            ("熟成奶霜", 55),
            ("太妃奶茶", 55),
        ]
        for i, (name, price) in enumerate(items2):
            db.add(MenuItem(
                menu_id=drink_menu.id,
                category_id=cat2.id,
                name=name,
                price=price,
                sort_order=i,
            ))
        
        print(f"✅ 建立飲料店: {drink_store.name}")
        
        # 建立便當店
        meal_store = Store(
            name="池上便當",
            category=CategoryType.MEAL,
            logo_url=None,
            is_active=True,
        )
        db.add(meal_store)
        db.flush()
        
        # 建立菜單
        meal_menu = Menu(
            store_id=meal_store.id,
            is_active=True,
        )
        db.add(meal_menu)
        db.flush()
        
        # 便當
        meal_cat = MenuCategory(menu_id=meal_menu.id, name="便當", sort_order=0)
        db.add(meal_cat)
        db.flush()
        
        # 雞腿便當（含選項）
        chicken = MenuItem(
            menu_id=meal_menu.id,
            category_id=meal_cat.id,
            name="雞腿便當",
            price=100,
            sort_order=0,
        )
        db.add(chicken)
        db.flush()
        
        db.add(ItemOption(menu_item_id=chicken.id, name="加飯", price_diff=10, sort_order=0))
        db.add(ItemOption(menu_item_id=chicken.id, name="加蛋", price_diff=15, sort_order=1))
        db.add(ItemOption(menu_item_id=chicken.id, name="不要香菜", price_diff=0, sort_order=2))
        
        # 排骨便當
        pork = MenuItem(
            menu_id=meal_menu.id,
            category_id=meal_cat.id,
            name="排骨便當",
            price=90,
            sort_order=1,
        )
        db.add(pork)
        db.flush()
        
        db.add(ItemOption(menu_item_id=pork.id, name="加飯", price_diff=10, sort_order=0))
        db.add(ItemOption(menu_item_id=pork.id, name="加蛋", price_diff=15, sort_order=1))
        
        print(f"✅ 建立便當店: {meal_store.name}")
        
        db.commit()
        print("\n🎉 種子資料建立完成！")
        print("\n測試帳號:")
        print("  管理員: test-admin-user")
        print("  一般用戶: test-user-1, test-user-2")
        
    except Exception as e:
        db.rollback()
        print(f"❌ 錯誤: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
