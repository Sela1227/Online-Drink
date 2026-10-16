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
        sort_pages = {"picker": pages.pop("__picker__"), "admin": pages.pop("__admin_stores__")}
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
                print(f"  OK  {mode}：預設熱門、三種排序順序正確、卡片小字、選擇有記住{'；隱藏欄位不送出、甜冰依店家、快捷標籤今天／明天' if mode == 'picker' else ''}")
            else:
                problems.append(f"sort/{mode}：{res.get('msg')}")
                print(f"  !   sort/{mode}：{res.get('msg')}")
    for f in (ROOT / "_importcheck.db",):
        if f.exists():
            f.unlink()
    if problems:
        print(f"\n失敗 {len(problems)} 項"); sys.exit(1)
    print("\n全部通過")


if __name__ == "__main__":
    main()
