"""Không ghi đè file .md đã sửa tay khi chạy lại snap2book."""

import pytest

from snap2book.cli import parse_args
from snap2book.markdown import fingerprint_path, ocr_path, save_markdown
from snap2book.pipeline import _edited_book
from snap2book.structure import Block, Book

OCR1 = "# Sách\n\nBản OCR lần một.\n"
OCR2 = "# Sách\n\nBản OCR lần hai.\n"
EDITED = "# Sách\n\nBản đã sửa tay.\n"


@pytest.fixture
def md(tmp_path):
    return tmp_path / "sach.md"


def test_first_run_writes(md):
    assert save_markdown(md, OCR1) == md
    assert md.read_text(encoding="utf-8") == OCR1
    assert fingerprint_path(md).exists()
    assert not ocr_path(md).exists()


def test_unchanged_rerun_overwrites(md):
    save_markdown(md, OCR1)
    assert save_markdown(md, OCR2) == md
    assert md.read_text(encoding="utf-8") == OCR2
    assert not ocr_path(md).exists()


def test_edited_file_is_preserved(md):
    save_markdown(md, OCR1)
    md.write_text(EDITED, encoding="utf-8")
    assert save_markdown(md, OCR2) == ocr_path(md)
    assert md.read_text(encoding="utf-8") == EDITED
    assert ocr_path(md).read_text(encoding="utf-8") == OCR2
    # lần sau vẫn giữ (mã băm không đổi theo bản OCR mới)
    assert save_markdown(md, OCR1) == ocr_path(md)
    assert md.read_text(encoding="utf-8") == EDITED


def test_md_without_fingerprint_is_preserved(md):
    # file từ bản snap2book cũ (chưa ghi mã băm): không biết đã sửa chưa, nên giữ lại
    md.write_text(EDITED, encoding="utf-8")
    assert save_markdown(md, OCR2) == ocr_path(md)
    assert md.read_text(encoding="utf-8") == EDITED


def test_force_overwrites(md):
    save_markdown(md, OCR1)
    md.write_text(EDITED, encoding="utf-8")
    assert save_markdown(md, OCR2, force=True) == md
    assert md.read_text(encoding="utf-8") == OCR2
    # sau khi ghi đè, mã băm khớp lại: lần chạy sau ghi đè bình thường
    assert save_markdown(md, OCR1) == md


def test_force_flag():
    assert parse_args(["in.pdf", "--force"]).force
    assert not parse_args(["in.pdf"]).force


def test_text_pdf_built_from_edited_md(md):
    ocr_book = Book([Block("p", "Bản OCR lần hai.")], [])
    md.write_text(EDITED, encoding="utf-8")
    book, title = _edited_book(md, ocr_path(md), ocr_book, "sach")
    assert book.blocks == [Block("p", "Bản đã sửa tay.")]
    assert title == "Sách"


def test_unreadable_edited_md_falls_back_to_ocr(md):
    ocr_book = Book([Block("p", "Bản OCR.")], [])
    md.write_text("# Sách\n\nThiếu chú thích[^1].\n", encoding="utf-8")
    assert _edited_book(md, ocr_path(md), ocr_book, "sach") == (ocr_book, "sach")
