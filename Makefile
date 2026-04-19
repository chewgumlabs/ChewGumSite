# shanecurry.com — build / serve / clean
#
# Source of truth lives in content/. Run `make build` to regenerate site/.
# Visit http://localhost:8765/ via `make serve` (or use the .claude/launch.json
# preview server, which serves the same directory).

# Need Python 3.11+ for tomllib. Homebrew Python is fine; system /usr/bin
# Python on macOS is 3.9 and lacks it.
PYTHON ?= /opt/homebrew/bin/python3
PORT   ?= 8765

.PHONY: build serve clean help

help:
	@echo "make build    regenerate site/ from content/"
	@echo "make serve    serve site/ on http://localhost:$(PORT)"
	@echo "make clean    remove generated site/*.html (preserves assets/, content/)"

build:
	@$(PYTHON) tools/build.py

serve:
	@cd site && $(PYTHON) -m http.server $(PORT)

# Only delete files we generate. Hand-authored content lives in content/.
# Static assets (fonts, css, js, experiment bundles) live in site/assets/
# and are NOT touched.
clean:
	@find site -name 'index.html' -delete
	@echo "removed generated site/**/index.html (assets and content untouched)"
