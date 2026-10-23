"""Dựng nội dung sách từ các dòng OCR của từng trang.

  - bỏ header/footer (tên sách, tên tác giả, số trang) và dòng rác,
  - nhận tiêu đề chương (các dòng căn giữa ở đầu trang),
  - tách chú thích cuối trang, đánh dấu vị trí số mũ trong thân bài,
  - ghép dòng thành đoạn (theo thụt đầu dòng), nối đoạn bị ngắt giữa hai trang.

Không phụ thuộc OCR engine: chỉ cần các dòng có toạ độ chuẩn hoá (xem ocr.Line).
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence
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
    # quote: đoạn trích (vd. lá thư trong truyện); image, table: chỉ có khi đọc từ Markdown sửa tay
    kind: Literal["h1", "h2", "p", "quote", "image", "table"]
    text: str  # chỗ có chú thích được đánh dấu bằng note_ref(n); với image là chú thích ảnh (alt)
    src: str = ""  # image: đường dẫn file ảnh, tính từ thư mục chứa file Markdown
    rows: list[list[str]] = field(default_factory=list)  # table: các ô theo hàng
    header: bool = False  # table: hàng đầu là hàng tiêu đề


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
LOCAL_LINES = 2  # so độ dài dòng với chừng này dòng ngay phía trên
FOOTER_TOP = 0.92  # dòng nằm dưới mức này (theo chiều cao trang) luôn thuộc vùng chân trang
FOOTER_MIN_TOP = 0.8  # hàng cuối trang tách xa phần trên (FOOTER_GAP) và thấp hơn mức này: chân trang
FOOTER_GAP = 1.6  # khoảng cách tới hàng trên, tính theo khoảng cách dòng thường của trang
HEADER_BOTTOM = 0.06
HEADER_MIN_PAGES = 3  # dòng đầu trang lặp lại trên chừng này trang trở lên: tên sách / tác giả in đầu trang
HEADER_MIN_PREFIX = (
    8  # dòng đầu trang bị cắt mất đầu/đuôi ("Những cánh") vẫn nhận ra nếu dài ít nhất chừng này
)
HEADER_LOOSE_BOTTOM = 0.12  # dòng đầu trang đã biết (lặp lại) thì nhận cả khi ảnh cắt chừa lề trên rộng hơn

# số mũ chú thích thường bị OCR đọc thành dấu nháy: "Sotori'"
_NOTE_MARK = re.compile(r"(?<=\w)['’ʼ`¹](?=[\s,.;:!?]|$)")
_NOTE_START = re.compile(r"^\d{1,2}[.)]\s")


def _is_upper(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) > 0.8


def _footer_top(lines: Sequence[TextLine]) -> float:
    """Mép trên vùng chân trang. Ảnh cắt rộng thì chân trang có thể nằm cao hơn FOOTER_TOP, nên
    xét theo trang: hàng cuối cùng (các dòng cùng độ cao, vd. số trang và tên sách) cách hàng trên
    xa hơn hẳn khoảng cách dòng thường thì là chân trang."""
    rows: list[list[float]] = []  # tâm các dòng, gom theo hàng
    for line in sorted(lines, key=lambda line: (line.y0 + line.y1) / 2):
        center = (line.y0 + line.y1) / 2
        if rows and center - rows[-1][-1] < 0.5 * (line.y1 - line.y0):
            rows[-1].append(center)
        else:
            rows.append([center])
    if len(rows) < 4:
        return FOOTER_TOP
    centers = [float(np.mean(r)) for r in rows]
    pitch = float(np.median(np.diff(centers)))
    last = [line for line in lines if abs((line.y0 + line.y1) / 2 - centers[-1]) < 0.5 * pitch]
    top = min(line.y0 for line in last)
    if centers[-1] - centers[-2] > FOOTER_GAP * pitch and top > FOOTER_MIN_TOP:
        return min(top, FOOTER_TOP)
    return FOOTER_TOP


def _header_key(text: str) -> str:
    """Chữ của dòng đầu trang để so giữa các trang: bỏ dấu, chữ thường, bỏ số trang ở hai đầu."""
    return re.sub(r"^[\d\s\W]+|[\d\s\W]+$", "", re.sub(r"\s+", " ", _unaccent(text)))


def _top_line(lines: Sequence[TextLine]) -> TextLine | None:
    return lines[0] if lines and lines[0].y1 < HEADER_BOTTOM else None


def running_headers(pages: Sequence[Sequence[TextLine]]) -> frozenset[str]:
    """Dòng đầu trang (tên sách, tên tác giả...) in lặp lại ở mép trên nhiều trang. Tiêu đề chương
    không tính, kể cả khi sát mép trên."""
    keys = [_header_key(top.text) for lines in pages if (top := _top_line(lines))]
    counts = Counter(k for k in keys if k and not _CHAPTER.match(k))
    # dòng bị cắt mất đầu/đuôi ("nhung canh") cũng tính cho dòng đầy đủ ("nhung canh dong kim cuong")
    total = {k: sum(n for j, n in counts.items() if _part_of(j, k)) for k in counts}
    return frozenset(k for k, n in total.items() if n >= HEADER_MIN_PAGES)


def _part_of(key: str, header: str) -> bool:
    """key là header, hoặc là header bị cắt mất đầu / đuôi (ảnh cắt sát mép)."""
    return key == header or (
        len(key) >= HEADER_MIN_PREFIX and (header.startswith(key) or header.endswith(key))
    )


def _is_header(text: str, headers: frozenset[str]) -> bool:
    key = _header_key(text)
    return bool(key) and any(_part_of(key, h) for h in headers)


def _running_flags(lines: Sequence[TextLine], headers: frozenset[str] = frozenset()) -> list[bool]:
    """Header/footer: dòng ở mép trên/dưới chỉ là số, hoặc viết hoa (tên sách, tác giả), hoặc là
    dòng đầu trang lặp lại trên nhiều trang (headers, xem running_headers)."""
    footer_top = _footer_top(lines) if lines else FOOTER_TOP
    flags = []
    for index, line in enumerate(lines):
        text = line.text.strip()
        at_bottom = line.y0 >= footer_top
        at_top = line.y1 < HEADER_BOTTOM and index == 0
        if re.fullmatch(r"[\d\s]+", text):
            flags.append(at_bottom or at_top)
        else:
            near_top = line.y1 < HEADER_LOOSE_BOTTOM and index == 0
            known = (near_top or at_bottom) and _is_header(text, headers)  # vd. tên tác giả ở chân trang đầu
            flags.append((at_bottom and _is_upper(text)) or known)
    return flags


_EDGE_NUMBER = re.compile(r"^\W*(\d{1,4})\b|\b(\d{1,4})\W*$")


def page_number(lines: Sequence[TextLine], headers: frozenset[str] = frozenset()) -> int | None:
    """Số trang in trên trang (lấy từ header/footer), None nếu không đọc được.
    Ưu tiên dòng chỉ có số; sau đó số ở đầu/cuối dòng header/footer ("SAKAGUCHI ANGO 7",
    "10 VỤ ÁN SÁT NHÂN...")."""
    flags = _running_flags(lines, headers)
    running = [line.text.strip() for line, run in zip(lines, flags, strict=True) if run]
    for text in running:
        if re.fullmatch(r"\d{1,4}", digits := text.replace(" ", "")):
            return int(digits)
    for text in running:
        if m := _EDGE_NUMBER.search(text):
            return int(m.group(1) or m.group(2))
    return None


Margin = Callable[[float], float]  # lề (trái/phải) tại độ cao y của trang

MIN_SLANT = 0.02  # lề trôi ít hơn chừng này từ dòng đầu tới dòng cuối: coi là thẳng đứng
MIN_SLANT_LINES = 8  # ít dòng hơn thì không đủ để ước lượng lề nghiêng
MARGIN_TOL = 0.015  # dòng cách đường lề trong chừng này (theo chiều rộng trang) coi là chạm lề


def _margin(ys: np.ndarray, xs: np.ndarray, side: Literal["left", "right"]) -> Margin:
    """Lề trái/phải của trang theo độ cao y.

    Thường lề thẳng đứng: trái = trung vị x0, phải = phân vị 90 của x1. Nhưng trang chụp chéo
    góc (phối cảnh) thì khối chữ là hình thang, lề trôi dần theo chiều dọc; coi lề là hằng số thì
    nửa trang trông như dòng nào cũng thụt đầu dòng / cũng là dòng cuối đoạn. Khi đó lề là đường
    thẳng x = a*y + b bao ngoài khối chữ: chạm nhiều dòng nhất mà gần như không dòng nào vượt
    qua. Dòng thụt đầu dòng, dòng ngắn (kể cả cả trang thư toàn dòng ngắn) nằm hẳn bên trong nên
    không kéo lệch nó.
    """
    const = float(np.median(xs)) if side == "left" else float(np.percentile(xs, 90))
    if len(xs) < MIN_SLANT_LINES:
        return lambda y: const
    out = -xs if side == "left" else xs  # quy về lề phải: đường bao trên của các điểm
    best, best_score = None, 0
    for i in range(len(xs)):
        for j in range(i + 1, len(xs)):
            if abs(ys[j] - ys[i]) < 0.1:  # hai dòng quá gần nhau theo chiều dọc: hệ số góc không tin được
                continue
            slope = (out[j] - out[i]) / (ys[j] - ys[i])
            resid = out - (out[i] + slope * (ys - ys[i]))
            if (resid > MARGIN_TOL * 1.5).sum() > 1:  # đường cắt vào trong khối chữ
                continue
            score = int((np.abs(resid) <= MARGIN_TOL).sum())
            if score > best_score:
                best, best_score = (i, j), score
    if best is None or best_score < MIN_SLANT_LINES // 2:
        return lambda y: const
    i, j = best
    slope = (out[j] - out[i]) / (ys[j] - ys[i])
    near = np.abs(out - (out[i] + slope * (ys - ys[i]))) <= MARGIN_TOL
    coef = np.polyfit(ys[near], out[near], 1)  # khớp lại trên các dòng chạm lề
    if side == "left":
        coef = -coef
    if abs(coef[0]) * (ys.max() - ys.min()) < MIN_SLANT:
        return lambda y: const
    return lambda y: float(np.polyval(coef, y))


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
        self.headers: frozenset[str] = frozenset()  # dòng đầu trang lặp lại (running_headers)

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
        self.book.page_numbers.append(page_number(lines, self.headers))
        body = [
            line
            for line, running in zip(lines, _running_flags(lines, self.headers), strict=True)
            if not running and not _is_noise(line.text.strip())
        ]
        if not body:
            return
        ys = np.array([(line.y0 + line.y1) / 2 for line in body])
        left = _margin(ys, np.array([line.x0 for line in body]), "left")
        right = _margin(ys, np.array([line.x1 for line in body]), "right")

        start = self._take_heading(body, left, right)
        end = self._take_footnote(body, start)
        text_lines = body[start:end]
        for k, (line, y) in enumerate(zip(text_lines, ys[start:end], strict=True)):
            self.add_line(line.text.strip(), starts_paragraph=line.x0 > left(y) + INDENT)
            # dòng cuối đoạn: ngắn hẳn so với các dòng ngay trên nó (dòng đầu trang: so với dòng dưới),
            # không so với lề cả trang: khung thư in hẹp hơn trang, các dòng dài ngang nhau là một đoạn
            near = text_lines[max(0, k - LOCAL_LINES) : k + (2 if k == 0 else 1)]
            local_right = min(right(y), max(other.x1 for other in near))
            if line.x1 < local_right - SHORT_LINE:
                self.end_paragraph()

    def _take_heading(self, body: Sequence[TextLine], left: Margin, right: Margin) -> int:
        """Tiêu đề chương = các dòng căn giữa ở đầu trang. Trả về chỉ số dòng thân bài đầu tiên."""
        i = 0
        while i < len(body):
            y = (body[i].y0 + body[i].y1) / 2
            if not (body[i].x0 > left(y) + 0.1 and body[i].x1 < right(y) - 0.1):
                break
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
    builder.headers = running_headers(pages)
    for lines in pages:
        builder.add_page(lines)
    builder.end_paragraph()
    number_chapters(builder.book)
    return builder.book


_CHAPTER = re.compile(r"^chuong\b\W*(\S*)\W*$")  # trên chữ đã bỏ dấu, chữ thường
_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50}


def _unaccent(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").lower()


def _chapter_number(token: str) -> int | None:
    """ "2" -> 2, "IV" -> 4; chữ số kiểu trang trí hay bị OCR đọc thành "I", "l", "|" -> 1."""
    token = token.lower().replace("|", "i")
    if token.isdigit():
        return int(token)
    if token and all(c in _ROMAN for c in token):
        values = [_ROMAN[c] for c in token]
        return sum(-v if i + 1 < len(values) and v < values[i + 1] else v for i, v in enumerate(values))
    return None


def number_chapters(book: Book) -> None:
    """Đổi tiêu đề chương ("CHƯƠNG I", "CHUONG 2", "Chương :") thành "Chương N" thống nhất.

    Số chương phải tăng dần: số đọc được mà không lớn hơn chương trước (hoặc không đọc được)
    thì lấy chương trước + 1; chương đầu không đọc được số thì lấy số chương sau - 1, hoặc 1.
    Số lớn hơn chương trước + 1 vẫn giữ (sách chụp bỏ qua vài chương).
    """
    heads = [b for b in book.blocks if b.kind == "h1" and _CHAPTER.match(_unaccent(b.text.strip()))]
    read = [_chapter_number(_CHAPTER.match(_unaccent(b.text.strip())).group(1)) for b in heads]
    prev = None
    for k, (block, n) in enumerate(zip(heads, read, strict=True)):
        if prev is None and n is None:
            later = next(((m, j) for j, m in enumerate(read[k + 1 :], 1) if m), None)
            n = max(1, later[0] - later[1]) if later else 1
        elif prev is not None and (n is None or n <= prev):
            n = prev + 1
        block.text = f"Chương {n}"
        prev = n
