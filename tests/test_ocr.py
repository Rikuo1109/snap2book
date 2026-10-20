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
