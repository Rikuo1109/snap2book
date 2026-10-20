# snap2book

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
make typeset MD=output/sach.md         # dàn lại sach.pdf từ file .md đã sửa
```

Hoặc gọi trực tiếp sau khi cài (`make setup` hoặc `pip install -e .`):

```bash
snap2book resources/ -o output [--scan-only] [--debug] [--keep-duplicates] [-q]
snap2book typeset output/sach.md [-o sach.pdf] [-q]
```

Mỗi file PDF đầu vào là một cuốn; các ảnh rời `.jpg/.png/...` trong cùng thư mục, sắp theo tên,
gộp thành một cuốn.

Sau OCR, script đọc số trang in ở header/footer để cảnh báo trang bị thiếu, trang chụp 2 lần
hoặc ảnh sai thứ tự. Trang chụp 2 lần liền nhau chỉ giữ ảnh đọc được nhiều dòng hơn
(`--keep-duplicates` để giữ cả).

### Sửa lỗi OCR rồi dàn trang lại

1. Chụp sách, chạy `make` → có `output/<tên>.md` và `output/<tên>.pdf`.
2. Mở `output/<tên>.md`, đối chiếu với `<tên> - scan.pdf` và sửa lỗi OCR. Giữ đúng dạng:
   `## ` tiêu đề chương, `### ` tiêu đề phụ, các đoạn cách nhau bằng dòng trống, chú thích
   ghi `[^n]` trong bài và `[^n]: nội dung` ở cuối file (số thứ tự được đánh lại tự động).
3. `make typeset MD="output/<tên>.md"` → ghi đè `output/<tên>.pdf` bằng bản đã sửa.

Lưu ý: chạy lại `make` trên cùng cuốn sách sẽ ghi đè file `.md` đã sửa; nên sao chép ra chỗ khác.

**Mẹo chụp:** đưa trang cần chụp vào giữa khung hình. Khi ảnh có hai trang, script chọn trang
nằm gần giữa nhất.

## Cách hoạt động

```
sources ─► cleanup ─► scan_pdf                      (<tên> - scan.pdf)
              │
              └─► ocr ─► structure ─┬─► markdown    (<tên>.md) ─┐ sửa tay
                                    └─► typeset     (<tên>.pdf) ◄┘ snap2book typeset
```

| Module | Việc |
|---|---|
| `sources.py` | Đọc ảnh từ PDF/ảnh rời, gom đầu vào thành từng cuốn |
| `cleanup.py` | Làm phẳng ánh sáng, xoay thẳng, tìm trang chính, bỏ trang bên cạnh / ngón tay / khăn bàn, cắt sát vùng chữ |
| `scan_pdf.py` | Ghép ảnh đã làm sạch thành PDF ảnh cùng khổ |
| `ocr.py` | OCR tiếng Việt bằng Apple Vision, xử lý chữ hoa lớn đầu chương (drop cap) |
| `structure.py` | Bỏ header/footer (giữ lại số trang in), nhận tiêu đề chương, tách chú thích, nối đoạn qua các trang |
| `pagecheck.py` | Soát số trang in: trang thiếu, chụp lặp, sai thứ tự (có tính đến OCR đọc nhầm số) |
| `markdown.py` | Xuất Markdown (chú thích dạng `[^1]`) và đọc ngược lại để dàn trang bản đã sửa |
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
  dễ sai dấu. Nên đọc soát file `.md` rồi dàn lại bằng `snap2book typeset`.
- Số mũ chú thích đôi khi bị OCR đọc thành dấu nháy; script nhận dạng được trường hợp này,
  các dạng lỗi khác thì chưa. Tương tự, nháy đơn đầu đoạn ngay trước chữ hoa (`'Đương...`) được
  sửa thành ngoặc kép.
