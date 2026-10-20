import subprocess
import sys


def test_cli_import_does_not_load_pymupdf():
    # tiến trình con (spawn) chạy lại lệnh snap2book, tức import snap2book.cli; nếu kéo theo
    # pymupdf thì onnxruntime được nạp và tiến trình con có thể treo khi thoát (xem pages.py)
    code = (
        "import sys, snap2book.cli; print(sorted(m for m in ('pymupdf', 'onnxruntime') if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
