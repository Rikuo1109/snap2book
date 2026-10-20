"""Dòng lệnh:
  snap2book <file hoặc thư mục> [-o thư_mục_ra] [-j số_tiến_trình] [--no-cache] [--scan-only]
            [--no-dewarp] [--no-spellfix] [--debug] [--force] [--to-books] [--to-icloud [thư_mục]]
  snap2book typeset <file .md> [-o file.pdf] [--to-books] [--to-icloud [thư_mục]]
                                                    dàn trang lại từ Markdown đã sửa

Mỗi file PDF đầu vào (vd. PDF từ app scan của iPhone) là một cuốn sách; các ảnh rời
.jpg/.png trong cùng thư mục (sắp theo tên) gộp thành một cuốn.

Đầu ra cho mỗi cuốn, trong thư mục ra (mặc định output/):
  <tên>.pdf         sách dàn trang lại từ chữ OCR (gọn, tìm kiếm/copy được)
  <tên>.epub        sách điện tử: chữ tự dàn theo màn hình, mục lục theo chương
  <tên>.md          nội dung dạng text, để soát/sửa lỗi OCR
  <tên> - scan.pdf  ảnh các trang đã làm sạch (để đối chiếu)

Kết quả làm sạch + OCR từng trang được cache trong <thư mục ra>/.cache/<tên>/, chạy lại
(vd. sau khi thêm vài ảnh) chỉ phải xử lý các trang mới / đã đổi.

Sau khi soát/sửa lỗi OCR trong <tên>.md, chạy "snap2book typeset <tên>.md" để dàn lại
<tên>.pdf (mặc định ghi cạnh file .md). Chạy lại snap2book sẽ không ghi đè <tên>.md đã
sửa: bản OCR mới ghi ra <tên>.ocr.md và <tên>.pdf/.epub dàn từ bản đã sửa (--force để ghi đè).

--to-books thêm <tên>.epub (không có thì .pdf) vào app Sách (Apple Books) trên Mac; Sách đồng bộ
sang iPhone nếu đã bật iCloud Drive cho Sách. Chỉ thêm khi nội dung đổi, để không sinh bản trùng.

--to-icloud chép <tên>.pdf và <tên>.epub vào iCloud Drive (mặc định snap2book/Sách đã xử lý); trên iPhone mở
bằng app Tệp, hoặc Chia sẻ → Sách. Không phụ thuộc vào đồng bộ của app Sách.
"""

import argparse
import logging
import os
import sys
import warnings
from pathlib import Path

from snap2book import __version__
from snap2book.pipeline import convert, output_paths
from snap2book.sources import find_jobs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="snap2book", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("input", type=Path, help="file PDF / ảnh, hoặc thư mục")
    ap.add_argument(
        "-o", "--out-dir", type=Path, default=Path("output"), help="thư mục ra (mặc định: output)"
    )
    ap.add_argument(
        "-j",
        "--jobs",
        type=_positive_int,
        default=os.cpu_count() or 1,
        help="số trang xử lý song song (mặc định: số nhân CPU, %(default)s)",
    )
    ap.add_argument(
        "--no-cache", action="store_true", help="không dùng / không ghi cache, làm sạch và OCR lại mọi trang"
    )
    ap.add_argument("--scan-only", action="store_true", help="không OCR, chỉ xuất PDF ảnh đã làm sạch")
    ap.add_argument("--no-dewarp", action="store_true", help="không làm phẳng trang cong")
    ap.add_argument("--no-spellfix", action="store_true", help="không sửa lỗi dấu OCR theo từ điển chính tả")
    ap.add_argument("-v", "--verbose", action="store_true", help="in chi tiết (vd. từng từ đã sửa dấu)")
    ap.add_argument("--debug", action="store_true", help="lưu ảnh đánh dấu vùng cắt vào <thư mục ra>/debug")
    ap.add_argument(
        "--keep-duplicates",
        action="store_true",
        help="giữ cả các ảnh chụp lặp một trang (mặc định bỏ bớt, theo số trang in)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="ghi đè cả <tên>.md đã sửa tay (mặc định giữ lại, bản OCR mới ghi ra <tên>.ocr.md)",
    )
    _add_to_books(ap)
    ap.add_argument("-q", "--quiet", action="store_true", help="chỉ in lỗi")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return ap.parse_args(argv)


