"""訂單核對單服務：產生漂亮的 PDF / PNG（給團主跟店家核對）

設計：
- 上半「店家總項」：彙總全部相同品項，店家只關心做幾份什麼
- 下半「每人明細」：團主對帳用，列出每個人點了什麼、各付多少
- 頂部放店家 logo + 店名 + 日期

技術：reportlab 內建 CID 中文字型（STSong-Light，零外部字型檔），
PNG 由 pypdfium2 將 PDF render 成圖（同源、清晰）。
"""
from io import BytesIO
from collections import defaultdict
from decimal import Decimal

from sqlalchemy.orm import Session

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

from app.models.group import Group
from app.models.order import Order, OrderStatus

# 主題色（#7528d4）
THEME = colors.HexColor("#7528D4")
THEME_LIGHT = colors.HexColor("#F4EEFC")
GRAY = colors.HexColor("#666666")
LIGHT_GRAY = colors.HexColor("#999999")

_FONT = "STSong-Light"
_font_registered = False


def _ensure_font():
    global _font_registered
    if not _font_registered:
        pdfmetrics.registerFont(UnicodeCIDFont(_FONT))
        _font_registered = True


def _store_display_name(group: Group) -> str:
    """店名（店家已刪用快照）"""
    if group.store is not None:
        return group.store.name
    return getattr(group, "store_name", None) or "（店家已移除）"


def _collect(db: Session, group: Group):
    """收集核對單資料：店家總項彙總 + 每人明細"""
    orders = db.query(Order).filter(
        Order.group_id == group.id,
        Order.status == OrderStatus.SUBMITTED,
    ).all()

    # 店家總項：彙總相同品項（品名+規格+選項+加料）
    summary = defaultdict(lambda: {"quantity": 0, "unit": Decimal("0")})
    # 每人明細
    people = []

    for order in sorted(orders, key=lambda o: o.user.show_name):
        person = {"name": order.user.show_name, "items": [], "total": order.total_amount}
        for item in order.items:
            parts = [item.item_name]
            if item.size:
                parts.append(f"({item.size})")
            if item.sugar:
                parts.append(item.sugar)
            if item.ice:
                parts.append(item.ice)
            for opt in item.selected_options:
                parts.append(opt.option_name)
            for top in item.selected_toppings:
                parts.append(f"+{top.topping_name}")
            if item.note:
                parts.append(f"註:{item.note}")
            key = " ".join(parts)

            summary[key]["quantity"] += item.quantity
            summary[key]["unit"] = item.unit_price + item.options_total + item.toppings_total

            person["items"].append({
                "desc": key,
                "qty": item.quantity,
                "subtotal": item.subtotal,
            })
        people.append(person)

    total_qty = sum(v["quantity"] for v in summary.values())
    total_amount = sum(v["quantity"] * v["unit"] for v in summary.values())

    return {
        "summary": sorted(summary.items()),
        "people": people,
        "total_qty": total_qty,
        "total_amount": total_amount,
        "people_count": len(people),
    }


