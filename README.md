# book-scanner

Chuyển ảnh chụp sách (PDF từ app scan của iPhone, hoặc ảnh rời) thành sách PDF gọn:
làm sạch từng trang, OCR tiếng Việt rồi dàn trang lại thành nội dung liền mạch.

Mỗi cuốn sách cho ra 3 file trong `output/`:

| File | Nội dung |
|---|---|
| `<tên>.pdf` | Sách dàn trang lại từ chữ OCR: khổ A5, tìm kiếm/copy được, chú thích ở chân trang |
| `<tên>.md` | Nội dung dạng text, để đọc soát và sửa lỗi OCR |
| `<tên> - scan.pdf` | Ảnh các trang đã làm sạch, để đối chiếu với bản gốc |

## Yêu cầu

- macOS: OCR dùng Apple Vision, dàn trang dùng font Times New Roman có sẵn của hệ thống.
  Trên hệ điều hành khác chỉ chạy được chế độ `--scan-only`.
- Python 3.10 trở lên.

## Cách dùng

```bash
make                                   # lần đầu tự tạo .venv; xử lý mọi file trong resources/
make run IN=duong/dan/sach.pdf         # một file hoặc thư mục cụ thể; OUT=thư mục ra
make scan                              # chỉ xuất bản ảnh đã làm sạch, không OCR
make debug                             # lưu thêm ảnh đánh dấu vùng cắt vào output/debug/
```

Hoặc gọi trực tiếp sau khi cài (`make setup` hoặc `pip install -e .`):

```bash
book-scanner resources/ -o output [--scan-only] [--debug] [-q]
```

Mỗi file PDF đầu vào là một cuốn; các ảnh rời `.jpg/.png/...` trong cùng thư mục, sắp theo tên,
gộp thành một cuốn.

**Mẹo chụp:** đưa trang cần chụp vào giữa khung hình. Khi ảnh có hai trang, script chọn trang
nằm gần giữa nhất.

## Cách hoạt động

```
sources ─► cleanup ─► scan_pdf                      (<tên> - scan.pdf)
              │
              └─► ocr ─► structure ─┬─► markdown    (<tên>.md)
                                    └─► typeset     (<tên>.pdf)
```

| Module | Việc |
|---|---|
| `sources.py` | Đọc ảnh từ PDF/ảnh rời, gom đầu vào thành từng cuốn |
| `cleanup.py` | Làm phẳng ánh sáng, xoay thẳng, tìm trang chính, bỏ trang bên cạnh / ngón tay / khăn bàn, cắt sát vùng chữ |
| `scan_pdf.py` | Ghép ảnh đã làm sạch thành PDF ảnh cùng khổ |
| `ocr.py` | OCR tiếng Việt bằng Apple Vision, xử lý chữ hoa lớn đầu chương (drop cap) |
| `structure.py` | Bỏ header/footer, nhận tiêu đề chương, tách chú thích, nối đoạn qua các trang |
| `markdown.py` | Xuất Markdown (chú thích dạng `[^1]`) |
| `typeset.py` | Dàn trang PDF: chú thích ở chân trang có số mũ, chống dòng mồ côi |
| `pipeline.py`, `cli.py` | Điều phối các bước, dòng lệnh |

## Phát triển

```bash
make test       # pytest
make lint       # ruff check + kiểm tra định dạng
make format     # ruff tự sửa và định dạng
```

## Hạn chế

- Trang chụp cong nhiều (gần gáy sách) chỉ được xoay thẳng, chưa làm phẳng, nên OCR ở vùng đó
  dễ sai dấu. Nên đọc soát file `.md`.
- Số mũ chú thích đôi khi bị OCR đọc thành dấu nháy; script nhận dạng được trường hợp này,
  các dạng lỗi khác thì chưa.
