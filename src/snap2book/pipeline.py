"""Chạy toàn bộ quy trình cho một cuốn sách: làm sạch -> PDF ảnh -> OCR -> Markdown + PDF chữ."""

import logging
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from snap2book.cache import PageCache
from snap2book.pages import PageTask, Settings, process_pages
from snap2book.scan_pdf import write_scan_pdf
from snap2book.sources import is_cover, load_images, save_cover_images

if TYPE_CHECKING:
    from snap2book.structure import Block, Book

log = logging.getLogger(__name__)


@dataclass
class Outputs:
    scan_pdf: Path  # ảnh các trang đã làm sạch
    text_pdf: Path | None = None  # sách dàn trang lại từ chữ OCR (khổ A5, chỉ khi cần --pdf)
    markdown: Path | None = None  # nội dung dạng text
    epub: Path | None = None  # sách điện tử (chữ tự dàn theo màn hình)

    def books(self) -> list[Path]:
        """Các file sách để đọc (PDF chữ, EPUB); chế độ chỉ-ảnh thì là PDF ảnh."""
        found = [p for p in (self.epub, self.text_pdf) if p]
        return found or [self.scan_pdf]

    def wants_text(self) -> bool:
        """Có xuất bản chữ nào không (không thì bỏ qua OCR, chỉ xuất PDF ảnh)."""
        return any((self.epub, self.markdown, self.text_pdf))


def output_paths(out_dir: Path, name: str, pdf: bool = False) -> Outputs:
    """Mặc định xuất EPUB (đọc trên điện thoại) + Markdown (soát lỗi) + PDF ảnh (đối chiếu);
    pdf=True thêm PDF chữ khổ A5."""
    return Outputs(
        scan_pdf=out_dir / f"{name} - scan.pdf",
        text_pdf=out_dir / f"{name}.pdf" if pdf else None,
        markdown=out_dir / f"{name}.md",
        epub=out_dir / f"{name}.epub",
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
    force: bool = False,
) -> Outputs:
    """Xử lý các file đầu vào (theo thứ tự trang) thành một cuốn sách.
    Không xuất bản chữ nào (epub/markdown/text_pdf đều None) thì bỏ qua OCR, chỉ xuất PDF ảnh.
    drop_duplicates: bỏ nội dung ảnh chụp lặp một trang (theo số trang in).
    flatten: làm phẳng trang cong. spellfix: sửa lỗi dấu theo từ điển chính tả.
    jobs: số tiến trình xử lý trang song song (mặc định: số nhân CPU).
    cache_dir: thư mục cache kết quả từng trang (None: không dùng cache).
    force: ghi đè cả file .md đã sửa tay (mặc định giữ lại, bản OCR mới ghi ra <tên>.ocr.md).
    File bìa (cover.pdf / cover.jpg) không OCR: trang đầu là bìa EPUB, các trang sau là ảnh ở
    đầu sách."""
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
    covers = [p for p in inputs if is_cover(p)]
    inputs = [p for p in inputs if not is_cover(p)]

    def tasks() -> Iterator[PageTask]:
        idx = 0
        for src in inputs:
            for gray in load_images(src):
                idx += 1
                yield PageTask(gray, debug_dir / f"page_{idx:03d}.jpg" if debug_dir else None)

    do_ocr = outputs.wants_text()
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
    from snap2book.markdown import save_markdown, to_markdown
    from snap2book.pagecheck import check_pages
    from snap2book.structure import build_book, page_number, running_headers
    from snap2book.typeset import to_pdf

    headers = running_headers(lines)
    check = check_pages([page_number(page, headers) for page in lines], [len(page) for page in lines])
    for msg in check.warnings:
        log.warning("  cảnh báo: %s", msg)
    photos = list(range(1, len(lines) + 1))  # số thứ tự ảnh của từng trang còn giữ, để ghi log
    if check.duplicates and drop_duplicates:
        log.warning("  bỏ ảnh chụp lặp: %s", ", ".join(str(i + 1) for i in check.duplicates))
        lines = [page for i, page in enumerate(lines) if i not in check.duplicates]
        photos = [i + 1 for i in range(len(photos)) if i not in check.duplicates]

    if spellfix:
        from snap2book.spellfix import MacSpellChecker, fix_pages

        # cần cả sách để biết tần suất từ, nên sửa sau khi OCR xong mọi trang; sau khi bỏ ảnh chụp
        # lặp, để hai bản đọc lệch nhau của cùng một trang không làm bằng chứng cho nhau
        per_page = fix_pages(lines, MacSpellChecker())
        for photo, changes in zip(photos, per_page, strict=True):
            for c in changes:
                log.debug("    ảnh %d: %s → %s | %s", photo, c.before, c.after, c.line)
        log.info("  sửa dấu: %d từ", sum(len(c) for c in per_page))

    book = build_book(lines)
    first_out = next(p for p in (outputs.epub, outputs.markdown, outputs.text_pdf) if p)
    title, out_dir = first_out.stem, first_out.parent
    if covers:
        book.blocks[:0] = _cover_blocks(covers, out_dir, title)

    if outputs.markdown:
        written = save_markdown(outputs.markdown, to_markdown(book, title), force)
        log.info("=> %s", written)
        if written != outputs.markdown:
            book, title = _edited_book(outputs.markdown, written, book, title)
    if outputs.epub:
        from snap2book.epub import to_epub

        chapters = to_epub(book, title, outputs.epub, resources=out_dir)
        log.info("=> %s (%d chương, từ %d trang chụp)", outputs.epub, chapters, len(pages))
    if outputs.text_pdf:
        n = to_pdf(book, title, outputs.text_pdf, resources=out_dir)
        log.info("=> %s (%d trang)", outputs.text_pdf, n)
    return outputs


def _cover_blocks(covers: Sequence[Path], out_dir: Path, name: str) -> list["Block"]:
    """Lưu ảnh bìa vào <thư mục ra>/images/<tên>/ và trả về các khối ảnh đặt ở đầu sách:
    ảnh đầu tiên là bìa (chú thích COVER_ALT), các ảnh sau là trang ảnh mở đầu."""
    from snap2book.epub import COVER_ALT
    from snap2book.structure import Block

    paths = [p for cover in covers for p in save_cover_images(cover, out_dir / "images" / name)]
    log.info("  bìa: %d ảnh", len(paths))
    return [
        Block("image", COVER_ALT if i == 0 else "", src=p.relative_to(out_dir).as_posix())
        for i, p in enumerate(paths)
    ]


def _edited_book(md: Path, ocr_md: Path, book: "Book", title: str) -> tuple["Book", str]:
    """File .md đã sửa tay được giữ nguyên: dàn PDF chữ từ bản đã sửa (nếu đọc được)."""
    from snap2book.markdown import from_markdown

    log.warning(
        "  cảnh báo: %s đã được sửa tay nên KHÔNG bị ghi đè; bản OCR mới ghi ở %s (--force để ghi đè).",
        md,
        ocr_md,
    )
    try:
        edited, edited_title = from_markdown(md.read_text(encoding="utf-8"))
    except ValueError as e:
        log.warning("  cảnh báo: không đọc được %s (%s); sách dựng từ bản OCR mới.", md, e)
        return book, title
    log.warning("  Sách được dựng từ bản đã sửa %s.", md)
    return edited, edited_title or title
