# Chuyển ảnh chụp sách thành PDF.
#   make                             cài môi trường (lần đầu) rồi xử lý mọi file trong resources/
#   make run IN=resources/sach.pdf   xử lý một file / thư mục cụ thể (OUT=thư mục ra)
#   make scan                        chỉ xuất bản ảnh đã làm sạch, không OCR
#   make debug                       lưu thêm ảnh đánh dấu vùng cắt vào output/debug/
#   make typeset MD=output/sach.md   dàn lại PDF từ file .md đã sửa (ghi đè output/sach.pdf)
#   make FORCE=1                     ghi đè cả file .md đã sửa tay (mặc định giữ, bản mới ra .ocr.md)
#   make books                       như make, rồi thêm PDF vào app Sách trên Mac
#   make icloud                      như make, rồi chép PDF vào iCloud Drive/snap2book/Sách đã xử lý
#                                    BOOKS=1 / ICLOUD=1 làm điều tương tự cho mọi lệnh,
#                                    vd. make typeset MD=output/sach.md ICLOUD=1
#   make test | lint | format        kiểm thử, kiểm tra / định dạng code
#   make clean                       xoá output/ (cả cache output/.cache/)   make distclean   xoá cả .venv/

IN ?= resources
OUT ?= output
# OCR (pyobjc) cần Python >= 3.10; mặc định lấy bản 3.12 của pyenv nếu có
PYTHON ?= $(firstword $(wildcard $(HOME)/.pyenv/versions/3.12*/bin/python) python3)
VENV := .venv
BIN := $(VENV)/bin
DELIVER := $(if $(BOOKS),--to-books) $(if $(ICLOUD),--to-icloud)
CLI := $(BIN)/snap2book -o "$(OUT)" $(if $(FORCE),--force) $(DELIVER)

.PHONY: all run books icloud scan debug typeset setup test lint format clean distclean

all: run

$(VENV)/.installed: pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -e ".[dev]"
	touch $@

setup: $(VENV)/.installed

run: setup
	$(CLI) "$(IN)"

books: setup
	$(CLI) "$(IN)" --to-books

icloud: setup
	$(CLI) "$(IN)" --to-icloud

scan: setup
	$(CLI) "$(IN)" --scan-only

debug: setup
	$(CLI) "$(IN)" --debug

typeset: setup
	@test -n "$(MD)" || { echo 'Cần chỉ file: make typeset MD=output/<tên>.md'; exit 1; }
	$(BIN)/snap2book typeset "$(MD)" $(DELIVER)

test: setup
	$(BIN)/pytest -q

lint: setup
	$(BIN)/ruff check src tests
	$(BIN)/ruff format --check src tests

format: setup
	$(BIN)/ruff check --fix src tests
	$(BIN)/ruff format src tests

clean:
	rm -rf "$(OUT)"

distclean: clean
	rm -rf $(VENV) src/*.egg-info .pytest_cache .ruff_cache
