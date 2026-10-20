# Chuyển ảnh chụp sách thành PDF.
#   make                             cài môi trường (lần đầu) rồi xử lý mọi file trong resources/
#   make run IN=resources/sach.pdf   xử lý một file / thư mục cụ thể (OUT=thư mục ra)
#   make scan                        chỉ xuất bản ảnh đã làm sạch, không OCR
#   make debug                       lưu thêm ảnh đánh dấu vùng cắt vào output/debug/
#   make typeset MD=output/sach.md   dàn lại PDF từ file .md đã sửa (ghi đè output/sach.pdf)
#   make test | lint | format        kiểm thử, kiểm tra / định dạng code
#   make clean                       xoá output/ (cả cache output/.cache/)   make distclean   xoá cả .venv/

IN ?= resources
OUT ?= output
# OCR (pyobjc) cần Python >= 3.10; mặc định lấy bản 3.12 của pyenv nếu có
PYTHON ?= $(firstword $(wildcard $(HOME)/.pyenv/versions/3.12*/bin/python) python3)
VENV := .venv
BIN := $(VENV)/bin
CLI := $(BIN)/snap2book -o "$(OUT)"

.PHONY: all run scan debug typeset setup test lint format clean distclean

all: run

$(VENV)/.installed: pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -e ".[dev]"
	touch $@

setup: $(VENV)/.installed

run: setup
	$(CLI) "$(IN)"

scan: setup
	$(CLI) "$(IN)" --scan-only

debug: setup
	$(CLI) "$(IN)" --debug

typeset: setup
	@test -n "$(MD)" || { echo 'Cần chỉ file: make typeset MD=output/<tên>.md'; exit 1; }
	$(BIN)/snap2book typeset "$(MD)"

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
