"""V2.26.0：店家縣市。

- 店家 `stores.city`：22 縣市之一，或「不分縣市」（宅配／團購，永遠顯示）；NULL＝還沒設（也永遠顯示）。
- 使用者 `users.cities`：JSON 陣列，勾了哪些縣市；空＝全部顯示。
- 店家縣市預設從地址開頭判斷（「彰化縣鹿港鎮…」「臺中市…」「505 彰化縣…」都認得），可在工作台改。
"""
import json
import re
import unicodedata

CITY_GROUPS = [
    ("北部", ["台北市", "新北市", "桃園市", "新竹市", "新竹縣", "基隆市", "宜蘭縣"]),
    ("中部", ["苗栗縣", "台中市", "彰化縣", "南投縣", "雲林縣"]),
    ("南部", ["嘉義市", "嘉義縣", "台南市", "高雄市", "屏東縣"]),
    ("東部與離島", ["花蓮縣", "台東縣", "澎湖縣", "金門縣", "連江縣"]),
]
ALL_CITIES = [c for _, cs in CITY_GROUPS for c in cs]
NO_CITY = "不分縣市"

# 改制前的舊名 → 現名
_OLD_NAMES = {"台北縣": "新北市", "台中縣": "台中市", "台南縣": "台南市", "高雄縣": "高雄市", "桃園縣": "桃園市"}
_NO_CITY_WORDS = {"不分縣市", "不分", "全台", "全國", "全台灣", "宅配", "網購"}


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", str(s or "")).replace("臺", "台").strip()


def normalize_city(v) -> str | None:
    """各種寫法 → 標準縣市名／NO_CITY；認不得回 None"""
    t = _norm(v).replace(" ", "")
    if not t:
        return None
    if t in _NO_CITY_WORDS:
        return NO_CITY
    if t in ALL_CITIES:
        return t
    if t in _OLD_NAMES:
        return _OLD_NAMES[t]
    hits = [c for c in ALL_CITIES if c[:2] == t[:2] and len(t) == 2]  # 「彰化」「台中」；「新竹」「嘉義」有市有縣，不猜
    return hits[0] if len(hits) == 1 else None


def city_from_address(addr) -> str | None:
    """地址開頭 → 縣市；判斷不出來回 None"""
    t = _norm(addr).replace(" ", "")
    t = re.sub(r"^\d{3,6}", "", t)  # 郵遞區號
    for prefix in ("中華民國", "台灣省", "台灣"):
        if t.startswith(prefix):
            t = t[len(prefix):]
    t = re.sub(r"^\d{3,6}", "", t)
    for c in ALL_CITIES:
        if t.startswith(c):
            return c
    for old, new in _OLD_NAMES.items():
        if t.startswith(old):
            return new
    return None


def parse_user_cities(raw) -> list[str]:
    """users.cities（JSON 文字）→ 標準縣市清單；壞資料當沒設"""
    if not raw:
        return []
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return []
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        c = normalize_city(x)
        if c and c != NO_CITY and c not in out:
            out.append(c)
    return out


def store_visible_in(city: str | None, user_cities: list[str]) -> bool:
    """沒勾縣市＝全部；店家沒設縣市或「不分縣市」永遠顯示"""
    return (not user_cities) or (not city) or city == NO_CITY or city in user_cities
