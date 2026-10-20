# Chuyển ảnh chụp sách thành PDF.
#   make            cài môi trường (lần đầu) rồi xử lý mọi file trong resources/
#   make run IN=resources/sach.pdf   xử lý một file / thư mục cụ thể
#   make scan       chỉ xuất bản ảnh đã làm sạch, không OCR
#   make debug      lưu thêm ảnh đánh dấu vùng cắt vào output/debug/
#   make clean      xoá output/        make distclean   xoá cả .venv/

IN ?= resources
# OCR (pyobjc) cần Python >= 3.10; mặc định lấy bản 3.12 của pyenv nếu có
PYTHON ?= $(firstword $(wildcard $(HOME)/.pyenv/versions/3.12*/bin/python) python3)
VENV := .venv
PY := $(VENV)/bin/python -W ignore

.PHONY: all run scan debug setup clean distclean

all: run

$(VENV)/.installed: requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q --upgrade pip
	$(VENV)/bin/pip install -q -r requirements.txt
	touch $@

setup: $(VENV)/.installed

run: setup
	$(PY) scan2pdf.py "$(IN)"

scan: setup
	$(PY) scan2pdf.py "$(IN)" --scan-only

debug: setup
	$(PY) scan2pdf.py "$(IN)" --debug

clean:
	rm -rf output

distclean: clean
	rm -rf $(VENV)
