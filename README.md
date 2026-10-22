# snap2book

Chuyển ảnh chụp sách (PDF từ app scan của iPhone, hoặc ảnh rời) thành sách PDF gọn:
làm sạch từng trang, OCR tiếng Việt rồi dàn trang lại thành nội dung liền mạch.

Mỗi cuốn sách cho ra các file trong `output/`:

| File | Nội dung |
|---|---|
| `<tên>.epub` | Sách điện tử để đọc trên điện thoại: chữ tự dàn theo màn hình, chỉnh cỡ chữ, mục lục theo chương, bấm số mũ để xem chú thích |
| `<tên>.md` | Nội dung dạng text, để đọc soát và sửa lỗi OCR (chạy lại không ghi đè bản đã sửa) |
| `<tên> - scan.pdf` | Ảnh các trang đã làm sạch, để đối chiếu khi soát lỗi (chỉ nằm trên máy, không lên iCloud) |
| `<tên>.pdf` | Chỉ khi có `--pdf` / `PDF=1`: sách dàn trang lại khổ A5, chú thích ở chân trang |

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
make typeset MD=output/sach.md         # dựng lại sach.epub từ file .md đã sửa
make icloud PDF=1                      # xuất thêm PDF chữ khổ A5
make FORCE=1                           # ghi đè cả file .md đã sửa tay
make icloud                            # xử lý bản quét trong iCloud Drive/snap2book/Bản quét → Sách đã xử lý
make books                             # như make, rồi thêm PDF vào app Sách trên Mac
```

Hoặc gọi trực tiếp sau khi cài (`make setup` hoặc `pip install -e .`):

```bash
snap2book resources/ -o output [-j N] [--no-cache] [--scan-only] [--pdf] [--no-dewarp] [--no-spellfix] [--debug] [-v] [--keep-duplicates] [--force] [--to-books] [--to-icloud [THƯ_MỤC]] [-q]
snap2book typeset output/sach.md [-o sach.epub] [--pdf] [--to-books] [--to-icloud [THƯ_MỤC]] [-q]
snap2book llmfix output/sach.md [--chapter N] [-o sach.llmfix.md] [-q]
```

Mỗi file PDF đầu vào là một cuốn; các ảnh rời `.jpg/.png/...` trong cùng thư mục, sắp theo tên,
gộp thành một cuốn; mỗi thư mục con cũng là một cuốn (gộp mọi PDF/ảnh trong đó theo tên).

Sau OCR, script đọc số trang in ở header/footer để cảnh báo trang bị thiếu, trang chụp 2 lần
hoặc ảnh sai thứ tự. Trang chụp 2 lần liền nhau chỉ giữ ảnh đọc được nhiều dòng hơn
(`--keep-duplicates` để giữ cả).

### Sách dài: xử lý song song và cache

Các trang được làm sạch và OCR song song, mỗi trang một tiến trình (`-j N`, mặc định bằng số
nhân CPU; `-j 1` chạy tuần tự). Apple Vision gọi từ nhiều luồng trong cùng một tiến trình không
nhanh hơn chạy tuần tự, nên dùng tiến trình chứ không dùng luồng. Bước sửa dấu cần từ vựng của
cả cuốn nên vẫn chạy sau khi mọi trang đã OCR xong.

Kết quả từng trang (ảnh đã làm sạch, các dòng OCR kèm toạ độ và phương án đọc) được lưu trong
`output/.cache/<tên>/`. Khoá cache gồm nội dung ảnh gốc, tuỳ chọn làm phẳng và phiên bản code
(mã nguồn phần làm sạch / OCR, bản macOS), nên chạy lại chỉ phải xử lý các trang mới thêm, ảnh
đã đổi, hoặc khi đổi tuỳ chọn / sửa code. Trang không dùng tới quá 30 ngày tự bị xoá khỏi cache;
`--no-cache` để bỏ qua cache, `make clean` xoá cả `output/` lẫn cache. `--debug` luôn làm sạch
lại (để vẽ ảnh đánh dấu) nhưng vẫn dùng OCR đã cache.

Thời gian trên sách mẫu (9 ảnh, máy 11 nhân đang bận việc khác, load ~10):

| | Thời gian |
|---|---|
| Trước (tuần tự, không cache) | 13–14 s |
| Lần đầu, `-j` mặc định | 8–9 s |
| Chạy lại, mọi trang có trong cache | 1.7 s |

Riêng OCR 26 ảnh: tuần tự 16 s, 2–8 luồng 15–17 s, 8 tiến trình 4 s. Sách càng dài thì lợi
càng rõ, vì chi phí khởi động tiến trình (nạp OpenCV, Vision) chỉ trả một lần.

### Sửa lỗi OCR rồi dàn trang lại

1. Chụp sách, chạy `make` → có `output/<tên>.md` và `output/<tên>.epub`.
2. Mở `output/<tên>.md`, đối chiếu với `<tên> - scan.pdf` và sửa lỗi OCR. Giữ đúng dạng:
   `## ` tiêu đề chương, `### ` tiêu đề phụ, các đoạn cách nhau bằng dòng trống, `> ` đầu đoạn
   trích (vd. lá thư trong truyện, EPUB in nghiêng và thụt lề), chú thích
   ghi `[^n]` trong bài và `[^n]: nội dung` ở cuối file (số thứ tự được đánh lại tự động).
   Ảnh / bảng trong sách (OCR không đọc được) thì thêm tay: `![chú thích](images/so-do.jpg)`
     (đường dẫn tính từ thư mục chứa file .md, ảnh .jpg/.png được nhúng vào EPUB) và bảng
     `| ô | ô |` mỗi hàng một dòng (thêm `| --- | --- |` sau hàng đầu nếu hàng đầu là tiêu đề).
