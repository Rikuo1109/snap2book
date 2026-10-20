from dataclasses import dataclass

import pytest


@dataclass
class FakeLine:
    """Dòng OCR giả (cùng dạng ocr.Line, nhưng không cần Apple Vision)."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float


LINE_H = 0.03


@pytest.fixture
def page():
    """Tạo một trang từ các dòng (text, kiểu): "body" dòng đầy, "indent" đầu đoạn,
    "last" dòng cuối đoạn (ngắn), "center" tiêu đề căn giữa. Có thể gán y bằng (text, kiểu, y)."""

    def make(*rows):
        lines, y = [], 0.05
        for row in rows:
            text, kind, *pos = row
            if pos:
                y = pos[0]
            x0, x1 = {
                "body": (0.02, 0.98),
                "indent": (0.10, 0.98),
                "last": (0.02, 0.50),
                "center": (0.30, 0.70),
            }[kind]
            lines.append(FakeLine(text, x0, y, x1, y + LINE_H))
            y += LINE_H + 0.005
        return lines

    return make
