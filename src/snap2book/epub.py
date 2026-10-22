"""Xuất sách ra EPUB 3 để đọc trên điện thoại (app Sách, Kindle...): chữ tự dàn theo màn hình,
chỉnh được cỡ chữ, có mục lục theo chương và chú thích bật lên khi bấm vào số mũ.

Mỗi chương (Block h1) là một file XHTML; phần trước chương đầu tiên (nếu có) là một file riêng.
Ảnh (Block image) được chép vào OEBPS/images/; bảng (Block table) thành <table>.
Chú thích nằm cuối chương có số mũ trỏ tới nó (epub:type="footnote"); chú thích không có số
mũ nào trỏ tới thì gom cuối sách. File tạo ra không phụ thuộc thời điểm chạy (trừ khi truyền
modified), để chạy lại cùng nội dung thì cùng file.
"""

import html
import logging
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from snap2book.structure import NOTE_REF, Block, Book

log = logging.getLogger(__name__)

LANGUAGE = "vi"
FIXED_TIME = (2020, 1, 1, 0, 0, 0)  # giờ ghi vào các mục trong file zip
FIXED_MODIFIED = "2020-01-01T00:00:00Z"

CSS = """\
body { font-family: serif; line-height: 1.5; margin: 0 4%; }
h1 { font-size: 1.4em; text-align: center; margin: 2em 0 0.3em; }
h2 { font-size: 1.1em; font-style: italic; font-weight: normal; text-align: center; margin: 0 0 2em; }
p { text-indent: 1.4em; margin: 0; text-align: justify; }
p.first { text-indent: 0; }
a.noteref { text-decoration: none; }
aside.footnote { font-size: 0.85em; margin-top: 1em; }
aside.footnote p { text-indent: 0; }
hr.notes { width: 30%; margin: 2em 0 0.5em; }
blockquote { margin: 0.6em 1.5em; font-style: italic; }
blockquote p { text-indent: 0; }
nav ol { list-style: none; padding-left: 0; }
figure { margin: 1em 0; text-align: center; }
figure img { max-width: 100%; }
figcaption { font-size: 0.85em; font-style: italic; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; font-size: 0.85em; }
th, td { border: 1px solid #888; padding: 0.2em 0.4em; vertical-align: top; text-align: left; }
"""


@dataclass
class _Chapter:
    label: str  # tên trong mục lục
    blocks: list[Block] = field(default_factory=list)


def _chapters(book: Book, title: str) -> list[_Chapter]:
    chapters: list[_Chapter] = []
    for block in book.blocks:
        if block.kind == "h1":
            chapters.append(_Chapter(block.text))
        elif not chapters:
            chapters.append(_Chapter(title))
        if block.kind == "h2" and chapters[-1].blocks and chapters[-1].blocks[-1].kind == "h1":
            chapters[-1].label += f": {block.text}"
        chapters[-1].blocks.append(block)
    return chapters or [_Chapter(title)]


def _xhtml(title: str, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
        f'xml:lang="{LANGUAGE}" lang="{LANGUAGE}">\n'
        f'<head><meta charset="utf-8"/><title>{html.escape(title)}</title>'
        '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
        f"<body>\n{body}\n</body>\n</html>\n"
    )


def _notes_html(numbers: list[int], book: Book) -> str:
    if not numbers:
        return ""
    asides = "\n".join(
        f'<aside epub:type="footnote" class="footnote" id="fn{n}">'
        f'<p><a href="#ref{n}">{n}.</a> {html.escape(book.notes[n - 1])}</p></aside>'
        for n in numbers
    )
    return f'<hr class="notes"/>\n{asides}'


MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}


def _images(book: Book, resources: Path | None) -> dict[str, Path]:
    """{src trong Markdown: file ảnh}, chỉ những ảnh đọc được và đúng định dạng."""
    found = {}
    for block in book.blocks:
        if block.kind != "image" or block.src in found:
            continue
        path = (resources or Path()) / block.src
        if path.suffix.lower() not in MEDIA_TYPES or not path.is_file():
            log.warning("  bỏ qua ảnh không đọc được: %s", path)
            continue
        found[block.src] = path
    return found


def _image_name(i: int, path: Path) -> str:
    return f"images/img{i:03d}{path.suffix.lower()}"


def _table_html(block: Block, cell) -> str:
    rows = []
    for k, row in enumerate(block.rows):
        tag = "th" if block.header and k == 0 else "td"
        rows.append("<tr>" + "".join(f"<{tag}>{cell(c)}</{tag}>" for c in row) + "</tr>")
    return "<table>\n" + "\n".join(rows) + "\n</table>"


