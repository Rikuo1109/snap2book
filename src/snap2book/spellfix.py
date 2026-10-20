"""Sửa lỗi dấu do OCR theo từ điển chính tả và chính cuốn sách.

OCR tiếng Việt hay đọc sai dấu ("dịnh" thay vì "định", "hăn" thay vì "hắn"). Với mỗi từ SAI
chính tả, xét các ứng viên CHỈ KHÁC DẤU (cùng bộ chữ cái), lấy từ hai nguồn:
  - các phương án đọc khác của dòng: ứng viên phụ của Vision, bản OCR ảnh trước khi làm phẳng;
  - các từ cùng bộ chữ cái đã xuất hiện trong sách (để sửa cả tên riêng: "Kõichi" → "Koichi").
Ứng viên phải đúng chính tả hoặc xuất hiện nhiều lần trong sách. Ưu tiên ứng viên khác ít dấu nhất
("dịnh" → "định" chứ không phải "đình"), rồi đến ứng viên xuất hiện nhiều trong sách; ứng viên chỉ lấy
từ sách thì chỉ được khác tối đa MAX_SPELL_MARKS dấu. Chỉ thay khi ứng viên phổ biến hơn chính từ đang
xét, nên từ đúng mà từ điển báo nhầm ("ngu") vẫn được giữ.

Không bao giờ thay sang từ khác chữ cái; từ đúng chính tả không bị đụng tới. Vì vậy không sửa
được từ có thật nhưng sai ngữ cảnh ("chẳng" → "chăng").
"""

import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Protocol

WORD = re.compile(r"[^\W\d_]+")  # chỉ chữ cái (kể cả có dấu), không số, không gạch dưới
NAME_MIN_COUNT = 3  # từ không có trong từ điển nhưng xuất hiện ít nhất chừng này lần (tên riêng)
ALT_BONUS = 0.5  # ưu tiên nhẹ ứng viên có trong phương án đọc khác của chính dòng đó
MAX_VOCAB_MARKS = 2  # ứng viên chỉ lấy từ sách (không có trong ảnh) được khác tối đa chừng này dấu

IsValid = Callable[[str], bool]


class OcrLine(Protocol):
    text: str
    alternatives: list[str]


@dataclass
class Change:
    before: str
    after: str
    line: str  # dòng sau khi sửa, để xem ngữ cảnh


