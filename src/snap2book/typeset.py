"""Dàn trang nội dung sách thành PDF chữ.

  - chú thích đặt ở chân trang có số mũ, có vạch ngăn,
  - không để 1 dòng lẻ của đoạn ở cuối/đầu trang, không để tiêu đề nằm cuối trang,
  - số trang ở giữa chân trang, chỉ nhúng các ký tự font thực dùng.

Dùng pymupdf.Story (HTML + CSS). Story không hỗ trợ widows/orphans hay chú thích chân
trang, nên dàn nháp nhiều lượt: sau mỗi lượt đọc lại vị trí từng dòng và số mũ, rồi
chỉnh giới hạn đáy của từng trang cho tới khi ổn định.
"""

import html
import io
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import pymupdf

from snap2book.structure import NOTE_REF, Book

FONT_DIR = "/System/Library/Fonts/Supplemental"  # Times New Roman có đủ dấu tiếng Việt
FONT_FILE = "Times New Roman.ttf"

BODY_PT = 11
NOTE_PT = 9
CSS = f"""
@font-face {{ font-family: Body; src: url("Times New Roman.ttf"); }}
@font-face {{ font-family: Body; src: url("Times New Roman Bold.ttf"); font-weight: bold; }}
@font-face {{ font-family: Body; src: url("Times New Roman Italic.ttf"); font-style: italic; }}
* {{ font-family: Body; }}
body {{ font-size: {BODY_PT}pt; line-height: 1.25; text-align: justify; }}
h1 {{ font-size: 15pt; text-align: center; margin: 0 0 2pt 0; }}
h2 {{ font-size: 12.5pt; text-align: center; font-style: italic; font-weight: normal; margin: 0 0 8pt 0; }}
p {{ text-indent: 1.4em; margin: 0; }}
p.first {{ text-indent: 0; }}
p.note {{ font-size: {NOTE_PT}pt; line-height: 1.2; text-indent: 0; }}
"""
HEADING_MIN_PT = BODY_PT + 1  # dòng có chữ lớn hơn mức này là tiêu đề


@dataclass(frozen=True)
class PageStyle:
    size: str = "a5"
    margin: float = 24  # lề trên/trái/phải (pt)
    footer: float = 14  # chỗ cho số trang, thêm vào lề dưới
    note_gap: float = 8  # khoảng giữa thân trang và phần chú thích
    rule_width: float = 72  # độ dài vạch ngăn chú thích
    max_passes: int = 200


DEFAULT_STYLE = PageStyle()


class Row(NamedTuple):
    """Một dòng chữ đã dàn (đơn vị pt)."""

    y0: float
    y1: float
    x0: float
    size: float  # cỡ chữ lớn nhất trong dòng


def _story(body: str) -> pymupdf.Story:
    return pymupdf.Story(html=body, user_css=CSS, archive=pymupdf.Archive(FONT_DIR))


def _book_html(book: Book) -> str:
    parts = []
    after_heading = True
    for block in book.blocks:
        text = NOTE_REF.sub(r"<sup>\1</sup>", html.escape(block.text))
        if block.kind in ("h1", "h2"):
            parts.append(f"<{block.kind}>{text}</{block.kind}>")
            after_heading = True
        else:
            parts.append(f'<p class="first">{text}</p>' if after_heading else f"<p>{text}</p>")
            after_heading = False
    return "".join(parts)


def _read_rows(doc: pymupdf.Document) -> tuple[dict[int, int], list[list[Row]]]:
    """Từ bản dàn nháp: ({số chú thích: trang chứa số mũ}, các dòng chữ của từng trang).
    Số mũ thứ k theo thứ tự xuất hiện là chú thích k."""
    notes: dict[int, int] = {}
    pages = []
    for pg, page in enumerate(doc):
        rows: list[list[float]] = []  # số mũ có thể là dòng riêng trong get_text nên gộp theo y
        for blk in page.get_text("dict")["blocks"]:
            for line in blk.get("lines", []):
                spans = [sp for sp in line["spans"] if sp["text"].strip()]
                if not spans:
                    continue
                for sp in spans:
                    if sp["flags"] & pymupdf.TEXT_FONT_SUPERSCRIPT and sp["text"].strip().isdigit():
                        notes[len(notes) + 1] = pg
                x0, y0, _, y1 = line["bbox"]
                size = max(sp["size"] for sp in spans)
                for r in rows:
                    if abs((r[0] + r[1]) / 2 - (y0 + y1) / 2) < 3:
                        r[2], r[3] = min(r[2], x0), max(r[3], size)
                        break
                else:
                    rows.append([y0, y1, x0, size])
        pages.append([Row(*r) for r in sorted(rows)])
    return notes, pages


