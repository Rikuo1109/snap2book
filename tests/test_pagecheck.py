from snap2book.pagecheck import check_pages
from snap2book.structure import build_book, page_number


def numbered(page, n, footer="digits", lines=2):
    """Trang có thân bài và chân trang mang số trang n (kiểu footer như sách mẫu)."""
    body = [(f"Nội dung trang {n} dòng {k}", "body") for k in range(lines)]
    if footer == "digits":
        return page(*body, ("SAKAGUCHI ANGO", "center", 0.95), (str(n), "body", 0.96))
    if footer == "trailing":
        return page(*body, (f"SAKAGUCHI ANGO {n}", "center", 0.95))
    if footer == "leading":
        return page(*body, (f"{n} VỤ ÁN SÁT NHÂN KHÔNG LIÊN HOÀN", "body", 0.95))
    return page(*body)


def run(pages):
    return check_pages([page_number(p) for p in pages], [len(p) for p in pages])


def test_page_number_from_footer_styles(page):
    assert page_number(numbered(page, 7)) == 7
    assert page_number(numbered(page, 8, "trailing")) == 8
    assert page_number(numbered(page, 10, "leading")) == 10
    assert page_number(numbered(page, 11, None)) is None
    # số ở thân bài không phải số trang
    assert page_number(page(("Năm 1947 trời mưa", "body"), ("12", "body"))) is None


def test_page_numbers_recorded_without_changing_content(page):
    book = build_book([numbered(page, 7), numbered(page, 8, "leading")])
    assert book.page_numbers == [7, 8]
    assert all("ANGO" not in b.text and "VỤ ÁN" not in b.text for b in book.blocks)


def test_in_order_no_warnings(page):
    check = run([numbered(page, n, ("digits", "trailing", "leading")[n % 3]) for n in range(5, 14)])
    assert check.warnings == []
    assert check.duplicates == []


def test_gap(page):
    check = run([numbered(page, n) for n in (45, 46, 48, 49, 52, 53)])
    assert check.warnings == ["thiếu trang 47", "thiếu trang 50–51"]


def test_duplicate_keeps_photo_with_more_lines(page):
    pages = [numbered(page, 51), numbered(page, 52), numbered(page, 52, lines=5), numbered(page, 53)]
    check = run(pages)
    assert check.warnings == ["trang 52 chụp 2 lần: ảnh 2 và 3 (giữ ảnh 3)"]
    assert check.duplicates == [1]


def test_duplicate_tie_keeps_first(page):
    check = run([numbered(page, n) for n in (51, 52, 52, 53)])
    assert check.duplicates == [2]


def test_misread_corrected_by_neighbors():
    # 13 đọc nhầm thành 18, 15 không đọc được: đều suy ra từ hai ảnh bên cạnh
    check = check_pages([11, 12, 18, 14, None, 16], [10] * 6)
    assert check.numbers == [11, 12, 13, 14, 15, 16]
    assert check.warnings == []


def test_isolated_misread_at_end_ignored():
    check = check_pages([11, 12, 13, 81], [10] * 4)
    assert check.numbers == [11, 12, 13, None]
    assert check.warnings == ["ảnh 4: số trang đọc được (81) không khớp các ảnh bên cạnh, bỏ qua"]


def test_unknown_photos_cover_gap():
    assert check_pages([11, None, None, 14], [10] * 4).warnings == []
    assert check_pages([11, None, 15, 16], [10] * 4).warnings == [
        "thiếu khoảng 2 trang trong số trang 12–14 (ảnh 2 không rõ số trang)"
    ]


def test_out_of_order():
    check = check_pages([10, 12, 11, 13], [10] * 4)
    assert check.warnings == ["ảnh 3 (trang 11) nằm sau ảnh 2 (trang 12): sai thứ tự"]
