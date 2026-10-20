from snap2book.markdown import to_markdown
from snap2book.structure import build_book, note_ref


def texts(book, kind="p"):
    return [b.text for b in book.blocks if b.kind == kind]


def test_paragraphs_split_on_indent_and_short_line(page):
    book = build_book(
        [
            page(
                ("Một hai", "indent"),
                ("ba bốn", "body"),
                ("năm.", "last"),
                ("Sáu bảy", "indent"),
                ("tám", "body"),
            )
        ]
    )
    assert texts(book) == ["Một hai ba bốn năm.", "Sáu bảy tám"]


def test_paragraph_continues_across_pages(page):
    book = build_book(
        [
            page(("Đầu đoạn", "indent"), ("giữa đoạn", "body")),
            page(("cuối đoạn.", "last"), ("Đoạn mới", "indent"), ("tiếp", "body")),
        ]
    )
    assert texts(book) == ["Đầu đoạn giữa đoạn cuối đoạn.", "Đoạn mới tiếp"]


def test_running_footer_and_page_number_removed(page):
    book = build_book(
        [
            page(
                ("Nội dung", "indent"),
                ("trang sách", "body"),
                ("SAKAGUCHI ANGO", "center", 0.95),
                ("7", "body", 0.96),
            )
        ]
    )
    assert texts(book) == ["Nội dung trang sách"]


def test_noise_line_removed(page):
    book = build_book([page(("Nội dung", "indent"), ("4..d", "body"), ("tiếp", "body"))])
    assert texts(book) == ["Nội dung tiếp"]


def test_chapter_heading(page):
    book = build_book(
        [
            page(
                ("CHƯƠNG I", "center"),
                ("Những mối quan hệ", "center"),
                ("của con người", "center"),
                ("Cuối tháng Sáu", "body", 0.25),
                ("năm 1947, Utagawa", "body"),
                ("Kazuma gọi cho tôi", "body"),
                ("và hẹn gặp.", "last"),
            )
        ]
    )
    assert texts(book, "h1") == ["CHƯƠNG I"]
    assert texts(book, "h2") == ["Những mối quan hệ của con người"]
    assert texts(book) == ["Cuối tháng Sáu năm 1947, Utagawa Kazuma gọi cho tôi và hẹn gặp."]


def test_footnote_extracted_and_marked(page):
    book = build_book(
        [
            page(
                ("Nàng Sotori', công chúa", "indent", 0.50),
                ("cổ tích.", "last"),
                ("1. Một nhân vật trong", "body", 0.70),
                ("truyền thuyết.", "last"),
            )
        ]
    )
    assert book.notes == ["Một nhân vật trong truyền thuyết."]
    assert texts(book) == [f"Nàng Sotori{note_ref(1)}, công chúa cổ tích."]
    md = to_markdown(book, "Sách")
    assert "Sotori[^1], công chúa" in md
    assert md.rstrip().endswith("[^1]: Một nhân vật trong truyền thuyết.")


def test_ocr_single_quote_opening_dialogue_fixed(page):
    book = build_book(
        [
            page(
                ("'Đương nhiên là có rồi.\" Kazuma", "indent"),
                ("nói.", "last"),
                ("'tôi' là người kể.", "indent"),
            )
        ]
    )
    assert texts(book) == ['"Đương nhiên là có rồi." Kazuma nói.', "'tôi' là người kể."]
