# -*- coding: utf-8 -*-
"""V2.35.0：同名帳號標示。

同一個人用兩個 LINE 帳號登入過，系統會有兩個同名使用者；管理員在部門加人時只看名字，
很容易選到她沒在用的那個（Sela 2026-11-09 實際發生：先開部門限定團，再拉人進部門，她還是看不到）。
這裡算出「跟誰撞名」：暱稱或 LINE 名稱任一相同（不分全半形、大小寫、前後空白）就算。
"""
import unicodedata


def _key(name: str | None) -> str:
    return unicodedata.normalize("NFKC", name or "").strip().casefold()


def dup_name_counts(users) -> dict[int, int]:
    """回傳 {user_id: 同名帳號數}，只列 ≥ 2 的。users 給全部（非訪客）使用者。"""
    groups: dict[str, set[int]] = {}
    for u in users:
        for k in {_key(u.show_name), _key(u.display_name)}:
            if k:
                groups.setdefault(k, set()).add(u.id)
    out: dict[int, int] = {}
    for ids in groups.values():
        if len(ids) > 1:
            for i in ids:
                out[i] = max(out.get(i, 0), len(ids))
    return out
