# -*- coding: utf-8 -*-
"""使用者輸入的清理與驗證 — 單一來源（V2.11.1）。

放在這裡而不是各路由各自寫，是因為同一種欄位散在多支路由（網址就有五個欄位、
三支路由），任何一處漏掉就等於沒做。
"""
import re
from urllib.parse import urlparse

from fastapi import HTTPException

# 看起來像「網域開頭」的字串：example.com、maps.app.goo.gl/abc、a.co:8080/x
_DOMAIN_START = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}(?::\d+)?(?:[/?#]|$)")


def clean_http_url(value: str | None, max_len: int = 500, *, field: str = "網址") -> str | None:
    """只允許 http/https 的網址，其餘一律擋下（V2.11.1 P0-06）。

    未驗證協定時，使用者可以送出 `javascript:alert(document.cookie)`，
    它會被原樣輸出成 `href`：推薦的菜單網址會出現在後台的推薦列表與匯入頁，
    核准後又會被複製到 `store.website_url`，於是出現在所有人都看得到的
    團單頁與店家頁。這是儲存型 XSS，不是顯示問題，Jinja 的自動逸出擋不住
    ——它逸出的是內容，不是協定。
    """
    v = (value or "").strip()
    if not v:
        return None
    # V2.11.2 N-06：舊資料常見「maps.app.goo.gl/abc」這種沒有協定的網址。
    # 一律擋下的代價是：管理員只想改電話，整頁存不了，而且訊息不說是哪個欄位，
    # 等於這家店的任何欄位都改不了。看起來像網域的就自動補 https://，
    # 但危險協定（javascript: / data: / vbscript:）絕不補，維持擋下。
    # V2.11.3 R-08：原本「沒有 :// 就補 https://」太寬，`tel:0412345678` 會變成
    # `https://tel:0412345678` 這種壞掉的連結存進資料庫。改成只有「看起來像網域開頭」
    # 才補，其餘直接回 400 讓使用者改正。
    if "://" not in v:
        if _DOMAIN_START.match(v):
            v = "https://" + v
        else:
            raise HTTPException(status_code=400, detail=f"{field}格式不正確")
    parsed = urlparse(v)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail=f"{field}需以 http:// 或 https:// 開頭")
    return v[:max_len]


def clean_text(value: str | None, max_len: int, *, field: str = "欄位",
               required: bool = False) -> str | None:
    """去頭尾空白並限制長度，超過就回 400 而不是讓 PostgreSQL 丟 500。

    SQLite 對超長字串照收，PostgreSQL 會直接報錯，所以本機測不出來。
    """
    v = (value or "").strip()
    if not v:
        if required:
            raise HTTPException(status_code=400, detail=f"{field}不可空白")
        return None
    if len(v) > max_len:
        raise HTTPException(status_code=400, detail=f"{field}最多 {max_len} 字")
    return v


def parse_department_ids(raw_ids, db) -> list[int]:
    """表單送來的部門編號 → 驗證過的 id 清單（V2.11.3 R-07）。

    原本各處寫 `int(dept_id)`，非數字會拋 ValueError → 500；後來補的
    `lstrip("-").isdigit()` 又讓 `-3` 通過，外鍵檢查時照樣 500；
    不存在或已停用的編號也一律放行。這裡一次處理格式、存在性與啟用狀態。
    """
    from app.models.department import Department

    ids = []
    for raw in (raw_ids or []):
        text = str(raw).strip()
        if not text.isdigit():
            raise HTTPException(status_code=400, detail="部門編號格式錯誤")
        ids.append(int(text))
    if not ids:
        return []
    ids = list(dict.fromkeys(ids))
    alive = {
        row[0] for row in db.query(Department.id).filter(
            Department.id.in_(ids), Department.is_active == True
        ).all()
    }
    if set(ids) - alive:
        raise HTTPException(status_code=400, detail="部門不存在或已停用")
    return ids


def parse_store_ids(raw_ids, db) -> list[int]:
    """表單送來的店家編號 → 驗證過的 id 清單（V2.11.4 S-05）。

    與 parse_department_ids 同一套規則：格式、存在性、啟用狀態；另外排除個人代購店
    （它們不該出現在投票選項裡）。負數或不存在的編號原本會在外鍵檢查時 500。
    """
    from app.models.store import Store

    ids = []
    for raw in (raw_ids or []):
        text = str(raw).strip()
        if not text.isdigit():
            raise HTTPException(status_code=400, detail="店家編號格式錯誤")
        ids.append(int(text))
    if not ids:
        return []
    ids = list(dict.fromkeys(ids))
    alive = {
        row[0] for row in db.query(Store.id).filter(
            Store.id.in_(ids),
            Store.is_active == True,
            Store.is_personal != True,
        ).all()
    }
    if set(ids) - alive:
        raise HTTPException(status_code=400, detail="店家不存在、已停用或不可作為投票選項")
    return ids
