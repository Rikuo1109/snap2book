"""OCR các trang đã làm sạch (Apple Vision) và dựng lại nội dung liền mạch.

Từ các dòng OCR của từng trang:
  - bỏ header/footer (tên sách, tên tác giả, số trang),
  - nhận tiêu đề chương (dòng căn giữa ở đầu trang),
  - tách chú thích cuối trang,
  - ghép dòng thành đoạn (theo thụt đầu dòng), nối đoạn bị ngắt giữa hai trang.
Rồi xuất Markdown và PDF dàn trang lại.
"""
import html
import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import pymupdf as fitz
import Foundation
import numpy as np
import Vision

FONT_DIR = "/System/Library/Fonts/Supplemental"  # Times New Roman có đủ dấu tiếng Việt


# ---------------------------------------------------------------- OCR

@dataclass
class Line:
    text: str
    x0: float  # toạ độ chuẩn hoá 0..1, gốc trên-trái
    y0: float
    x1: float
    y1: float


def _vision_ocr(img):
    ok, buf = cv2.imencode(".png", img)
    data = Foundation.NSData.dataWithBytes_length_(buf.tobytes(), len(buf))
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setRecognitionLanguages_(["vi-VT"])
    req.setUsesLanguageCorrection_(True)
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"Vision OCR lỗi: {err}")
    lines = []
    for obs in req.results() or []:
        b = obs.boundingBox()  # gốc dưới-trái
        y0 = 1 - b.origin.y - b.size.height
        lines.append(Line(obs.topCandidates_(1)[0].string(),
                          b.origin.x, y0, b.origin.x + b.size.width, y0 + b.size.height))
    return lines


def ocr_page(img):
    """OCR một trang (ảnh xám, nền trắng). Xử lý riêng chữ hoa lớn đầu chương (drop cap):
    để nguyên thì Vision gộp 2 dòng cạnh nó thành 1 dòng sai, nên xoá đi, OCR riêng rồi ghép lại."""
    h, w = img.shape
    ink = (img < 128).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    heights = [s[3] for s in stats[1:] if s[4] > 30]
    if not heights:
        return []
    glyph_h = np.median(heights)

    clean = img.copy()
    caps = []
    for x, y, bw, bh, area in stats[1:]:
        # chữ cao > 2.5 lần chữ thường, nằm ở lề trái, dưới vùng tiêu đề
        if 2.5 * glyph_h < bh < 6 * glyph_h and x < 0.15 * w and y > 0.1 * h:
            caps.append((x, y, bw, bh))
            # thu nhỏ về cỡ chữ hoa thường, đặt sát đầu dòng thứ nhất
            nh = int(glyph_h * 1.6)
            nw = max(1, int(bw * nh / bh))
            small = cv2.resize(img[y:y + bh, x:x + bw], (nw, nh), interpolation=cv2.INTER_AREA)
            clean[y:y + bh, x:x + bw] = 255
            clean[y:y + nh, x + bw - nw:x + bw] = np.minimum(clean[y:y + nh, x + bw - nw:x + bw], small)

    lines = _vision_ocr(clean)
    # các dòng nằm cạnh drop cap thực ra không thụt đầu dòng
    for x, y, bw, bh in caps:
        for l in lines:
            if l.y0 * h < y + bh and l.y1 * h > y and l.x0 * w < x + bw * 2:
                l.x0 = 0.0
    lines.sort(key=lambda l: (l.y0, l.x0))
    return lines


# ---------------------------------------------------------------- dựng nội dung

@dataclass
class Block:
    kind: str  # "h1" | "h2" | "p"
    text: str


@dataclass
class Book:
    blocks: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def _is_upper(s):
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) > 0.8


def _running_lines(pages):
    """Header/footer: dòng ở mép trên/dưới chỉ là số, hoặc viết hoa (tên sách, tác giả)."""
    drop = set()
    for pi, lines in enumerate(pages):
        for li, l in enumerate(lines):
            text = l.text.strip()
            digits_only = re.fullmatch(r"[\d\s]+", text) is not None
            at_bottom = l.y0 > 0.92
            at_top = l.y1 < 0.06 and li == 0
            if digits_only and (at_bottom or at_top):
                drop.add((pi, li))
            elif at_bottom and _is_upper(text):
                drop.add((pi, li))
    return drop


