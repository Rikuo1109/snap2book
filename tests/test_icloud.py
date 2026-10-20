import os

from snap2book import icloud


def test_copies_and_overwrites_without_leftovers(tmp_path):
    src = tmp_path / "sách.pdf"
    dest_dir = tmp_path / "icloud" / "Sách đã xử lý"
    src.write_bytes(b"ban 1")
    assert icloud.copy_to_icloud(src, dest_dir) == dest_dir / "sách.pdf"
    src.write_bytes(b"ban 2")
    icloud.copy_to_icloud(src, dest_dir)
    assert (dest_dir / "sách.pdf").read_bytes() == b"ban 2"  # chép đè, không sinh bản trùng
    assert os.listdir(dest_dir) == ["sách.pdf"]  # không còn file tạm


def test_permission_denied_is_reported_not_raised(tmp_path, caplog):
    src = tmp_path / "a.pdf"
    src.write_bytes(b"x")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        assert icloud.copy_to_icloud(src, locked) is None
    finally:
        locked.chmod(0o700)
    assert "Quyền riêng tư" in caplog.text


def test_skipped_when_icloud_drive_missing(tmp_path, monkeypatch):
    drive = tmp_path / "no-icloud"
    monkeypatch.setattr(icloud, "ICLOUD_DRIVE", drive)
    src = tmp_path / "a.pdf"
    src.write_bytes(b"x")
    assert icloud.copy_to_icloud(src, drive / "snap2book") is None
    assert not drive.exists()
