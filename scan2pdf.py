#!/usr/bin/env python3
"""Chuyển ảnh chụp sách (PDF từ app scan của iPhone, hoặc thư mục ảnh) thành sách PDF gọn.

Với mỗi ảnh chụp:
  1. Làm phẳng ánh sáng (nền giấy về trắng, bỏ bóng đổ).
  2. Xoay thẳng dòng chữ (deskew).
  3. Tìm trang chính trong ảnh (bỏ phần trang bên cạnh, ngón tay, mép bàn).
  4. Cắt theo vùng chữ, scale để mọi trang có cùng cỡ chữ, đặt lên khổ giấy đồng nhất.
  5. OCR tiếng Việt (Apple Vision), ghép thành nội dung liền mạch, dàn trang lại.

Đầu ra (trong output/):
  <tên>.pdf         sách dàn trang lại từ chữ OCR (gọn, tìm kiếm/copy được)
  <tên>.md          nội dung dạng text, để soát/sửa lỗi OCR
  <tên> - scan.pdf  ảnh các trang đã làm sạch (để đối chiếu)

Cách dùng:
  python scan2pdf.py resources/sach.pdf                 # -> output/sach.pdf, .md, - scan.pdf
  python scan2pdf.py thu_muc_anh/ -o out.pdf            # ảnh .jpg/.png, sắp theo tên
  python scan2pdf.py resources/ --debug                 # xử lý mọi file, lưu ảnh debug
  python scan2pdf.py resources/ --scan-only             # bỏ qua OCR, chỉ xuất bản ảnh
"""
import argparse
import sys
from pathlib import Path

import cv2
import pymupdf as fitz
import numpy as np

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
PAGE_WIDTH_PT = 420  # khổ A5 (148mm)


# ---------------------------------------------------------------- input

def load_images(path: Path):
    """Trả về list ảnh grayscale (numpy) theo thứ tự trang."""
    if path.suffix.lower() == ".pdf":
        doc = fitz.open(path)
        for page in doc:
            imgs = page.get_images()
            if len(imgs) == 1:
                data = doc.extract_image(imgs[0][0])["image"]
                img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
            else:
                img = None
            if img is None:  # trang không phải đúng 1 ảnh: render lại
                pix = page.get_pixmap(dpi=300, colorspace=fitz.csGRAY)
                img = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w).copy()
            yield img
    else:
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError(f"Không đọc được ảnh: {path}")
        yield img


# ---------------------------------------------------------------- xử lý 1 trang