def _add_to_books(ap: argparse.ArgumentParser) -> None:
    from snap2book.icloud import DEFAULT_DIR

    ap.add_argument(
        "--to-books",
        action="store_true",
        help="thêm PDF vào app Sách trên Mac (sang iPhone nếu Sách bật iCloud Drive), không thêm trùng",
    )
    ap.add_argument(
        "--to-icloud",
        nargs="?",
        const=DEFAULT_DIR,
        type=Path,
        metavar="THƯ_MỤC",
        help=f"chép PDF vào iCloud Drive để mở trên iPhone (mặc định: {DEFAULT_DIR.name} trong snap2book)",
    )


def _deliver(files: list[Path], args: argparse.Namespace) -> None:
    """Gửi sách tới app Sách và/hoặc iCloud Drive theo cờ dòng lệnh. iCloud nhận mọi file;
    app Sách chỉ nhận một bản (EPUB nếu có, đọc dễ hơn) để không thành hai cuốn trùng nhau."""
    if args.to_books:
        from snap2book.books import send_to_books

        epubs = [f for f in files if f.suffix == ".epub"]
        send_to_books((epubs or files)[0])
    if args.to_icloud:
        from snap2book.icloud import copy_to_icloud

        for f in files:
            copy_to_icloud(f, args.to_icloud)


def _positive_int(text: str) -> int:
    n = int(text)
    if n < 1:
        raise argparse.ArgumentTypeError(f"phải >= 1: {text}")
    return n


def parse_typeset_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="snap2book typeset", description="Dàn trang PDF từ file Markdown (đã soát/sửa lỗi OCR)."
    )
    ap.add_argument("markdown", type=Path, help="file .md (dạng snap2book xuất ra)")
    ap.add_argument("-o", "--output", type=Path, help="file PDF ra (mặc định: cạnh file .md, đuôi .pdf)")
    _add_to_books(ap)
    ap.add_argument("-q", "--quiet", action="store_true", help="chỉ in lỗi")
    return ap.parse_args(argv)


def typeset(args: argparse.Namespace) -> None:
    from snap2book.epub import to_epub
    from snap2book.markdown import from_markdown
    from snap2book.typeset import to_pdf

    try:
        text = args.markdown.read_text(encoding="utf-8")
    except FileNotFoundError:
        sys.exit(f"Không tìm thấy: {args.markdown}")
    try:
        book, title = from_markdown(text)
    except ValueError as e:
        sys.exit(f"{args.markdown}: {e}")
    out = args.output or args.markdown.with_suffix(".pdf")
    title = title or args.markdown.stem
    n = to_pdf(book, title, out)
    logging.info("=> %s (%d trang)", out, n)
    epub = out.with_suffix(".epub")
    logging.info("=> %s (%d chương)", epub, to_epub(book, title, epub))
    _deliver([out, epub], args)


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    is_typeset = argv[:1] == ["typeset"]
    args = parse_typeset_args(argv[1:]) if is_typeset else parse_args(argv)
    level = (
        logging.WARNING if args.quiet else logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    )
    logging.basicConfig(level=level, format="%(message)s")
    warnings.filterwarnings("ignore", category=FutureWarning, module="pymupdf")
    if is_typeset:
        typeset(args)
        return

    try:
        from snap2book.icloud import DEFAULT_DIR

        # thư mục kết quả có thể nằm trong thư mục đầu vào (vd. iCloud Drive/snap2book): không coi là sách
        jobs = find_jobs(args.input, exclude=[args.out_dir, DEFAULT_DIR, *filter(None, [args.to_icloud])])
    except FileNotFoundError:
        sys.exit(f"Không tìm thấy: {args.input}")
    if not jobs:
        sys.exit(f"Không có file PDF hay ảnh nào trong: {args.input} (quét sách vào thư mục này trước)")

    for name, inputs in jobs:
        logging.info("%s:", name)
        outputs = output_paths(args.out_dir, name)
        if args.scan_only:
            outputs.text_pdf = outputs.markdown = outputs.epub = None
        debug_dir = args.out_dir / "debug" / name if args.debug else None
        convert(
            inputs,
            outputs,
            debug_dir,
            drop_duplicates=not args.keep_duplicates,
            flatten=not args.no_dewarp,
            spellfix=not args.no_spellfix,
            jobs=args.jobs,
            cache_dir=None if args.no_cache else args.out_dir / ".cache" / name,
            force=args.force,
        )
        _deliver(outputs.books(), args)


if __name__ == "__main__":
    main()
