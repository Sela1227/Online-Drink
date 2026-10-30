# -*- coding: utf-8 -*-
"""模板共用 filter（V2.15.1）。

本專案每個 router 各自建立 Jinja2Templates 實例（坑 #6 的歷史包袱），所以 filter 要
每個實例都掛。這裡集中定義，各 router 只要 `register_filters(templates.env)`。
"""
from datetime import timezone, timedelta
from decimal import Decimal, InvalidOperation


def to_taipei_time(dt):
    if dt is None:
        return None
    taipei_tz = timezone(timedelta(hours=8))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(taipei_tz)


def money(v) -> str:
    """金額顯示：Numeric(10,2) 讀回來是 Decimal('55.00')，直接輸出會變 $55.00；
    `|int` 又會把 32.5 截成 32。整數顯示整數，有小數才顯示小數，千分位。"""
    if v is None or v == "":
        return ""
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return str(v)
    if not d.is_finite():
        return str(v)
    if d == d.to_integral_value():
        return f"{int(d):,}"
    s = f"{d.normalize():f}"
    whole, _, frac = s.partition(".")
    neg = whole.startswith("-")
    whole = f"{int(whole):,}" if not neg else "-" + f"{int(whole[1:]):,}"
    return f"{whole}.{frac}" if frac else whole


def register_filters(env):
    env.filters["taipei"] = to_taipei_time
    env.filters["money"] = money
    # V2.26.0：版本號（base.html「我的」頁最下面），唯一來源 app/version.py
    from app.version import APP_VERSION
    env.globals["app_version"] = APP_VERSION
