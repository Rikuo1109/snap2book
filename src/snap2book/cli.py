"""Dòng lệnh:
  snap2book <file hoặc thư mục> [-o thư_mục_ra] [-j số_tiến_trình] [--no-cache] [--scan-only]
            [--no-dewarp] [--no-spellfix] [--debug] [--force]
  snap2book typeset <file .md> [-o file.pdf]     dàn trang lại từ Markdown đã sửa

Mỗi file PDF đầu vào (vd. PDF từ app scan của iPhone) là một cuốn sách; các ảnh rời
.jpg/.png trong cùng thư mục (sắp theo tên) gộp thành một cuốn.

Đầu ra cho mỗi cuốn, trong thư mục ra (mặc định output/):
  <tên>.pdf         sách dàn trang lại từ chữ OCR (gọn, tìm kiếm/copy được)
  <tên>.md          nội dung dạng text, để soát/sửa lỗi OCR
  <tên> - scan.pdf  ảnh các trang đã làm sạch (để đối chiếu)

Kết quả làm sạch + OCR từng trang được cache trong <thư mục ra>/.cache/<tên>/, chạy lại
(vd. sau khi thêm vài ảnh) chỉ phải xử lý các trang mới / đã đổi.

Sau khi soát/sửa lỗi OCR trong <tên>.md, chạy "snap2book typeset <tên>.md" để dàn lại
<tên>.pdf (mặc định ghi cạnh file .md). Chạy lại snap2book sẽ không ghi đè <tên>.md đã
sửa: bản OCR mới ghi ra <tên>.ocr.md và <tên>.pdf dàn từ bản đã sửa (--force để ghi đè).
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
    ap.add_argument("-q", "--quiet", action="store_true", help="chỉ in lỗi")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return ap.parse_args(argv)


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
    ap.add_argument("-q", "--quiet", action="store_true", help="chỉ in lỗi")
    return ap.parse_args(argv)


def typeset(args: argparse.Namespace) -> None:
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
    n = to_pdf(book, title or args.markdown.stem, out)
    logging.info("=> %s (%d trang)", out, n)


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
        jobs = find_jobs(args.input)
    except FileNotFoundError:
        sys.exit(f"Không tìm thấy: {args.input}")
    if not jobs:
        sys.exit(f"Không có file PDF hay ảnh nào trong: {args.input}")

    for name, inputs in jobs:
        logging.info("%s:", name)
        outputs = output_paths(args.out_dir, name)
        if args.scan_only:
            outputs.text_pdf = outputs.markdown = None
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


if __name__ == "__main__":
    main()
