"""Synthetic Invoice Generator for PDF and Image Documents.

Generates realistic invoice documents (PDF and PNG) with headers, line item tables,
tax, totals, supplier details, PO numbers, and remittance details for testing and
demonstrating the Multimodal LLM Extraction Engine.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image, ImageDraw, ImageFont


DEFAULT_SAMPLE_INVOICE = {
    "invoice_number": "INV-2026-8801",
    "supplier_name": "Apex Industrial Supplies LLC",
    "supplier_tax_id": "US-XX-9876543",
    "supplier_address": "100 Innovation Way, Suite 400, Austin, TX 78701",
    "invoice_date": "2026-09-20",
    "due_date": "2026-10-20",
    "currency": "USD",
    "po_number": "PO-9001",
    "bank_account_last4": "4321",
    "lines": [
        {
            "line_number": 1,
            "description": "Industrial Pneumatic Valves - Model PV-100",
            "quantity": 2.0,
            "unit_price": 500.00,
            "total": 1000.00,
        },
        {
            "line_number": 2,
            "description": "High-Pressure Seal Kits",
            "quantity": 4.0,
            "unit_price": 50.00,
            "total": 200.00,
        },
    ],
    "subtotal": 1200.00,
    "tax_amount": 96.00,
    "total_amount": 1296.00,
}


def create_sample_invoice_pdf(
    output_path: str | Path,
    invoice_data: dict[str, Any] | None = None,
) -> Path:
    """Generate a realistic vector PDF invoice using PyMuPDF.

    Args:
        output_path: File path to save the generated PDF.
        invoice_data: Optional dictionary overriding default invoice fields.

    Returns:
        Path to the saved PDF file.
    """
    data = {**DEFAULT_SAMPLE_INVOICE, **(invoice_data or {})}
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open()
    # Standard A4: 595 x 842 points
    page = doc.new_page(width=595, height=842)

    # 1. Header & Brand Banner
    page.draw_rect(pymupdf.Rect(40, 40, 555, 100), color=(0.12, 0.25, 0.55), fill=(0.95, 0.97, 1.0))
    page.insert_text(
        (55, 75),
        data["supplier_name"],
        fontsize=18,
        fontname="helv",
        color=(0.1, 0.2, 0.5),
    )
    page.insert_text(
        (55, 92),
        f"Tax ID / EIN: {data.get('supplier_tax_id', 'N/A')}  |  {data.get('supplier_address', '')}",
        fontsize=9,
        fontname="helv",
        color=(0.3, 0.3, 0.3),
    )

    page.insert_text(
        (430, 75),
        "INVOICE",
        fontsize=22,
        fontname="helv",
        color=(0.1, 0.2, 0.5),
    )
    page.insert_text(
        (430, 92),
        f"#{data['invoice_number']}",
        fontsize=11,
        fontname="helv",
        color=(0.2, 0.2, 0.2),
    )

    # 2. Metadata Grid
    page.draw_line(pymupdf.Point(40, 115), pymupdf.Point(555, 115), color=(0.8, 0.8, 0.8), width=1)

    y_meta = 135
    page.insert_text((55, y_meta), "Invoice Date:", fontsize=10, fontname="helv", color=(0.4, 0.4, 0.4))
    page.insert_text((140, y_meta), str(data["invoice_date"]), fontsize=10, fontname="helv")

    page.insert_text((320, y_meta), "PO Reference:", fontsize=10, fontname="helv", color=(0.4, 0.4, 0.4))
    page.insert_text((420, y_meta), str(data.get("po_number", "N/A")), fontsize=10, fontname="helv")

    y_meta += 20
    page.insert_text((55, y_meta), "Due Date:", fontsize=10, fontname="helv", color=(0.4, 0.4, 0.4))
    page.insert_text((140, y_meta), str(data.get("due_date", "N/A")), fontsize=10, fontname="helv")

    page.insert_text((320, y_meta), "Currency:", fontsize=10, fontname="helv", color=(0.4, 0.4, 0.4))
    page.insert_text((420, y_meta), str(data.get("currency", "USD")), fontsize=10, fontname="helv")

    # 3. Line Items Table Header
    y_table = 190
    page.draw_rect(pymupdf.Rect(40, y_table, 555, y_table + 24), color=(0.2, 0.3, 0.6), fill=(0.2, 0.3, 0.6))
    page.insert_text((55, y_table + 16), "#", fontsize=10, fontname="helv", color=(1.0, 1.0, 1.0))
    page.insert_text((85, y_table + 16), "Description", fontsize=10, fontname="helv", color=(1.0, 1.0, 1.0))
    page.insert_text((340, y_table + 16), "Qty", fontsize=10, fontname="helv", color=(1.0, 1.0, 1.0))
    page.insert_text((400, y_table + 16), "Unit Price", fontsize=10, fontname="helv", color=(1.0, 1.0, 1.0))
    page.insert_text((485, y_table + 16), "Total", fontsize=10, fontname="helv", color=(1.0, 1.0, 1.0))

    # 4. Table Rows
    curr_y = y_table + 24
    lines = data.get("lines", [])
    for idx, item in enumerate(lines):
        row_y = curr_y + (idx * 26)
        # Alternate subtle row background
        if idx % 2 == 1:
            page.draw_rect(pymupdf.Rect(40, row_y, 555, row_y + 26), color=(0.96, 0.96, 0.98), fill=(0.96, 0.96, 0.98))
        page.draw_line(pymupdf.Point(40, row_y + 26), pymupdf.Point(555, row_y + 26), color=(0.9, 0.9, 0.9), width=0.5)

        page.insert_text((55, row_y + 18), str(item.get("line_number", idx + 1)), fontsize=9, fontname="helv")
        page.insert_text((85, row_y + 18), str(item.get("description", "")), fontsize=9, fontname="helv")
        page.insert_text((340, row_y + 18), f"{item.get('quantity', 1):,.1f}", fontsize=9, fontname="helv")
        page.insert_text((400, row_y + 18), f"${item.get('unit_price', 0.0):,.2f}", fontsize=9, fontname="helv")
        page.insert_text((485, row_y + 18), f"${item.get('total', 0.0):,.2f}", fontsize=9, fontname="helv")

    curr_y += len(lines) * 26 + 20

    # 5. Financial Summary Box
    summary_rect = pymupdf.Rect(320, curr_y, 555, curr_y + 90)
    page.draw_rect(summary_rect, color=(0.85, 0.85, 0.85), fill=(0.98, 0.98, 0.99))

    page.insert_text((340, curr_y + 22), "Subtotal:", fontsize=10, fontname="helv", color=(0.4, 0.4, 0.4))
    page.insert_text((475, curr_y + 22), f"${data.get('subtotal', 0.0):,.2f}", fontsize=10, fontname="helv")

    page.insert_text((340, curr_y + 44), "Tax Amount:", fontsize=10, fontname="helv", color=(0.4, 0.4, 0.4))
    page.insert_text((475, curr_y + 44), f"${data.get('tax_amount', 0.0):,.2f}", fontsize=10, fontname="helv")

    page.draw_line(pymupdf.Point(340, curr_y + 55), pymupdf.Point(535, curr_y + 55), color=(0.7, 0.7, 0.7), width=1)

    page.insert_text((340, curr_y + 75), "Total Amount:", fontsize=11, fontname="helv", color=(0.1, 0.2, 0.5))
    page.insert_text(
        (470, curr_y + 75),
        f"${data.get('total_amount', 0.0):,.2f} {data.get('currency', 'USD')}",
        fontsize=11,
        fontname="helv",
        color=(0.1, 0.2, 0.5),
    )

    # 6. Remittance / Bank Info
    bank_y = curr_y + 115
    page.draw_rect(pymupdf.Rect(40, bank_y, 555, bank_y + 45), color=(0.85, 0.90, 0.95), fill=(0.95, 0.97, 1.0))
    page.insert_text((55, bank_y + 20), "Payment & Remittance Instructions:", fontsize=10, fontname="helv", color=(0.1, 0.2, 0.5))
    bank_last4 = data.get("bank_account_last4", "4321")
    page.insert_text(
        (55, bank_y + 36),
        f"ACH / Wire Remittance Account ending in ****{bank_last4}  |  Terms: Net 30 days",
        fontsize=9,
        fontname="helv",
        color=(0.3, 0.3, 0.3),
    )

    doc.save(str(target))
    doc.close()
    return target


def create_sample_invoice_image(
    output_path: str | Path,
    invoice_data: dict[str, Any] | None = None,
) -> Path:
    """Generate a raster PNG invoice image.

    Renders the invoice via PyMuPDF vector renderer directly to a crisp 150 DPI PNG.

    Args:
        output_path: File path to save the generated PNG.
        invoice_data: Optional dictionary overriding default invoice fields.

    Returns:
        Path to the saved PNG image file.
    """
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    # Render directly to PDF in memory, then rasterize page 0 to PNG
    temp_pdf = create_sample_invoice_pdf(target.with_suffix(".tmp.pdf"), invoice_data)
    doc = pymupdf.open(str(temp_pdf))
    page = doc[0]
    pix = page.get_pixmap(dpi=150)
    pix.save(str(target))
    doc.close()
    if temp_pdf.exists():
        temp_pdf.unlink()

    return target
