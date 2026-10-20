"""Ghép các trang ảnh đã làm sạch thành PDF ảnh (bản đối chiếu với ảnh gốc)."""

from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np
import pymupdf

PAGE_WIDTH_PT = 420  # khổ A5 (148mm)
CONTENT_WIDTH_PX = 1600  # ~300dpi trên A5 sau khi trừ lề


def write_scan_pdf(
    pages: Sequence[np.ndarray], out_path: Path, margin: float = 0.09, jpeg_quality: int = 80
) -> None:
    """Đặt mọi trang lên cùng khổ: chiều rộng vùng chữ bằng nhau, căn trên."""
    # tỉ lệ khung chữ = trung vị các trang (+5% dư); trang nào cao hơn thì thu nhỏ cho vừa
    body_aspect = float(np.median([p.shape[0] / p.shape[1] for p in pages])) * 1.05
    pad = int(CONTENT_WIDTH_PX * margin / (1 - 2 * margin))
    page_w = CONTENT_WIDTH_PX + 2 * pad
    page_h = int(CONTENT_WIDTH_PX * body_aspect) + 2 * pad
    pt_per_px = PAGE_WIDTH_PT / page_w

    doc = pymupdf.open()
    for img in pages:
        h, w = img.shape
        s = min(CONTENT_WIDTH_PX / w, (page_h - 2 * pad) / h)
        resized = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
        canvas = np.full((page_h, page_w), 255, np.uint8)
        rh, rw = resized.shape
        x = (page_w - rw) // 2
        canvas[pad : pad + rh, x : x + rw] = resized
        _, buf = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
        page = doc.new_page(width=page_w * pt_per_px, height=page_h * pt_per_px)
        page.insert_image(page.rect, stream=buf.tobytes())

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path, garbage=4, deflate=True)
