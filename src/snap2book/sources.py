"""Đọc ảnh đầu vào: PDF từ app scan (mỗi trang một ảnh) hoặc file ảnh rời."""

import logging
import re
import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"})
RENDER_DPI = 300  # khi trang PDF không phải đúng một ảnh thì render lại ở độ phân giải này
COVER_STEM = "cover"  # file cover.pdf / cover.jpg trong thư mục sách: bìa và các trang ảnh mở đầu
COVER_MAX_SIDE = 1600  # cạnh dài nhất của ảnh bìa lưu ra (px)


def is_cover(path: Path) -> bool:
    return path.stem.lower() == COVER_STEM


def save_cover_images(path: Path, out_dir: Path) -> list[Path]:
    """Lưu từng trang của file bìa thành ảnh màu out_dir/cover-<n>.jpg (không làm sạch, không
    OCR: bìa và trang ảnh giữ nguyên như chụp). Trả về các file đã lưu, theo thứ tự trang."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() != ".pdf":
        images = [cv2.imread(str(path), cv2.IMREAD_COLOR)]
    else:
        import pymupdf  # import trong hàm: xem load_images

        images = []
        with pymupdf.open(path) as doc:
            for page in doc:
                pix = page.get_pixmap(dpi=RENDER_DPI, colorspace=pymupdf.csRGB)
                rgb = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, 3)
                images.append(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    saved = []
    for n, img in enumerate(images, 1):
        if img is None:
            raise ValueError(f"Không đọc được ảnh: {path}")
        scale = COVER_MAX_SIDE / max(img.shape[:2])
        if scale < 1:
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        out = out_dir / f"cover-{n}.jpg"
        cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        saved.append(out)
    return saved


def load_images(path: Path) -> Iterator[np.ndarray]:
    """Các ảnh xám (uint8) theo thứ tự trang."""
    if path.suffix.lower() != ".pdf":
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError(f"Không đọc được ảnh: {path}")
        yield img
        return

    # import trong hàm: tiến trình con (spawn) chạy lại lệnh snap2book -> cli -> module này;
    # pymupdf 2 nạp onnxruntime, và onnxruntime treo khi tiến trình con thoát (xem pages.py)
    import pymupdf

    with pymupdf.open(path) as doc:
        for page in doc:
            img = None
            images = page.get_images()
            if len(images) == 1:  # lấy thẳng ảnh gốc, không render lại cho đỡ mất nét
                data = doc.extract_image(images[0][0])["image"]
                img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
            if img is None:
                pix = page.get_pixmap(dpi=RENDER_DPI, colorspace=pymupdf.csGRAY)
                img = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w).copy()
            yield img


def find_jobs(src: Path, exclude: Iterable[Path] = ()) -> list[tuple[str, list[Path]]]:
    """Gom đầu vào thành các cuốn sách: (tên, danh sách file theo thứ tự trang).

    Trong thư mục src:
      - mỗi file PDF là một cuốn (tên = tên file);
      - các ảnh rời là một cuốn (tên = tên thư mục);
      - mỗi thư mục con là một cuốn (tên = tên thư mục con), gồm mọi PDF và ảnh trong đó sắp theo
        tên kiểu tự nhiên ("2" trước "10"): một cuốn quét làm nhiều lần thì để chung một thư mục.
        File cover.pdf / cover.jpg trong đó (nếu có) đứng đầu danh sách: bìa sách, không OCR.
    Bỏ qua thư mục con ẩn, thư mục con là symlink (vd. resources/icloud trỏ ra iCloud Drive) và
    các thư mục trong exclude (vd. thư mục kết quả nằm trong thư mục đầu vào). Nếu một file PDF
    trùng tên với một thư mục con thì dùng thư mục con.

    Tên chuẩn hoá NFC: macOS lưu tên file tiếng Việt dạng tách dấu (NFD), để nguyên thì
    tiêu đề trong PDF/Markdown trông giống nhưng không khớp khi tìm kiếm, so sánh.
    """
    if not src.exists():
        raise FileNotFoundError(src)
    if not src.is_dir():
        return [(_nfc(src.stem), [src])]

    skip = {p.resolve() for p in exclude}
    entries = sorted(src.iterdir(), key=_natural_key)
    folders = [
        p
        for p in entries
        if p.is_dir() and not p.is_symlink() and not p.name.startswith(".") and p.resolve() not in skip
    ]
    folder_jobs = [(_nfc(d.name), files) for d in folders if (files := _book_files(d))]
    folder_names = {name for name, _ in folder_jobs}

    jobs = []
    for p in entries:
        if p.suffix.lower() != ".pdf":
            continue
        if _nfc(p.stem) in folder_names:
            log.warning("Bỏ qua %s: đã có thư mục cùng tên, chuyển file này vào thư mục đó", p.name)
            continue
        jobs.append((_nfc(p.stem), [p]))
    images = [p for p in entries if p.suffix.lower() in IMAGE_EXTS]
    if images:
        jobs.append((_nfc(src.name), images))
    return jobs + folder_jobs


def _book_files(folder: Path) -> list[Path]:
    """PDF và ảnh trong một thư mục sách, theo thứ tự tên tự nhiên (không đi sâu hơn); file bìa
    (nếu có) đứng đầu."""
    files = [
        p
        for p in sorted(folder.iterdir(), key=_natural_key)
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in IMAGE_EXTS | {".pdf"}
    ]
    return sorted(files, key=lambda p: not is_cover(p))  # sort ổn định: chỉ đưa bìa lên đầu


def _natural_key(path: Path) -> list:
    """Khoá sắp xếp tự nhiên: "Lần 2" trước "Lần 10"."""
    name = _nfc(path.name).lower()
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


def _nfc(name: str) -> str:
    return unicodedata.normalize("NFC", name)