3. `make typeset MD="output/<tên>.md"` → ghi đè `output/<tên>.epub` bằng bản đã sửa (`PDF=1` thêm PDF).

Chạy lại `make` trên cùng cuốn sách không làm mất phần đã sửa: mỗi lần ghi `<tên>.md`, script
lưu kèm mã băm vào file ẩn `output/.<tên>.md.sha256`. Lần chạy sau, nếu `<tên>.md` khác mã băm
đó (tức đã sửa tay), script giữ nguyên nó, ghi bản OCR mới ra `<tên>.ocr.md` để so sánh, in cảnh
báo và dựng sách từ bản đã sửa (`<tên> - scan.pdf` vẫn được làm lại). File `.md` không có
mã băm (xuất từ bản cũ) cũng được giữ lại cho chắc. Muốn ghi đè bằng bản OCR mới: thêm `--force`
(`make run IN=... FORCE=1`).

### Sửa dấu bằng Claude (tuỳ chọn)

Từ điển không bắt được từ có thật nhưng sai dấu ("trò thành", "Chăng bao lâu"). Bước `llmfix`
gửi các đoạn văn cho Claude Haiku 5.5 sửa theo ngữ cảnh. Code chỉ nhận thay đổi về dấu (cùng chữ
cái, cùng hoa/thường, giữ nguyên dấu câu và số từ); đề xuất khác thì bị bỏ qua và in ra.

1. `.venv/bin/pip install -e ".[llm]"`, chép `.env.example` thành `.env` rồi điền `ANTHROPIC_API_KEY`
   (`.env` không được commit).
2. `.venv/bin/snap2book llmfix "output/<tên>.md"` (thêm `--chapter 2` để thử một chương) → ghi
   `output/<tên>.llmfix.md`, in từng từ đã sửa và chi phí (cả cuốn ~200 đoạn khoảng $0.03).
3. Đọc lướt danh sách sửa, rồi `snap2book typeset "output/<tên>.llmfix.md" -o "output/<tên>.epub"`.

### Đọc trên iPhone

**Cách chắc chắn: iCloud Drive.** Trên iCloud Drive dùng thư mục `snap2book`:

```
snap2book/
├── Bản quét/                            ← quét từ iPhone vào đây
│   ├── Sách A.pdf                       (một lần quét = một cuốn)
│   └── Vụ án sát nhân không liên hoàn/  (cuốn quét nhiều lần: để chung một thư mục, tự gộp)
│       ├── 1.pdf
│       └── 2.pdf
└── Sách đã xử lý/                       ← kết quả, đọc trên iPhone
```

1. iPhone: app **Tệp** → iCloud Drive → snap2book → Bản quét (hoặc thư mục con của cuốn sách) →
   "…" → **Quét tài liệu**. Đổi tên file thành tên sách (hoặc `1`, `2`, … nếu để trong thư mục sách).
2. Mac, trong Terminal: `make icloud` (tự tạo `Bản quét` nếu chưa có). Trang đã xử lý lần trước được
   lấy từ cache, chỉ trang mới phải OCR.
3. iPhone: app **Tệp** → snap2book → **Sách đã xử lý** → mở file **`.epub`**, Chia sẻ → **Sách**.

Mỗi file PDF trong `Bản quét` là một cuốn; mỗi thư mục con là một cuốn, gồm mọi PDF và ảnh trong đó
theo thứ tự tên ("2" trước "10"). Nếu một file PDF trùng tên với thư mục con thì dùng thư mục con.
Trang chụp lặp hoặc thiếu được cảnh báo theo số trang in.

Với thư mục khác hoặc lệnh khác, dùng `--to-icloud` / `ICLOUD=1`, vd.
`make typeset MD=output/sach.md ICLOUD=1`. Chép đè theo tên file nên chạy lại không sinh bản trùng.
macOS chặn ứng dụng chưa được cấp quyền đọc/ghi iCloud Drive: chạy trong Terminal (lần đầu bấm Cho
phép), hoặc cấp quyền ở Cài đặt hệ thống → Quyền riêng tư & Bảo mật → Tệp và thư mục.

