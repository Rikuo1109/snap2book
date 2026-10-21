import pytest

from snap2book.spellfix import Vocabulary, base_form, fix_text, mark_distance

DICTIONARY = {
    "hắn",
    "hằn",
    "định",
    "đình",
    "chẳng",
    "chăng",
    "mấy",
    "đến",
    "tựa",
    "tua",
    "ngu",
    "ngư",
    "quyết",
    "lăng",
    "nhăng",
    "thì",
    "có",
    "gì",
    "không",
    "ưa",
    "đi",
    "và",
    "là",
}


def is_valid(word):
    return word.lower() in DICTIONARY


def fix(text, alternatives=(), book=""):
    return fix_text(text, alternatives, is_valid, Vocabulary([book, text]))[0]


def test_base_form_and_mark_distance():
    assert base_form("Đường") == "duong"
    assert mark_distance("dịnh", "định") == 1
    assert mark_distance("dịnh", "đình") == 2
    assert mark_distance("chắng", "chẳng") == 1  # đổi dấu thanh tính 1, không phải 2
    assert mark_distance("mãy", "mấy") == 2


def test_alternative_reading_fixes_misspelled_word():
    assert fix("quyết dịnh", ["quyết định"]) == "quyết định"


def test_book_vocabulary_picks_closest_then_most_frequent():
    book = "gia đình gia đình gia đình quyết định hắn hắn hắn"
    assert fix("quyết dịnh", book=book) == "quyết định"  # gần dấu hơn "đình" dù "đình" nhiều hơn
    assert fix("lăng nhăng hăn", ["lăng nhăng hằn"], book=book) == "lăng nhăng hắn"


def test_names_fixed_from_book_vocabulary():
    book = "Koichi Koichi Koichi"
    assert fix("Doi Kõichi", book=book) == "Doi Koichi"


def test_valid_words_and_unknown_words_untouched():
    assert fix("thì chăng có gì", ["thì chẳng có gì"]) == "thì chăng có gì"  # đúng chính tả: không đụng
    assert fix("Kazuma đi", ["Kazama đi"]) == "Kazuma đi"  # khác chữ cái: không thay


@pytest.mark.parametrize("book", ["ngu", "ngu ngốc"])
def test_frequent_word_wrongly_flagged_is_kept(book):
    # từ điển báo nhầm "ngu" là sai: chỉ thay khi ứng viên phổ biến hơn chính nó trong sách
    def strict(word):
        return word != "ngu" and is_valid(word)

    vocab = Vocabulary([book, "ngu"])
    assert fix_text("ngu", ["ngư"], strict, vocab)[0] == "ngu"


def test_case_preserved():
    assert fix("Dến", book="đến đến đến") == "Đến"


def test_word_kept_when_its_phrase_recurs_in_the_book():
    # từ điển báo nhầm "ngu" là sai; "ngủ" phổ biến hơn, nhưng cụm "ngu ngốc" lặp lại trong sách
    def strict(word):
        return word != "ngu" and is_valid(word)

    book = ["thật ngu ngốc", "đi ngủ sớm", "buồn ngủ quá", "ngủ ngon", "giấc ngủ dài"]
    vocab = Vocabulary([*book, "anh ngu ngốc"])
    assert fix_text("anh ngu ngốc", [], strict, vocab)[0] == "anh ngu ngốc"


def test_repeated_misreading_still_fixed_when_context_supports_candidate():
    # "chắng phải" đọc sai 2 lần, nhưng "chẳng phải" xuất hiện nhiều hơn
    book = ["thì chắng phải", "chẳng phải thế", "chẳng phải vậy", "chẳng phải đâu"]
    vocab = Vocabulary([*book, "nó chắng phải"])
    assert fix_text("nó chắng phải", [], lambda w: w != "chắng", vocab)[0] == "nó chẳng phải"


def test_context_beats_fewer_marks():
    # "may" chỉ khác 1 dấu, "mấy" khác 2, nhưng "không mấy" mới là cụm có trong sách
    book = ["không mấy ai", "không mấy khi", "gặp may mắn", "may quá"]
    vocab = Vocabulary([*book, "cô không mãy ưa"])
    assert fix_text("cô không mãy ưa", [], is_valid, vocab)[0] == "cô không mấy ưa"
