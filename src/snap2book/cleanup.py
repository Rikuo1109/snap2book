"""Làm sạch một ảnh chụp trang sách.

1. Làm phẳng ánh sáng: nền giấy về trắng đều, bỏ bóng đổ.
2. Xoay thẳng dòng chữ (deskew).
3. Tìm trang chính trong ảnh, bỏ phần trang bên cạnh, ngón tay, khăn bàn, bóng gáy sách.
4. Cắt sát vùng chữ, mọi thứ ngoài vùng chữ thành trắng.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

INK_THRESHOLD = 150  # sau khi làm phẳng ánh sáng, điểm tối hơn mức này là mực
MAX_SKEW_DEG = 6.0


@dataclass
class CleanedPage:
    image: np.ndarray  # ảnh xám đã cắt sát vùng chữ, nền trắng
    angle: float  # góc đã xoay (độ)


def flatten_illumination(gray: np.ndarray) -> np.ndarray:
    """Chia cho nền (ước lượng bằng closing + blur) để giấy thành trắng đều."""
    k = max(15, (min(gray.shape) // 40) | 1)
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    bg = cv2.GaussianBlur(bg, (0, 0), k / 2)
    return cv2.divide(gray, bg, scale=255)


def ink_mask(norm: np.ndarray) -> np.ndarray:
    """Mask chữ: điểm tối, bỏ vệt lớn (ngón tay, mép sách), vệt chạm mép ảnh và nhiễu."""
    mask = (norm < INK_THRESHOLD).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    h, w = mask.shape
    max_h = h * 0.06  # chữ cao không quá ~6% ảnh (kể cả tiêu đề chương)
    # nét chữ mảnh: bán kính nét lớn nhất của mỗi vệt (khăn bàn, bóng đổ thì dày)
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
    stroke = np.zeros(n, np.float32)
    np.maximum.at(stroke, labels.ravel(), dist.ravel())
    max_stroke = max(h, w) * 0.006
    edge = max(h, w) * 0.015  # đã tính phần nêm trắng sinh ra khi xoay
    keep = np.zeros(n, bool)
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < 6 or bh > max_h or bw > w * 0.3 or stroke[i] > max_stroke:
            continue
        if stroke[i] > 0.3 * bh and bh > h * 0.012:  # hình đặc (không phải dấu chấm): khăn bàn
            continue
        if x < edge or y < edge or x + bw > w - edge or y + bh > h - edge:  # khăn bàn, trang bị cắt
            continue
        keep[i] = True
    return keep[labels].astype(np.uint8)


def find_skew(mask: np.ndarray, max_deg: float = MAX_SKEW_DEG) -> float:
    """Góc xoay làm các dòng chữ nằm ngang nhất (tối đa phương sai profile hàng)."""
    scale = 1000 / max(mask.shape)
    small = cv2.resize(mask * 255, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    h, w = small.shape
    center = (w / 2, h / 2)

    def score(a: float) -> float:
        m = cv2.getRotationMatrix2D(center, a, 1.0)
        r = cv2.warpAffine(small, m, (w, h))
        return np.var(r.sum(axis=1, dtype=np.float64))

    best = max(np.arange(-max_deg, max_deg + 0.01, 0.5), key=score)
    best = max(np.arange(best - 0.5, best + 0.51, 0.1), key=score)
    return float(best)


def rotate(img: np.ndarray, angle: float, border: int) -> np.ndarray:
    h, w = img.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=border
    )


def main_page_region(mask: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Vùng chữ của trang chính: (mask các khối chữ đã chọn, bbox x0, y0, x1, y1).

    Nối chữ thành khối; trong các khối lớn, khối gần giữa ảnh nhất là trang được
    chụp (người chụp đưa trang cần chụp vào giữa). Sau đó thêm các khối cùng cột
    (đoạn văn khác, tiêu đề, số trang) - khối của trang bên cạnh lệch cột nên bị bỏ.
    """
    h, w = mask.shape
    kx, ky = max(3, int(w * 0.012)), max(3, int(h * 0.02))
    blocks = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_RECT, (kx, ky)))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(blocks, 8)
    if n <= 1:
        return np.ones_like(mask), (0, 0, w, h)
    ink = np.bincount(labels.ravel(), weights=mask.ravel(), minlength=n)
    ink[0] = 0
    big = [i for i in range(1, n) if ink[i] >= 0.4 * ink.max()]
    main = min(big, key=lambda i: abs(stats[i][0] + stats[i][2] / 2 - w / 2))
    x0, y0, bw, bh, _ = stats[main]
    x1, y1 = x0 + bw, y0 + bh
    mx0, mx1 = x0, x1
    selected = {main}

    # nới dần theo chiều dọc: chỉ nhận khối cùng cột và nằm sát vùng đã chọn
    max_gap = h * 0.05
    changed = True
    while changed:
        changed = False
        for i in range(1, n):
            if i in selected or ink[i] < 40:
                continue
            x, y, cw, ch, _ = stats[i]
            if ink[i] < 0.04 * cw * ch:  # lưa thưa vài chấm: nhiễu, không phải dòng chữ
                continue
            if ch > 2 * cw:  # vệt dọc (bóng gáy sách, mép trang) - chữ luôn nằm ngang
                continue
            overlap = min(mx1, x + cw) - max(mx0, x)
            in_column = overlap > 0.8 * cw  # nằm gọn trong cột, không tràn sang trang khác
            gap = max(y0 - (y + ch), y - y1, 0)
            if in_column and gap < max_gap:
                selected.add(i)
                x0, y0 = min(x0, x), min(y0, y)
                x1, y1 = max(x1, x + cw), max(y1, y + ch)
                mx0, mx1 = min(mx0, x), max(mx1, x + cw)
                changed = True

    # bbox theo điểm mực thật (bbox của khối đã dilate thì bị phình)
    region = np.isin(labels, list(selected)).astype(np.uint8)
    ys, xs = np.nonzero(region & mask)
    return region, (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def enhance(norm: np.ndarray) -> np.ndarray:
    """Đẩy nền gần trắng thành trắng hẳn, tăng tương phản chữ, giữ khử răng cưa."""
    lut = np.clip((np.arange(256) - 60) * 255.0 / (215 - 60), 0, 255).astype(np.uint8)
    return cv2.LUT(norm, lut)


def clean_page(gray: np.ndarray, debug_path: Path | None = None) -> CleanedPage:
    """Làm sạch một ảnh chụp. debug_path: lưu ảnh đánh dấu mực (đỏ) và vùng cắt (xanh)."""
    norm = flatten_illumination(gray)
    angle = find_skew(ink_mask(norm))
    norm = rotate(norm, angle, 255)
    mask = ink_mask(norm)
    region, (x0, y0, x1, y1) = main_page_region(mask)
    p = int(0.006 * norm.shape[1])  # chừa vài px để không sát mép chữ
    h, w = norm.shape
    x0, y0, x1, y1 = max(0, x0 - p), max(0, y0 - p), min(w, x1 + p), min(h, y1 + p)
    # ngoài các khối chữ đã chọn -> trắng (xoá khăn bàn, mẩu trang bên cạnh lọt vào khung)
    region = cv2.dilate(region, np.ones((p, p), np.uint8))
    page = np.where(region > 0, enhance(norm), 255).astype(np.uint8)

    if debug_path:
        dbg = cv2.cvtColor(norm, cv2.COLOR_GRAY2BGR)
        dbg[mask > 0] = (0, 0, 255)
        cv2.rectangle(dbg, (x0, y0), (x1, y1), (0, 200, 0), 8)
        cv2.imwrite(str(debug_path), cv2.resize(dbg, None, fx=0.35, fy=0.35))
    return CleanedPage(page[y0:y1, x0:x1], angle)
