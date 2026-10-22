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


def test_load_env(tmp_path, monkeypatch):
    from snap2book.llmfix import load_env

    env = tmp_path / ".env"
    env.write_text('# ghi chú\nSNAP2BOOK_A="khoá 1"\nSNAP2BOOK_B=\nSNAP2BOOK_C=x\n')
    monkeypatch.delenv("SNAP2BOOK_A", raising=False)
    monkeypatch.delenv("SNAP2BOOK_B", raising=False)
    monkeypatch.setenv("SNAP2BOOK_C", "sẵn có")
    load_env(env)
    import os

    assert os.environ["SNAP2BOOK_A"] == "khoá 1"
    assert "SNAP2BOOK_B" not in os.environ  # để trống: coi như chưa điền
    assert os.environ["SNAP2BOOK_C"] == "sẵn có"
    monkeypatch.delenv("SNAP2BOOK_A")


def test_cli_chapter_with_title(tmp_path, monkeypatch):
    import snap2book.llmfix
    from snap2book.cli import main

    md = tmp_path / "sach.md"
    md.write_text("# Sách\n\n## Chương 1\n\nThể nhưng.\n\n## Chương 2 - Tên chương\n\nThể nhưng.\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(snap2book.llmfix, "claude_ask", lambda: fake_ask({"Thể nhưng.": "Thế nhưng."}))
    main(["llmfix", str(md), "--chapter", "2", "-o", str(tmp_path / "ra.md")])
    out = (tmp_path / "ra.md").read_text()
    assert out == "# Sách\n\n## Chương 1\n\nThể nhưng.\n\n## Chương 2 - Tên chương\n\nThế nhưng.\n"
