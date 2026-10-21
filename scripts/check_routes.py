import os, collections
os.environ.setdefault("DATABASE_URL", "sqlite:///./_check.db")
from app.main import app


def walk(routes, prefix=""):
    """攤平所有路由。

    V2.22.0：FastAPI 0.13x 起 include_router 不再把子路由攤平到 app.routes，
    而是包成一個 _IncludedRouter（original_router＋include_context.prefix）。
    原本只看 app.routes 的寫法在新版只數到 1 條，等於關掉重複路由檢查（Kit 坑 #81 假完成訊號），
    所以兩種形狀都要走。
    """
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            ctx = getattr(r, "include_context", None)
            yield from walk(inner.routes, prefix + (getattr(ctx, "prefix", "") or ""))
        elif hasattr(r, "methods") and r.methods:
            yield (tuple(sorted(r.methods - {"HEAD", "OPTIONS"})), prefix + r.path)


rs = list(walk(app.routes))
# 防線：數到的路由少得離譜代表攤平方式又變了，不能當通過
if len(rs) < 100:
    print(f"路由只數到 {len(rs)} 條，攤平方式可能又變了，請檢查 scripts/check_routes.py")
    raise SystemExit(1)
dups = [k for k, v in collections.Counter(rs).items() if v > 1]
if dups:
    for m, p in dups:
        print(f"重複路由：{'/'.join(m)} {p}")
    raise SystemExit(1)
print(f"路由檢查通過（共 {len(rs)} 條）")
