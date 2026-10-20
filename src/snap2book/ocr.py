"""OCR tiếng Việt bằng Apple Vision (chỉ chạy trên macOS)."""

from dataclasses import dataclass

import cv2
import Foundation
import numpy as np
import Vision

LANGUAGE = "vi-VT"  # mã tiếng Việt của Vision (không phải vi-VN)


@dataclass
class Line:
    """Một dòng OCR; toạ độ chuẩn hoá 0..1 theo ảnh trang, gốc trên-trái."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float


def recognize(img: np.ndarray) -> list[Line]:
    """OCR một ảnh, trả về các dòng theo thứ tự Vision."""
    _, buf = cv2.imencode(".png", img)
    data = Foundation.NSData.dataWithBytes_length_(buf.tobytes(), len(buf))
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setRecognitionLanguages_([LANGUAGE])
    req.setUsesLanguageCorrection_(True)
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise RuntimeError(f"Vision OCR lỗi: {err}")
    lines = []
    for obs in req.results() or []:
        b = obs.boundingBox()  # gốc dưới-trái
        y0 = 1 - b.origin.y - b.size.height
        lines.append(
            Line(
                obs.topCandidates_(1)[0].string(),
                b.origin.x,
                y0,
                b.origin.x + b.size.width,
                y0 + b.size.height,
            )
        )
    return lines


def ocr_page(img: np.ndarray) -> list[Line]:
    """OCR một trang đã làm sạch (ảnh xám, nền trắng), các dòng sắp từ trên xuống.

    Chữ hoa lớn đầu chương (drop cap) làm Vision gộp hai dòng cạnh nó thành một dòng
    sai, nên thu nhỏ nó về cỡ chữ thường và đặt sát đầu dòng thứ nhất trước khi OCR.
    """
    h, w = img.shape
    ink = (img < 128).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    heights = [s[3] for s in stats[1:] if s[4] > 30]
    if not heights:
        return []
    glyph_h = np.median(heights)

    clean = img.copy()
    caps = []
    for x, y, bw, bh, _ in stats[1:]:
        # chữ cao 2.5-6 lần chữ thường, nằm ở lề trái, dưới vùng tiêu đề
        if 2.5 * glyph_h < bh < 6 * glyph_h and x < 0.15 * w and y > 0.1 * h:
            caps.append((x, y, bw, bh))
            nh = int(glyph_h * 1.6)
            nw = max(1, int(bw * nh / bh))
            small = cv2.resize(img[y : y + bh, x : x + bw], (nw, nh), interpolation=cv2.INTER_AREA)
            clean[y : y + bh, x : x + bw] = 255
            clean[y : y + nh, x + bw - nw : x + bw] = np.minimum(
                clean[y : y + nh, x + bw - nw : x + bw], small
            )

    lines = recognize(clean)
    # các dòng nằm cạnh drop cap thực ra không thụt đầu dòng
    for x, y, bw, bh in caps:
        for line in lines:
            if line.y0 * h < y + bh and line.y1 * h > y and line.x0 * w < x + bw * 2:
                line.x0 = 0.0
    lines.sort(key=lambda line: (line.y0, line.x0))
    return lines
