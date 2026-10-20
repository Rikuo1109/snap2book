"""Soát ảnh chụp theo số trang in (đọc từ header/footer, xem structure.page_number):
trang bị thiếu, trang chụp 2 lần, ảnh sai thứ tự.

Số trang OCR có thể đọc nhầm hoặc không đọc được, nên dựa vào các ảnh bên cạnh trước khi kết luận:
  - ảnh nằm giữa hai ảnh cách nhau đúng 2 trang (12, ?, 14) chắc chắn là trang ở giữa (13),
  - số lệch hẳn mọi ảnh bên cạnh (..., 12, 13, 81 ở ảnh cuối) coi như đọc nhầm, bỏ qua.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise

MAX_STEP = 2  # số lệch khỏi ảnh bên cạnh quá chừng này trang (so với kỳ vọng +1) = đọc nhầm


@dataclass
class PageCheck:
    numbers: list[int | None]  # số trang của từng ảnh sau khi sửa đọc nhầm (None: không rõ)
    warnings: list[str] = field(default_factory=list)
    duplicates: list[int] = field(default_factory=list)  # chỉ số ảnh (từ 0) chụp lặp, nên bỏ


def _ranges(nums: Sequence[int]) -> str:
    """[47, 48, 49, 52] -> "47–49, 52"."""
    parts: list[str] = []
    start = prev = nums[0]
    for n in [*nums[1:], None]:
        if n is not None and n == prev + 1:
            prev = n
            continue
        parts.append(str(start) if start == prev else f"{start}–{prev}")
        if n is not None:
            start = prev = n
    return ", ".join(parts)


def _fix_misreads(read: Sequence[int | None]) -> list[int | None]:
    nums = list(read)
    # ảnh kẹp giữa hai ảnh cách nhau đúng 2 trang (trừ khi trùng số một bên: có thể là chụp lặp)
    for i in range(1, len(read) - 1):
        a, b = read[i - 1], read[i + 1]
        if a is not None and b is not None and b - a == 2 and read[i] not in (a, b):
            nums[i] = a + 1
    # số không khớp ảnh bên cạnh nào
    fixed = list(nums)
    for i, n in enumerate(nums):
        if n is None:
            continue
        near = [(j, nums[j]) for j in (i - 1, i + 1) if 0 <= j < len(nums) and nums[j] is not None]
        if near and all(abs((n - m) - (i - j)) > MAX_STEP for j, m in near):
            fixed[i] = None
    return fixed


def check_pages(read: Sequence[int | None], line_counts: Sequence[int]) -> PageCheck:
    """read[i]: số trang đọc được ở ảnh i; line_counts[i]: số dòng OCR của ảnh i
    (trang chụp lặp thì giữ ảnh nhiều dòng hơn)."""
    nums = _fix_misreads(read)
    check = PageCheck(nums)
    warn = check.warnings.append

    for i, (r, n) in enumerate(zip(read, nums, strict=True)):
        if r is not None and n is None:
            warn(f"ảnh {i + 1}: số trang đọc được ({r}) không khớp các ảnh bên cạnh, bỏ qua")

    known = [i for i, n in enumerate(nums) if n is not None]
    seen = {nums[i] for i in known}

    by_number: dict[int, list[int]] = {}
    for i in known:
        by_number.setdefault(nums[i], []).append(i)  # type: ignore[arg-type]
    groups = {n: photos for n, photos in sorted(by_number.items()) if len(photos) > 1}

    def best(photos: list[int]) -> int:
        return max(photos, key=lambda i: (line_counts[i], -i))  # nhiều dòng hơn; hoà thì ảnh trước

    adjacent = {n for n, photos in groups.items() if photos[-1] - photos[0] == len(photos) - 1}
    # chụp lặp không liền nhau, thường gặp khi quét tiếp: chụp lại vài trang cuối của lần trước
    # (..., 12, 13 | 12, 13, 14, ...). Chỉ tự bỏ khi bỏ xong thì các ảnh còn lại đúng thứ tự trang;
    # còn lại là ảnh bị xáo trộn thật, để người dùng tự xếp.
    apart = [n for n in groups if n not in adjacent]
    drop_apart = [i for n in apart for i in groups[n] if i != best(groups[n])]
    drop_adjacent = [i for n in adjacent for i in groups[n] if i != best(groups[n])]
    kept = [i for i in known if i not in drop_apart and i not in drop_adjacent]
    apart_ok = all(nums[p] < nums[i] for p, i in pairwise(kept))  # type: ignore[operator]

    for n, photos in groups.items():
        names = ", ".join(str(i + 1) for i in photos[:-1]) + f" và {photos[-1] + 1}"
        msg = f"trang {n} chụp {len(photos)} lần: ảnh {names}"
        if n in adjacent or apart_ok:
            keep = best(photos)
            check.duplicates += [i for i in photos if i != keep]
            msg += f" (giữ ảnh {keep + 1})"
        else:
            msg += " (không liền nhau, không tự bỏ)"
        warn(msg)
    check.duplicates.sort()
    known = [i for i in known if i not in check.duplicates]  # thứ tự / chỗ thiếu: xét ảnh được giữ

    for p, i in pairwise(known):
        a, b = nums[p], nums[i]
        assert a is not None and b is not None
        if b < a:
            warn(f"ảnh {i + 1} (trang {b}) nằm sau ảnh {p + 1} (trang {a}): sai thứ tự")
            continue
        missing = [k for k in range(a + 1, b) if k not in seen]
        unknown = i - p - 1  # số ảnh ở giữa không rõ số trang
        if unknown == 0 and missing:
            warn(f"thiếu trang {_ranges(missing)}")
        elif len(missing) > unknown:
            photos = str(p + 2) if unknown == 1 else f"{p + 2}–{i}"
            warn(
                f"thiếu khoảng {len(missing) - unknown} trang trong số trang {_ranges(missing)}"
                f" (ảnh {photos} không rõ số trang)"
            )
    return check
