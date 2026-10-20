"""Chạy toàn bộ quy trình cho một cuốn sách: làm sạch -> PDF ảnh -> OCR -> Markdown + PDF chữ."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from snap2book.cleanup import clean_page
from snap2book.scan_pdf import write_scan_pdf
from snap2book.sources import load_images

log = logging.getLogger(__name__)


@dataclass
class Outputs:
    scan_pdf: Path  # ảnh các trang đã làm sạch
    text_pdf: Path | None = None  # sách dàn trang lại từ chữ OCR
    markdown: Path | None = None  # nội dung dạng text


def output_paths(out_dir: Path, name: str) -> Outputs:
    return Outputs(
        scan_pdf=out_dir / f"{name} - scan.pdf",
        text_pdf=out_dir / f"{name}.pdf",
        markdown=out_dir / f"{name}.md",
    )


def convert(inputs: Sequence[Path], outputs: Outputs, debug_dir: Path | None = None) -> Outputs:
    """Xử lý các file đầu vào (theo thứ tự trang) thành một cuốn sách.
    outputs.text_pdf = None thì bỏ qua OCR, chỉ xuất PDF ảnh."""
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)

    pages = []
    for src in inputs:
        for gray in load_images(src):
            idx = len(pages) + 1
            debug_path = debug_dir / f"page_{idx:03d}.jpg" if debug_dir else None
            page = clean_page(gray, debug_path)
            pages.append(page.image)
            log.info("  trang %d: xoay %+.1f°, vùng chữ %dx%d", idx, page.angle, *page.image.shape[::-1])
    if not pages:
        raise ValueError("Không có trang nào.")

    write_scan_pdf(pages, outputs.scan_pdf)
    log.info("=> %s (%d trang ảnh)", outputs.scan_pdf, len(pages))
    if outputs.text_pdf is None:
        return outputs

    # import muộn: OCR cần macOS (Apple Vision), chế độ chỉ-ảnh thì không cần
    from snap2book.markdown import to_markdown
    from snap2book.ocr import ocr_page
    from snap2book.structure import build_book
    from snap2book.typeset import to_pdf

    lines = []
    for idx, img in enumerate(pages, 1):
        lines.append(ocr_page(img))
        log.info("  OCR trang %d: %d dòng", idx, len(lines[-1]))
    book = build_book(lines)
    title = outputs.text_pdf.stem

    if outputs.markdown:
        outputs.markdown.write_text(to_markdown(book, title), encoding="utf-8")
        log.info("=> %s", outputs.markdown)
    n = to_pdf(book, title, outputs.text_pdf)
    log.info("=> %s (%d trang, từ %d trang chụp)", outputs.text_pdf, n, len(pages))
    return outputs
