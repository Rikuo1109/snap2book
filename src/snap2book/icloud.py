"""Chép PDF vào iCloud Drive để mở trên iPhone (app Tệp, hoặc Chia sẻ → Sách).

Không phụ thuộc vào đồng bộ của app Sách: iCloud Drive tự đồng bộ thư mục sang iPhone. Chép đè
theo tên file nên chạy lại chỉ thay bản cũ, không sinh bản trùng. Ghi ra tên tạm rồi đổi tên
một lần, để iCloud không đồng bộ một file đang ghi dở.
"""

import logging
import os
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

ICLOUD_DRIVE = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
ROOT = ICLOUD_DRIVE / "snap2book"
SCAN_DIR = ROOT / "Bản quét"  # quét từ iPhone vào đây (make icloud đọc từ đây)
DEFAULT_DIR = ROOT / "Sách đã xử lý"  # kết quả để đọc trên iPhone


def copy_to_icloud(pdf: Path, dest_dir: Path = DEFAULT_DIR) -> Path | None:
    """Chép pdf vào dest_dir (tạo nếu chưa có). Trả về đường dẫn đích, None nếu không chép được."""
    if dest_dir.is_relative_to(ICLOUD_DRIVE) and not ICLOUD_DRIVE.exists():
        log.warning("  iCloud: không thấy iCloud Drive trên máy này (%s), bỏ qua", ICLOUD_DRIVE)
        return None
    dest = dest_dir / pdf.name
    tmp = dest_dir / f".{pdf.name}.tmp"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf, tmp)
        os.replace(tmp, dest)
    except PermissionError:
        log.warning(
            "  iCloud: macOS không cho ghi vào %s. Cấp quyền iCloud Drive cho ứng dụng đang chạy lệnh "
            "(Cài đặt hệ thống → Quyền riêng tư & Bảo mật → Tệp và thư mục), hoặc chạy trong Terminal.",
            dest_dir,
        )
        return None
    except OSError as e:
        tmp.unlink(missing_ok=True)
        log.warning("  iCloud: không chép được %s (%s)", pdf.name, e)
        return None
    log.info("=> đã chép %s vào iCloud Drive: %s", pdf.name, dest_dir)
    return dest
