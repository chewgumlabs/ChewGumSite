# shanecurry.com — build / serve / clean
#
# Source of truth lives in content/. Run `make build` to regenerate site/.
# Visit http://localhost:8765/ via `make serve` (or use the .claude/launch.json
# preview server, which serves the same directory).

# Need Python 3.11+ for tomllib. Homebrew Python is fine; system /usr/bin
# Python on macOS is 3.9 and lacks it.
PYTHON ?= /opt/homebrew/bin/python3
PORT   ?= 8765

.PHONY: build serve watch clean truth-steward-smoke truth-steward-emit truth-steward-validate truth-steward-audit truth-steward-window-audit truth-steward-taxonomy truth-steward-registry truth-steward-review truth-steward-propose truth-steward-trace truth-steward-trace-review truth-steward-memory-index truth-steward-editor-pass truth-steward-skills digging-index help

help:
	@echo "make build    regenerate site/ from content/"
	@echo "make serve    serve site/ on http://localhost:$(PORT)"
	@echo "make watch    serve + rebuild on every content/ or tools/ change"
	@echo "make clean    remove generated site/*.html (preserves assets/, content/)"
	@echo "make truth-steward-smoke"
	@echo "              run the truth-steward fixture matrix"
	@echo "make truth-steward-emit PACKET=tools/truth-steward/fixtures/triangle-engines.packet.json"
	@echo "              emit and validate a private truth-steward draft"
	@echo "make truth-steward-validate DRAFT=_Internal/truth-steward-drafts/YYYY-MM-DD-slug"
	@echo "              validate an existing private truth-steward draft"
	@echo "make truth-steward-audit"
	@echo "              audit public content, llms.txt, and sitemap.xml"
	@echo "make truth-steward-window-audit"
	@echo "              audit public page window titles against tracked taxonomy policy"
	@echo "make truth-steward-taxonomy"
	@echo "              audit site pages against tracked category doctrine"
	@echo "make truth-steward-registry"
	@echo "              revalidate and index private truth-steward drafts into _Internal/truth-steward-registry/"
	@echo "make truth-steward-review"
	@echo "              render a private human review memo from the truth-steward registry"
	@echo "make truth-steward-propose SOURCE=content/blog/phosphor/post.frag.html"
	@echo "              ask local Qwen to propose private truth-steward packets from a source file"
	@echo "              pass PROPOSE_ARGS='--repair-blocked' to run one blocked-candidate repair pass"
	@echo "make truth-steward-trace PROPOSAL=_Internal/truth-steward-proposals/YYYY-MM-DD-slug"
	@echo "              export a private Chew/Gum workflow trace and training-memory JSONL"
	@echo "make truth-steward-trace-review TRACE=_Internal/truth-steward-traces/YYYY-MM-DD-slug"
	@echo "              create or apply human labels for a private Chew/Gum workflow trace"
	@echo "make truth-steward-memory-index"
	@echo "              sweep reviewed traces into a private truth-steward memory index"
	@echo "make truth-steward-editor-pass DRAFT=_Internal/truth-steward-drafts/YYYY-MM-DD-slug"
	@echo "              run a private llama.cpp/Qwen editor pass over a draft fragment"
	@echo "make truth-steward-skills"
	@echo "              print tracked Chew/Gum site-building capability notes"
	@echo "make digging-index"
	@echo "              privately index old pile modules/assets into _Internal/digging/"

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

truth-steward-smoke:
	@$(PYTHON) tools/truth-steward/run_truth_steward_smoke.py

truth-steward-emit:
	@[ -n "$(PACKET)" ] || { echo "usage: make truth-steward-emit PACKET=tools/truth-steward/fixtures/triangle-engines.packet.json"; exit 2; }
	@$(PYTHON) tools/truth-steward/emit_truth_steward_draft.py "$(PACKET)"

truth-steward-validate:
	@[ -n "$(DRAFT)" ] || { echo "usage: make truth-steward-validate DRAFT=_Internal/truth-steward-drafts/YYYY-MM-DD-slug"; exit 2; }
	@$(PYTHON) tools/truth-steward/validate_truth_steward_draft.py "$(DRAFT)"

truth-steward-audit:
	@$(PYTHON) tools/truth-steward/audit_public_surface.py

truth-steward-window-audit:
	@$(PYTHON) tools/truth-steward/audit_window_taxonomy.py

truth-steward-taxonomy:
	@$(PYTHON) tools/truth-steward/audit_site_taxonomy.py

truth-steward-registry:
	@$(PYTHON) tools/truth-steward/index_truth_steward_registry.py

truth-steward-review: truth-steward-registry
	@$(PYTHON) tools/truth-steward/render_truth_steward_review.py

truth-steward-propose:
	@[ -n "$(SOURCE)" ] || { echo "usage: make truth-steward-propose SOURCE=content/blog/phosphor/post.frag.html"; exit 2; }
	@$(PYTHON) tools/truth-steward/run_truth_steward_proposer.py "$(SOURCE)" $(PROPOSE_ARGS)

truth-steward-trace:
	@[ -n "$(PROPOSAL)" ] || { echo "usage: make truth-steward-trace PROPOSAL=_Internal/truth-steward-proposals/YYYY-MM-DD-slug"; exit 2; }
	@$(PYTHON) tools/truth-steward/export_truth_steward_trace.py "$(PROPOSAL)"

truth-steward-trace-review:
	@[ -n "$(TRACE)" ] || { echo "usage: make truth-steward-trace-review TRACE=_Internal/truth-steward-traces/YYYY-MM-DD-slug [LABELS=_Internal/path/to/labels.json]"; exit 2; }
	@$(PYTHON) tools/truth-steward/review_truth_steward_trace.py "$(TRACE)" $(if $(LABELS),--labels "$(LABELS)")

truth-steward-memory-index:
	@$(PYTHON) tools/truth-steward/index_truth_steward_memory.py

truth-steward-editor-pass:
	@[ -n "$(DRAFT)" ] || { echo "usage: make truth-steward-editor-pass DRAFT=_Internal/truth-steward-drafts/YYYY-MM-DD-slug"; exit 2; }
	@$(PYTHON) tools/truth-steward/run_truth_steward_editor_pass.py "$(DRAFT)"

truth-steward-skills:
	@sed -n '1,260p' tools/truth-steward/site_builder_skills.md

digging-index:
	@$(PYTHON) tools/digging/index_pile_contracts.py
