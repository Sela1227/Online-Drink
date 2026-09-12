import os, collections
os.environ.setdefault("DATABASE_URL", "sqlite:///./_check.db")
from app.main import app

rs = [(tuple(sorted(r.methods - {"HEAD", "OPTIONS"})), r.path)
      for r in app.routes if hasattr(r, "methods")]
dups = [k for k, v in collections.Counter(rs).items() if v > 1]
if dups:
    for m, p in dups:
        print(f"重複路由：{'/'.join(m)} {p}")
    raise SystemExit(1)
print(f"路由檢查通過（共 {len(rs)} 條）")