def flatten_illumination(gray):
    """Chia cho nền (ước lượng bằng closing + blur) để giấy thành trắng đều."""
    k = max(15, (min(gray.shape) // 40) | 1)
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    bg = cv2.GaussianBlur(bg, (0, 0), k / 2)
    norm = cv2.divide(gray, bg, scale=255)
    return norm


def ink_mask(norm):
    """Mask chữ: điểm tối, bỏ vệt lớn (ngón tay, mép sách), vệt chạm mép ảnh và nhiễu."""
    mask = (norm < 150).astype(np.uint8)
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


def find_skew(mask, max_deg=6.0):
    """Góc xoay làm các dòng chữ nằm ngang nhất (tối đa phương sai profile hàng)."""
    scale = 1000 / max(mask.shape)
    small = cv2.resize(mask * 255, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    h, w = small.shape
    center = (w / 2, h / 2)

    def score(a):
        m = cv2.getRotationMatrix2D(center, a, 1.0)
        r = cv2.warpAffine(small, m, (w, h))
        return np.var(r.sum(axis=1, dtype=np.float64))

    best = max(np.arange(-max_deg, max_deg + 0.01, 0.5), key=score)
    best = max(np.arange(best - 0.5, best + 0.51, 0.1), key=score)
    return float(best)


def rotate(img, angle, border):
    h, w = img.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=border)


def main_page_region(mask):
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
    return region, (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)


def enhance(norm):
    """Đẩy nền gần trắng thành trắng hẳn, tăng tương phản chữ, giữ khử răng cưa."""
    lut = np.clip((np.arange(256) - 60) * 255.0 / (215 - 60), 0, 255).astype(np.uint8)
    return cv2.LUT(norm, lut)


def process_page(gray, debug_path=None):
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
    crop = page[y0:y1, x0:x1]

    if debug_path:
        dbg = cv2.cvtColor(norm, cv2.COLOR_GRAY2BGR)
        dbg[mask > 0] = (0, 0, 255)
        cv2.rectangle(dbg, (x0, y0), (x1, y1), (0, 200, 0), 8)
        cv2.imwrite(str(debug_path), cv2.resize(dbg, None, fx=0.35, fy=0.35))
    return crop, angle


# ---------------------------------------------------------------- ghép PDF

def build_pdf(crops, out_path, margin=0.09, jpeg_quality=80):
    """Đặt mọi trang lên cùng khổ: chiều rộng chữ bằng nhau, căn trên."""
    # tỉ lệ khung chữ = trung vị các trang (+5% dư); trang nào cao hơn thì thu nhỏ cho vừa
    content_w = 1600  # px, ~ 300dpi trên A5 sau khi trừ lề
    body_aspect = float(np.median([c.shape[0] / c.shape[1] for c in crops])) * 1.05
    pad = int(content_w * margin / (1 - 2 * margin))
    page_w = content_w + 2 * pad
    page_h = int(content_w * body_aspect) + 2 * pad

    doc = fitz.open()
    pt_per_px = PAGE_WIDTH_PT / page_w
    for crop in crops:
        h, w = crop.shape
        s = min(content_w / w, (page_h - 2 * pad) / h)
        resized = cv2.resize(crop, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
        canvas = np.full((page_h, page_w), 255, np.uint8)
        rh, rw = resized.shape
        x = (page_w - rw) // 2
        canvas[pad:pad + rh, x:x + rw] = resized
        ok, buf = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
        page = doc.new_page(width=page_w * pt_per_px, height=page_h * pt_per_px)
        page.insert_image(page.rect, stream=buf.tobytes())

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path, garbage=4, deflate=True)


def convert(inputs, out_path, debug_dir=None, ocr=True):
    crops = []
    for src in inputs:
        for gray in load_images(src):
            idx = len(crops) + 1
            dbg = debug_dir / f"page_{idx:03d}.jpg" if debug_dir else None
            crop, angle = process_page(gray, dbg)
            crops.append(crop)
            print(f"  trang {idx}: xoay {angle:+.1f}°, vùng chữ {crop.shape[1]}x{crop.shape[0]}")
    if not crops:
        raise SystemExit("Không có trang nào.")
    if not ocr:
        build_pdf(crops, out_path)
        print(f"=> {out_path} ({len(crops)} trang ảnh)")
        return

    import book_text  # cần macOS (Apple Vision)

    scan_path = out_path.with_name(f"{out_path.stem} - scan.pdf")
    build_pdf(crops, scan_path)
    pages = []
    for idx, crop in enumerate(crops, 1):
        pages.append(book_text.ocr_page(crop))
        print(f"  OCR trang {idx}: {len(pages[-1])} dòng")
    book = book_text.build_book(pages)
    title = out_path.stem
    md_path = out_path.with_suffix(".md")
    md_path.write_text(book_text.to_markdown(book, title), encoding="utf-8")
    n = book_text.to_pdf(book, title, out_path)
    print(f"=> {out_path} ({n} trang, từ {len(crops)} trang chụp)")
    print(f"=> {md_path}")
    print(f"=> {scan_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path, help="file PDF / ảnh, hoặc thư mục")
    ap.add_argument("-o", "--output", type=Path, help="file PDF đầu ra (mặc định: output/<tên>.pdf)")
    ap.add_argument("--debug", action="store_true", help="lưu ảnh đánh dấu vùng cắt vào output/debug")
    ap.add_argument("--scan-only", action="store_true", help="không OCR, chỉ xuất PDF ảnh đã làm sạch")
    args = ap.parse_args()

    src = args.input
    if src.is_dir():
        pdfs = sorted(p for p in src.iterdir() if p.suffix.lower() == ".pdf")
        images = sorted(p for p in src.iterdir() if p.suffix.lower() in IMAGE_EXTS)
        # thư mục ảnh -> 1 PDF; thư mục PDF -> mỗi PDF 1 output
        jobs = [(pdf, [pdf]) for pdf in pdfs]
        if images:
            jobs.append((src, images))
    elif src.exists():
        jobs = [(src, [src])]
    else:
        sys.exit(f"Không tìm thấy: {src}")

    for name_src, inputs in jobs:
        out = args.output if args.output and len(jobs) == 1 else Path("output") / f"{name_src.stem}.pdf"
        debug_dir = None
        if args.debug:
            debug_dir = Path("output") / "debug" / name_src.stem
            debug_dir.mkdir(parents=True, exist_ok=True)
        print(f"{name_src}:")
        out.parent.mkdir(parents=True, exist_ok=True)
        convert(inputs, out, debug_dir, ocr=not args.scan_only)


if __name__ == "__main__":
    main()
