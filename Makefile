PYTHON ?= python

.PHONY: help run generate dry-run test bench benchmark clean

OUT ?= wordlist.txt
GEN_WORKERS ?= 4
GEN_ARGS ?=
WORKERS ?= 1,4
BENCH_ARGS ?=
FORCE ?= 0

ifeq ($(FORCE),1)
REPLACE_ARG = --force
endif

help:
	@echo "Available targets:"
	@echo "  make run        Run the Wordlist Studio desktop app"
	@echo "  make generate   Generate a wordlist from the terminal"
	@echo "  make dry-run    Show generation estimates without writing"
	@echo "  make test       Run the unit tests"
	@echo "  make bench      Compare benchmark worker counts in a table"
	@echo "  make clean      Remove Python cache files"
	@echo ""
	@echo "Generation variables: OUT=wordlist.txt GEN_WORKERS=4 GEN_ARGS='--min-length 4 ...'"
	@echo "Add FORCE=1 to replace an existing output file."
	@echo "Benchmark variables: WORKERS=1,4 BENCH_ARGS='--length 7 --compression plain'"

run:
	$(PYTHON) -m wordlist_studio

generate:
	$(PYTHON) -m wordlist_studio generate --output "$(OUT)" --workers $(GEN_WORKERS) $(GEN_ARGS) $(REPLACE_ARG)

dry-run:
	$(PYTHON) -m wordlist_studio generate --output "$(OUT)" --workers $(GEN_WORKERS) --dry-run $(GEN_ARGS)

test:
	$(PYTHON) -m unittest discover -s tests -v

bench: benchmark

benchmark:
	$(PYTHON) -m wordlist_studio benchmark --workers "$(WORKERS)" $(BENCH_ARGS)

clean:
	rmdir /s /q __pycache__ 2>nul || true
	for /d %d in (".") do @if exist "%d\__pycache__" rmdir /s /q "%d\__pycache__" 2>nul
	for /r %d in (.) do @if exist "%d\__pycache__" rmdir /s /q "%d\__pycache__" 2>nul
