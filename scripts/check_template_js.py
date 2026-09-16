# -*- coding: utf-8 -*-
"""模板內 JavaScript 的檢查 — 抓 py_compile 與 Jinja parse 都看不見的一類問題。

跑法：
    PYTHONPATH=. python scripts/check_template_js.py

兩道檢查：

【一】插值逸出（全部模板，零容忍）
    `name: "{{ item.name }}"` 這種寫法只靠外層引號包住插值。只要那個值含有
    雙引號（品項名、店名都是使用者/匯入來的），整段 <script> 就語法錯誤，
    該頁的 Alpine 全部失效——而且畫面上不會有錯誤訊息，只是按了沒反應。
    規則：**<script> 內的插值一律過 `| tojson`**，由 Jinja 負責逸出，
    連 enum 這種「現在很安全」的也要，否則下次有人照抄旁邊那行就破功。

【二】渲染後語法檢查（需要 node，沒有就跳過）
    用假資料把模板渲染成 HTML，抽出指定的函式再 `node --check`。
    只涵蓋 RENDER_TARGETS 裡登記的模板——要加新的就得附一組假 context，
    這部分有維護成本，是刻意的取捨：檢查一涵蓋不到的東西才交給它。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app" / "templates"

os.environ.setdefault("DATABASE_URL", "sqlite:///./_tplcheck.db")
os.environ.setdefault("SECRET_KEY", "template_check_only")
sys.path.insert(0, str(ROOT))

SCRIPT_BLOCK = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S | re.I)
QUOTED_INTERP = re.compile(r"""["']\{\{\s*(.+?)\s*\}\}["']""")

failures = []


def check_escaping():
    """【一】<script> 內被引號包住的插值，必須經過 tojson"""
    hits = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        for block in SCRIPT_BLOCK.finditer(text):
            base = text[: block.start()].count("\n")
            body = block.group(1)
            for m in QUOTED_INTERP.finditer(body):
                if "tojson" in m.group(1):
                    continue
                ln = base + body[: m.start()].count("\n")
                rel = path.relative_to(ROOT)
                hits.append(f"{rel}:{ln + 1}: {lines[ln].strip()[:100]}")
    if hits:
        failures.append("插值未經 tojson（共 %d 處）" % len(hits))
        for h in hits:
            print("  !", h)
    else:
        print("  OK  <script> 內的插值全部經過 tojson")


# ---- 【二】渲染目標：模板 → (假 context, 要抽出來檢查的函式名) ----

class Stub:
    """假物件：沒設定到的屬性一律回 None。

    StrictUndefined 是用來守「context 變數沒傳」（P0-02 那一類），
    不是用來守「假資料少寫一個欄位」—— 後者只會逼人不斷補 stub，
    對真實缺陷沒有偵測力。所以物件屬性走寬鬆、頂層 context 走嚴格。
    """

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return None


def _ctx_group_new():
    class FakeStore(Stub):
        def __init__(self, i, name, cat, logo=None, branches=None, toppings=False):
            self.id = i
            self.name = name
            self.logo_url = logo
            self.toppings = toppings
            self.branches = branches or []
            self.category = type("C", (), {"value": cat})()

    stores = [
        # 刻意放引號與反斜線，驗證逸出真的有效
        FakeStore(1, '春水堂 "測試" \\ 分店', "drink", None,
                  [{"id": 1, "name": "彰化店", "phone": "04-000"}]),
        FakeStore(2, "迷客夏", "drink", "https://example/logo.png"),
        FakeStore(3, "八方雲集", "meal"),
    ]
    return {
        "request": Stub(url=Stub(path="/groups/new"), scope={}),
        "user": Stub(id=1, is_admin=False, show_name="測試", display_name="測試"),
        "stores": stores,
        "departments": [],
        "my_templates": [],
        "preselect_store_id": None,
        "favorite_store_ids": [2],
        "group_counts": {1: 47, 2: 39, 3: 52},
        "copy_from": None,
    }


def _ctx_group_new_copy():
    """複製開團（V2.11.1 P0-02）：與開新團同一個模板、不同路由。

    V2.11.0 只在 new_group_page 補了 group_counts / favorite_store_ids，
    copy_group_page 沒補 → 複製開團直接 500。這裡把兩條路徑都渲染一次，
    加上底下的 StrictUndefined，模板日後新增變數時會立刻在這裡爆掉。
    """
    ctx = _ctx_group_new()
    ctx["copy_from"] = Stub(
        category=type("C", (), {"value": "drink"})(),
        store_id=1, name="舊團", is_public=True,
    )
    ctx["preselect_store_id"] = 1
    return ctx


RENDER_TARGETS = [
    ("group_new.html", _ctx_group_new, "newGroupForm"),
    ("group_new.html", _ctx_group_new_copy, "newGroupForm"),
]


def check_rendered_js():
    if not shutil.which("node"):
        print("  --  跳過（環境沒有 node）")
        return
    from jinja2 import Environment, FileSystemLoader

    # StrictUndefined：未傳進來的變數立刻爆炸，而不是安靜地渲染成空字串。
    # P0-02 就是「模板用了某個 context 沒給的變數」，正式環境的預設 Undefined
    # 對 `.get()` 才會拋錯，對 `{% if x %}` 則靜靜當成 False —— 抓不到。
    from jinja2 import StrictUndefined
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), undefined=StrictUndefined)
    env.filters["taipei"] = lambda d: d

    for name, ctx_fn, func_name in RENDER_TARGETS:
        try:
            html = env.get_template(name).render(**ctx_fn())
        except Exception as e:
            failures.append(f"{name} 渲染失敗")
            print(f"  !  {name} 渲染失敗：{type(e).__name__}: {e}")
            continue

        m = re.search(r"function %s\(\)\s*\{.*?\n\}" % re.escape(func_name), html, re.S)
        if not m:
            failures.append(f"{name} 找不到 {func_name}()")
            print(f"  !  {name} 找不到 {func_name}()（改名了就更新 RENDER_TARGETS）")
            continue

        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
            fh.write(m.group(0))
            tmp = fh.name
        try:
            r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
            if r.returncode != 0:
                failures.append(f"{name}::{func_name}() 語法錯誤")
                print(f"  !  {name}::{func_name}() 語法錯誤：")
                print("     " + (r.stderr.strip().split("\n")[0] if r.stderr else ""))
            else:
                print(f"  OK  {name}::{func_name}() 渲染後語法正確")
        finally:
            os.unlink(tmp)


def main():
    print("[1] <script> 插值逸出")
    check_escaping()
    print("\n[2] 渲染後 JS 語法")
    check_rendered_js()

    if failures:
        print("\n失敗 %d 項：" % len(failures))
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print("\n全部通過")


if __name__ == "__main__":
    main()
