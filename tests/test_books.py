import json
import subprocess

import pymupdf
import pytest

from snap2book import books


def make_pdf(path, *pages, title="Sách"):
    doc = pymupdf.open()
    for text in pages:
        doc.new_page().insert_text((72, 72), text)
    doc.set_metadata({"title": title})
    doc.save(path)
    return path


class FakeRun:
    """Thay cho subprocess.run: ghi lại lệnh, không mở app Sách thật."""

    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if self.fail:
            raise subprocess.CalledProcessError(1, cmd)


@pytest.fixture(autouse=True)
def on_mac(monkeypatch):
    monkeypatch.setattr(books.sys, "platform", "darwin")


def test_pushes_once_then_skips_unchanged(tmp_path):
    pdf = make_pdf(tmp_path / "sach.pdf", "trang một", "trang hai")
    run = FakeRun()
    assert books.send_to_books(pdf, run)
    assert run.calls == [[*books.OPEN_COMMAND, str(pdf)]]

    make_pdf(pdf, "trang một", "trang hai")  # ghi lại, byte có thể khác nhưng nội dung y hệt
    assert not books.send_to_books(pdf, run)
    assert len(run.calls) == 1


def test_pushes_again_when_content_changes(tmp_path, caplog):
    pdf = make_pdf(tmp_path / "sach.pdf", "bản cũ")
    run = FakeRun()
    books.send_to_books(pdf, run)
    make_pdf(pdf, "bản đã sửa lỗi OCR")
    with caplog.at_level("WARNING"):
        assert books.send_to_books(pdf, run)
    assert len(run.calls) == 2
    assert "bản cũ" in caplog.text  # nhắc xoá bản cũ trong Sách
    state = json.loads((tmp_path / books.STATE_FILE).read_text())
    assert state == {"sach.pdf": books.fingerprint(pdf)}


def test_failure_is_not_recorded(tmp_path):
    pdf = make_pdf(tmp_path / "sach.pdf", "nội dung")
    assert not books.send_to_books(pdf, FakeRun(fail=True))
    assert not (tmp_path / books.STATE_FILE).exists()
    assert books.send_to_books(pdf, FakeRun())  # lần sau vẫn thử đẩy


def test_skipped_outside_macos(tmp_path, monkeypatch):
    monkeypatch.setattr(books.sys, "platform", "linux")
    pdf = make_pdf(tmp_path / "sach.pdf", "nội dung")
    run = FakeRun()
    assert not books.send_to_books(pdf, run)
    assert run.calls == []


def test_fingerprint_ignores_bytes_but_sees_page_breaks(tmp_path):
    a = make_pdf(tmp_path / "a.pdf", "một hai", "ba")
    b = make_pdf(tmp_path / "b.pdf", "một hai", "ba")
    c = make_pdf(tmp_path / "c.pdf", "một", "hai ba")
    assert books.fingerprint(a) == books.fingerprint(b)
    assert books.fingerprint(a) != books.fingerprint(c)
