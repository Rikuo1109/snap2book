from snap2book.llmfix import diacritic_only, fix_paragraphs


def fake_ask(replies):
    """Model giả: trả lời theo bảng đoạn gốc → đoạn sửa, không có thì trả y nguyên."""
    calls = []

    def ask(items):
        calls.append(items)
        return {it["id"]: replies.get(it["text"], it["text"]) for it in items}, 100, 20

    ask.calls = calls
    return ask


def test_diacritic_only():
    assert diacritic_only("trò", "trở")
    assert diacritic_only("Chăng", "Chẳng")
    assert diacritic_only("dịnh", "định")
    assert not diacritic_only("Chăng", "chẳng")  # đổi hoa/thường
    assert not diacritic_only("mày", "mấy ai")
    assert not diacritic_only("nao", "nào đó")
    assert not diacritic_only("ngu", "ngủ.")


def test_only_diacritic_changes_applied():
    text = "Hắn trò thành kẻ khác. Chăng bao lâu sau[^1], hắn đi."
    reply = "Hắn trở thành người khác. Chẳng bao lâu sau[^1], hắn đi."
    result = fix_paragraphs([text], fake_ask({text: reply}))
    assert result.paragraphs == ["Hắn trở thành kẻ khác. Chẳng bao lâu sau[^1], hắn đi."]
    assert [(c.before, c.after) for c in result.changes] == [("trò", "trở"), ("Chăng", "Chẳng")]
    assert result.rejected == [(0, "kẻ", "người")]


def test_structure_change_keeps_original():
    text = "Thể nhưng, hắn không đến."
    result = fix_paragraphs([text], fake_ask({text: "Thế nhưng hắn lại không đến."}))
    assert result.paragraphs == [text]
    assert result.changes == []


def test_only_selected_paragraphs_sent_and_usage_counted():
    paras = ["## Chương 1", "Thể nhưng hắn đi.", "", "Chăng ai biết."]
    ask = fake_ask({"Thể nhưng hắn đi.": "Thế nhưng hắn đi."})
    result = fix_paragraphs(paras, ask, [1, 3])
    assert [it["id"] for batch in ask.calls for it in batch] == [1, 3]
    assert result.paragraphs == ["## Chương 1", "Thế nhưng hắn đi.", "", "Chăng ai biết."]
    assert (result.usage.calls, result.usage.input_tokens, result.usage.output_tokens) == (1, 100, 20)


def test_missing_reply_keeps_original():
    result = fix_paragraphs(["Thể nhưng"], lambda items: ({}, 5, 0))
    assert result.paragraphs == ["Thể nhưng"]
