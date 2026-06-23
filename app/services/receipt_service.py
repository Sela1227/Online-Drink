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
from reportlab.pdfbase.ttfonts import TTFont

import os

from app.models.group import Group
from app.models.order import Order, OrderStatus

# 主題色（#653985 北歐低彩度紫）
THEME = colors.HexColor("#653985")
THEME_LIGHT = colors.HexColor("#EBE7EE")
GRAY = colors.HexColor("#666666")
LIGHT_GRAY = colors.HexColor("#999999")
ZEBRA = colors.HexColor("#ECE5F2")  # 一人一色區底色（比原 F2EEF5 略深，核對更清楚）

_FONT = "CJKFont"
_FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "fonts", "cjk-font.ttf")
_font_registered = False


def _ensure_font():
    global _font_registered
    if not _font_registered:
        pdfmetrics.registerFont(TTFont(_FONT, _FONT_PATH))
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
    header_h = 36 * mm
    c.setFillColor(THEME)
    c.rect(0, H - header_h, W, header_h, fill=1, stroke=0)

    # 店家 logo（若有，畫在左側白底圓角框）
    logo_drawn = False
    if group.store is not None and getattr(group.store, "logo_url", None):
        try:
            import urllib.request
            with urllib.request.urlopen(group.store.logo_url, timeout=5) as resp:
                logo_data = resp.read()
            # 縮圖避免大圖塞進 PDF（最長邊 400px，logo 放大後解析度要夠）
            from PIL import Image
            pil_logo = Image.open(BytesIO(logo_data)).convert("RGBA")
            pil_logo.thumbnail((400, 400))
            logo_buf = BytesIO()
            pil_logo.save(logo_buf, format="PNG")
            logo_buf.seek(0)
            from reportlab.lib.utils import ImageReader
            logo_img = ImageReader(logo_buf)
            logo_size = 30 * mm
            c.setFillColor(colors.white)
            c.roundRect(margin, H - header_h + (header_h - logo_size) / 2,
                        logo_size, logo_size, 3 * mm, fill=1, stroke=0)
            c.drawImage(logo_img, margin + 2 * mm, H - header_h + (header_h - logo_size) / 2 + 2 * mm,
                        logo_size - 4 * mm, logo_size - 4 * mm, preserveAspectRatio=True, mask='auto')
            logo_drawn = True
        except Exception:
            logo_drawn = False

    text_x = margin + (36 * mm if logo_drawn else 0)
    c.setFillColor(colors.white)
    c.setFont(_FONT, 18)
    c.drawString(text_x, H - 16 * mm, _store_display_name(group))
    c.setFont(_FONT, 10)
    c.drawString(text_x, H - 23 * mm, f"訂單核對單　{group.deadline.strftime('%Y/%m/%d %H:%M')} 截止")

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
    row_idx = 0
    for key, info in data["summary"]:
        if y < 40 * mm:
            c.showPage()
            _ensure_font()
            y = H - margin
        qty = info["quantity"]
        line_total = qty * info["unit"]
        row_h = 7 * mm
        # 斑馬紋：奇數列淺底
        if row_idx % 2 == 1:
            c.setFillColor(ZEBRA)
            c.rect(x, y - 2 * mm, W - 2 * margin, row_h, fill=1, stroke=0)
        c.setFillColor(colors.black)
        name = key if len(key) <= 32 else key[:31] + "…"
        c.drawString(x + 2 * mm, y, name)
        c.setFillColor(THEME)
        c.drawRightString(W - margin - 22 * mm, y, f"×{qty}")
        c.setFillColor(GRAY)
        c.drawRightString(W - margin - 2 * mm, y, f"${int(line_total)}")
        y -= row_h
        row_idx += 1

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
    person_idx = 0
    for person in data["people"]:
        # 先算這個人區塊需要的高度（姓名列 + 各品項列 + 上下內距）
        name_h = 7 * mm
        items_h = len(person["items"]) * 5 * mm
        block_h = name_h + items_h + 2 * mm
        # 換頁判斷（整塊放不下就換頁）
        if y - block_h < 18 * mm:
            c.showPage()
            _ensure_font()
            y = H - margin

        block_top = y + 4 * mm  # 區塊頂緣（姓名列上方留白）
        # 一人一色區塊：隔人交替底色（先畫底，內容畫在上面）
        if person_idx % 2 == 1:
            c.setFillColor(ZEBRA)
            c.rect(x - 3 * mm, block_top - block_h, W - 2 * margin + 6 * mm, block_h, fill=1, stroke=0)

        # 姓名 + 金額
        c.setFillColor(colors.black)
        c.setFont(_FONT, 11)
        c.drawString(x, y, f"● {person['name']}")
        c.setFillColor(THEME)
        c.drawRightString(W - margin - 2 * mm, y, f"${int(person['total'])}")
        y -= 6 * mm
        # 品項
        c.setFont(_FONT, 9)
        for it in person["items"]:
            c.setFillColor(GRAY)
            desc = it["desc"]
            if len(desc) > 36:
                desc = desc[:35] + "…"
            qty_str = f" ×{it['qty']}" if it["qty"] > 1 else ""
            c.drawString(x + 5 * mm, y, f"{desc}{qty_str}")
            c.drawRightString(W - margin - 2 * mm, y, f"${int(it['subtotal'])}")
            y -= 5 * mm
        y -= 4 * mm
        person_idx += 1

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
