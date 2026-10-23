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
    assert texts(book, "h1") == ["Chương 1"]
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


def test_footer_found_above_fixed_line_when_page_cropped_loosely(page):
    body = [(f"dòng nội dung {k} của trang sách", "body") for k in range(20)]
    lines = page(*body)  # các dòng cách nhau 0.035, dòng cuối ở khoảng 0.72
    lines += page(("22", "last", 0.83), ("VỤ ÁN SÁT NHÂN KHÔNG LIÊN HOÀN", "center", 0.83))
    book = build_book([lines])
    assert "VỤ ÁN" not in " ".join(b.text for b in book.blocks)
    assert "22" not in " ".join(b.text for b in book.blocks)
    assert book.page_numbers == [22]


def test_last_body_line_not_mistaken_for_footer(page):
    body = [(f"dòng {k} của đoạn văn rất dài", "body") for k in range(20)]
    lines = page(*body, ("HẾT", "center"))  # chữ hoa nhưng sát ngay dòng trên: không phải chân trang
    assert "HẾT" in " ".join(b.text for b in build_book([lines]).blocks)


def test_letter_box_lines_join_into_one_paragraph(page):
    lines = page(
        ("Đó là buổi sáng ngày mười tháng Bảy và tôi nhận", "indent"),
        ("được một lá thư từ Kazuma.", "last"),
        ("Trong thư nói rằng:", "last"),
    )
    # khung thư hẹp hơn trang: các dòng dài ngang nhau (~0.75) là một đoạn, chỉ dòng cuối ngắn
    for k, text in enumerate(
        [
            "Văn phòng du lịch sẽ gửi vé",
            "cho anh vào ngày mười lăm",
            "tháng Bảy, nên xin hãy đến",
            "bằng chuyến tàu cuối ngày.",
        ]
    ):
        x1 = 0.75 if k < 3 else 0.45
        lines.append(type(lines[0])(text, 0.10 if k == 0 else 0.05, 0.2 + 0.035 * k, x1, 0.23 + 0.035 * k))
    lines += page(*[(f"dòng thường số {k} của trang", "body") for k in range(6)])
    for i, line in enumerate(lines[-6:]):
        line.y0, line.y1 = 0.4 + 0.035 * i, 0.43 + 0.035 * i
    paras = texts(build_book([lines]))
    letter = "Văn phòng du lịch sẽ gửi vé cho anh vào ngày mười lăm tháng Bảy, nên xin hãy đến"
    assert f"{letter} bằng chuyến tàu cuối ngày." in paras


def test_subtitle_still_a_heading_on_page_full_of_short_lines(page):
    rows = [("CHƯƠNG 2", "center"), ("Những kẻ không ai ngờ", "center")]
    rows += [("Đoạn mở đầu của chương", "body", 0.25)]
    rows += [(f"dòng đầy {k} của đoạn mở đầu", "body") for k in range(6)]
    rows += [(f"dòng ngắn {k}", "last") for k in range(12)]  # lá thư: nhiều dòng ngắn hơn dòng đầy
    book = build_book([page(*rows)])
    assert texts(book, "h1") == ["Chương 2"]
    assert texts(book, "h2") == ["Những kẻ không ai ngờ"]


def chapters(*titles):
    from snap2book.structure import Block, Book, number_chapters

    book = Book([Block("h1", t) for t in titles] + [Block("h1", "Lời bạt")])
    number_chapters(book)
    return [b.text for b in book.blocks]


def test_chapter_titles_normalized_and_numbered():
    # "I" là số 1 in bằng font trang trí; "CHUONG" thiếu dấu; tiêu đề không phải chương giữ nguyên
    assert chapters("CHƯƠNG I", "CHUONG 2", "Chương 3") == ["Chương 1", "Chương 2", "Chương 3", "Lời bạt"]
    assert chapters("CHƯƠNG IV", "CHƯƠNG V") == ["Chương 4", "Chương 5", "Lời bạt"]


def test_unreadable_or_wrong_chapter_numbers_follow_order():
    assert chapters("CHƯƠNG :", "CHƯƠNG 3") == ["Chương 2", "Chương 3", "Lời bạt"]  # suy ra từ chương sau
    assert chapters("CHƯƠNG 2", "CHƯƠNG 2", "CHƯƠNG") == ["Chương 2", "Chương 3", "Chương 4", "Lời bạt"]
    assert chapters("CHƯƠNG 1", "CHƯƠNG 5") == ["Chương 1", "Chương 5", "Lời bạt"]  # chụp bỏ qua vài chương


def test_recurring_top_headers_removed(page):
    # tên sách / tác giả in luân phiên ở mép trên; một trang bị cắt mất đuôi dòng đầu trang
    title, author = "Những cánh đồng kim cương", "Russell H. Conwell"
    heads = [title, author, "Những cánh", author, title, author]
    pages = []
    for k, head in enumerate(heads):
        rows = [(head, "center", 0.003)]
        rows += [(f"trang {k} dòng {i} của bài giảng dài", "body", 0.06 + 0.035 * i) for i in range(10)]
        pages.append(page(*rows))
    text = " ".join(b.text for b in build_book(pages).blocks)
    assert "Conwell" not in text and "Những cánh" not in text
    assert "dài trang 1 dòng 0" in text  # đoạn nối liền qua trang, không bị dòng đầu trang chen vào


def test_chapter_heading_at_top_is_not_a_running_header(page):
    pages = [
        page((f"CHƯƠNG {k}", "center", 0.003), (f"Nội dung chương {k}.", "last", 0.1)) for k in (1, 2, 3)
    ]
    text = " ".join(b.text for b in build_book(pages).blocks)
    assert all(f"hương {k}" in text for k in (1, 2, 3))  # không bị coi là dòng đầu trang mà bỏ đi


def test_known_header_cut_at_start_lower_or_at_bottom(page):
    author = "Russell H. Conwell"

    def rows(k, head, y=0.003):
        body = [(f"trang {k} dòng {i} của bài giảng dài", "body", 0.12 + 0.035 * i) for i in range(10)]
        return [(head, "center", y), *body]

    pages = [page(*rows(k, author)) for k in range(3)]
    pages.append(page(*rows(3, "H. Conwell")))  # ảnh cắt mất đầu dòng
    pages.append(page(*rows(4, author, 0.074)))  # ảnh chừa lề trên rộng
    pages.append(page(*rows(5, "Lời nói đầu")[1:], (author, "center", 0.977)))  # tên tác giả ở chân trang
    text = " ".join(b.text for b in build_book(pages).blocks)
    assert "Conwell" not in text


def test_last_line_matching_header_tail_is_kept(page):
    title = "Những cánh đồng kim cương"
    pages = []
    for k in range(4):
        body = [(f"trang {k} dòng {i} nói về quả cầu lửa nguội", "body", 0.06 + 0.035 * i) for i in range(25)]
        pages.append(page((title, "center", 0.003), *body))
    pages[1].append(
        type(pages[1][0])("kim cương.", 0.01, 0.973, 0.24, 0.999)
    )  # dòng cuối đoạn sát chân trang
    assert "kim cương." in " ".join(b.text for b in build_book(pages).blocks)