def generate_receipt_pdf(db: Session, group: Group) -> BytesIO:
    """產生核對單 PDF"""
    _ensure_font()
    data = _collect(db, group)

    buf = BytesIO()
    W, H = A4
    c = canvas.Canvas(buf, pagesize=A4)

    margin = 18 * mm
    x = margin
    y = H - margin

    # ===== 頂部標題列（主題色底）=====
    header_h = 22 * mm
    c.setFillColor(THEME)
    c.rect(0, H - header_h, W, header_h, fill=1, stroke=0)

    # 店家 logo（若有，畫在左側白底圓角框）
    logo_drawn = False
    if group.store is not None and getattr(group.store, "logo_url", None):
        try:
            import urllib.request
            with urllib.request.urlopen(group.store.logo_url, timeout=5) as resp:
                logo_data = resp.read()
            # 縮圖避免大圖塞進 PDF（最長邊 200px）
            from PIL import Image
            pil_logo = Image.open(BytesIO(logo_data)).convert("RGBA")
            pil_logo.thumbnail((200, 200))
            logo_buf = BytesIO()
            pil_logo.save(logo_buf, format="PNG")
            logo_buf.seek(0)
            from reportlab.lib.utils import ImageReader
            logo_img = ImageReader(logo_buf)
            logo_size = 14 * mm
            c.setFillColor(colors.white)
            c.roundRect(margin, H - header_h + (header_h - logo_size) / 2,
                        logo_size, logo_size, 2 * mm, fill=1, stroke=0)
            c.drawImage(logo_img, margin + 1 * mm, H - header_h + (header_h - logo_size) / 2 + 1 * mm,
                        logo_size - 2 * mm, logo_size - 2 * mm, preserveAspectRatio=True, mask='auto')
            logo_drawn = True
        except Exception:
            logo_drawn = False

    text_x = margin + (18 * mm if logo_drawn else 0)
    c.setFillColor(colors.white)
    c.setFont(_FONT, 16)
    c.drawString(text_x, H - 12 * mm, _store_display_name(group))
    c.setFont(_FONT, 10)
    c.drawString(text_x, H - 18 * mm, f"訂單核對單　{group.deadline.strftime('%Y/%m/%d %H:%M')} 截止")

    y = H - header_h - 10 * mm

    # ===== 上半：店家總項 =====
    c.setFillColor(THEME)
    c.setFont(_FONT, 13)
    c.drawString(x, y, "■ 店家總項（請依此製作）")
    y -= 7 * mm

    # 表頭
    c.setFillColor(THEME_LIGHT)
    c.rect(x, y - 1 * mm, W - 2 * margin, 7 * mm, fill=1, stroke=0)
    c.setFillColor(GRAY)
    c.setFont(_FONT, 10)
    c.drawString(x + 2 * mm, y + 0.5 * mm, "品項")
    c.drawRightString(W - margin - 22 * mm, y + 0.5 * mm, "數量")
    c.drawRightString(W - margin - 2 * mm, y + 0.5 * mm, "小計")
    y -= 8 * mm

    c.setFont(_FONT, 10)
    for key, info in data["summary"]:
        if y < 40 * mm:
            c.showPage()
            _ensure_font()
            y = H - margin
        qty = info["quantity"]
        line_total = qty * info["unit"]
        c.setFillColor(colors.black)
        # 品項名（過長截斷）
        name = key if len(key) <= 32 else key[:31] + "…"
        c.drawString(x + 2 * mm, y, name)
        c.setFillColor(THEME)
        c.drawRightString(W - margin - 22 * mm, y, f"×{qty}")
        c.setFillColor(GRAY)
        c.drawRightString(W - margin - 2 * mm, y, f"${int(line_total)}")
        y -= 6 * mm
        # 分隔細線
        c.setStrokeColor(colors.HexColor("#EEEEEE"))
        c.setLineWidth(0.3)
        c.line(x, y + 2 * mm, W - margin, y + 2 * mm)

    # 總計列
    y -= 2 * mm
    c.setFillColor(THEME)
    c.rect(x, y - 1 * mm, W - 2 * margin, 8 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont(_FONT, 11)
    c.drawString(x + 2 * mm, y + 1 * mm, f"總計 {data['total_qty']} 份")
    c.drawRightString(W - margin - 2 * mm, y + 1 * mm, f"${int(data['total_amount'])}")
    y -= 14 * mm

    # ===== 下半：每人明細 =====
    if y < 50 * mm:
        c.showPage()
        _ensure_font()
        y = H - margin

    c.setFillColor(THEME)
    c.setFont(_FONT, 13)
    c.drawString(x, y, f"■ 每人明細（{data['people_count']} 人，團主對帳用）")
    y -= 8 * mm

    c.setFont(_FONT, 10)
    for person in data["people"]:
        if y < 30 * mm:
            c.showPage()
            _ensure_font()
            y = H - margin
        # 姓名 + 金額
        c.setFillColor(colors.black)
        c.setFont(_FONT, 11)
        c.drawString(x, y, f"● {person['name']}")
        c.setFillColor(THEME)
        c.drawRightString(W - margin - 2 * mm, y, f"${int(person['total'])}")
        y -= 6 * mm
        # 品項
        c.setFont(_FONT, 9)
        c.setFillColor(GRAY)
        for it in person["items"]:
            if y < 20 * mm:
                c.showPage()
                _ensure_font()
                y = H - margin
            desc = it["desc"]
            if len(desc) > 36:
                desc = desc[:35] + "…"
            qty_str = f" ×{it['qty']}" if it["qty"] > 1 else ""
            c.drawString(x + 5 * mm, y, f"{desc}{qty_str}")
            c.drawRightString(W - margin - 2 * mm, y, f"${int(it['subtotal'])}")
            y -= 5 * mm
        y -= 3 * mm

    # 頁尾
    c.setFillColor(LIGHT_GRAY)
    c.setFont(_FONT, 8)
    c.drawCentredString(W / 2, 10 * mm, f"SELA 快點來點餐　|　{group.name}")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf


def generate_receipt_png(db: Session, group: Group) -> BytesIO:
    """產生核對單 PNG（由 PDF render，零額外字型）"""
    pdf_buf = generate_receipt_pdf(db, group)
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(pdf_buf.getvalue())
    page = pdf[0]
    bitmap = page.render(scale=2.5)  # 2.5x 高解析，貼 LINE 清晰
    pil_image = bitmap.to_pil()
    out = BytesIO()
    pil_image.save(out, format="PNG")
    out.seek(0)
    return out
