"""Sửa dấu tiếng Việt bằng Claude (Haiku 5.5): bắt những lỗi OCR mà từ điển không bắt được vì
từ sai vẫn là từ có thật ("trò thành" → "trở thành", "Chăng bao lâu" → "Chẳng bao lâu").

Gửi từng lô đoạn văn (đánh số) cho model, nhận lại các đoạn đã sửa (JSON theo schema). Code chỉ
nhận thay đổi về dấu: mỗi từ sửa phải cùng bộ chữ cái với từ gốc (chỉ khác dấu thanh, dấu mũ /
trăng / móc, d/đ), cùng hoa/thường; dấu câu, khoảng trắng, số lượng từ phải giữ nguyên. Đoạn nào
model trả về khác cấu trúc thì giữ nguyên bản gốc; từ nào sửa quá dấu thì giữ từ gốc.

Cần gói anthropic (pip install -e ".[llm]") và ANTHROPIC_API_KEY (hoặc đã `ant auth login`).
"""

import json
import logging
import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from snap2book.spellfix import base_form

log = logging.getLogger(__name__)

MODEL = "claude-haiku-5-5"
PRICE_IN, PRICE_OUT = 0.10, 0.50  # USD / triệu token (prompt <= 100K token)
BATCH_CHARS = 6000  # mỗi lần gọi gửi khoảng chừng này ký tự
MAX_TOKENS = 16000

TOKEN = re.compile(r"[^\W\d_]+|[^\w]+|[\d_]+")  # từ / dấu câu + khoảng trắng / số

SYSTEM = """\
Bạn là người soát lỗi chính tả cho văn bản tiếng Việt được OCR từ ảnh chụp sách in. OCR hay \
nhận nhầm dấu: dấu thanh (huyền, sắc, hỏi, ngã, nặng), dấu mũ / trăng / móc (â ê ô ă ơ ư), \
và d/đ. Ví dụ: "trò thành" → "trở thành", "Chăng bao lâu" → "Chẳng bao lâu", \
"Thể nhưng" → "Thế nhưng", "môi quan hệ" → "mối quan hệ".

Với mỗi đoạn, trả lại đúng đoạn đó sau khi sửa các từ sai dấu theo ngữ cảnh. Quy tắc bắt buộc:
- Chỉ được thêm, bỏ hoặc đổi dấu trên chữ cái. Không đổi chữ cái, không thêm/bớt/đổi thứ tự \
từ, không đổi dấu câu, không đổi chữ hoa/thường, không sửa văn phong.
- Tên riêng (người, địa danh nước ngoài) và chỗ không chắc thì giữ nguyên.
- Đoạn không có lỗi thì trả lại y nguyên.
- Giữ nguyên các ký hiệu chú thích dạng [^1].
Trả về mọi đoạn đã nhận, đúng id."""

SCHEMA = {
    "type": "object",
    "properties": {
        "paragraphs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["paragraphs"],
    "additionalProperties": False,
}


@dataclass
class Change:
    paragraph: int
    before: str
    after: str


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    @property
    def cost(self) -> float:
        return (self.input_tokens * PRICE_IN + self.output_tokens * PRICE_OUT) / 1e6


@dataclass
class Result:
    paragraphs: list[str]
    changes: list[Change] = field(default_factory=list)
    rejected: list[tuple[int, str, str]] = field(default_factory=list)  # (đoạn, từ gốc, model đề xuất)
    usage: Usage = field(default_factory=Usage)


def _strip_marks(word: str) -> str:
    """Bỏ dấu nhưng giữ hoa/thường: "Đường" → "Duong"."""
    decomposed = unicodedata.normalize("NFD", word.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def diacritic_only(before: str, after: str) -> bool:
    """after chỉ khác before ở dấu (và d/đ), cùng hoa/thường từng chữ."""
    return _strip_marks(before) == _strip_marks(after) and base_form(before) == base_form(after)


def merge(index: int, original: str, proposed: str, result: Result) -> str:
    """Áp những từ model sửa hợp lệ vào original; trả về đoạn sau khi sửa."""
    proposed = unicodedata.normalize("NFC", proposed)
    old, new = TOKEN.findall(original), TOKEN.findall(proposed)
    if "".join(old) != original or len(old) != len(new):
        if proposed != original:
            log.debug("đoạn %d: model đổi cấu trúc, giữ nguyên", index)
            result.rejected.append((index, original, proposed))
        return original
    out = []
    for a, b in zip(old, new, strict=True):
        if a == b:
            out.append(a)
        elif a[:1].isalpha() and diacritic_only(a, b):
            out.append(b)
            result.changes.append(Change(index, a, b))
        else:
            if a[:1].isalpha():
                result.rejected.append((index, a, b))
            out.append(a)
    return "".join(out)


def _batches(paragraphs: Sequence[str], indices: Sequence[int]) -> list[list[int]]:
    batches: list[list[int]] = []
    size = 0
    for i in indices:
        if not batches or size + len(paragraphs[i]) > BATCH_CHARS:
            batches.append([])
            size = 0
        batches[-1].append(i)
        size += len(paragraphs[i])
    return batches


Ask = Callable[[list[dict]], tuple[dict[int, str], int, int]]


def claude_ask(client=None, model: str = MODEL) -> Ask:
    """Hàm gửi một lô {"id", "text"} cho Claude, trả về ({id: đoạn đã sửa}, token vào, token ra)."""
    if client is None:
        import anthropic

        client = anthropic.Anthropic()

    def ask(items: list[dict]) -> tuple[dict[int, str], int, int]:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps({"paragraphs": items}, ensure_ascii=False)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
        usage = response.usage
        if response.stop_reason != "end_turn":  # refusal / max_tokens: giữ nguyên lô này
            log.warning("Claude dừng vì %s, bỏ qua %d đoạn", response.stop_reason, len(items))
            return {}, usage.input_tokens, usage.output_tokens
        text = next(b.text for b in response.content if b.type == "text")
        fixed = {p["id"]: p["text"] for p in json.loads(text)["paragraphs"]}
        return fixed, usage.input_tokens, usage.output_tokens

    return ask


def fix_paragraphs(paragraphs: Sequence[str], ask: Ask, indices: Sequence[int] | None = None) -> Result:
    """Sửa dấu các đoạn paragraphs[i] với i trong indices (mặc định: tất cả)."""
    result = Result(list(paragraphs))
    indices = range(len(paragraphs)) if indices is None else indices
    for batch in _batches(paragraphs, indices):
        fixed, tokens_in, tokens_out = ask([{"id": i, "text": paragraphs[i]} for i in batch])
        result.usage.input_tokens += tokens_in
        result.usage.output_tokens += tokens_out
        result.usage.calls += 1
        for i in batch:
            if i in fixed:
                result.paragraphs[i] = merge(i, paragraphs[i], fixed[i], result)
    return result
