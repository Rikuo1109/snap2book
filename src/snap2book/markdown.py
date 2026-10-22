"""Chuyển nội dung sách sang Markdown (để đọc soát, sửa lỗi OCR) và đọc ngược lại.

Dạng Markdown:
  # Tên sách
  ## Tiêu đề chương        (h1)
  ### Tiêu đề phụ          (h2)
  Các đoạn văn cách nhau bằng dòng trống; chỗ có chú thích ghi [^n].
  > đoạn trích               (vd. lá thư trong truyện; mỗi đoạn trích một dòng "> ...")
  [^n]: nội dung chú thích (cuối file)
"""

import hashlib
import re
from pathlib import Path

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
        elif block.kind == "quote":
            out += [NOTE_REF.sub(r"[^\1]", f"> {block.text}"), ""]
        else:
            out += [NOTE_REF.sub(r"[^\1]", block.text), ""]
    out += [f"[^{i}]: {text}" for i, text in enumerate(book.notes, 1)]
    return "\n".join(out) + "\n"


def from_markdown(text: str) -> tuple[Book, str | None]:
    """Đọc lại Markdown (dạng to_markdown xuất ra, có thể đã sửa tay) thành (Book, tên sách).
    Dòng liền nhau gộp thành một đoạn; đoạn mở đầu bằng "> " là đoạn trích ("> " ở các dòng sau
    của đoạn có hay không đều được, dòng chỉ có ">" ngăn hai đoạn trích);
    dòng thụt vào sau [^n]: là phần tiếp của chú thích.
    Chú thích được đánh số lại theo thứ tự xuất hiện của [^n] trong bài (typeset cần vậy)."""
    title = None
    blocks: list[Block] = []
    defs: dict[str, str] = {}
    para: list[str] = []
    quote = False  # đoạn đang đọc là đoạn trích
    note: str | None = None  # nhãn chú thích đang đọc (để nối dòng tiếp theo)

    def end_paragraph() -> None:
        nonlocal quote
        if para:
            blocks.append(Block("quote" if quote else "p", " ".join(para)))
            para.clear()
        quote = False

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
        elif line.startswith(">"):
            line = line[1:].strip()
            if not line:
                end_paragraph()
                continue
            quote = quote or not para
            para.append(line)
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


def fingerprint_path(md: Path) -> Path:
    """File ẩn cạnh file .md, ghi mã băm của nội dung snap2book đã xuất ra."""
    return md.with_name(f".{md.name}.sha256")


def ocr_path(md: Path) -> Path:
    """Nơi ghi bản OCR mới khi file .md đã được sửa tay: <tên>.ocr.md."""
    return md.with_suffix(".ocr.md")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_hand_edited(md: Path) -> bool:
    """File .md đã có và khác bản snap2book ghi lần trước (hoặc không có mã băm để so,
    vd. file xuất từ bản cũ) thì coi là đã sửa tay."""
    if not md.exists():
        return False
    try:
        recorded = fingerprint_path(md).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return True
    return recorded != _sha256(md.read_bytes())


def save_markdown(md: Path, text: str, force: bool = False) -> Path:
    """Ghi Markdown vừa xuất kèm mã băm. Nếu file .md đã được sửa tay (và không force) thì
    giữ nguyên nó, ghi bản mới ra <tên>.ocr.md. Trả về đường dẫn đã ghi."""
    if not force and is_hand_edited(md):
        out = ocr_path(md)
        out.write_text(text, encoding="utf-8")
        return out
    data = text.encode("utf-8")
    md.write_bytes(data)
    fingerprint_path(md).write_text(_sha256(data) + "\n", encoding="utf-8")
    return md