def fix_first_bad_break(pages: list[list[Row]], limits: dict[int, float]) -> bool:
    """Tìm chỗ ngắt trang đầu tiên để lại dòng mồ côi / tiêu đề lẻ cuối trang và đặt
    limits[trang] (toạ độ đáy tối đa của thân trang) để dời chỗ ngắt. True nếu có sửa."""
    # lề trái thực của chữ; dòng thụt vào hơn = đầu đoạn
    indent_x = min(r.x0 for rows in pages for r in rows if r.size < HEADING_MIN_PT) + 5

    def is_head(r: Row) -> bool:
        return r.size >= HEADING_MIN_PT

    def starts_paragraph(rows: list[Row], i: int) -> bool:
        return rows[i].x0 > indent_x or (i > 0 and is_head(rows[i - 1]))

    for pg in range(len(pages) - 1):
        cur, nxt = pages[pg], pages[pg + 1]
        if not cur or not nxt:
            continue
        # tiêu đề nằm cuối trang: đẩy cả cụm tiêu đề sang trang sau
        if is_head(cur[-1]):
            i = len(cur) - 1
            while i > 0 and is_head(cur[i - 1]):
                i -= 1
            limits[pg] = cur[i].y0 + 1
            return True
        if nxt[0].x0 > indent_x:  # trang sau mở đầu bằng đoạn mới
            continue
        # số dòng của đoạn bị ngắt ở cuối trang này (tail) / đầu trang sau (head)
        start = len(cur) - 1
        while start > 0 and not is_head(cur[start]) and not starts_paragraph(cur, start):
            start -= 1
        tail = len(cur) - start
        head = 1
        while head < len(nxt) and nxt[head].x0 <= indent_x and not is_head(nxt[head]):
            head += 1
        if tail < 2 or (head < 2 and tail < 3):
            limits[pg] = cur[start].y0 + 1  # đẩy cả đoạn sang trang sau
            return True
        if head < 2:
            limits[pg] = cur[-1].y0 + 1  # kéo thêm 1 dòng xuống trang sau
            return True
    return False


class Typesetter:
    def __init__(self, book: Book, style: PageStyle = DEFAULT_STYLE):
        self.book = book
        self.style = style
        self.body = _book_html(book)
        self.page = pymupdf.paper_rect(style.size)
        m = style.margin
        self.content = self.page + (m, m, -m, -m - style.footer)

    def _notes_html(self, nums: list[int]) -> str:
        return "".join(f'<p class="note">{n}. {html.escape(self.book.notes[n - 1])}</p>' for n in nums)

    def _notes_height(self, nums: list[int]) -> float:
        _, filled = _story(self._notes_html(nums)).place(pymupdf.Rect(0, 0, self.content.width, 10000))
        return pymupdf.Rect(filled).height + self.style.note_gap

    def _render(
        self, target, reserve: dict[int, float], limits: dict[int, float], notes_on: dict[int, list[int]]
    ) -> dict[int, float]:
        """Dàn toàn bộ sách vào target. Trang i: chừa reserve[i] pt ở đáy cho chú thích
        notes_on[i], thân trang không xuống quá limits[i]. Trả về {trang: y vạch ngăn}."""
        c, gap = self.content, self.style.note_gap
        writer = pymupdf.DocumentWriter(target)
        story = _story(self.body)
        rules = {}
        page_no, more = 0, True
        while more:
            h = reserve.get(page_no, 0)
            bottom = min(c.y1 - h, limits.get(page_no, c.y1))
            dev = writer.begin_page(self.page)
            more, _ = story.place(pymupdf.Rect(c.x0, c.y0, c.x1, bottom))
            story.draw(dev)
            if nums := notes_on.get(page_no):
                notes = _story(self._notes_html(nums))
                notes.place(pymupdf.Rect(c.x0, c.y1 - h + gap, c.x1, c.y1))
                notes.draw(dev)
                rules[page_no] = c.y1 - h + gap * 0.4
            writer.end_page()
            page_no += 1
        writer.close()
        return rules

    def _plan(self) -> tuple[dict[int, float], dict[int, float], dict[int, list[int]]]:
        """Dàn nháp lặp lại tới khi ổn định: chú thích đúng trang có số mũ (chừa chỗ có thể
        đẩy số mũ sang trang sau), rồi sửa từng chỗ ngắt trang xấu từ đầu sách trở đi."""
        limits: dict[int, float] = {}
        reserve: dict[int, float] = {}
        notes_on: dict[int, list[int]] = {}
        for _ in range(self.style.max_passes):
            buf = io.BytesIO()
            self._render(buf, reserve, limits, {})
            with pymupdf.open("pdf", buf.getvalue()) as draft:
                where, rows = _read_rows(draft)
            notes_on = {}
            for n, pg in sorted(where.items()):
                notes_on.setdefault(pg, []).append(n)
            new_reserve = {pg: self._notes_height(nums) for pg, nums in notes_on.items()}
            if new_reserve != reserve:
                reserve = new_reserve
                continue
            if not fix_first_bad_break(rows, limits):
                break
        return reserve, limits, notes_on

    def write(self, out_path: Path, title: str) -> int:
        """Ghi PDF, trả về số trang."""
        reserve, limits, notes_on = self._plan()
        buf = io.BytesIO()
        rules = self._render(buf, reserve, limits, notes_on)

        c = self.content
        with pymupdf.open("pdf", buf.getvalue()) as doc:
            for i, page in enumerate(doc):
                number_box = pymupdf.Rect(
                    0,
                    page.rect.height - self.style.margin - self.style.footer + 4,
                    page.rect.width,
                    page.rect.height,
                )
                page.insert_textbox(
                    number_box,
                    str(i + 1),
                    fontsize=NOTE_PT,
                    fontname="Body",
                    fontfile=f"{FONT_DIR}/{FONT_FILE}",
                    align=pymupdf.TEXT_ALIGN_CENTER,
                )
                if i in rules:
                    page.draw_line((c.x0, rules[i]), (c.x0 + self.style.rule_width, rules[i]), width=0.5)
            doc.set_metadata({"title": title})
            doc.subset_fonts()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            doc.save(out_path, garbage=4, deflate=True)
            return doc.page_count


def to_pdf(book: Book, title: str, out_path: Path, style: PageStyle = DEFAULT_STYLE) -> int:
    """Dàn trang sách ra PDF chữ, trả về số trang."""
    return Typesetter(book, style).write(out_path, title)
