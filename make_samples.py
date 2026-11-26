"""make_samples.py - builds 10 fictional UK invoices and receipts plus ground_truth.json.

All businesses, people, addresses and VAT numbers are made up for this lab.
Usage:  python3 make_samples.py            (writes ./samples/ and ./ground_truth.json)
Needs:  reportlab (PDFs) and Pillow (PNG/JPG).
"""
import json
import random
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path("samples")
P = lambda s: Decimal(s)                      # money from strings, never floats
R = lambda d: d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

# ---------------------------------------------------------------- the 10 documents
# prices_include_vat=False: line amounts are net (invoices). True: amounts include VAT (till receipts).
# vat_override: the VAT figure printed on the document when the supplier made a mistake.
DOCS = [
    dict(file="01_harbour_lane_invoice.pdf", doc_type="invoice", supplier_name="Harbour Lane Stationery Ltd",
         supplier_vat_number="GB 482 7731 09", invoice_number="HLS-10432", invoice_date="2026-09-02",
         due_date="2026-10-02", printed_dates=("02/09/2026", "02/10/2026"), prices_include_vat=False,
         lines=[("A4 copier paper, 80gsm (box of 5 reams)", "4", "21.50", 20),
                ("Black gel pens (pack of 12)", "6", "4.75", 20),
                ("Lever arch files, assorted", "10", "2.10", 20)]),
    dict(file="02_brightwell_energy_invoice.pdf", doc_type="invoice", supplier_name="Brightwell Home Energy Ltd",
         supplier_vat_number="GB 731 2290 44", invoice_number="BHE-2026-0877", invoice_date="2026-08-14",
         due_date="2026-09-13", printed_dates=("14 August 2026", "13 September 2026"), prices_include_vat=False,
         lines=[("Heating oil delivery, 900 litres (domestic)", "900", "0.62", 5),
                ("Tank level sensor (domestic)", "1", "38.00", 5),
                ("Boiler service call-out", "1", "95.00", 20)]),
    dict(file="03_kestrel_print_invoice.pdf", doc_type="invoice", supplier_name="Kestrel Print Co.",
         supplier_vat_number="GB 655 0182 37", invoice_number="KP-5519", invoice_date="2026-07-21",
         due_date="2026-08-20", printed_dates=("21/07/2026", "20/08/2026"), prices_include_vat=False,
         lines=[("Business cards, 400gsm matt (500)", "2", "34.00", 20),
                ("A5 flyers, double-sided (1000)", "1", "79.00", 20),
                ("Loyalty discount", "1", "-10.00", 20),
                ("Courier delivery", "1", "6.50", 20)]),
    dict(file="04_morrow_joinery_invoice.pdf", doc_type="invoice", supplier_name="Morrow & Daughters Joinery Ltd",
         supplier_vat_number="GB 219 8804 61", invoice_number="MDJ/0315", invoice_date="2026-08-03",
         due_date="2026-09-02", printed_dates=("03/08/2026", "02/09/2026"), prices_include_vat=False,
         lines=[("Fitted oak shelving, reception (labour, 2 days)", "2", "280.00", 20),
                ("Oak boards and fixings", "1", "214.60", 20)]),
    dict(file="05_northgate_it_invoice.pdf", doc_type="invoice", supplier_name="Northgate IT Supplies Ltd",
         supplier_vat_number="GB 388 4410 72", invoice_number="NIT-77120", invoice_date="2026-09-18",
         due_date="2026-10-18", printed_dates=("18/09/2026", "18/10/2026"), prices_include_vat=False,
         vat_override="72.90",   # supplier typo: correct 20% VAT is 82.90
         lines=[("USB-C docking station", "2", "64.99", 20),
                ("27-inch monitor", "1", "139.00", 20),
                ("Wireless keyboard and mouse set", "3", "18.50", 20),
                ("HDMI cable, 2 m", "4", "3.25", 20),
                ("Laptop stand, aluminium", "2", "12.40", 20),
                ("Webcam, 1080p", "1", "24.99", 20),
                ("Surge-protected extension, 6-way", "2", "9.80", 20),
                ("Screen cleaning kit", "1", "7.65", 20)]),
    dict(file="06_fenwick_garden_invoice.pdf", doc_type="invoice", supplier_name="Fenwick Garden Services",
         supplier_vat_number=None, invoice_number="FGS-041", invoice_date="2026-09-29",
         due_date="2026-10-13", printed_dates=("29/09/2026", "13/10/2026"), prices_include_vat=False,
         lines=[("Lawn mowing and edging (monthly)", "1", "85.00", 0),
                ("Hedge trimming, front boundary", "1", "60.00", 0),
                ("Green waste removal", "1", "25.00", 0)]),
    dict(file="07_copper_kettle_receipt.png", doc_type="receipt", supplier_name="The Copper Kettle Cafe",
         supplier_vat_number="GB 904 1123 58", invoice_number="T4-118203", invoice_date="2026-10-06",
         due_date=None, printed_dates=("06/10/26 12:41", None), prices_include_vat=True,
         lines=[("Flat white", "2", "3.40", 20), ("Ham & cheese toastie", "1", "6.95", 20),
                ("Carrot cake slice", "1", "3.80", 20), ("Sparkling water", "1", "2.10", 20)]),
    dict(file="08_riverside_fuel_receipt.jpg", doc_type="receipt", supplier_name="Riverside Fuel Station",
         supplier_vat_number="GB 512 6670 13", invoice_number="0042-5571", invoice_date="2026-09-25",
         due_date=None, printed_dates=("25-09-2026 07:58", None), prices_include_vat=True,
         lines=[("Unleaded pump 4 (litres)", "38.52", "1.459", 20), ("Screenwash 5L", "1", "4.99", 20)]),
    dict(file="09_hartley_hardware_receipt.png", doc_type="receipt", supplier_name="Hartley Hardware",
         supplier_vat_number="GB 277 3051 96", invoice_number="HH-30914", invoice_date="2026-09-11",
         due_date=None, printed_dates=("11 Sep 2026 15:22", None), prices_include_vat=True,
         lines=[("Wood screws 4x40 (200)", "2", "5.49", 20), ("Masking tape 50m", "3", "2.25", 20),
                ("Paint roller set", "1", "8.99", 20), ("Dust sheets (pack of 3)", "1", "6.50", 20),
                ("Sandpaper assorted", "2", "3.75", 20)]),
    dict(file="10_cityline_taxi_receipt.jpg", doc_type="receipt", supplier_name="CityLine Taxis",
         supplier_vat_number=None, invoice_number="CL-88214", invoice_date="2026-10-02",
         due_date=None, printed_dates=("02/10/2026 22:15", None), prices_include_vat=True,
         lines=[("Fare: Kings Cross to Islington", "1", "18.40", 0), ("Late-night supplement", "1", "2.00", 0)]),
]


