import xml.etree.ElementTree as ET
import zipfile

from snap2book.epub import to_epub
from snap2book.structure import Block, Book, note_ref

XHTML = "{http://www.w3.org/1999/xhtml}"


def make_book():
    return Book(
        [
            Block("p", "Lời mở đầu & giới thiệu."),
            Block("h1", "CHƯƠNG I"),
            Block("h2", "Khởi đầu"),
            Block("p", f"Nàng Sotori{note_ref(1)} xuất hiện."),
            Block("p", "Đoạn hai <không phải thẻ>."),
            Block("h1", "CHƯƠNG II"),
            Block("p", f"Hòa ca{note_ref(2)} là thể thơ."),
        ],
        notes=["Nhân vật truyền thuyết.", "Thể thơ Nhật.", "Chú thích không ai trỏ tới."],
    )


def read(path):
    zf = zipfile.ZipFile(path)
    return zf, {name: zf.read(name).decode() for name in zf.namelist()}


def test_container_layout_and_valid_xml(tmp_path):
    out = tmp_path / "sach.epub"
    assert to_epub(make_book(), "Sách & thử", out) == 3  # mở đầu + 2 chương
    zf, files = read(out)
    first = zf.infolist()[0]
    assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    assert files["mimetype"] == "application/epub+zip"
    for name, content in files.items():
        if name.endswith((".xhtml", ".opf", ".xml")):
            ET.fromstring(content)  # XML hợp lệ (đã escape & < >)
    assert "<dc:title>Sách &amp; thử</dc:title>" in files["OEBPS/content.opf"]
    assert "<dc:language>vi</dc:language>" in files["OEBPS/content.opf"]


def test_chapters_toc_and_footnotes(tmp_path):
    out = tmp_path / "sach.epub"
    to_epub(make_book(), "Sách", out)
    _, files = read(out)
    nav = ET.fromstring(files["OEBPS/nav.xhtml"])
    labels = [a.text for a in nav.iter(f"{XHTML}a")]
    assert labels == ["Sách", "CHƯƠNG I: Khởi đầu", "CHƯƠNG II"]
    chap1, chap2 = files["OEBPS/chap002.xhtml"], files["OEBPS/chap003.xhtml"]
    assert 'epub:type="noteref"' in chap1 and 'href="#fn1"' in chap1
    assert 'id="fn1"' in chap1 and "Nhân vật truyền thuyết." in chap1  # chú thích ở chương có số mũ
    assert 'id="fn2"' in chap2 and "Thể thơ Nhật." in chap2
    assert 'id="fn3"' in chap2  # không ai trỏ tới: gom cuối sách
    assert '<p class="first">Nàng Sotori' in chap1  # đoạn đầu sau tiêu đề không thụt
    assert "<p>Đoạn hai &lt;không phải thẻ&gt;.</p>" in chap1


def test_deterministic(tmp_path):
    a, b = tmp_path / "a.epub", tmp_path / "b.epub"
    to_epub(make_book(), "Sách", a)
    to_epub(make_book(), "Sách", b)
    assert a.read_bytes() == b.read_bytes()


def test_book_without_headings_is_one_chapter(tmp_path):
    out = tmp_path / "sach.epub"
    assert to_epub(Book([Block("p", "Chỉ một đoạn.")]), "Sách", out) == 1


def test_quote_block(tmp_path):
    out = tmp_path / "sach.epub"
    to_epub(
        Book([Block("h1", "CHƯƠNG I"), Block("quote", "Thư & lời nhắn."), Block("p", "Sau thư.")]), "S", out
    )
    chap = read(out)[1]["OEBPS/chap001.xhtml"]
    assert "<blockquote><p>Thư &amp; lời nhắn.</p></blockquote>" in chap
    assert "<p>Sau thư.</p>" in chap  # đoạn sau thư thụt vào như thường
    ET.fromstring(chap)
