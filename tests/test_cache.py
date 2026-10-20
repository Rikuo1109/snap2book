import os
import time

import cv2
import numpy as np
import pytest

from snap2book import cache as cache_mod
from snap2book import pages as pages_mod
from snap2book.ocr import Line
from snap2book.pages import PageTask, Settings, process_pages

CALLS = []  # các lần gọi OCR giả: (ảnh, có ảnh phụ hay không)


def fake_ocr(img, alt):
    """OCR giả: một dòng ghi độ sáng trung bình của ảnh (để phân biệt các trang)."""
    CALLS.append(alt is not None)
    return [Line(f"trang {img.mean():.3f}", 0.1, 0.2, 0.9, 0.25, ["phương án"])]


def photo(seed=0):
    """Ảnh "chụp" giả: vài dòng chữ đen trên nền xám."""
    img = np.full((1800, 1200), 200, np.uint8)
    for i in range(12):
        text = f"dong chu so {i + seed} " * 2
        cv2.putText(img, text, (150, 300 + i * 90), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 30, 2)
    return img


def run(images, cache_dir, jobs=1, **kw):
    settings = Settings(cache_dir=cache_dir, **kw)
    return list(process_pages([PageTask(img) for img in images], settings, jobs, ocr=fake_ocr))


@pytest.fixture(autouse=True)
def reset_calls():
    CALLS.clear()


@pytest.fixture
def cleans(monkeypatch):
    """Đếm số lần làm sạch trang."""
    calls = []
    real = pages_mod.clean_page

    def counting(*args, **kw):
        calls.append(1)
        return real(*args, **kw)

    monkeypatch.setattr(pages_mod, "clean_page", counting)
    return calls


def test_rerun_hits_cache(tmp_path, cleans):
    first = run([photo(0), photo(1)], tmp_path)
    assert len(cleans) == 2 and len(CALLS) == 2
    assert not any(p.cached for p in first)

    second = run([photo(0), photo(1)], tmp_path)
    assert len(cleans) == 2 and len(CALLS) == 2  # không làm sạch, không OCR lại
    assert all(p.cached for p in second)
    for a, b in zip(first, second, strict=True):
        assert np.array_equal(a.image, b.image)
        assert (a.angle, a.curve, a.flattened) == (b.angle, b.curve, b.flattened)
        assert a.lines == b.lines


def test_no_cache_dir_recomputes(cleans):
    run([photo()], None)
    run([photo()], None)
    assert len(cleans) == 2 and len(CALLS) == 2


def test_changed_image_misses(tmp_path, cleans):
    run([photo(0)], tmp_path)
    changed = photo(0)
    changed[5, 5] = 0
    (page,) = run([changed], tmp_path)
    assert not page.cached and len(cleans) == 2 and len(CALLS) == 2


def test_flatten_option_is_part_of_key(tmp_path, cleans):
    run([photo()], tmp_path, flatten=True)
    run([photo()], tmp_path, flatten=False)
    assert len(cleans) == 2
    run([photo()], tmp_path, flatten=True)  # bộ cũ vẫn còn
    assert len(cleans) == 2


def test_ocr_options_reuse_cleaned_page(tmp_path, cleans):
    run([photo()], tmp_path, with_alt=True)
    (page,) = run([photo()], tmp_path, with_alt=False)
    assert len(cleans) == 1  # ảnh đã làm sạch lấy từ cache
    assert len(CALLS) == 2 and not page.cached  # nhưng phải OCR lại

    run([photo()], tmp_path, ocr=False)  # chỉ-ảnh: không cần OCR
    assert len(cleans) == 1 and len(CALLS) == 2


def test_code_change_invalidates(tmp_path, monkeypatch, cleans):
    run([photo()], tmp_path)
    monkeypatch.setattr(cache_mod, "ocr_version", lambda: "ocr.py đã sửa")
    run([photo()], tmp_path)
    assert len(cleans) == 1 and len(CALLS) == 2

    monkeypatch.setattr(cache_mod, "clean_version", lambda: "cleanup.py đã sửa")
    run([photo()], tmp_path)
    assert len(cleans) == 2 and len(CALLS) == 3


def test_corrupt_entry_is_recomputed(tmp_path, cleans):
    (first,) = run([photo()], tmp_path)
    for png in tmp_path.glob("*/page.png"):
        png.write_bytes(b"hong")
    (page,) = run([photo()], tmp_path)
    assert not page.cached and len(cleans) == 2
    assert np.array_equal(page.image, first.image)


def test_debug_bypasses_cleanup_cache(tmp_path, cleans):
    run([photo()], tmp_path)
    debug = tmp_path / "debug.jpg"
    list(process_pages([PageTask(photo(), debug)], Settings(cache_dir=tmp_path), ocr=fake_ocr))
    assert len(cleans) == 2 and debug.exists()
    assert len(CALLS) == 1  # OCR vẫn lấy từ cache


def test_prune_removes_only_old_entries(tmp_path):
    run([photo(0), photo(1)], tmp_path)
    old, fresh = sorted(tmp_path.iterdir())
    past = time.time() - (cache_mod.MAX_AGE_DAYS + 1) * 86400
    os.utime(old, (past, past))
    assert cache_mod.PageCache(tmp_path).prune() == 1
    assert [d.name for d in tmp_path.iterdir()] == [fresh.name]


def test_parallel_keeps_order_and_matches_serial(tmp_path):
    images = [photo(i) for i in range(4)]
    serial = run(images, None)
    run(images[:2], tmp_path, jobs=2)  # nửa đầu đã có trong cache
    parallel = run(images, tmp_path, jobs=2)
    assert [p.cached for p in parallel] == [True, True, False, False]
    for a, b in zip(serial, parallel, strict=True):
        assert np.array_equal(a.image, b.image)
        assert a.lines == b.lines
