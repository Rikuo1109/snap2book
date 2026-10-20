from pathlib import Path

import pymupdf
import pytest

from snap2book.structure import Block, Book, note_ref
from snap2book.typeset import FONT_DIR, FONT_FILE, Row, fix_first_bad_break, to_pdf

LEFT, INDENT = 35.0, 50.0


def rows(*kinds, top=24.0, pitch=14.0):
    """Các dòng của một trang: "s" đầu đoạn (thụt vào), "c" dòng tiếp, "h" tiêu đề."""
    out = []
    for i, k in enumerate(kinds):
        y = top + i * pitch
        out.append(Row(y, y + 12, INDENT if k == "s" else LEFT, 15.0 if k == "h" else 11.0))
    return out


def test_good_break_untouched():
    limits = {}
    assert not fix_first_bad_break([rows("s", "c", "c", "c"), rows("c", "c", "s", "c")], limits)
    assert limits == {}


def test_single_line_at_top_of_next_page_pulls_one_more_line():
    cur = rows("s", "c", "s", "c", "c")
    limits = {}
    assert fix_first_bad_break([cur, rows("c", "s", "c")], limits)
    assert limits == {0: cur[-1].y0 + 1}


def test_single_line_at_bottom_pushes_paragraph():
    cur = rows("s", "c", "c", "s")
    limits = {}
    assert fix_first_bad_break([cur, rows("c", "c", "s")], limits)
    assert limits == {0: cur[-1].y0 + 1}


def test_heading_at_bottom_moves_to_next_page():
    cur = rows("s", "c", "h", "h")
    limits = {}
    assert fix_first_bad_break([cur, rows("s", "c")], limits)
    assert limits == {0: cur[2].y0 + 1}


@pytest.mark.skipif(not Path(FONT_DIR, FONT_FILE).exists(), reason="cần font Times New Roman của macOS")
def test_footnote_on_same_page_as_reference(tmp_path):
    filler = "Một đoạn văn dài để lấp đầy trang sách cho đủ nhiều dòng. " * 12
    blocks = [Block("h1", "CHƯƠNG I")]
    blocks += [Block("p", filler) for _ in range(4)]
    blocks.append(Block("p", f"Nàng Sotori{note_ref(1)} xuất hiện. " + filler))
    blocks += [Block("p", filler) for _ in range(4)]
    book = Book(blocks, notes=["Nhân vật trong truyền thuyết Nhật Bản."])

    out = tmp_path / "sach.pdf"
    n = to_pdf(book, "Sách", out)

    with pymupdf.open(out) as doc:
        assert doc.page_count == n > 1
        pages = [p.get_text().replace("\xa0", " ") for p in doc]  # Story dùng dấu cách không ngắt
        ref_page = next(i for i, t in enumerate(pages) if "Sotori" in t)
        note_page = next(i for i, t in enumerate(pages) if "truyền thuyết Nhật" in t)
        assert ref_page == note_page
