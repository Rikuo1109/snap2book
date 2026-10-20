"""Cache kết quả từng trang (ảnh đã làm sạch + dòng OCR) để chạy lại nhanh.

Khoá mỗi trang = băm điểm ảnh gốc + tuỳ chọn làm phẳng + phiên bản code (băm mã nguồn
các module làm sạch), nên đổi ảnh, đổi tuỳ chọn hay sửa code thì trang đó tự tính lại.
Mỗi trang một thư mục <root>/<khoá>/:
  page.png, unflattened.png   ảnh đã làm sạch (và ảnh trước khi làm phẳng, nếu có)
  page.json                   góc xoay, độ võng...; ghi sau cùng, có nó mới là đủ bộ
  ocr-<khoá OCR>.json         dòng OCR; khoá OCR gồm mã nguồn ocr.py, bản macOS (Vision),
                              có OCR ảnh phụ trước khi làm phẳng hay không
Trang không dùng tới quá MAX_AGE_DAYS ngày thì bị xoá.
"""

import hashlib
import json
import os
import platform
import shutil
import time
from dataclasses import asdict
from functools import cache
from pathlib import Path

import cv2
import numpy as np

from snap2book import cleanup, dewarp, ocr
from snap2book.cleanup import CleanedPage
from snap2book.ocr import Line

FORMAT_VERSION = 1  # tăng khi đổi cách lưu
MAX_AGE_DAYS = 30  # trang không dùng quá chừng này ngày thì xoá khỏi cache


def _digest(*parts: bytes | str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode() if isinstance(part, str) else part)
        h.update(b"\0")
    return h.hexdigest()


def _source(module) -> bytes:
    return Path(module.__file__).read_bytes()


@cache
def clean_version() -> str:
    """Phiên bản phần làm sạch: đổi khi sửa cleanup.py / dewarp.py."""
    return _digest(str(FORMAT_VERSION), _source(cleanup), _source(dewarp))


@cache
def ocr_version() -> str:
    """Phiên bản phần OCR: đổi khi sửa ocr.py hoặc cập nhật macOS (Vision đọc khác đi)."""
    return _digest(str(FORMAT_VERSION), _source(ocr), platform.mac_ver()[0])


class PageCache:
    def __init__(self, root: Path):
        self.root = root

    def key(self, gray: np.ndarray, flatten: bool) -> str:
        """Khoá của một ảnh trang gốc (ảnh xám) với tuỳ chọn làm phẳng."""
        gray = np.ascontiguousarray(gray)
        return _digest(clean_version(), str(flatten), str(gray.shape), gray.data)[:32]

    def load_clean(self, key: str) -> CleanedPage | None:
        d = self.root / key
        try:
            meta = json.loads((d / "page.json").read_text())
            image = _read_png(d / "page.png")
            unflattened = _read_png(d / "unflattened.png") if meta["flattened"] else None
        except (OSError, ValueError, KeyError):
            return None
        os.utime(d)  # đánh dấu vừa dùng, để prune không xoá
        return CleanedPage(image, meta["angle"], meta["curve"], meta["flattened"], unflattened)

    def save_clean(self, key: str, page: CleanedPage) -> None:
        d = self.root / key
        d.mkdir(parents=True, exist_ok=True)
        _write(d / "page.png", _png(page.image))
        if page.unflattened is not None:
            _write(d / "unflattened.png", _png(page.unflattened))
        meta = {"angle": page.angle, "curve": page.curve, "flattened": page.flattened}
        _write(d / "page.json", json.dumps(meta).encode())

    def load_ocr(self, key: str, with_alt: bool) -> list[Line] | None:
        try:
            rows = json.loads(self._ocr_path(key, with_alt).read_text(encoding="utf-8"))
            return [Line(**row) for row in rows]
        except (OSError, ValueError, TypeError):
            return None

    def save_ocr(self, key: str, with_alt: bool, lines: list[Line]) -> None:
        path = self._ocr_path(key, with_alt)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write(path, json.dumps([asdict(line) for line in lines], ensure_ascii=False).encode())

    def prune(self, max_age_days: float = MAX_AGE_DAYS) -> int:
        """Xoá các trang lâu không dùng (ảnh đã bỏ, code / tuỳ chọn đã đổi); trả về số trang xoá.
        Không xoá ngay trang không dùng ở lần chạy này: chạy xen kẽ --no-dewarp và mặc định
        thì cả hai bộ đều còn."""
        if not self.root.is_dir():
            return 0
        cutoff = time.time() - max_age_days * 86400
        stale = [d for d in self.root.iterdir() if d.is_dir() and d.stat().st_mtime < cutoff]
        for d in stale:
            shutil.rmtree(d, ignore_errors=True)
        return len(stale)

    def _ocr_path(self, key: str, with_alt: bool) -> Path:
        return self.root / key / f"ocr-{_digest(ocr_version(), str(with_alt))[:16]}.json"


def _png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("Không mã hoá được ảnh PNG")
    return buf.tobytes()


def _read_png(path: Path) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Ảnh cache hỏng: {path}")
    return img


def _write(path: Path, data: bytes) -> None:
    """Ghi qua file tạm rồi đổi tên: chạy dở bị ngắt hay hai tiến trình cùng ghi
    cũng không để lại file hỏng."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
