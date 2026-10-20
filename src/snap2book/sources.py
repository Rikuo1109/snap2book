"""Đọc ảnh đầu vào: PDF từ app scan (mỗi trang một ảnh) hoặc file ảnh rời."""

import unicodedata
from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np
import pymupdf

IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"})
RENDER_DPI = 300  # khi trang PDF không phải đúng một ảnh thì render lại ở độ phân giải này


def load_images(path: Path) -> Iterator[np.ndarray]:
    """Các ảnh xám (uint8) theo thứ tự trang."""
    if path.suffix.lower() != ".pdf":
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError(f"Không đọc được ảnh: {path}")
        yield img
        return

    with pymupdf.open(path) as doc:
        for page in doc:
            img = None
            images = page.get_images()
            if len(images) == 1:  # lấy thẳng ảnh gốc, không render lại cho đỡ mất nét
                data = doc.extract_image(images[0][0])["image"]
                img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
            if img is None:
                pix = page.get_pixmap(dpi=RENDER_DPI, colorspace=pymupdf.csGRAY)
                img = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w).copy()
            yield img


def find_jobs(src: Path) -> list[tuple[str, list[Path]]]:
    """Gom đầu vào thành các cuốn sách: (tên, danh sách file).

    Mỗi file PDF là một cuốn; các ảnh rời trong cùng thư mục (sắp theo tên) là một cuốn.
    Tên chuẩn hoá NFC: macOS lưu tên file tiếng Việt dạng tách dấu (NFD), để nguyên thì
    tiêu đề trong PDF/Markdown trông giống nhưng không khớp khi tìm kiếm, so sánh.
    """
    if not src.exists():
        raise FileNotFoundError(src)
    if not src.is_dir():
        return [(_nfc(src.stem), [src])]
    files = sorted(src.iterdir())
    jobs = [(_nfc(p.stem), [p]) for p in files if p.suffix.lower() == ".pdf"]
    images = [p for p in files if p.suffix.lower() in IMAGE_EXTS]
    if images:
        jobs.append((_nfc(src.name), images))
    return jobs


def _nfc(name: str) -> str:
    return unicodedata.normalize("NFC", name)
