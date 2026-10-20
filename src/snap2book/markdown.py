"""Chuyển nội dung sách sang Markdown (để đọc soát, sửa lỗi OCR) và đọc ngược lại.

Dạng Markdown:
  # Tên sách
  ## Tiêu đề chương        (h1)
  ### Tiêu đề phụ          (h2)
  Các đoạn văn cách nhau bằng dòng trống; chỗ có chú thích ghi [^n].
  [^n]: nội dung chú thích (cuối file)
"""

import re

from snap2book.structure import NOTE_REF, Block, Book, note_ref

_HEADING = {"h1": "##", "h2": "###"}  # "#" dành cho tên sách
_KIND = {v: k for k, v in _HEADING.items()}
_HEADING_LINE = re.compile(r"(#{1,3})\s+(.*)")
_FOOTNOTE_REF = re.compile(r"\[\^(\w+)\](?!:)")
_FOOTNOTE_DEF = re.compile(r"\[\^(\w+)\]:\s*(.*)")


def to_markdown(book: Book, title: str) -> str:
    out = [f"# {title}", ""]
    for block in book.blocks:
        if block.kind in _HEADING:
            out += [f"{_HEADING[block.kind]} {block.text}", ""]
        else:
            out += [NOTE_REF.sub(r"[^\1]", block.text), ""]
    out += [f"[^{i}]: {text}" for i, text in enumerate(book.notes, 1)]
    return "\n".join(out) + "\n"


def from_markdown(text: str) -> tuple[Book, str | None]:
    """Đọc lại Markdown (dạng to_markdown xuất ra, có thể đã sửa tay) thành (Book, tên sách).
    Dòng liền nhau gộp thành một đoạn; dòng thụt vào sau [^n]: là phần tiếp của chú thích.
    Chú thích được đánh số lại theo thứ tự xuất hiện của [^n] trong bài (typeset cần vậy)."""
    title = None
    blocks: list[Block] = []
    defs: dict[str, str] = {}
    para: list[str] = []
    note: str | None = None  # nhãn chú thích đang đọc (để nối dòng tiếp theo)

    def end_paragraph() -> None:
        if para:
            blocks.append(Block("p", " ".join(para)))
            para.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if note is not None and line and raw[:1].isspace():
            defs[note] += " " + line
            continue
        note = None
        if not line:
            end_paragraph()
        elif m := _FOOTNOTE_DEF.fullmatch(line):
            end_paragraph()
            note = m[1]
            defs[note] = m[2].strip()
        elif m := _HEADING_LINE.fullmatch(line):
            end_paragraph()
            if m[1] == "#":
                title = title or m[2].strip()
            else:
                blocks.append(Block(_KIND[m[1]], m[2].strip()))
        else:
            para.append(line)
    end_paragraph()

    # đánh số lại: chú thích thứ k là [^...] thứ k xuất hiện trong bài
    order: dict[str, int] = {}

    def renumber(m: re.Match) -> str:
        label = m[1]
        if label not in defs:
            raise ValueError(f"Chú thích [^{label}] không có nội dung ([^{label}]: ...)")
        order.setdefault(label, len(order) + 1)
        return note_ref(order[label])

    for block in blocks:
        block.text = _FOOTNOTE_REF.sub(renumber, block.text)
    for label in defs:  # chú thích không được tham chiếu: giữ ở cuối
        order.setdefault(label, len(order) + 1)
    notes = [defs[label] for label in sorted(order, key=order.get)]
    return Book(blocks, notes), title
