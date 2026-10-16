"""店名近似比對（V2.16.1 B-8）

「新增一家店」時店名跟既有店很像（「可不可 熟成紅茶（彰化店）」vs「可不可熟成紅茶」），
提醒管理員可能是同一家、一鍵改成更新那家店。只提醒不擋。

規則：正規化後相同、一邊包含另一邊、或 SequenceMatcher 相似度 ≥ SIMILAR_RATIO。
正規化：NFKC（全形→半形）、去空白、去括號內容、去「總店／分店／門市／店」字尾、小寫。
"""
import re
import unicodedata
from difflib import SequenceMatcher

SIMILAR_RATIO = 0.8
MAX_HITS = 3

_BRACKETS = re.compile(r"[（(\[【][^）)\]】]*[）)\]】]")
_SUFFIX = re.compile(r"(總店|分店|門市|旗艦店|店)$")


def normalize_store_name(name: str) -> str:
    s = unicodedata.normalize("NFKC", name or "")
    s = _BRACKETS.sub("", s)
    s = re.sub(r"\s+", "", s)
    s = _SUFFIX.sub("", s)
    return s.lower()


def similarity(a: str, b: str) -> float:
    na, nb = normalize_store_name(a), normalize_store_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return max(SIMILAR_RATIO, SequenceMatcher(None, na, nb).ratio())
    return SequenceMatcher(None, na, nb).ratio()


def similar_stores(name: str, stores, exclude_exact: bool = True) -> list:
    """stores：有 .name 的物件序列。回傳相似度由高到低的 (store, ratio)，最多 MAX_HITS 筆。"""
    hits = []
    for s in stores:
        if exclude_exact and (s.name or "").strip() == (name or "").strip():
            continue
        r = similarity(name, s.name or "")
        if r >= SIMILAR_RATIO:
            hits.append((s, r))
    hits.sort(key=lambda t: -t[1])
    return hits[:MAX_HITS]