def _chapter_html(chapter: _Chapter, book: Book, used: set[int], images: dict[str, str]) -> str:
    parts = []
    after_heading = True
    refs: list[int] = []

    def noteref(m) -> str:
        n = int(m.group(1))
        if not 1 <= n <= len(book.notes):
            return ""
        refs.append(n)
        return f'<a epub:type="noteref" class="noteref" href="#fn{n}" id="ref{n}"><sup>{n}</sup></a>'

    def cell(text: str) -> str:
        return NOTE_REF.sub(noteref, html.escape(text))

    for block in chapter.blocks:
        text = cell(block.text)
        if block.kind == "image":
            if block.src in images:
                caption = f"<figcaption>{text}</figcaption>" if block.text else ""
                parts.append(f'<figure><img src="{images[block.src]}" alt="{text}"/>{caption}</figure>')
            after_heading = False
        elif block.kind == "table":
            parts.append(_table_html(block, cell))
            after_heading = False
        elif block.kind in ("h1", "h2"):
            parts.append(f"<{block.kind}>{text}</{block.kind}>")
            after_heading = True
        elif block.kind == "quote":
            parts.append(f"<blockquote><p>{text}</p></blockquote>")
            after_heading = False
        else:
            parts.append(f'<p class="first">{text}</p>' if after_heading else f"<p>{text}</p>")
            after_heading = False
    numbers = [n for n in dict.fromkeys(refs) if n not in used]
    used.update(numbers)
    return "\n".join(parts) + "\n" + _notes_html(numbers, book)


def _nav(title: str, chapters: list[_Chapter]) -> str:
    items = "\n".join(
        f'<li><a href="chap{i:03d}.xhtml">{html.escape(c.label)}</a></li>' for i, c in enumerate(chapters, 1)
    )
    body = f'<nav epub:type="toc" id="toc"><h1>Mục lục</h1>\n<ol>\n{items}\n</ol>\n</nav>'
    return _xhtml(title, body)


def _opf(title: str, chapters: list[_Chapter], modified: str, images: dict[str, str]) -> str:
    book_id = uuid.uuid5(uuid.NAMESPACE_URL, f"snap2book:{title}")
    items = "\n".join(
        f'    <item id="chap{i:03d}" href="chap{i:03d}.xhtml" media-type="application/xhtml+xml"/>'
        for i in range(1, len(chapters) + 1)
    )
    for k, name in enumerate(images.values(), 1):
        media = MEDIA_TYPES[Path(name).suffix]
        items += f'\n    <item id="img{k:03d}" href="{name}" media-type="{media}"/>'
    spine = "\n".join(f'    <itemref idref="chap{i:03d}"/>' for i in range(1, len(chapters) + 1))
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="{LANGUAGE}">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:{book_id}</dc:identifier>
    <dc:title>{html.escape(title)}</dc:title>
    <dc:language>{LANGUAGE}</dc:language>
    <meta property="dcterms:modified">{modified}</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="css" href="style.css" media-type="text/css"/>
{items}
  </manifest>
  <spine>
{spine}
  </spine>
</package>
"""


CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def to_epub(
    book: Book, title: str, out_path: Path, modified: datetime | None = None, resources: Path | None = None
) -> int:
    """Ghi sách ra EPUB 3, trả về số chương. resources: thư mục gốc của đường dẫn ảnh (thư mục
    chứa file Markdown)."""
    chapters = _chapters(book, title)
    files_in = _images(book, resources)
    images = {src: _image_name(i, path) for i, (src, path) in enumerate(files_in.items(), 1)}
    used: set[int] = set()
    bodies = [_chapter_html(c, book, used, images) for c in chapters]
    leftover = [n for n in range(1, len(book.notes) + 1) if n not in used]
    if leftover:  # chú thích không có số mũ nào trỏ tới: gom cuối sách
        bodies[-1] += "\n" + _notes_html(leftover, book)
    stamp = modified.strftime("%Y-%m-%dT%H:%M:%SZ") if modified else FIXED_MODIFIED

    files = {
        "META-INF/container.xml": CONTAINER,
        "OEBPS/content.opf": _opf(title, chapters, stamp, images),
        "OEBPS/nav.xhtml": _nav(title, chapters),
        "OEBPS/style.css": CSS,
    }
    for i, (chapter, body) in enumerate(zip(chapters, bodies, strict=True), 1):
        files[f"OEBPS/chap{i:03d}.xhtml"] = _xhtml(chapter.label, body)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(f".{out_path.name}.tmp")
    with zipfile.ZipFile(tmp, "w") as zf:
        # mimetype phải là mục đầu tiên, không nén (yêu cầu của chuẩn EPUB)
        zf.writestr(zipfile.ZipInfo("mimetype", FIXED_TIME), "application/epub+zip", zipfile.ZIP_STORED)
        for name, content in files.items():
            zf.writestr(zipfile.ZipInfo(name, FIXED_TIME), content.encode("utf-8"), zipfile.ZIP_DEFLATED)
        for src, name in images.items():
            data = files_in[src].read_bytes()  # ảnh đã nén sẵn: lưu nguyên
            zf.writestr(zipfile.ZipInfo(f"OEBPS/{name}", FIXED_TIME), data, zipfile.ZIP_STORED)
    tmp.replace(out_path)
    return len(chapters)
