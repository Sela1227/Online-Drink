# -*- coding: utf-8 -*-
"""頁面載入後的提示（toast）是否真的會顯示 —— V2.11.4 S-01

為什麼需要這支：後端煙霧測試、Jinja parse、`node --check` 全部看不見
「頁面載入時就要顯示的訊息，到底有沒有出現在畫面上」。V2.11.3 的 toast
在兩個情境（複製結果、表單錯誤）下永遠不會顯示，三支既有檢查全綠。

做法：用假 context 渲染 base.html 的最小子模板，載入 jsdom，把 Alpine 放在
body 最後執行（等同正式環境 defer：先跑完頁面內所有 inline script 再初始化），
再讀 toast 元件的文字。

跑法：
    PYTHONPATH=. python scripts/check_frontend_toast.py
需要 node 與 node_modules 裡的 jsdom、alpinejs；任一缺少就跳過（不視為失敗）。
安裝：在專案根目錄或 scripts/ 執行 `npm i jsdom@24 alpinejs@3`（會產生 node_modules，
打包前記得清掉）。也可設環境變數 NODE_PATH 指向已有的 node_modules。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app" / "templates"
NODE_SCRIPT = ROOT / "scripts" / "jsdom_toast_check.js"

os.environ.setdefault("DATABASE_URL", "sqlite:///./_tplcheck.db")
os.environ.setdefault("SECRET_KEY", "template_check_only")
sys.path.insert(0, str(ROOT))


class Stub:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        return None

    def __iter__(self):
        return iter([])

    def __len__(self):
        return 0


def _render(block_html: str, path: str) -> str:
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)))
    env.filters["taipei"] = lambda d: d
    tpl = env.from_string('{% extends "base.html" %}{% block content %}' + block_html + '{% endblock %}')
    return tpl.render(
        request=Stub(url=Stub(path=path), scope={}),
        user=Stub(id=1, is_admin=False, show_name="測試", display_name="測試"),
        app_version="check",
    )


# 與 group.html 中複製結果 IIFE 相同的邏輯（只測機制，不測 group.html 的完整 context）
COPIED_SCRIPT = """<script>
(function () {
    var q = new URLSearchParams(window.location.search);
    if (!q.has('copied')) return;
    var c = parseInt(q.get('copied') || '0', 10), k = parseInt(q.get('skipped') || '0', 10);
    var m = c > 0 ? ('已複製 ' + c + ' 項') : '沒有可複製的品項';
    if (k > 0) m += '，' + k + ' 項無法複製';
    if (window.toast) { window.toast(m, c > 0 ? 'ok' : 'error'); }
})();
</script><p>x</p>"""

CASES = [
    # (名稱, 內容區塊, 網址, 期望文字, 是否在 head 預先寫 sessionStorage)
    ("頁面內 script 呼叫 toast（複製結果）", COPIED_SCRIPT,
     "http://localhost/groups/1?copied=2&skipped=1", "已複製 2 項，1 項無法複製", None),
    ("表單錯誤經 sessionStorage 返回（flash）", "<p>x</p>",
     "http://localhost/home", "測試錯誤訊息", "測試錯誤訊息"),
]


def static_checks() -> list[str]:
    """不需要 node 的靜態斷言（審核建議的最低限度）"""
    problems = []
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    if "window.toast = function" not in base:
        problems.append("base.html 找不到 window.toast 定義")
    elif base.index("window.toast = function") > base.index("<main class"):
        problems.append("window.toast 必須在 <main> 之前定義，否則頁面內的 script 呼叫不到（S-01）")
    if "@apptoast.window" in base and "_toastShow" not in base:
        problems.append("不可只依賴 @apptoast.window 接收載入時的訊息：x-init 先於 x-on（S-01）")
    if "_toastShow" not in base:
        problems.append("toast 元件應提供 window._toastShow 並倒出佇列（S-01）")
    return problems


def main():
    print("[1] 靜態檢查")
    problems = static_checks()
    for p in problems:
        print("  !", p)
    if not problems:
        print("  OK  window.toast 在 <main> 之前、元件提供 _toastShow")

    print("\n[2] jsdom 實際渲染")
    if not shutil.which("node"):
        print("  --  跳過（沒有 node）")
        return _finish(problems)
    probe = subprocess.run(
        ["node", "-e", "require.resolve('jsdom');require.resolve('alpinejs/dist/cdn.js')"],
        capture_output=True, text=True,
    )
    if probe.returncode != 0:
        print("  --  跳過（沒有 jsdom / alpinejs；npm i jsdom@24 alpinejs@3 或設 NODE_PATH）")
        return _finish(problems)

    for name, block, url, expected, preset_flash in CASES:
        html = _render(block, url)
        if preset_flash:
            html = html.replace(
                "<head>",
                "<head><script>try{sessionStorage.setItem('flash',%s)}catch(e){}</script>"
                % json.dumps(preset_flash, ensure_ascii=False),
                1,
            )
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as fh:
            fh.write(html)
            tmp = fh.name
        try:
            r = subprocess.run(
                ["node", str(NODE_SCRIPT), tmp, expected, url],
                capture_output=True, text=True,
            )
            last = (r.stdout.strip().split("\n") or [""])[-1]
            try:
                result = json.loads(last)
            except json.JSONDecodeError:
                result = {"ok": False, "text": last}
            if result.get("ok"):
                print(f"  OK  {name} → 「{result.get('text')}」")
            else:
                problems.append(f"{name}：期望「{expected}」，實得「{result.get('text')}」")
                print(f"  !   {name}：期望「{expected}」，實得「{result.get('text')}」")
        finally:
            os.unlink(tmp)

    return _finish(problems)


def _finish(problems):
    if problems:
        print("\n失敗 %d 項" % len(problems))
        raise SystemExit(1)
    print("\n全部通過")


if __name__ == "__main__":
    main()
