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
    for f in (ROOT / "_importcheck.db",):
        if f.exists():
            f.unlink()
    if problems:
        print(f"\n失敗 {len(problems)} 項"); sys.exit(1)
    print("\n全部通過")


if __name__ == "__main__":
    main()
