"""Dựng nội dung sách từ các dòng OCR của từng trang.

  - bỏ header/footer (tên sách, tên tác giả, số trang) và dòng rác,
  - nhận tiêu đề chương (các dòng căn giữa ở đầu trang),
  - tách chú thích cuối trang, đánh dấu vị trí số mũ trong thân bài,
  - ghép dòng thành đoạn (theo thụt đầu dòng), nối đoạn bị ngắt giữa hai trang.

Không phụ thuộc OCR engine: chỉ cần các dòng có toạ độ chuẩn hoá (xem ocr.Line).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

import numpy as np


class TextLine(Protocol):
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class Block:
    kind: Literal["h1", "h2", "p"]
    text: str  # chỗ có chú thích được đánh dấu bằng note_ref(n)


@dataclass
class Book:
    blocks: list[Block] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # chú thích thứ n ở notes[n - 1]
    page_numbers: list[int | None] = field(default_factory=list)  # số trang in, theo trang vào


NOTE_REF = re.compile(r"\[\[(\d+)\]\]")  # dấu tham chiếu chú thích trong Block.text


def note_ref(n: int) -> str:
    return f"[[{n}]]"


INDENT = 0.03  # dòng lùi vào hơn lề trái chừng này (theo chiều rộng trang) = đầu đoạn
SHORT_LINE = 0.12  # dòng ngắn hơn lề phải chừng này = cuối đoạn
FOOTER_TOP = 0.92  # dòng nằm dưới mức này (theo chiều cao trang) là vùng chân trang
HEADER_BOTTOM = 0.06

# số mũ chú thích thường bị OCR đọc thành dấu nháy: "Sotori'"
_NOTE_MARK = re.compile(r"(?<=\w)['’ʼ`¹](?=[\s,.;:!?]|$)")
_NOTE_START = re.compile(r"^\d{1,2}[.)]\s")


def _is_upper(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) > 0.8


def _is_running_line(line: TextLine, index: int) -> bool:
    """Header/footer: dòng ở mép trên/dưới chỉ là số, hoặc viết hoa (tên sách, tác giả)."""
    text = line.text.strip()
    at_bottom = line.y0 > FOOTER_TOP
    at_top = line.y1 < HEADER_BOTTOM and index == 0
    if re.fullmatch(r"[\d\s]+", text):
        return at_bottom or at_top
    return at_bottom and _is_upper(text)


_EDGE_NUMBER = re.compile(r"^\W*(\d{1,4})\b|\b(\d{1,4})\W*$")


def page_number(lines: Sequence[TextLine]) -> int | None:
    """Số trang in trên trang (lấy từ header/footer), None nếu không đọc được.
    Ưu tiên dòng chỉ có số; sau đó số ở đầu/cuối dòng header/footer ("SAKAGUCHI ANGO 7",
    "10 VỤ ÁN SÁT NHÂN...")."""
    running = [line.text.strip() for i, line in enumerate(lines) if _is_running_line(line, i)]
    for text in running:
        if re.fullmatch(r"\d{1,4}", digits := text.replace(" ", "")):
            return int(digits)
    for text in running:
        if m := _EDGE_NUMBER.search(text):
            return int(m.group(1) or m.group(2))
    return None


def _is_noise(text: str) -> bool:
    """Dòng rác (mẩu logo, vết bẩn): gần như không có chữ."""
    return sum(c.isalpha() for c in text) < 2 and not re.fullmatch(r"[\W\d]*[.!?…\"”]", text)


def _fix_open_quote(text: str) -> str:
    """Ngoặc kép mở đầu lời thoại hay bị OCR đọc thành nháy đơn: 'Đương nhiên..." -> "Đương nhiên..."
    Chỉ sửa khi nháy đơn đứng đầu đoạn và ngay sau là chữ hoa."""
    if text[:1] == "'" and text[1:2].isupper():
        return '"' + text[1:]
    return text


class _Builder:
    def __init__(self) -> None:
        self.book = Book()
        self.para: str | None = None  # đoạn đang dở (có thể kéo sang trang sau)

    def end_paragraph(self) -> None:
        if self.para:
            text = re.sub(r"\s+", " ", self.para).strip()
            self.book.blocks.append(Block("p", _fix_open_quote(text)))
        self.para = None

    def add_line(self, text: str, starts_paragraph: bool) -> None:
        if self.para is None or starts_paragraph:
            self.end_paragraph()
            self.para = text
        else:
            self.para += " " + text

    def add_page(self, lines: Sequence[TextLine]) -> None:
        self.book.page_numbers.append(page_number(lines))
        body = [
            line
            for i, line in enumerate(lines)
            if not _is_running_line(line, i) and not _is_noise(line.text.strip())
        ]
        if not body:
            return
        left = float(np.median([line.x0 for line in body]))
        right = float(np.percentile([line.x1 for line in body], 90))

        start = self._take_heading(body, left, right)
        end = self._take_footnote(body, start)
        for line in body[start:end]:
            self.add_line(line.text.strip(), starts_paragraph=line.x0 > left + INDENT)
            if line.x1 < right - SHORT_LINE:
                self.end_paragraph()

    def _take_heading(self, body: Sequence[TextLine], left: float, right: float) -> int:
        """Tiêu đề chương = các dòng căn giữa ở đầu trang. Trả về chỉ số dòng thân bài đầu tiên."""
        i = 0
        while i < len(body) and body[i].x0 > left + 0.1 and body[i].x1 < right - 0.1:
            i += 1
        if i == 0 or i == len(body) or body[0].y0 >= 0.25:
            return 0
        self.end_paragraph()
        heads = [line.text.strip() for line in body[:i]]
        self.book.blocks.append(Block("h1", heads[0]))
        if len(heads) > 1:
            self.book.blocks.append(Block("h2", " ".join(heads[1:])))
        return i

    def _take_footnote(self, body: Sequence[TextLine], start: int) -> int:
        """Chú thích = từ dòng "1. ..." ở nửa dưới trang, cách dòng trên xa hơn hẳn bình thường.
        Lưu chú thích, đánh dấu số mũ trong thân trang. Trả về chỉ số dòng chú thích đầu tiên."""
        centers = [(line.y0 + line.y1) / 2 for line in body]
        pitch = float(np.median(np.diff(centers))) if len(centers) > 1 else 1.0
        for j in range(max(start, 1), len(body)):
            if (
                _NOTE_START.match(body[j].text.strip())
                and body[j].y0 > 0.5
                and centers[j] - centers[j - 1] > 1.4 * pitch
            ):
                break
        else:
            return len(body)

        note = " ".join(line.text.strip() for line in body[j:])
        self.book.notes.append(_NOTE_START.sub("", note, count=1).strip())
        n = len(self.book.notes)
        for line in reversed(body[start:j]):
            if _NOTE_MARK.search(line.text):
                line.text = _NOTE_MARK.sub(note_ref(n), line.text, count=1)
                break
        return j


def build_book(pages: Sequence[Sequence[TextLine]]) -> Book:
    """Dựng nội dung từ các trang (mỗi trang là các dòng OCR sắp từ trên xuống)."""
    builder = _Builder()
    for lines in pages:
        builder.add_page(lines)
    builder.end_paragraph()
    return builder.book