def figures(d):
    """Return (lines_with_totals, subtotal, vat_total, total) exactly as printed on the document."""
    lines, net_sum, vat_sum, gross_sum = [], Decimal(0), Decimal(0), Decimal(0)
    for desc, qty, unit, rate in d["lines"]:
        amount = R(P(qty) * P(unit))
        lines.append(dict(description=desc, quantity=float(P(qty)), unit_price=float(P(unit)),
                          vat_rate=rate, line_total=float(amount)))
        if d["prices_include_vat"]:
            gross_sum += amount
            vat_sum += amount * rate / (100 + rate)
        else:
            net_sum += amount
            vat_sum += amount * rate / 100
    vat = R(vat_sum)
    if d.get("vat_override"):
        vat = P(d["vat_override"])
    if d["prices_include_vat"]:
        total = R(gross_sum)
        subtotal = total - vat
    else:
        subtotal = R(net_sum)
        total = subtotal + vat
    return lines, subtotal, vat, total


def money(x):
    return f"£{x:,.2f}" if x >= 0 else f"-£{abs(x):,.2f}"


# ---------------------------------------------------------------- PDF invoices
def make_pdf(d, path):
    lines, sub, vat, tot = figures(d)
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 18); c.drawString(40, h - 60, d["supplier_name"])
    c.setFont("Helvetica", 9)
    c.drawString(40, h - 76, "Unit 4, Example Business Park, Exampleton, EX1 2AB  |  accounts@example.invalid")
    if d["supplier_vat_number"]:
        c.drawString(40, h - 89, f"VAT registration no: {d['supplier_vat_number']}")
    else:
        c.drawString(40, h - 89, "Sole trader - not registered for VAT")
    c.setFont("Helvetica-Bold", 22); c.drawRightString(w - 40, h - 60, "INVOICE")
    c.setFont("Helvetica", 10)
    c.drawRightString(w - 40, h - 80, f"Invoice no: {d['invoice_number']}")
    c.drawRightString(w - 40, h - 94, f"Invoice date: {d['printed_dates'][0]}")
    c.drawRightString(w - 40, h - 108, f"Payment due: {d['printed_dates'][1]}")
    c.drawString(40, h - 130, "Bill to: Cloudboosta Training Ltd (fictional), 1 Sample Street, London, SW1A 0AA")
    y = h - 170
    c.setFont("Helvetica-Bold", 10)
    for x, t in ((40, "Description"), (330, "Qty"), (380, "Unit price"), (460, "VAT %"), (w - 40, "Amount")):
        (c.drawRightString if x == w - 40 else c.drawString)(x, y, t)
    c.line(40, y - 4, w - 40, y - 4)
    c.setFont("Helvetica", 10)
    for ln in lines:
        y -= 18
        c.drawString(40, y, ln["description"])
        q = ln["quantity"]; c.drawString(330, y, str(int(q)) if q == int(q) else str(q))
        c.drawString(380, y, money(Decimal(str(ln["unit_price"]))))
        c.drawString(460, y, f"{ln['vat_rate']}%")
        c.drawRightString(w - 40, y, money(Decimal(str(ln["line_total"]))))
    y -= 12; c.line(330, y, w - 40, y)
    for label, val, bold in (("Subtotal (net)", sub, False), ("VAT", vat, False), ("Total due", tot, True)):
        y -= 18
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 11 if bold else 10)
        c.drawString(380, y, label); c.drawRightString(w - 40, y, money(vat if label == "VAT" else val))
    c.setFont("Helvetica", 8)
    c.drawString(40, 60, "Bank: Example Bank  Sort code 00-00-00  Account 00000000  (fictional details for training)")
    c.save()


