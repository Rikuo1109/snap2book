"""OCR tiếng Việt bằng Apple Vision (chỉ chạy trên macOS)."""

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from itertools import pairwise

import cv2
import numpy as np

LANGUAGE = "vi-VT"  # mã tiếng Việt của Vision (không phải vi-VN)
CANDIDATES = 3  # số phương án đọc lấy cho mỗi dòng
SIDE_OVERLAP = 0.3  # hai mảnh chồng ngang hơn chừng này (theo mảnh hẹp hơn) thì là hai dòng khác nhau
ALT_MATCH = 0.6  # độ giống tối thiểu để coi một dòng ở ảnh phụ là cùng dòng


@dataclass
class Line:
    """Một dòng OCR; toạ độ chuẩn hoá 0..1 theo ảnh trang, gốc trên-trái."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    alternatives: list[str] = field(default_factory=list)  # các phương án đọc khác của dòng


def recognize(img: np.ndarray) -> list[Line]:
    """OCR một ảnh, trả về các dòng theo thứ tự Vision."""
    import Foundation  # pyobjc, chỉ có trên macOS; import muộn để phần còn lại dùng được ở mọi nơi
    import Vision

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
        text, *alts = [c.string() for c in obs.topCandidates_(CANDIDATES)]
        lines.append(Line(text, b.origin.x, y0, b.origin.x + b.size.width, y0 + b.size.height, alts))
    return lines


def ocr_page(img: np.ndarray, alt: np.ndarray | None = None) -> list[Line]:
    """OCR một trang đã làm sạch (ảnh xám, nền trắng), các dòng sắp từ trên xuống.

    alt: một ảnh khác của cùng trang (vd. trước khi làm phẳng); kết quả OCR của nó được
    gắn vào Line.alternatives của dòng tương ứng, làm phương án đọc phụ.
    """
    lines = _read(img)
    if alt is not None:
        _attach_alternatives(lines, _read(alt))
    return lines


def _attach_alternatives(lines: list[Line], others: list[Line]) -> None:
    """Gắn mỗi dòng ở others vào dòng giống nó nhất (theo nội dung chữ, vì toạ độ hai ảnh lệch nhau)."""
    for other in others:
        best, score = None, ALT_MATCH
        for line in lines:
            ratio = SequenceMatcher(None, line.text, other.text, autojunk=False).ratio()
            if ratio > score:
                best, score = line, ratio
        if best is not None:
            best.alternatives += [other.text, *other.alternatives]


def _read(img: np.ndarray) -> list[Line]:
    """OCR một ảnh trang. Chữ hoa lớn đầu chương (drop cap) làm Vision gộp hai dòng cạnh nó
    thành một dòng sai, nên thu nhỏ nó về cỡ chữ thường và đặt sát đầu dòng thứ nhất trước."""
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
        # (không xét 10% cuối trang: hình trang trí ở chân trang, vd. logo cạnh số trang)
        if 2.5 * glyph_h < bh < 6 * glyph_h and x < 0.15 * w and y > 0.1 * h and y + bh < 0.9 * h:
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
    return merge_rows(lines)


def _overlap(left: str, right: str, limit: int = 4) -> int:
    """Độ dài dài nhất (tối đa limit ký tự) mà cuối left trùng đầu right."""
    for n in range(min(limit, len(left), len(right)), 0, -1):
        if left.endswith(right[:n]):
            return n
    return 0


def merge_rows(lines: list[Line]) -> list[Line]:
    """Gộp các mảnh cùng một dòng (Vision đôi khi tách một dòng thành vài mảnh, lệch nhau
    vài px theo chiều dọc) thành một dòng, ghép chữ trái sang phải; sắp các dòng từ trên xuống.
    Hai mảnh cùng dòng khi chồng nhau theo chiều dọc hơn nửa chiều cao mảnh thấp hơn và gần như
    không chồng nhau theo chiều ngang."""
    rows: list[list[Line]] = []
    for line in sorted(lines, key=lambda line: (line.y0 + line.y1) / 2):
        for row in rows:
            top, bottom = min(r.y0 for r in row), max(r.y1 for r in row)
            overlap = min(bottom, line.y1) - max(top, line.y0)
            # mảnh của cùng một dòng nằm cạnh nhau; hai dòng khác nhau (dòng nghiêng nên khung bao
            # cao, chồng lên dòng kế) thì trải trên cùng khoảng ngang
            side_by_side = all(
                min(r.x1, line.x1) - max(r.x0, line.x0) < SIDE_OVERLAP * min(r.x1 - r.x0, line.x1 - line.x0)
                for r in row
            )
            if overlap > 0.5 * min(line.y1 - line.y0, bottom - top) and side_by_side:
                row.append(line)
                break
        else:
            rows.append([line])
    merged = []
    for row in rows:
        row.sort(key=lambda line: line.x0)
        text = row[0].text.strip()
        for prev, line in pairwise(row):
            part = line.text.strip()
            if line.x0 < prev.x1:  # hai mảnh chồng nhau: phần chồng có thể bị đọc hai lần
                part = part[_overlap(text, part) :].lstrip()
            text = f"{text} {part}" if part else text
        merged.append(
            Line(
                text,
                row[0].x0,
                min(line.y0 for line in row),
                max(line.x1 for line in row),
                max(line.y1 for line in row),
                # phương án đọc khác chỉ áp được cho cả dòng khi dòng là một mảnh
                row[0].alternatives if len(row) == 1 else [],
            )
        )
    merged.sort(key=lambda line: (line.y0, line.x0))
    return merged