NOTE_MARK = re.compile(r"(?<=\w)['’ʼ`¹](?=[\s,.;:!?]|$)")  # số mũ chú thích OCR thường ra dấu nháy


def _is_noise(text):
    """Dòng rác (mẩu logo, vết bẩn): gần như không có chữ."""
    return sum(c.isalpha() for c in text) < 2 and not re.fullmatch(r"[\W\d]*[.!?…\"”]", text)


def build_book(pages):
    """pages: list[list[Line]] theo thứ tự trang."""
    book = Book()
    drop = _running_lines(pages)
    cur = None  # đoạn đang dở (có thể kéo sang trang sau)

    def flush():
        nonlocal cur
        if cur:
            book.blocks.append(Block("p", re.sub(r"\s+", " ", cur).strip()))
        cur = None

    for pi, lines in enumerate(pages):
        body = [l for li, l in enumerate(lines) if (pi, li) not in drop and not _is_noise(l.text.strip())]
        if not body:
            continue
        left = float(np.median([l.x0 for l in body]))
        right = float(np.percentile([l.x1 for l in body], 90))
        centers = [(l.y0 + l.y1) / 2 for l in body]
        pitches = np.diff(centers)
        pitch = float(np.median(pitches)) if len(pitches) else 1.0
        indent = 0.03

        # tiêu đề chương: các dòng căn giữa ở đầu trang
        i = 0
        heads = []
        while i < len(body) and body[i].x0 > left + 0.1 and body[i].x1 < right - 0.1:
            heads.append(body[i].text.strip())
            i += 1
        if heads and i < len(body) and body[0].y0 < 0.25:
            flush()
            book.blocks.append(Block("h1", heads[0]))
            if len(heads) > 1:
                book.blocks.append(Block("h2", " ".join(heads[1:])))
        else:
            i = 0

        # chú thích cuối trang: dòng "1. ..." ở nửa dưới, cách dòng trên xa hơn hẳn bình thường
        fi = len(body)
        for j in range(max(i, 1), len(body)):
            if (re.match(r"^\d{1,2}[.)]\s", body[j].text.strip()) and body[j].y0 > 0.5
                    and centers[j] - centers[j - 1] > 1.4 * pitch):
                fi = j
                break
        if fi < len(body):
            note = " ".join(l.text.strip() for l in body[fi:])
            book.notes.append(re.sub(r"^\d{1,2}[.)]\s*", "", note))
            # đánh dấu vị trí chú thích trong thân trang
            n = len(book.notes)
            for l in reversed(body[i:fi]):
                if NOTE_MARK.search(l.text):
                    l.text = NOTE_MARK.sub(f"[[{n}]]", l.text, count=1)
                    break

        for l in body[i:fi]:
            text = l.text.strip()
            new_para = l.x0 > left + indent
            if cur is None or new_para:
                flush()
                cur = text
            else:
                cur += " " + text
            # dòng ngắn hẳn = hết đoạn
            if l.x1 < right - 0.12:
                flush()
    flush()
    return book


# ---------------------------------------------------------------- xuất

def to_markdown(book, title):
    out = [f"# {title}", ""]
    for b in book.blocks:
        if b.kind == "h1":
            out += [f"## {b.text}", ""]
        elif b.kind == "h2":
            out += [f"### {b.text}", ""]
        else:
            out += [re.sub(r"\[\[(\d+)\]\]", r"[^\1]", b.text), ""]
    if book.notes:
        out += [f"[^{i}]: {t}" for i, t in enumerate(book.notes, 1)]
    return "\n".join(out) + "\n"


