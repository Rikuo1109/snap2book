"""Đẩy PDF vào app Sách (Apple Books) của macOS; Sách tự đồng bộ sang iPhone/iPad qua iCloud.

Sách không nhận ra hai file là cùng một cuốn, mỗi lần thêm là một bản mới. Vì vậy ghi lại dấu
vân tay của từng PDF đã đẩy (trong <thư mục PDF>/.books.json) và chỉ đẩy lại khi nội dung đổi.
Dấu vân tay tính theo chữ từng trang chứ không theo byte: mỗi lần ghi, PyMuPDF đặt tên font
rút gọn khác nhau nên byte đổi dù nội dung y hệt.
"""

import hashlib
import json
import logging
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pymupdf

log = logging.getLogger(__name__)

STATE_FILE = ".books.json"  # {tên file PDF: dấu vân tay lần đẩy gần nhất}
OPEN_COMMAND = ["open", "-g", "-a", "Books"]  # -g: mở Sách ở nền, không che màn hình

Runner = Callable[..., object]


def fingerprint(pdf: Path) -> str:
    """Dấu vân tay nội dung: tiêu đề + chữ từng trang (đổi chữ hay chỗ ngắt trang đều khác)."""
    with pymupdf.open(pdf) as doc:
        parts = [doc.metadata.get("title") or "", *(page.get_text() for page in doc)]
    return hashlib.sha256("\f".join(parts).encode("utf-8")).hexdigest()


def _load_state(path: Path) -> dict[str, str]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def send_to_books(pdf: Path, run: Runner = subprocess.run) -> bool:
    """Thêm pdf vào app Sách nếu chưa từng đẩy bản có cùng nội dung. True nếu đã đẩy."""
    if sys.platform != "darwin":
        log.warning("  Sách: chỉ có trên macOS, bỏ qua %s", pdf)
        return False

    state_path = pdf.parent / STATE_FILE
    state = _load_state(state_path)
    mark = fingerprint(pdf)
    previous = state.get(pdf.name)
    if previous == mark:
        log.info("  Sách: %s đã có trong Sách, không thêm lại", pdf.name)
        return False

    try:
        run([*OPEN_COMMAND, str(pdf)], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as e:
        log.warning("  Sách: không thêm được %s vào Sách (%s)", pdf.name, e)
        return False

    state[pdf.name] = mark
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log.info("=> đã thêm %s vào Sách trên Mac (sang iPhone nếu Sách bật iCloud Drive)", pdf.name)
    if previous is not None:
        log.warning("  Sách: bản cũ của %s vẫn còn trong Sách, xoá tay nếu không cần", pdf.name)
    return True
