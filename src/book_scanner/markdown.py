"""Xuất nội dung sách ra Markdown (để đọc soát, sửa lỗi OCR)."""

from book_scanner.structure import NOTE_REF, Book

_HEADING = {"h1": "##", "h2": "###"}  # "#" dành cho tên sách


def to_markdown(book: Book, title: str) -> str:
    out = [f"# {title}", ""]
    for block in book.blocks:
        if block.kind in _HEADING:
            out += [f"{_HEADING[block.kind]} {block.text}", ""]
        else:
            out += [NOTE_REF.sub(r"[^\1]", block.text), ""]
    out += [f"[^{i}]: {text}" for i, text in enumerate(book.notes, 1)]
    return "\n".join(out) + "\n"
