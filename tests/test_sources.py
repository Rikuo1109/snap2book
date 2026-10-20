import unicodedata

from snap2book.sources import find_jobs


def test_book_names_are_nfc(tmp_path):
    nfd = unicodedata.normalize("NFD", "Vụ án sát nhân")
    (tmp_path / f"{nfd}.pdf").write_bytes(b"")
    (tmp_path / "a.jpg").write_bytes(b"")
    names = [name for name, _ in find_jobs(tmp_path)]
    assert names == ["Vụ án sát nhân", tmp_path.name]
    assert all(unicodedata.is_normalized("NFC", n) for n in names)
