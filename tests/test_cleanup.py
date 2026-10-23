import cv2
import numpy as np

from snap2book.cleanup import INK_THRESHOLD, clean_page, flatten_illumination, ink_mask, ink_threshold


def text_page(ink: int) -> np.ndarray:
    """Trang giả: nền trắng, 25 dòng "chữ" (vạch ngắn) màu ink."""
    img = np.full((1600, 1000), 245, np.uint8)
    for row in range(25):
        y = 150 + row * 50
        for x in range(80, 900, 40):
            cv2.putText(img, "ab", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, ink, 2)
    return img


def test_normal_page_keeps_default_threshold():
    assert ink_threshold(flatten_illumination(text_page(30))) == INK_THRESHOLD


def test_faint_page_raises_threshold_and_keeps_text():
    norm = flatten_illumination(text_page(170))  # ảnh mờ: nét chữ xám nhạt hơn ngưỡng mặc định
    threshold = ink_threshold(norm)
    assert threshold > INK_THRESHOLD
    assert ink_mask(norm).sum() == 0  # ngưỡng mặc định: mất hết chữ
    assert ink_mask(norm, threshold).sum() > 0.8 * ink_mask(flatten_illumination(text_page(30))).sum()
    assert (clean_page(text_page(170), flatten=False).image < 200).any()


def lines_mask(mask, x0, x1, y0, y1, pitch=40):
    """Vẽ các "dòng chữ" (vạch ngang mảnh) vào mask trong khung đã cho."""
    for y in range(y0, y1, pitch):
        mask[y : y + 12, x0:x1] = 1


def test_paragraph_split_by_vertical_gap_keeps_whole_page():
    from snap2book.cleanup import main_page_region

    h, w = 2400, 1400
    mask = np.zeros((h, w), np.uint8)
    lines_mask(mask, 250, 1330, 250, 850)  # hai đoạn rộng phía trên
    lines_mask(mask, 250, 1330, 900, 1500)
    # đoạn cuối bị một khe lóa sáng dọc chẻ: mẩu đầu dòng hẹp, phần giữa, phần phải
    lines_mask(mask, 265, 370, 1550, 2200)
    lines_mask(mask, 420, 960, 1550, 2200)
    lines_mask(mask, 1000, 1330, 1550, 2200)
    _, (x0, y0, x1, y1) = main_page_region(mask)
    assert x0 <= 255 and x1 >= 1325 and y0 <= 255 and y1 >= 2190
