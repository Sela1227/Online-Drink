# -*- coding: utf-8 -*-
"""匯入頁「貼上就自動檢查」的實際行為 —— V2.15.0

跟 check_frontend_toast.py 同一類：後端測試看不見 htmx 到底有沒有發請求。
用 TestClient 把匯入頁（選定店家／未選店家）渲染成 HTML，交給 scripts/jsdom_import_check.js。

跑法：
    PYTHONPATH=. python scripts/check_frontend_import.py
需要 node 與 node_modules 裡的 jsdom、alpinejs、htmx.org（`npm i jsdom@24 alpinejs@3 htmx.org@1.9.10`
或設 NODE_PATH）；任一缺少就跳過。**打包前記得清掉 node_modules。**
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NODE_SCRIPT = ROOT / "scripts" / "jsdom_import_check.js"
SORT_SCRIPT = ROOT / "scripts" / "jsdom_store_sort_check.js"  # V2.16.2 店家排序
GROUP_SCRIPT = ROOT / "scripts" / "jsdom_group_check.js"  # V2.18.0 團頁
WORKBENCH_SCRIPT = ROOT / "scripts" / "jsdom_workbench_check.js"  # V2.21.0 工作台共用選項

os.environ["DATABASE_URL"] = "sqlite:///./_importcheck.db"
os.environ["SECRET_KEY"] = "template_check_only"
sys.path.insert(0, str(ROOT))


def _render_pages() -> dict:
    from app.database import Base, engine, SessionLocal
    from app.models.user import User
    from app.models.store import Store, CategoryType
    import app.routers.admin as adm
    import app.main as m
    from fastapi.testclient import TestClient
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    u = User(line_user_id="importcheck", display_name="檢查", is_admin=True)
    st = Store(name="檢查店", category=CategoryType.MEAL)
    db.add_all([u, st]); db.commit()

    async def fake_admin(request, d):
        return d.query(User).filter(User.line_user_id == "importcheck").first()
    adm.get_admin_user = fake_admin
    c = TestClient(m.app)
    pages = {"store": c.get(f"/admin/import?store_id={st.id}").text, "nostore": c.get("/admin/import").text}
    # V2.15.1 審核 P1-1：XHR 假回應改用**真實**的預覽片段，才測得到確認鈕
    import json as _json
    menu = {"menu": {"categories": [{"name": "主食", "items": [{"name": "雞腿飯", "price": 100}]}]}}
    frag = c.post("/admin/import/preview", data={"store_id": str(st.id), "json_text": _json.dumps(menu, ensure_ascii=False)},
                  headers={"HX-Request": "true"}).text
    assert "確認" in frag and "base_menu_id" in frag, "預覽片段應含確認鈕"
    pages["__fragment__"] = frag
    # V2.16.1 B-8：新增一家店、店名近似既有「檢查店」→ 片段應有「改為更新」按鈕
    frag2 = c.post("/admin/import/preview", data={"store_id": "", "new_store_name": "檢查店（彰化店）", "new_store_category": "meal",
                                                 "json_text": _json.dumps(menu, ensure_ascii=False)},
                   headers={"HX-Request": "true"}).text
    assert "改為更新「檢查店」" in frag2 and "確定是新店家" in frag2, "近似店名片段應含切換按鈕"
    pages["__similar__"] = frag2

    # V2.16.2 店家排序：三家餐廳——甲店開過 5 次（上次最舊）、乙店 1 次（上次最新）、丙店沒開過
    from app.models.group import Group
    from app.models.menu import Menu
    from datetime import datetime, timedelta
    import app.routers.groups as grp
    jia = Store(name="甲店", category=CategoryType.MEAL); yi = Store(name="乙店", category=CategoryType.MEAL); bing = Store(name="丙店", category=CategoryType.MEAL)
    # V2.16.3 審核 P0-2：丁店是飲料店，甜冰選項是「全糖／半糖」「去冰」（不是寫死的「正常糖」）
    from app.models.store import StoreOption, OptionType
    ding = Store(name="丁店", category=CategoryType.DRINK)
    db.add_all([jia, yi, bing, ding]); db.commit()
    db.add_all([StoreOption(store_id=ding.id, option_type=OptionType.SUGAR, option_value="全糖", sort_order=0),
                StoreOption(store_id=ding.id, option_type=OptionType.SUGAR, option_value="半糖", sort_order=1),
                StoreOption(store_id=ding.id, option_type=OptionType.ICE, option_value="去冰", sort_order=0)]); db.commit()
    for st_, n, days in ((jia, 5, 30), (yi, 1, 1)):
        mn = Menu(store_id=st_.id, is_active=True); db.add(mn); db.commit()
        for i in range(n):
            db.add(Group(owner_id=u.id, store_id=st_.id, menu_id=mn.id, name=f"{st_.name}{i}", category=CategoryType.MEAL,
                         deadline=datetime(2026, 1, 1) + timedelta(hours=1), created_at=datetime.utcnow() - timedelta(days=days + i)))
        db.commit()
    async def fake_user(request, d):
        return d.query(User).filter(User.line_user_id == "importcheck").first()
    grp.get_current_user = fake_user
    pages["__picker__"] = c.get("/groups/new").text
    pages["__admin_stores__"] = c.get("/admin/stores").text
    # V2.17.0 店家分頁：乙店已收藏
    import app.routers.home as home_r
    from app.models.user import UserFavorite
    db.add(UserFavorite(user_id=u.id, store_id=yi.id)); db.commit()
    home_r.get_current_user = fake_user
    pages["__catalog__"] = c.get("/stores").text

    # V2.18.0 團頁：member＝別人開的團、我購物車有 1 件 $100；owner＝我開的團、別人點了還沒送出
    from app.models.order import Order, OrderItem, OrderStatus
    from app.models.menu import MenuItem
    import app.routers.orders as ord_r
    other = User(line_user_id="importcheck-other", display_name="別人"); db.add(other); db.commit()
    mn_jia = db.query(Menu).filter(Menu.store_id == jia.id).first()
    from app.models.menu import MenuCategory
    cat = MenuCategory(menu_id=mn_jia.id, name="主食", sort_order=0); db.add(cat); db.flush()
    mi = MenuItem(menu_id=mn_jia.id, category_id=cat.id, name="雞腿飯", price=100, sort_order=0); db.add(mi); db.flush()
    from app.models.group import taipei_now
    g_member = Group(owner_id=other.id, store_id=jia.id, menu_id=mn_jia.id, name="別人開的", category=CategoryType.MEAL,
                     deadline=taipei_now() + timedelta(hours=2), is_public=True)
    g_owner = Group(owner_id=u.id, store_id=jia.id, menu_id=mn_jia.id, name="我開的", category=CategoryType.MEAL,
                    deadline=taipei_now() + timedelta(hours=2), is_public=True)
    db.add_all([g_member, g_owner]); db.flush()
    o_me = Order(group_id=g_member.id, user_id=u.id, status=OrderStatus.DRAFT); db.add(o_me); db.flush()
    db.add(OrderItem(order_id=o_me.id, menu_item_id=mi.id, item_name="雞腿飯", unit_price=100, quantity=1))
    o_other = Order(group_id=g_member.id, user_id=other.id, status=OrderStatus.SUBMITTED); db.add(o_other); db.flush()
    db.add(OrderItem(order_id=o_other.id, menu_item_id=mi.id, item_name="雞腿飯", unit_price=100, quantity=2))
    o_pending = Order(group_id=g_owner.id, user_id=other.id, status=OrderStatus.DRAFT); db.add(o_pending); db.flush()
    db.add(OrderItem(order_id=o_pending.id, menu_item_id=mi.id, item_name="雞腿飯", unit_price=100, quantity=1))
    db.commit()
    async def fake_user_opt(request, d):
        return d.query(User).filter(User.line_user_id == "importcheck").first(), None
    grp.get_current_user_optional = fake_user_opt
    ord_r.get_current_user = fake_user
    pages["__group_member__"] = c.get(f"/groups/{g_member.id}").text
    pages["__group_member_mine__"] = c.get(f"/groups/{g_member.id}/orders/mine").text
    pages["__group_member_wall__"] = c.get(f"/groups/{g_member.id}/orders/wall").text
    pages["__group_owner__"] = c.get(f"/groups/{g_owner.id}").text
    pages["__group_owner_mine__"] = c.get(f"/groups/{g_owner.id}/orders/mine").text
    pages["__group_owner_wall__"] = c.get(f"/groups/{g_owner.id}/orders/wall").text
    assert 'data-cart-count="1"' in pages["__group_member_mine__"], "member 購物車片段應有 1 件"
    # V2.21.0 工作台共用選項：丁店（飲料，甜度 全糖／半糖）加兩項加料，第二項停用
    from app.models.store import StoreTopping
    db.add_all([StoreTopping(store_id=ding.id, name="珍珠", price=10, sort_order=0, is_active=True),
                StoreTopping(store_id=ding.id, name="椰果", price=10, sort_order=1, is_active=False)]); db.commit()
    adm.get_admin_user = fake_admin
    pages["__workbench__"] = c.get(f"/admin/stores/{ding.id}?tab=options").text
    assert 'id="toppings-form"' in pages["__workbench__"], "工作台應有加料表單"
    db.close()
    return pages


def main():
    print("[前端] 匯入頁自動檢查（jsdom）")
    if not shutil.which("node"):
        print("  --  跳過（沒有 node）"); return
    env = dict(os.environ)
    if not env.get("NODE_PATH"):
        for cand in (ROOT / "node_modules", ROOT / "scripts" / "node_modules"):
            if cand.exists():
                env["NODE_PATH"] = str(cand); break
    probe = subprocess.run(["node", "-e", "require('jsdom');require.resolve('alpinejs/dist/cdn.min.js');require.resolve('htmx.org/dist/htmx.min.js')"], env=env, capture_output=True, text=True)
    if probe.returncode != 0:
        print("  --  跳過（沒有 jsdom / alpinejs / htmx.org；npm i jsdom@24 alpinejs@3 htmx.org@1.9.10 或設 NODE_PATH）"); return
    pages = _render_pages()
    problems = []
    with tempfile.TemporaryDirectory() as td:
        frag_path = Path(td) / "fragment.html"
        frag_path.write_text(pages.pop("__fragment__"), encoding="utf-8")
        sim_path = Path(td) / "similar.html"
        sim_path.write_text(pages.pop("__similar__"), encoding="utf-8")
        sort_pages = {"picker": pages.pop("__picker__"), "admin": pages.pop("__admin_stores__"), "catalog": pages.pop("__catalog__")}
        group_pages = {k: (pages.pop(f"__group_{k}__"), pages.pop(f"__group_{k}_mine__"), pages.pop(f"__group_{k}_wall__")) for k in ("member", "owner")}
        workbench_page = pages.pop("__workbench__")
        for mode, html in pages.items():
            p = Path(td) / f"import_{mode}.html"
            p.write_text(html, encoding="utf-8")
            r = subprocess.run(["node", str(NODE_SCRIPT), str(p), mode, str(frag_path), str(sim_path)], env=env, capture_output=True, text=True, timeout=60)
            line = (r.stdout.strip().splitlines() or [""])[-1]
            try:
                res = json.loads(line)
            except Exception:
                res = {"ok": False, "msg": (r.stdout + r.stderr)[-300:]}
            if res.get("ok"):
                print(f"  OK  {mode}：貼上自動檢查、清空不發、拖檔去 BOM、拖文字、拖圖片當對照、確認鈕會送、改內容後舊鈕失效{'、搜尋選店重查、帶入目前菜單、近似店名切換' if mode == 'nostore' else '、帶入鈕、單一指令鈕'}（{res.get('posts')} 次請求）")
            else:
                problems.append(f"{mode}：{res.get('msg')}")
                print(f"  !   {mode}：{res.get('msg')}")
        # V2.16.2：店家排序的實際順序（開團覆蓋層／後台列表）
        print("[前端] 店家排序（jsdom）")
        for mode, html in sort_pages.items():
            p = Path(td) / f"sort_{mode}.html"
            p.write_text(html, encoding="utf-8")
            r = subprocess.run(["node", str(SORT_SCRIPT), str(p), mode], env=env, capture_output=True, text=True, timeout=60)
            line = (r.stdout.strip().splitlines() or [""])[-1]
            try:
                res = json.loads(line)
            except Exception:
                res = {"ok": False, "msg": (r.stdout + r.stderr)[-300:]}
            if res.get("ok"):
                print(f"  OK  {mode}：預設熱門、三種排序順序正確、卡片小字、選擇有記住{'；隱藏欄位不送出、甜冰依店家、快捷標籤今天／明天' if mode == 'picker' else ''}{'；收藏區／只看收藏／分類／搜尋攤平' if mode == 'catalog' else ''}")
            else:
                problems.append(f"sort/{mode}：{res.get('msg')}")
                print(f"  !   sort/{mode}：{res.get('msg')}")
        # V2.18.0：團頁（結帳列／菜單收合／團主列／更多 sheet／催單文字）
        print("[前端] 團頁（jsdom）")
        for mode, (html, mine, wall) in group_pages.items():
            p = Path(td) / f"group_{mode}.html"; p.write_text(html, encoding="utf-8")
            pm = Path(td) / f"group_{mode}_mine.html"; pm.write_text(mine, encoding="utf-8")
            pw = Path(td) / f"group_{mode}_wall.html"; pw.write_text(wall, encoding="utf-8")
            r = subprocess.run(["node", str(GROUP_SCRIPT), str(p), mode, str(pm), str(pw)], env=env, capture_output=True, text=True, timeout=60)
            line = (r.stdout.strip().splitlines() or [""])[-1]
            try:
                res = json.loads(line)
            except Exception:
                res = {"ok": False, "msg": (r.stdout + r.stderr)[-300:]}
            if res.get("ok"):
                print(f"  OK  {mode}：" + ("結帳列讀到件數金額、查看並送出開 sheet、導覽列常點／熱門／骰子、送出後菜單收合與再加點、訂單牆跟單鈕" if mode == "member" else "團主列三顆、更多 sheet 切匯出、催單文字含截止、複製連結"))
            else:
                problems.append(f"group/{mode}：{res.get('msg')}")
                print(f"  !   group/{mode}：{res.get('msg')}")
        # V2.21.0：店家工作台共用選項（甜冰標籤、加料批次編輯、分頁切換）
        print("[前端] 店家工作台（jsdom）")
        p = Path(td) / "workbench.html"; p.write_text(workbench_page, encoding="utf-8")
        r = subprocess.run(["node", str(WORKBENCH_SCRIPT), str(p)], env=env, capture_output=True, text=True, timeout=60)
        line = (r.stdout.strip().splitlines() or [""])[-1]
        try:
            res = json.loads(line)
        except Exception:
            res = {"ok": False, "msg": (r.stdout + r.stderr)[-300:]}
        if res.get("ok"):
            print("  OK  甜冰標籤新增／排序／移除／預設組 → 送出值；加料改名／空白與重複擋下／新增／刪除可復原／排序 → toppings_json；刪除要確認；分頁切換與網址")
        else:
            problems.append(f"workbench：{res.get('msg')}")
            print(f"  !   workbench：{res.get('msg')}")
    for f in (ROOT / "_importcheck.db",):
        if f.exists():
            f.unlink()
    if problems:
        print(f"\n失敗 {len(problems)} 項"); sys.exit(1)
    print("\n全部通過")


if __name__ == "__main__":
    main()
