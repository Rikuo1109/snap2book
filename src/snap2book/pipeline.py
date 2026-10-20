"""Chạy toàn bộ quy trình cho một cuốn sách: làm sạch -> PDF ảnh -> OCR -> Markdown + PDF chữ."""

import logging
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from snap2book.cache import PageCache
from snap2book.pages import PageTask, Settings, process_pages
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


def convert(
    inputs: Sequence[Path],
    outputs: Outputs,
    debug_dir: Path | None = None,
    drop_duplicates: bool = True,
    flatten: bool = True,
    spellfix: bool = True,
    jobs: int | None = None,
    cache_dir: Path | None = None,
) -> Outputs:
    """Xử lý các file đầu vào (theo thứ tự trang) thành một cuốn sách.
    outputs.text_pdf = None thì bỏ qua OCR, chỉ xuất PDF ảnh.
    drop_duplicates: bỏ nội dung ảnh chụp lặp một trang (theo số trang in).
    flatten: làm phẳng trang cong. spellfix: sửa lỗi dấu theo từ điển chính tả.
    jobs: số tiến trình xử lý trang song song (mặc định: số nhân CPU).
    cache_dir: thư mục cache kết quả từng trang (None: không dùng cache)."""
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)

    def tasks() -> Iterator[PageTask]:
        idx = 0
        for src in inputs:
            for gray in load_images(src):
                idx += 1
                yield PageTask(gray, debug_dir / f"page_{idx:03d}.jpg" if debug_dir else None)

    do_ocr = outputs.text_pdf is not None
    settings = Settings(flatten, do_ocr, with_alt=spellfix, cache_dir=cache_dir)

    pages, lines, hits = [], [], 0
    for idx, page in enumerate(process_pages(tasks(), settings, jobs or os.cpu_count() or 1), 1):
        pages.append(page.image)
        hits += page.cached
        flat = f", làm phẳng (võng {page.curve:.0f}px)" if page.flattened else ""
        ocr = ""
        if page.lines is not None:
            lines.append(page.lines)
            ocr = f", OCR {len(page.lines)} dòng"
        log.info(
            "  trang %d: xoay %+.1f°%s, vùng chữ %dx%d%s%s",
            idx,
            page.angle,
            flat,
            *page.image.shape[::-1],
            ocr,
            " (cache)" if page.cached else "",
        )
    if not pages:
        raise ValueError("Không có trang nào.")
    if cache_dir:
        log.info("  cache: %d/%d trang không phải tính lại", hits, len(pages))
        PageCache(cache_dir).prune()

    write_scan_pdf(pages, outputs.scan_pdf)
    log.info("=> %s (%d trang ảnh)", outputs.scan_pdf, len(pages))
    if not do_ocr:
        return outputs

    # import muộn: OCR cần macOS (Apple Vision), chế độ chỉ-ảnh thì không cần
    from snap2book.markdown import to_markdown
    from snap2book.pagecheck import check_pages
    from snap2book.structure import build_book, page_number
    from snap2book.typeset import to_pdf

    if spellfix:
        from snap2book.spellfix import MacSpellChecker, fix_pages

        # cần cả sách để biết tần suất từ, nên sửa sau khi OCR xong mọi trang
        per_page = fix_pages(lines, MacSpellChecker())
        for idx, changes in enumerate(per_page, 1):
            for c in changes:
                log.debug("    trang %d: %s → %s | %s", idx, c.before, c.after, c.line)
        log.info("  sửa dấu: %d từ", sum(len(c) for c in per_page))

    check = check_pages([page_number(page) for page in lines], [len(page) for page in lines])
    for msg in check.warnings:
        log.warning("  cảnh báo: %s", msg)
    if check.duplicates and drop_duplicates:
        log.warning("  bỏ ảnh chụp lặp: %s", ", ".join(str(i + 1) for i in check.duplicates))
        lines = [page for i, page in enumerate(lines) if i not in check.duplicates]
    book = build_book(lines)
    title = outputs.text_pdf.stem

    if outputs.markdown:
        outputs.markdown.write_text(to_markdown(book, title), encoding="utf-8")
        log.info("=> %s", outputs.markdown)
    n = to_pdf(book, title, outputs.text_pdf)
    log.info("=> %s (%d trang, từ %d trang chụp)", outputs.text_pdf, n, len(pages))
    return outputs