CSS = """
@font-face { font-family: Body; src: url("Times New Roman.ttf"); }
@font-face { font-family: Body; src: url("Times New Roman Bold.ttf"); font-weight: bold; }
@font-face { font-family: Body; src: url("Times New Roman Italic.ttf"); font-style: italic; }
* { font-family: Body; }
body { font-size: 11pt; line-height: 1.25; text-align: justify; }
h1 { font-size: 15pt; text-align: center; margin: 0 0 2pt 0; }
h2 { font-size: 12.5pt; text-align: center; font-style: italic; font-weight: normal; margin: 0 0 8pt 0; }
p { text-indent: 1.4em; margin: 0; }
p.first { text-indent: 0; }
p.note { font-size: 9pt; line-height: 1.2; text-indent: 0; }
"""


NOTE_GAP = 8  # khoảng giữa thân trang và vạch ngăn chú thích (pt)


def _story(body):
    return fitz.Story(html=body, user_css=CSS, archive=fitz.Archive(FONT_DIR))


def _notes_html(book, nums):
    return "".join(f'<p class="note">{n}. {html.escape(book.notes[n - 1])}</p>' for n in nums)


def _notes_height(book, nums, width):
    _, filled = _story(_notes_html(book, nums)).place(fitz.Rect(0, 0, width, 10000))
    return fitz.Rect(filled).height + NOTE_GAP


def _layout(body, page, content, reserve, limits, out=None, notes_on=None, book=None, rules=None):
    """Dàn thân sách. Trang i: chừa reserve[i] pt ở đáy cho chú thích, và thân trang
    không xuống quá toạ độ limits[i] (dùng để chống dòng mồ côi).
    Không có out: dàn nháp trong bộ nhớ, trả về ({số chú thích: trang}, dòng chữ từng trang).
    Có out: ghi file thật, vẽ chú thích notes_on[i] ở chân trang i."""
    import io

    target = out if out else io.BytesIO()
    writer = fitz.DocumentWriter(str(target) if out else target)
    story = _story(body)
    page_no = 0
    more = True
    while more:
        h = reserve.get(page_no, 0)
        bottom = min(content.y1 - h, limits.get(page_no, content.y1))
        dev = writer.begin_page(page)
        more, _ = story.place(fitz.Rect(content.x0, content.y0, content.x1, bottom))
        story.draw(dev)
        nums = (notes_on or {}).get(page_no)
        if nums:
            notes = _story(_notes_html(book, nums))
            notes.place(fitz.Rect(content.x0, content.y1 - h + NOTE_GAP, content.x1, content.y1))
            notes.draw(dev)
            rules[page_no] = content.y1 - h + NOTE_GAP * 0.4
        writer.end_page()
        page_no += 1
    writer.close()
    if out:
        return None

    # số mũ thứ k (theo thứ tự xuất hiện) là chú thích k
    found = {}
    pages = []
    doc = fitz.open("pdf", target.getvalue())
    for pg, p in enumerate(doc):
        rows = []  # (y0, y1, x0, cỡ chữ lớn nhất) - số mũ có thể tách thành dòng riêng nên gộp theo y
        for blk in p.get_text("dict")["blocks"]:
            for line in blk.get("lines", []):
                spans = [sp for sp in line["spans"] if sp["text"].strip()]
                for sp in spans:
                    if sp["flags"] & fitz.TEXT_FONT_SUPERSCRIPT and sp["text"].strip().isdigit():
                        found[len(found) + 1] = pg
                if not spans:
                    continue
                y0, y1 = line["bbox"][1], line["bbox"][3]
                size = max(sp["size"] for sp in spans)
                for r in rows:
                    if abs((r[0] + r[1]) / 2 - (y0 + y1) / 2) < 3:
                        r[2] = min(r[2], line["bbox"][0])
                        r[3] = max(r[3], size)
                        break
                else:
                    rows.append([y0, y1, line["bbox"][0], size])
        pages.append(sorted(rows))
    return found, pages