**App Sách trên Mac.** `--to-books` (hoặc `make books`, `BOOKS=1`) thêm `<tên>.epub` vào app Sách
trên Mac. Sách chỉ đồng bộ PDF sang iPhone khi bật iCloud Drive cho Sách ở cả hai máy (Mac: Cài đặt
hệ thống → [tên bạn] → iCloud → iCloud Drive → Sách; iPhone: Cài đặt → Ứng dụng → Sách → iCloud
Drive), và kể cả khi đã bật, việc đồng bộ có thể không chạy, nên ưu tiên `--to-icloud`. Sách không
nhận ra hai file là cùng một cuốn, nên script chỉ thêm khi nội dung PDF đổi so với lần thêm trước
(ghi nhớ trong `output/.books.json`); bản cũ trong Sách phải xoá tay.

**Mẹo chụp:** đưa trang cần chụp vào giữa khung hình. Khi ảnh có hai trang, script chọn trang
nằm gần giữa nhất.

## Cách hoạt động

```
sources ─► cleanup ─► dewarp ─► scan_pdf                                  (<tên> - scan.pdf)
                        │
                        └─► ocr ─► spellfix ─► structure ─┬─► markdown    (<tên>.md) ─┐ sửa tay
                                                          ├─► epub        (<tên>.epub) ◄┤ snap2book typeset
                                                          └─► typeset     (<tên>.pdf, --pdf) ◄┘
```

`cleanup`, `dewarp`, `ocr` chạy song song theo trang và được cache (`pages.py`, `cache.py`);
từ `spellfix` trở đi chạy trên cả cuốn.

| Module | Việc |
|---|---|
| `sources.py` | Đọc ảnh từ PDF/ảnh rời, gom đầu vào thành từng cuốn |
| `cleanup.py` | Làm phẳng ánh sáng, xoay thẳng, tìm trang chính, bỏ trang bên cạnh / ngón tay / khăn bàn, cắt sát vùng chữ |
| `dewarp.py` | Làm phẳng trang cong gần gáy sách: ước lượng độ võng từ các dòng chữ rồi kéo thẳng |
| `scan_pdf.py` | Ghép ảnh đã làm sạch thành PDF ảnh cùng khổ |
| `ocr.py` | OCR tiếng Việt bằng Apple Vision, xử lý chữ hoa lớn đầu chương (drop cap), gộp mảnh dòng bị tách |
| `structure.py` | Bỏ header/footer (giữ lại số trang in), nhận tiêu đề chương, tách chú thích, nối đoạn qua các trang |
| `pagecheck.py` | Soát số trang in: trang thiếu, chụp lặp, sai thứ tự (có tính đến OCR đọc nhầm số) |
| `spellfix.py` | Sửa lỗi dấu OCR: từ sai chính tả được thay bằng phương án đọc khác hoặc từ cùng chữ cái trong sách (từ điển tiếng Việt của macOS) |
| `llmfix.py` | Sửa dấu theo ngữ cảnh bằng Claude Haiku, chỉ nhận thay đổi về dấu |
| `markdown.py` | Xuất Markdown (chú thích dạng `[^1]`) và đọc ngược lại để dàn trang bản đã sửa |
| `epub.py` | Xuất EPUB 3: mỗi chương một file, mục lục, chú thích bật lên khi bấm số mũ |
| `typeset.py` | Dàn trang PDF: chú thích ở chân trang có số mũ, chống dòng mồ côi |
| `books.py` | Thêm PDF vào app Sách (Apple Books), bỏ qua nếu nội dung không đổi |
| `icloud.py` | Chép PDF vào iCloud Drive để mở trên iPhone |
| `pages.py` | Làm sạch + OCR từng trang song song nhiều tiến trình, giữ đúng thứ tự trang |
| `cache.py` | Cache ảnh đã làm sạch và dòng OCR của từng trang trong `output/.cache/` |
| `pipeline.py`, `cli.py` | Điều phối các bước, dòng lệnh |

## Phát triển

```bash
make test       # pytest
make lint       # ruff check + kiểm tra định dạng
make format     # ruff tự sửa và định dạng
```

## Hạn chế

- Trang cong được kéo thẳng theo chiều dọc, nhưng chữ bị co ngang gần gáy sách thì chưa sửa;
  OCR vẫn còn sai dấu lẻ tẻ, nên đọc soát file `.md` rồi dàn lại bằng `snap2book typeset`.
- Bước sửa dấu chỉ sửa từ không tồn tại ("dịnh" → "định"); từ có thật nhưng sai ngữ cảnh
  ("chẳng" đọc thành "chăng") thì chỉ sửa khi cụm đúng xuất hiện nhiều lần trong sách; còn lại dùng
  `snap2book llmfix`. `-v` in ra từng từ đã sửa. Lỗi mất / sai chữ cái (vd. chữ bị cắt ở mép
  trang) thì cả hai bước đều không sửa.
- Số mũ chú thích đôi khi bị OCR đọc thành dấu nháy; script nhận dạng được trường hợp này,
  các dạng lỗi khác thì chưa. Tương tự, nháy đơn đầu đoạn ngay trước chữ hoa (`'Đương...`) được
  sửa thành ngoặc kép.
