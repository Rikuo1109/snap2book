from pathlib import Path

import pymupdf
import pytest

from snap2book.cli import main
from snap2book.markdown import from_markdown, to_markdown
from snap2book.structure import Block, Book, note_ref
from snap2book.typeset import FONT_DIR, FONT_FILE

BOOK = Book(
    blocks=[
        Block("h1", "CHƯƠNG I"),
        Block("h2", "Những mối quan hệ của con người"),
        Block("p", f"Nàng Sotori{note_ref(1)}, công chúa cổ tích."),
        Block("p", '"Đương nhiên là có rồi." Kazuma nói.'),
        Block("h1", "CHƯƠNG II"),
        Block("p", f"Đoạn có hai chú thích{note_ref(2)} ở đây{note_ref(3)}."),
    ],
    notes=["Một nhân vật trong truyền thuyết.", "Chú thích hai.", "Chú thích ba."],
)


def test_round_trip():
    assert from_markdown(to_markdown(BOOK, "Sách")) == (BOOK, "Sách")


def test_hand_edited_markdown():
    md = """# Sách

## CHƯƠNG I

Dòng đầu bị ngắt
giữa chừng[^a].
## CHƯƠNG II
Đoạn khác[^1].

[^1]: Chú thích
    viết hai dòng.
[^a]: Chú thích a.
"""
    book, title = from_markdown(md)
    assert title == "Sách"
    assert book.blocks == [
        Block("h1", "CHƯƠNG I"),
        Block("p", f"Dòng đầu bị ngắt giữa chừng{note_ref(1)}."),
        Block("h1", "CHƯƠNG II"),
        Block("p", f"Đoạn khác{note_ref(2)}."),
    ]
    # đánh số lại theo thứ tự xuất hiện trong bài
    assert book.notes == ["Chú thích a.", "Chú thích viết hai dòng."]


def test_missing_footnote_definition():
    with pytest.raises(ValueError, match=r"\[\^2\]"):
        from_markdown("Đoạn[^2].\n")


@pytest.mark.skipif(not Path(FONT_DIR, FONT_FILE).exists(), reason="cần font Times New Roman của macOS")
def test_cli_typeset_markdown(tmp_path):
    md = tmp_path / "sach.md"
    md.write_text(to_markdown(BOOK, "Sách"), encoding="utf-8")

    main(["typeset", str(md), "-q"])  # mặc định chỉ EPUB
    assert not (tmp_path / "sach.pdf").exists()
    with pymupdf.open(tmp_path / "sach.epub") as doc:
        text = "".join(p.get_text() for p in doc).replace("\xa0", " ")
    assert "Sotori" in text and "Chú thích ba." in text

    main(["typeset", str(md), "-q", "--pdf"])
    with pymupdf.open(tmp_path / "sach.pdf") as doc:
        assert doc.metadata["title"] == "Sách"
        text = "".join(p.get_text() for p in doc).replace("\xa0", " ")
    assert "Sotori" in text and "Chú thích ba." in text


def test_quote_paragraphs():
    text = (
        "# Sách\n\nTrong thư nói rằng:\n\n"
        "> Văn phòng du lịch\n> sẽ gửi vé.\n>\n> Cầu xin[^1] mọi người.\n\n"
        "Hết thư.\n\n[^1]: Chú.\n"
    )
    book, _ = from_markdown(text)
    assert [(b.kind, b.text) for b in book.blocks] == [
        ("p", "Trong thư nói rằng:"),
        ("quote", "Văn phòng du lịch sẽ gửi vé."),
        ("quote", f"Cầu xin{note_ref(1)} mọi người."),
        ("p", "Hết thư."),
    ]
    assert from_markdown(to_markdown(book, "Sách"))[0] == book
