# shanecurry.com — build / serve / clean
#
# Source of truth lives in content/. Run `make build` to regenerate site/.
# Visit http://localhost:8765/ via `make serve` (or use the .claude/launch.json
# preview server, which serves the same directory).

# Need Python 3.11+ for tomllib. Homebrew Python is fine; system /usr/bin
# Python on macOS is 3.9 and lacks it.
PYTHON ?= /opt/homebrew/bin/python3
PORT   ?= 8765

.PHONY: build serve watch clean authority-smoke authority-emit authority-validate authority-audit authority-window-audit authority-taxonomy authority-registry authority-review authority-propose authority-trace authority-trace-review authority-memory-index authority-editor-pass authority-skills help

help:
	@echo "make build    regenerate site/ from content/"
	@echo "make serve    serve site/ on http://localhost:$(PORT)"
	@echo "make watch    serve + rebuild on every content/ or tools/ change"
	@echo "make clean    remove generated site/*.html (preserves assets/, content/)"
	@echo "make authority-smoke"
	@echo "              run the authority fixture matrix"
	@echo "make authority-emit PACKET=tools/authority/fixtures/triangle-engines.packet.json"
	@echo "              emit and validate a private authority draft"
	@echo "make authority-validate DRAFT=_Internal/authority-drafts/YYYY-MM-DD-slug"
	@echo "              validate an existing private authority draft"
	@echo "make authority-audit"
	@echo "              audit public content, llms.txt, and sitemap.xml"
	@echo "make authority-window-audit"
	@echo "              audit public page window titles against tracked taxonomy policy"
	@echo "make authority-taxonomy"
	@echo "              audit site pages against tracked category doctrine"
	@echo "make authority-registry"
	@echo "              revalidate and index private authority drafts into _Internal/authority-registry/"
	@echo "make authority-review"
	@echo "              render a private human review memo from the authority registry"
	@echo "make authority-propose SOURCE=content/blog/phosphor/post.frag.html"
	@echo "              ask local Qwen to propose private authority packets from a source file"
	@echo "              pass PROPOSE_ARGS='--repair-blocked' to run one blocked-candidate repair pass"
	@echo "make authority-trace PROPOSAL=_Internal/authority-proposals/YYYY-MM-DD-slug"
	@echo "              export a private Chew/Gum workflow trace and training-memory JSONL"
	@echo "make authority-trace-review TRACE=_Internal/authority-traces/YYYY-MM-DD-slug"
	@echo "              create or apply human labels for a private Chew/Gum workflow trace"
	@echo "make authority-memory-index"
	@echo "              sweep reviewed traces into a private authority memory index"
	@echo "make authority-editor-pass DRAFT=_Internal/authority-drafts/YYYY-MM-DD-slug"
	@echo "              run a private llama.cpp/Qwen editor pass over a draft fragment"
	@echo "make authority-skills"
	@echo "              print tracked Chew/Gum site-building capability notes"

build:
	@$(PYTHON) tools/build.py

serve:
	@cd site && $(PYTHON) -m http.server $(PORT)

# Author-mode: dev server + fswatch trigger on content/ or tools/ change.
# Requires `brew install fswatch`. Refresh the browser manually after a
# save; no WebSocket live-reload (keeps the stack at "two processes").
watch:
	@command -v fswatch >/dev/null || { echo "install fswatch: brew install fswatch"; exit 1; }
	@$(MAKE) build
	@(cd site && $(PYTHON) -m http.server $(PORT)) & \
	 SERVER_PID=$$!; \
	 trap "kill $$SERVER_PID 2>/dev/null" EXIT; \
	 echo "serving http://localhost:$(PORT)/ — watching content/ and tools/"; \
	 fswatch -o content tools | xargs -n1 -I{} $(MAKE) build

# Only delete files we generate. Hand-authored content lives in content/.
# Static assets (fonts, css, js, experiment bundles) live in site/assets/
# and are NOT touched.
clean:
	@find site -name 'index.html' -delete
	@echo "removed generated site/**/index.html (assets and content untouched)"

authority-smoke:
	@$(PYTHON) tools/authority/run_authority_smoke.py

authority-emit:
	@[ -n "$(PACKET)" ] || { echo "usage: make authority-emit PACKET=tools/authority/fixtures/triangle-engines.packet.json"; exit 2; }
	@$(PYTHON) tools/authority/emit_authority_draft.py "$(PACKET)"

authority-validate:
	@[ -n "$(DRAFT)" ] || { echo "usage: make authority-validate DRAFT=_Internal/authority-drafts/YYYY-MM-DD-slug"; exit 2; }
	@$(PYTHON) tools/authority/validate_authority_draft.py "$(DRAFT)"

authority-audit:
	@$(PYTHON) tools/authority/audit_public_surface.py

authority-window-audit:
	@$(PYTHON) tools/authority/audit_window_taxonomy.py

authority-taxonomy:
	@$(PYTHON) tools/authority/audit_site_taxonomy.py

authority-registry:
	@$(PYTHON) tools/authority/index_authority_registry.py

authority-review: authority-registry
	@$(PYTHON) tools/authority/render_authority_review.py

authority-propose:
	@[ -n "$(SOURCE)" ] || { echo "usage: make authority-propose SOURCE=content/blog/phosphor/post.frag.html"; exit 2; }
	@$(PYTHON) tools/authority/run_authority_proposer.py "$(SOURCE)" $(PROPOSE_ARGS)

authority-trace:
	@[ -n "$(PROPOSAL)" ] || { echo "usage: make authority-trace PROPOSAL=_Internal/authority-proposals/YYYY-MM-DD-slug"; exit 2; }
	@$(PYTHON) tools/authority/export_authority_trace.py "$(PROPOSAL)"

authority-trace-review:
	@[ -n "$(TRACE)" ] || { echo "usage: make authority-trace-review TRACE=_Internal/authority-traces/YYYY-MM-DD-slug [LABELS=_Internal/path/to/labels.json]"; exit 2; }
	@$(PYTHON) tools/authority/review_authority_trace.py "$(TRACE)" $(if $(LABELS),--labels "$(LABELS)")

authority-memory-index:
	@$(PYTHON) tools/authority/index_authority_memory.py

authority-editor-pass:
	@[ -n "$(DRAFT)" ] || { echo "usage: make authority-editor-pass DRAFT=_Internal/authority-drafts/YYYY-MM-DD-slug"; exit 2; }
	@$(PYTHON) tools/authority/run_authority_editor_pass.py "$(DRAFT)"

authority-skills:
	@sed -n '1,260p' tools/authority/site_builder_skills.md
