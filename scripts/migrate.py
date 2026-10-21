"""單獨跑資料庫遷移（V2.23.0，審核 P1-8）

    PYTHONPATH=. python scripts/migrate.py

用 DATABASE_URL 連線（Railway 上就是正式資料庫）。可重複執行：已經是最新的就只做檢查。
退出碼：0＝沒有錯誤（警告不算，例如重複訂單建不起唯一索引——那要人來決定怎麼合併）；1＝有錯誤。
App 啟動時也會自動跑同一份（app/main.py lifespan），這支是給部署前手動跑或排查用的。
"""
import sys

from app.database import engine
from app.migrations import run_migrations

if __name__ == "__main__":
    result = run_migrations(engine)
    sys.exit(1 if result.errors else 0)