# ---------------------------------------------------------------- PNG/JPG till receipts
def make_receipt(d, path, photo=False):
    """Till receipt. Pillow's built-in font has no pound sign, so amounts are printed as plain numbers
    under an 'Amounts in GBP' header, as many real till receipts do."""
    lines, sub, vat, tot = figures(d)
    font, big = ImageFont.load_default(size=22), ImageFont.load_default(size=30)
    num = lambda x: f"{x:,.2f}"
    rows = [(d["supplier_name"].upper(), "", big), ("12 High Street, Exampleton EX1 2AB", "", font)]
    rows.append((f"VAT No: {d['supplier_vat_number']}" if d["supplier_vat_number"] else "Not VAT registered", "", font))
    rows += [(f"Receipt: {d['invoice_number']}", "", font), (d["printed_dates"][0], "", font),
             ("Amounts in GBP", "", font), ("-" * 44, "", font)]
    for ln in lines:
        q, u = ln["quantity"], ln["unit_price"]
        qtxt = str(int(q)) if q == int(q) else f"{q}"
        utxt = f"{u:.3f}" if round(u, 2) != u else f"{u:.2f}"
        rows += [(ln["description"], "", font), (f"   {qtxt} @ {utxt}", num(ln["line_total"]), font)]
    rows += [("-" * 44, "", font), ("TOTAL", num(tot), big), ("Paid by contactless card", "", font)]
    if d["supplier_vat_number"]:
        rows += [("VAT @20% included", num(vat), font), ("Net amount", num(sub), font)]
    rows += [("Thank you - please call again", "", font)]
    hgt = 40 + sum(44 if f is big else 32 for *_, f in rows)
    img = Image.new("RGB", (620, hgt), "white")
    dr = ImageDraw.Draw(img)
    y = 20
    for left, right, f in rows:
        dr.text((24, y), left, fill="black", font=f)
        if right:
            dr.text((596, y), right, fill="black", font=f, anchor="ra")
        y += 44 if f is big else 32
    if photo:                                   # make it look like a phone photo of a receipt
        img = img.rotate(2.2, expand=True, fillcolor=(205, 200, 190)).filter(ImageFilter.GaussianBlur(0.8))
        rnd = random.Random(7)
        px = img.load()
        for _ in range(img.width * img.height // 25):
            x, yy = rnd.randrange(img.width), rnd.randrange(img.height)
            v = rnd.randint(150, 235); px[x, yy] = (v, v, v)
    img.save(path, quality=70) if path.suffix == ".jpg" else img.save(path)


def main():
    OUT.mkdir(exist_ok=True)
    truth = {}
    for d in DOCS:
        path = OUT / d["file"]
        if path.suffix == ".pdf":
            make_pdf(d, path)
        else:
            make_receipt(d, path, photo=d["file"].startswith(("08", "10")))
        lines, sub, vat, tot = figures(d)
        truth[d["file"]] = dict(
            doc_type=d["doc_type"], supplier_name=d["supplier_name"],
            supplier_vat_number=(d["supplier_vat_number"] or "").replace(" ", "") or None,
            invoice_number=d["invoice_number"], invoice_date=d["invoice_date"], due_date=d["due_date"],
            currency="GBP", prices_include_vat=d["prices_include_vat"], line_items=lines,
            subtotal=float(sub), vat_total=float(vat), total=float(tot),
            expected_status="needs_review" if d.get("vat_override") else "ok")
        print(f"{path}  total {money(tot)}  ({path.stat().st_size // 1024} KB)")
    Path("ground_truth.json").write_text(json.dumps(truth, indent=2))
    print("wrote ground_truth.json for", len(truth), "documents")


if __name__ == "__main__":
    main()
