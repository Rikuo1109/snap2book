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


def tilt_bottom(img, amount):
    """Các dòng nửa dưới nghiêng dần (trang chụp chéo gần gáy sách): lệch dọc tăng theo x và y."""
    h, w = img.shape
    xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    dy = amount * (xs / w) * np.clip((ys / h - 0.5) * 2, 0, 1)
    return cv2.remap(img, xs, ys - dy, cv2.INTER_LINEAR, borderValue=255)


def test_strongly_tilted_lines_are_used():
    img = tilt_bottom(text_page(), amount=150)  # dòng cuối nghiêng ~150px: khung bao > 8% ảnh
    h = img.shape[0]
    lines = find_lines(img)
    assert len(lines) == 18
    tall = [line for line in lines if np.ptp(np.polyval(line.coef, line.xs)) + 28 > 0.08 * h]
    assert tall  # có dòng khung bao cao bất thường vẫn được nhận


def test_merged_lines_are_rejected():
    img = text_page(n_lines=6)
    # dòng 3-5 dính thành một khối cao (> 8% ảnh) và dày gấp nhiều lần một dòng chữ: không phải
    # dòng nghiêng, không dùng để làm phẳng
    cv2.rectangle(img, (60, 120 + 2 * 75), (1080, 120 + 4 * 75 + 28), 0, -1)
    assert len(find_lines(img)) == 3


def test_chapter_heading_far_above_body_is_kept():
    from snap2book.cleanup import main_page_region

    h, w = 2400, 1600
    mask = np.zeros((h, w), np.uint8)
    for k in range(25):  # thân bài: 25 dòng từ 40% trang
        y = int(h * 0.40) + k * 50
        for x in range(100, 1500, 80):  # từ cách nhau 10px: nối thành dòng như chữ thật
            mask[y : y + 25, x : x + 70] = 1
    for x in range(560, 960, 60):  # "CHƯƠNG": cách thân bài ~15% trang (lớn hơn khoảng cách gom thường)
        mask[int(h * 0.20) : int(h * 0.20) + 60, x : x + 45] = 1
    mask[int(h * 0.20) : int(h * 0.20) + 60, 1000:1028] = 1  # chữ số "2": hẹp và cao
    _, (x0, y0, x1, y1) = main_page_region(mask)
    assert y0 <= int(h * 0.20) and x1 >= 1028
