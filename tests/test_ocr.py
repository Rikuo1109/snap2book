from snap2book.ocr import Line, merge_rows


def test_fragments_of_one_row_are_merged_left_to_right():
    lines = [
        Line("Ayaka tựa", 0.03, 0.69, 0.99, 0.72),
        Line("', công chúa cổ tích", 0.28, 0.721, 0.99, 0.749),  # lệch xuống vài px
        Line("như nàng Sotori',", 0.03, 0.725, 0.30, 0.749),
        Line("dòng sau", 0.03, 0.76, 0.99, 0.79),
    ]
    merged = merge_rows(lines)
    assert [line.text for line in merged] == [
        "Ayaka tựa",
        "như nàng Sotori', công chúa cổ tích",  # phần chồng "'," không bị lặp
        "dòng sau",
    ]
    assert merged[1].x0 == 0.03


def test_alternate_image_reading_attached_to_matching_line():
    from snap2book.ocr import _attach_alternatives

    lines = [Line("quyết dịnh quay sang", 0, 0.1, 1, 0.13), Line("dòng khác hẳn", 0, 0.2, 1, 0.23)]
    others = [Line("dòng khác hẳn", 0, 0.21, 1, 0.24), Line("quyết định quay sang", 0, 0.11, 1, 0.14, ["x"])]
    _attach_alternatives(lines, others)
    assert lines[0].alternatives == ["quyết định quay sang", "x"]
    assert lines[1].alternatives == ["dòng khác hẳn"]
