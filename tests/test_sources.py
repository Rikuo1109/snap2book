import unicodedata

from snap2book.sources import find_jobs


def test_book_names_are_nfc(tmp_path):
    nfd = unicodedata.normalize("NFD", "Vụ án sát nhân")
    (tmp_path / f"{nfd}.pdf").write_bytes(b"")
    (tmp_path / "a.jpg").write_bytes(b"")
    names = [name for name, _ in find_jobs(tmp_path)]
    assert names == ["Vụ án sát nhân", tmp_path.name]
    assert all(unicodedata.is_normalized("NFC", n) for n in names)


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_subfolder_is_one_book_in_natural_order(tmp_path):
    book = tmp_path / "Vụ án"
    parts = [touch(book / n) for n in ("Lần 10.pdf", "Lần 2.pdf", "Lần 1.pdf", "trang lẻ.jpg")]
    touch(book / ".DS_Store")
    jobs = dict(find_jobs(tmp_path))
    assert jobs == {"Vụ án": [parts[2], parts[1], parts[0], parts[3]]}


def test_skips_symlinks_hidden_and_excluded_folders(tmp_path):
    touch(tmp_path / "sách.pdf")
    touch(tmp_path / "Sách đã xử lý" / "kết quả.pdf")
    touch(tmp_path / ".cache" / "x.pdf")
    elsewhere = tmp_path.parent / f"{tmp_path.name}-elsewhere"
    touch(elsewhere / "scan.pdf")
    (tmp_path / "icloud").symlink_to(elsewhere)
    names = [name for name, _ in find_jobs(tmp_path, exclude=[tmp_path / "Sách đã xử lý"])]
    assert names == ["sách"]


def test_loose_pdf_with_same_name_as_folder_is_skipped(tmp_path, caplog):
    touch(tmp_path / "Vụ án.pdf")
    inside = touch(tmp_path / "Vụ án" / "phần 2.pdf")
    assert find_jobs(tmp_path) == [("Vụ án", [inside])]
    assert "chuyển file này vào thư mục" in caplog.text


def test_outputs_books_prefers_text_outputs(tmp_path):
    from snap2book.pipeline import output_paths

    out = output_paths(tmp_path, "Sách")  # mặc định chỉ EPUB, không PDF chữ
    assert [p.name for p in out.books()] == ["Sách.epub"]
    assert [p.name for p in output_paths(tmp_path, "Sách", pdf=True).books()] == ["Sách.epub", "Sách.pdf"]
    out.markdown = out.epub = None  # chế độ chỉ-ảnh
    assert not out.wants_text()
    assert [p.name for p in out.books()] == ["Sách - scan.pdf"]


def test_cover_file_comes_first(tmp_path):
    book = tmp_path / "Vụ án"
    parts = [touch(book / n) for n in ("1.pdf", "2.pdf", "cover.pdf")]
    assert dict(find_jobs(tmp_path)) == {"Vụ án": [parts[2], parts[0], parts[1]]}


def test_save_cover_images(tmp_path):
    import cv2
    import numpy as np
    import pymupdf

    from snap2book.sources import save_cover_images

    img = np.zeros((300, 200, 3), np.uint8)
    img[:, :, 2] = 200  # đỏ (BGR)
    ok, data = cv2.imencode(".png", img)
    doc = pymupdf.open()
    for _ in range(2):
        page = doc.new_page(width=200, height=300)
        page.insert_image(page.rect, stream=data.tobytes())
    doc.save(tmp_path / "cover.pdf")
    saved = save_cover_images(tmp_path / "cover.pdf", tmp_path / "images")
    assert [p.name for p in saved] == ["cover-1.jpg", "cover-2.jpg"]
    out = cv2.imread(str(saved[0]))
    assert max(out.shape[:2]) <= 1600 and out[150, 100, 2] > 150 and out[150, 100, 0] < 60  # giữ màu


def test_book_name_trailing_space_stripped(tmp_path):
    touch(tmp_path / "Những cánh đồng kim cương " / "1.pdf")
    assert [name for name, _ in find_jobs(tmp_path)] == ["Những cánh đồng kim cương"]