def _fix_break(pages, content, limits):
    """Tìm chỗ ngắt trang đầu tiên để lại dòng mồ côi; đặt limits để dời chỗ ngắt.
    Trả về True nếu có sửa."""
    # lề trái thực của chữ (Story có thể lệch so với khung), dòng thụt vào hơn = đầu đoạn
    indent_x = min(r[2] for rows in pages for r in rows if r[3] <= 12) + 5

    def kind(rows, i):
        y0, y1, x0, size = rows[i]
        if size > 12:
            return "head"
        prev_head = i > 0 and rows[i - 1][3] > 12
        return "start" if x0 > indent_x or prev_head else "cont"

    for pg in range(len(pages) - 1):
        cur, nxt = pages[pg], pages[pg + 1]
        if not cur or not nxt:
            continue
        kinds = [kind(cur, i) for i in range(len(cur))]
        # tiêu đề nằm cuối trang: đẩy cả cụm tiêu đề sang trang sau
        if kinds[-1] == "head":
            i = len(cur) - 1
            while i > 0 and kinds[i - 1] == "head":
                i -= 1
            limits[pg] = cur[i][0] + 1
            return True
        # trang sau bắt đầu bằng đoạn mới -> không có đoạn bị ngắt
        if nxt[0][2] > indent_x:
            continue
        # số dòng của đoạn bị ngắt ở cuối trang này / đầu trang sau
        start = len(cur) - 1
        while start > 0 and kinds[start] == "cont":
            start -= 1
        tail = len(cur) - start
        head = 1
        while head < len(nxt) and nxt[head][2] <= indent_x and nxt[head][3] <= 12:
            head += 1
        if tail < 2 or (head < 2 and tail - 1 < 2):
            limits[pg] = cur[start][0] + 1  # đẩy cả đoạn sang trang sau
            return True
        if head < 2:
            limits[pg] = cur[-1][0] + 1  # kéo thêm 1 dòng xuống trang sau
            return True
    return False


def to_pdf(book, title, out_path, page_size="a5"):
    parts = []
    after_heading = True
    for b in book.blocks:
        t = re.sub(r"\[\[(\d+)\]\]", r"<sup>\1</sup>", html.escape(b.text))
        if b.kind in ("h1", "h2"):
            parts.append(f"<{b.kind}>{t}</{b.kind}>")
            after_heading = True
        else:
            parts.append(f'<p class="first">{t}</p>' if after_heading else f"<p>{t}</p>")
            after_heading = False
    body = "".join(parts)

    page = fitz.paper_rect(page_size)
    margin = 24  # lề trên/trái/phải (pt); lề dưới chừa thêm chỗ cho số trang
    footer = 14
    content = page + (margin, margin, -margin, -margin - footer)

    # Dàn nháp lặp lại tới khi ổn định:
    #  - chú thích đặt ở chân trang có số mũ (chừa chỗ có thể đẩy số mũ sang trang sau),
    #  - chỗ ngắt trang không để lại 1 dòng lẻ của đoạn ở cuối/đầu trang.
    # Mỗi vòng sửa một chỗ ngắt, từ đầu sách trở đi, nên các trang trước không bị xáo lại.
    limits, reserve, notes_on = {}, {}, {}
    for _ in range(200):
        where, lines = _layout(body, page, content, reserve, limits)
        notes_on = {}
        for n, pg in sorted(where.items()):
            notes_on.setdefault(pg, []).append(n)
        new_reserve = {pg: _notes_height(book, nums, content.width) for pg, nums in notes_on.items()}
        if new_reserve != reserve:
            reserve = new_reserve
            continue
        if not _fix_break(lines, content, limits):
            break

    rules = {}
    _layout(body, page, content, reserve, limits, out_path, notes_on, book, rules)

    # số trang, vạch ngăn chú thích, metadata; chỉ nhúng các ký tự font thực dùng
    doc = fitz.open(out_path)
    for i, p in enumerate(doc, 1):
        p.insert_textbox(fitz.Rect(0, p.rect.height - margin - footer + 4, p.rect.width, p.rect.height), str(i),
                         fontsize=9, fontname="Body", fontfile=f"{FONT_DIR}/Times New Roman.ttf", align=1)
        if i - 1 in rules:
            y = rules[i - 1]
            p.draw_line((content.x0, y), (content.x0 + 72, y), width=0.5)
    doc.set_metadata({"title": title})
    doc.subset_fonts()
    tmp = out_path.with_suffix(".tmp.pdf")
    doc.save(tmp, garbage=4, deflate=True)
    doc.close()
    tmp.replace(out_path)
    doc = fitz.open(out_path)
    return len(doc)
