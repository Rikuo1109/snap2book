"""Xử lý từng trang (làm sạch -> OCR), song song nhiều tiến trình, có cache.

Dùng tiến trình chứ không dùng luồng: làm sạch là OpenCV nặng CPU, còn Apple Vision gọi
từ nhiều luồng trong một tiến trình không nhanh hơn chạy tuần tự (đo trên máy 11 nhân:
26 ảnh mất 16s tuần tự, 15-17s với 2-8 luồng, 4s với 8 tiến trình; kết quả giống hệt).

Tiến trình chính đọc ảnh (sources) rồi gửi sang; tiến trình con không được import pymupdf:
pymupdf 2 nạp onnxruntime, và onnxruntime bị treo khi tiến trình con thoát. Lưu ý spawn chạy lại
module chính (lệnh snap2book -> cli -> pipeline -> sources, scan_pdf), nên các module đó chỉ
import pymupdf bên trong hàm; tests/test_pages.py kiểm tra điều này.
"""

from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
from functools import partial
from multiprocessing import get_context
from pathlib import Path

import cv2
import numpy as np

from snap2book.cache import PageCache
from snap2book.cleanup import clean_page
from snap2book.ocr import Line

OcrFunc = Callable[[np.ndarray, np.ndarray | None], list[Line]]


@dataclass(frozen=True)
class PageTask:
    image: np.ndarray  # ảnh chụp gốc (ảnh xám)
    debug_path: Path | None = None  # lưu ảnh đánh dấu vùng cắt (luôn làm sạch lại, không lấy cache)


@dataclass(frozen=True)
class Settings:
    flatten: bool = True  # làm phẳng trang cong
    ocr: bool = True  # False: chỉ làm sạch (chế độ chỉ-ảnh)
    with_alt: bool = True  # OCR thêm ảnh trước khi làm phẳng làm phương án đọc phụ
    cache_dir: Path | None = None  # None: không dùng cache


@dataclass
class PageResult:
    image: np.ndarray  # ảnh đã làm sạch
    angle: float
    curve: float
    flattened: bool
    lines: list[Line] | None  # None khi không OCR
    cached: bool  # lấy toàn bộ từ cache, không phải tính lại gì


def process_page(task: PageTask, settings: Settings, ocr: OcrFunc | None = None) -> PageResult:
    """Một trang: lấy cache nếu có, không thì làm sạch / OCR rồi ghi cache.
    ocr: hàm OCR (mặc định Apple Vision), thay được khi kiểm thử."""
    gray = task.image
    cache = PageCache(settings.cache_dir) if settings.cache_dir else None
    key = cache.key(gray, settings.flatten) if cache else ""

    page = cache.load_clean(key) if cache and not task.debug_path else None
    cached = page is not None
    if page is None:
        page = clean_page(gray, task.debug_path, settings.flatten)
        if cache:
            cache.save_clean(key, page)

    lines = None
    if settings.ocr:
        lines = cache.load_ocr(key, settings.with_alt) if cache else None
        if lines is None:
            cached = False
            if ocr is None:
                # import muộn: OCR cần macOS (Apple Vision), chế độ chỉ-ảnh thì không cần
                from snap2book.ocr import ocr_page as ocr
            lines = ocr(page.image, page.unflattened if settings.with_alt else None)
            if cache:
                cache.save_ocr(key, settings.with_alt, lines)
    return PageResult(page.image, page.angle, page.curve, page.flattened, lines, cached)


def cached_page(task: PageTask, settings: Settings) -> PageResult | None:
    """Kết quả của trang nếu cache đã có đủ (không phải làm sạch hay OCR lại), không thì None."""
    if not settings.cache_dir or task.debug_path:
        return None
    cache = PageCache(settings.cache_dir)
    key = cache.key(task.image, settings.flatten)
    page = cache.load_clean(key)
    if page is None:
        return None
    lines = None
    if settings.ocr:
        lines = cache.load_ocr(key, settings.with_alt)
        if lines is None:
            return None
    return PageResult(page.image, page.angle, page.curve, page.flattened, lines, cached=True)


def process_pages(
    tasks: Iterable[PageTask], settings: Settings, jobs: int = 1, ocr: OcrFunc | None = None
) -> Iterator[PageResult]:
    """Kết quả các trang, đúng thứ tự tasks (trả dần ngay khi trang đầu dãy xong).
    jobs > 1: các trang chưa có trong cache chạy song song bằng chừng ấy tiến trình
    (chỉ khởi động tiến trình khi có trang phải tính)."""
    work = partial(process_page, settings=settings, ocr=ocr)
    if jobs <= 1:
        for task in tasks:
            yield cached_page(task, settings) or work(task)
        return
    ex = None
    pending: deque[PageResult | Future[PageResult]] = deque()  # đúng thứ tự trang
    try:
        for task in tasks:
            hit = cached_page(task, settings)
            if hit is None:
                if ex is None:
                    # spawn chứ không fork: fork tiến trình đã nạp Objective-C (Vision) không an toàn
                    ex = ProcessPoolExecutor(jobs, mp_context=get_context("spawn"), initializer=_init_worker)
                pending.append(ex.submit(work, task))
            else:
                pending.append(hit)
            # trả các trang đầu dãy đã xong; chỉ gửi trước vài trang mỗi tiến trình vì ảnh gốc
            # lớn (~12MB), gửi cả sách một lúc thì tốn RAM
            while pending and (len(pending) >= 2 * jobs or _done(pending[0])):
                yield _result(pending.popleft())
        while pending:
            yield _result(pending.popleft())
    finally:
        if ex is not None:
            ex.shutdown(cancel_futures=True)


def _done(item: PageResult | Future[PageResult]) -> bool:
    return not isinstance(item, Future) or item.done()


def _result(item: PageResult | Future[PageResult]) -> PageResult:
    return item.result() if isinstance(item, Future) else item


def _init_worker() -> None:
    cv2.setNumThreads(1)  # đã song song theo trang, để OpenCV tự chia luồng thêm thì tranh nhau CPU