def base_form(word: str) -> str:
    """Bỏ dấu thanh, dấu mũ/móc, đ → d, chữ thường: "Đường" → "duong"."""
    decomposed = unicodedata.normalize("NFD", word.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn").lower()


TONES = {"\u0300", "\u0301", "\u0303", "\u0309", "\u0323"}  # huyền, sắc, ngã, hỏi, nặng
SHAPES = {"\u0302", "\u0306", "\u031b"}  # mũ (â ê ô), trăng (ă), móc (ơ ư)


def mark_distance(a: str, b: str) -> int:
    """Số chỗ khác dấu giữa a và b (cùng bộ chữ cái), mỗi chữ cái tính riêng dấu thanh, dấu
    mũ/trăng/móc và d/đ: "dịnh"/"định" = 1, "dịnh"/"đình" = 2, "chắng"/"chẳng" = 1."""

    def marks(ch: str) -> tuple[frozenset[str], frozenset[str], bool]:
        parts = set(unicodedata.normalize("NFD", ch))
        return frozenset(parts & TONES), frozenset(parts & SHAPES), ch in "đĐ"

    return sum(
        sum(x != y for x, y in zip(marks(p), marks(q), strict=True))
        for p, q in zip(a.lower(), b.lower(), strict=True)
    )


def _match_case(word: str, like: str) -> str:
    if like.isupper() and len(like) > 1:
        return word.upper()
    if like[:1].isupper():
        return word[:1].upper() + word[1:]
    return word


class Vocabulary:
    """Tần suất từ (không phân biệt hoa thường) trong sách, nhóm theo bộ chữ cái."""

    def __init__(self, texts: Iterable[str]):
        self.count = Counter(w.lower() for text in texts for w in WORD.findall(text))
        self.by_base: dict[str, list[str]] = {}
        for word in self.count:
            self.by_base.setdefault(base_form(word), []).append(word)

    def __getitem__(self, word: str) -> int:
        return self.count[word.lower()]

    def variants(self, word: str) -> list[str]:
        return self.by_base.get(base_form(word), [])


def _aligned(words: Sequence[str], alternative: str) -> dict[int, str]:
    """Gióng từ của một phương án đọc với words theo dạng không dấu: {chỉ số trong words: từ}."""
    alt_words = WORD.findall(alternative)
    matcher = SequenceMatcher(
        None, [base_form(w) for w in words], [base_form(w) for w in alt_words], autojunk=False
    )
    return {
        block.a + k: alt_words[block.b + k]
        for block in matcher.get_matching_blocks()
        for k in range(block.size)
    }


def fix_text(
    text: str, alternatives: Iterable[str], is_valid: IsValid, vocab: Vocabulary
) -> tuple[str, list[tuple[str, str]]]:
    """Sửa các từ sai chính tả của text. Trả về (text mới, [(cũ, mới)])."""
    spans = [(m.start(), m.end(), m.group()) for m in WORD.finditer(text)]
    words = [w for _, _, w in spans]
    bad = [i for i, w in enumerate(words) if not is_valid(w)]
    if not bad:
        return text, []

    from_alts: dict[int, list[str]] = {i: [] for i in bad}
    for alt in alternatives:
        for i, candidate in _aligned(words, alt).items():
            if i in from_alts:
                from_alts[i].append(candidate)

    def acceptable(candidate: str, word: str) -> bool:
        return candidate.lower() != word.lower() and (
            is_valid(candidate) or vocab[candidate] >= NAME_MIN_COUNT
        )

    replacement = {}
    for i in bad:
        word = words[i]
        scores: dict[str, float] = {}
        for candidate in from_alts[i]:
            if acceptable(candidate, word):
                scores[candidate] = vocab[candidate] + ALT_BONUS
        for candidate in vocab.variants(word):
            candidate = _match_case(candidate, word)
            if (
                candidate not in scores
                and acceptable(candidate, word)
                and mark_distance(candidate, word) <= MAX_VOCAB_MARKS
            ):
                scores[candidate] = vocab[candidate]
        if scores:
            # khác ít dấu nhất, rồi phổ biến nhất; hoà nhau thì giữ thứ tự gặp trước
            best = min(scores, key=lambda c: (mark_distance(c, word), -scores[c]))
            if scores[best] > vocab[word] - 1:  # không tính chính lần xuất hiện này của từ
                replacement[i] = best

    if not replacement:
        return text, []
    out, pos, changes = [], 0, []
    for i, (start, end, word) in enumerate(spans):
        if i in replacement:
            out += [text[pos:start], replacement[i]]
            pos = end
            changes.append((word, replacement[i]))
    out.append(text[pos:])
    return "".join(out), changes


def fix_pages(pages: Sequence[Sequence[OcrLine]], is_valid: IsValid) -> list[list[Change]]:
    """Sửa tại chỗ Line.text của mọi dòng OCR trong sách. Trả về các thay đổi theo từng trang."""
    vocab = Vocabulary(line.text for page in pages for line in page)
    result = []
    for page in pages:
        changes = []
        for line in page:
            line.text, fixed = fix_text(line.text, line.alternatives, is_valid, vocab)
            changes += [Change(before, after, line.text) for before, after in fixed]
        result.append(changes)
    return result


class MacSpellChecker:
    """Từ điển chính tả tiếng Việt có sẵn của macOS (NSSpellChecker), có cache."""

    LANGUAGE = "vi"

    def __init__(self) -> None:
        import AppKit  # pyobjc, chỉ có trên macOS

        self._checker = AppKit.NSSpellChecker.sharedSpellChecker()
        if self.LANGUAGE not in self._checker.availableLanguages():
            raise RuntimeError("macOS không có từ điển chính tả tiếng Việt")
        self._cache: dict[str, bool] = {}

    def __call__(self, word: str) -> bool:
        if word not in self._cache:
            check = (
                self._checker.checkSpellingOfString_startingAt_language_wrap_inSpellDocumentWithTag_wordCount_
            )
            miss = check(word, 0, self.LANGUAGE, False, 0, None)[0]
            self._cache[word] = miss.length == 0
        return self._cache[word]
