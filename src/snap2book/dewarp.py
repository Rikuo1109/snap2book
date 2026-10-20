"""Làm phẳng trang cong (dòng chữ võng xuống gần gáy sách).

Ước lượng độ cong từ chính các dòng chữ:
  1. Nối chữ thành từng dòng, lấy đường giữa mỗi dòng dài, khớp đa thức bậc 3 y(x).
  2. Độ lệch dọc của mỗi dòng so với chính nó khi thẳng: dy(x) = y(x) - trung bình y.
  3. Nội suy dy cho mọi điểm ảnh (giữa các dòng theo chiều dọc), rồi remap để kéo thẳng.

Chỉ sửa độ cong theo chiều dọc; phần chữ bị co ngang gần gáy sách không đổi (OCR ít bị ảnh hưởng).
"""

from dataclasses import dataclass

import cv2
import numpy as np

MIN_CURVE = 0.012  # độ võng tối đa (theo chiều rộng ảnh) dưới mức này thì coi là phẳng, để nguyên
POLY_DEG = 3
GRID_STEP = 16  # px; tính độ lệch trên lưới thưa rồi phóng lên cả ảnh


@dataclass
class TextLine:
    xs: np.ndarray  # các điểm mẫu của đường giữa dòng
    ys: np.ndarray
    coef: np.ndarray  # đa thức y(x)

    @property
    def y_mean(self) -> float:
        return float(np.polyval(self.coef, self.xs).mean())

    def offset(self, x: np.ndarray) -> np.ndarray:
        """Độ lệch dọc tại x (ngoài phạm vi dòng thì giữ giá trị ở đầu mút)."""
        x = np.clip(x, self.xs[0], self.xs[-1])
        return np.polyval(self.coef, x) - self.y_mean

    @property
    def curve(self) -> float:
        """Độ võng: khoảng cách lớn nhất từ đường cong tới dây cung nối hai đầu."""
        fit = np.polyval(self.coef, self.xs)
        chord = np.interp(self.xs, [self.xs[0], self.xs[-1]], [fit[0], fit[-1]])
        return float(np.abs(fit - chord).max())


def find_lines(img: np.ndarray) -> list[TextLine]:
    """Các dòng chữ dài (≥ nửa chiều rộng ảnh) với đường giữa đã khớp đa thức."""
    ink = (img < 128).astype(np.uint8)
    h, w = ink.shape
    # nối các chữ trong dòng: kernel ngang dài, dọc 1px để không dính sang dòng khác
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, w // 40), 1))
    blobs = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kernel)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(blobs, 8)
    step = max(2, w // 60)
    lines = []
    for i in range(1, n):
        x, y, bw, bh, _ = stats[i]
        if bw < w * 0.5 or bh > h * 0.08:
            continue
        sub = (labels[y : y + bh, x : x + bw] == i) & (ink[y : y + bh, x : x + bw] > 0)
        xs, ys = [], []
        for c in range(0, bw, step):
            rows = np.nonzero(sub[:, c : c + step].any(axis=1))[0]
            if len(rows) >= 2:
                xs.append(x + c + step / 2)
                ys.append(y + (rows.min() + rows.max()) / 2)
        if len(xs) < 20:
            continue
        xs, ys = np.array(xs), np.array(ys)
        # khớp 2 lượt, bỏ điểm lệch (dấu, chữ có đuôi dài làm đường giữa nhảy)
        coef = np.polyfit(xs, ys, POLY_DEG)
        resid = np.abs(ys - np.polyval(coef, xs))
        good = resid < max(3.0, 2.5 * np.median(resid))
        if good.sum() >= 15:
            coef = np.polyfit(xs[good], ys[good], POLY_DEG)
        lines.append(TextLine(xs, ys, coef))
    lines.sort(key=lambda line: line.y_mean)
    return lines


def _offset_field(lines: list[TextLine], shape: tuple[int, int]) -> np.ndarray:
    """dy cho mọi điểm ảnh: ở mỗi cột, nội suy độ lệch giữa các dòng theo chiều dọc."""
    h, w = shape
    gx = np.arange(0, w + GRID_STEP, GRID_STEP, dtype=np.float64)
    gy = np.arange(0, h + GRID_STEP, GRID_STEP, dtype=np.float64)
    line_y = np.array([line.y_mean for line in lines])
    offsets = np.array([line.offset(gx) for line in lines])  # (số dòng, số cột)
    # làm mượt theo chiều dọc: trung vị 3 dòng liền kề, bớt ảnh hưởng một dòng khớp sai
    if len(lines) >= 3:
        padded = np.vstack([offsets[:1], offsets, offsets[-1:]])
        offsets = np.median(np.stack([padded[:-2], padded[1:-1], padded[2:]]), axis=0)
    grid = np.stack([np.interp(gy, line_y, offsets[:, j]) for j in range(len(gx))], axis=1)
    field = cv2.resize(
        grid.astype(np.float32), (len(gx) * GRID_STEP, len(gy) * GRID_STEP), interpolation=cv2.INTER_CUBIC
    )
    return field[:h, :w]


def dewarp(img: np.ndarray) -> tuple[np.ndarray, float]:
    """Kéo thẳng các dòng chữ cong. Trả về (ảnh, độ võng lớn nhất trước khi sửa, px).
    Ảnh gần như phẳng (hoặc quá ít dòng để ước lượng) được trả về nguyên vẹn."""
    lines = find_lines(img)
    if len(lines) < 4:
        return img, 0.0
    curve = max(line.curve for line in lines)
    if curve < MIN_CURVE * img.shape[1]:
        return img, curve

    # chừa lề trắng: nội dung sát mép trên/dưới có thể bị dời ra ngoài khung
    pad = int(np.ceil(max(np.abs(line.offset(line.xs)).max() for line in lines))) + 4
    padded = cv2.copyMakeBorder(img, pad, pad, 0, 0, cv2.BORDER_CONSTANT, value=255)
    for line in lines:
        line.coef = line.coef.copy()
        line.coef[-1] += pad  # dời toạ độ theo lề vừa thêm
    h, w = padded.shape
    dy = _offset_field(lines, (h, w))
    map_x, map_y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    flat = cv2.remap(
        padded, map_x, map_y + dy, cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=255
    )

    # cắt lại sát vùng chữ như trước
    ys = np.nonzero((flat < 128).any(axis=1))[0]
    if len(ys):
        margin = int(0.006 * w)
        flat = flat[max(0, ys.min() - margin) : min(h, ys.max() + 1 + margin)]
    return flat, curve
