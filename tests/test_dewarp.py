import cv2
import numpy as np

from snap2book.dewarp import dewarp, find_lines


def text_page(w=1200, h=1600, n_lines=18):
    """Trang giả: các dòng "chữ" là chuỗi khối đen nhỏ cách nhau như từ."""
    img = np.full((h, w), 255, np.uint8)
    rng = np.random.default_rng(0)
    for i in range(n_lines):
        y = 120 + i * 75
        x = 60
        while x < w - 120:
            word = int(rng.integers(40, 110))
            cv2.rectangle(img, (x, y), (x + word, y + 28), 0, -1)
            x += word + 18
    return img


def bend(img, amount):
    """Uốn võng các dòng như trang gần gáy sách: lệch dọc tăng dần về mép phải."""
    h, w = img.shape
    xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    dy = amount * (xs / w) ** 3
    return cv2.remap(img, xs, ys - dy, cv2.INTER_LINEAR, borderValue=255)


def max_curve(img):
    return max(line.curve for line in find_lines(img))


def test_flat_page_untouched():
    img = text_page()
    out, _ = dewarp(img)
    assert out is img


def test_curved_lines_are_straightened():
    curved = bend(text_page(), amount=45)
    before = max_curve(curved)
    out, measured = dewarp(curved)
    assert out is not curved
    assert measured == before > 15
    assert max_curve(out) < before / 4
