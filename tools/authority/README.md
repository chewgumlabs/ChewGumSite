# tools/authority — Online Presence Authority Draft Adapter

A small Python adapter + validator that turns a SwarmLab-shaped authority
packet into a private, scaffolded draft under
`_00_Online_Presence/_Internal/authority-drafts/`. **Promotion to the
public site is always manual.**

## Why this exists

The site (`_00_Online_Presence/`) and the real-work lab (`_swarmlab/`)
stay separate. SwarmLab generates and validates internal evidence; this
adapter consumes packet shapes inspired by SwarmLab's
`authority-promotion-packet.template.md`, emits private site drafts, and
runs public-safety checks. The adapter never edits `_swarmlab/`,
`content/`, `site/sitemap.xml`, or `site/llms.txt`.

## Files

```
tools/authority/
  README.md                       this file
  emit_authority_draft.py         packet -> private draft scaffold
  validate_authority_draft.py     public-safety gate on a draft directory
  run_authority_smoke.py          deterministic fixture matrix runner
  audit_public_surface.py         read-only audit of public site surfaces
  audit_window_taxonomy.py        read-only audit of window-title taxonomy drift
  audit_site_taxonomy.py          read-only audit of page categories and migration candidates
  index_authority_registry.py     index private drafts into a review queue
  render_authority_review.py      render private human review memo
  run_authority_proposer.py       private Qwen packet proposer
  qwen_authority_bible.md         prompt doctrine for useful Qwen proposals
  export_authority_trace.py       proposal run -> private Chew/Gum workflow trace
  review_authority_trace.py       human label gate for trace training records
  index_authority_memory.py       aggregate reviewed traces into memory corpus
  run_authority_editor_pass.py    private llama.cpp/Qwen prose editor pass
  site_builder_skills.md          tracked Chew/Gum site-building capability notes
  schemas/
    authority-draft-registry.v0.json
    authority-workflow-trace.v0.json
    authority-trace-labels.v0.json
    authority-memory-index.v0.json
    pass-evidence-policy.v0.json
    window-taxonomy.v0.json
    site-taxonomy.v0.json
  policies/
    pass-evidence-policy.v0.json       tracked Truth-state for pass evidence boundaries
    window-taxonomy.v0.json            tracked public-site window title taxonomy
    site-taxonomy.v0.json              tracked public-site category doctrine
  fixtures/
    triangle-engines.packet.json
                                          known-good existing-page enrichment fixture
    dead-beat-enrichment.packet.json
                                          known-good note enrichment fixture
    bad-private-path.packet.json
                                          must fail: private filesystem path leak
    bad-public-draft-residue.packet.json
                                          must fail: prototype-draft self-label
    bad-private-url.packet.json
                                          must fail: non-public URL in source_trail
    bad-private-url-in-related-surfaces.packet.json
                                          must fail: non-public URL in related_public_surfaces (post.jsonld mentions)
    bad-null-source-trail.packet.json
                                          must fail: source_trail is null
```

Drafts emit under `_00_Online_Presence/_Internal/authority-drafts/<YYYY-MM-DD>-<slug>/`.
That directory is gitignored; private working artifacts must not be
committed.

## Requirements

- Python 3.11+ (uses `tomllib`). The Makefile uses
  `/opt/homebrew/bin/python3`; the Python authority scripts hard-fail
  with a clear message if invoked under an older Python (e.g., macOS
  system `/usr/bin/python3` 3.9). Use the same Python that runs
  `make build`.
- No third-party dependencies.

## Usage

### Make targets

All authority targets use the Makefile `PYTHON` variable, which defaults
to `/opt/homebrew/bin/python3`.

```sh
make authority-smoke
```

Runs the full fixture matrix:

- the triangle existing-page enrichment fixture must pass
- the Dead Beat existing-page enrichment fixture must pass
- all bad fixtures must block
- the triangle fixture emitted as `--kind hold` must leave zero public
  candidate files
- a generated `recommended_output = "note"` scaffold must not contain a
  Live Toy placeholder
- smoke drafts are written to `_Internal/authority-smoke-drafts/`, not
  the operational `_Internal/authority-drafts/` root
- stale passing validation must be re-run before registry readiness
- fixture drafts must be excluded from the default registry view
- the Dead Beat enrichment must emit `enrichment.frag.html` and
  `jsonld.enrichment.json`, not replacement `post.*` files, and must be
  `ready_for_review` in the include-test registry view
- proposer self-tests must parse model JSON, strip model-supplied
  authority fields, and preserve human-promotion gating
- proposer draft-checks must use per-packet slugs so multiple candidates
  for the same existing page do not overwrite each other's private check
  artifacts
- proposer safety scans must block controls-only toy proposals that duplicate
  an existing interactive source page
- trace-exporter self-tests must capture Chew/Gum loop events and
  training-memory JSONL without calling a model
- trace-review self-tests must prevent unlabeled records from becoming
  trainable, accept complete human labels, and reject incomplete trainable
  labels
- memory-index self-tests must aggregate only reviewed trainable records
  while reporting traces that still need labels
- editor-pass self-tests must reject HTML structure changes such as
  edited section attributes or removed `<code>` markup
- window-taxonomy self-tests must preserve page-role, alias, and
  expressive-title behavior
- `_Internal/` must not be tracked by git

```sh
make authority-emit PACKET=tools/authority/fixtures/triangle-engines.packet.json
```

Emits and validates a private authority draft from a packet. The target
only writes under `_Internal/authority-drafts/`.

```sh
make authority-validate DRAFT=_Internal/authority-drafts/YYYY-MM-DD-slug
```

Validates an existing private authority draft directory.

```sh
make authority-audit
```

Runs a read-only audit of `content/`, `site/llms.txt`, and
`site/sitemap.xml`, then writes private reports to
`_Internal/authority-audits/<YYYY-MM-DD>/audit.md` and
`_Internal/authority-audits/<YYYY-MM-DD>/audit.json`. The audit reports
blocking findings and warnings but does not edit public files.

```sh
make authority-window-audit
```

Runs a read-only audit of `content/**/*.frag.html` window titles against
`tools/authority/policies/window-taxonomy.v0.json`, then writes private
reports to:

- `_Internal/authority-audits/<YYYY-MM-DD>/window-audit.md`
- `_Internal/authority-audits/<YYYY-MM-DD>/window-audit.json`

This audit is advisory. It reports deprecated labels, unknown labels, and
missing expected windows for page roles. It does not edit public files and
does not block builds.

```sh
make authority-taxonomy
```

Runs a read-only audit of current site pages against tracked category
doctrine in `tools/authority/policies/site-taxonomy.v0.json`, then writes
private reports to:

- `_Internal/authority-taxonomy/<YYYY-MM-DD>/taxonomy-report.md`
- `_Internal/authority-taxonomy/<YYYY-MM-DD>/taxonomy-report.json`
- `_Internal/authority-taxonomy/<YYYY-MM-DD>/memory-candidates.jsonl`

This is the reusable taxonomy migration pass. It inventories pages, applies
known human corrections, names migration candidates, records old-URL handling
requirements, and emits private memory candidates. It does not move files or
edit public content.

```sh
make authority-registry
```

Revalidates and indexes existing private draft directories under
`_Internal/authority-drafts/`, reads their `packet.json` files and fresh
`validation.json` reports, then writes:

- `_Internal/authority-registry/registry.json`
- `_Internal/authority-registry/registry.md`

The tracked schema is
`tools/authority/schemas/authority-draft-registry.v0.json`. The private
registry records ready-for-review, held, rejected, promoted, drafted, and
needs-revision states. Fixture and edge-case drafts are skipped by
default so smoke tests do not dominate the operational queue. It is a
queue and review surface only; no registry entry implies automatic
publication.

```sh
make authority-review
```

Revalidates/indexes private drafts via `make authority-registry`, then
renders a stable private human review memo at:

- `_Internal/authority-review/<YYYY-MM-DD>/review.md`

The memo groups the queue into ready entries, existing-page enrichments,
new-page candidates, held Truth Stewardship packets, needs-revision
items, risks/watchpoints, and promoted records. It is a planning surface
only; it never publishes and never edits public files.

```sh
make authority-propose SOURCE=content/lab/toys/phosphor/post.frag.html
```

Asks the local llama.cpp/Qwen server to propose private authority packet
candidates from one explicit source file. It writes only:

- `_Internal/authority-proposals/<YYYY-MM-DD>-<slug>/prompt.json`
- `_Internal/authority-proposals/<YYYY-MM-DD>-<slug>/model-output.json`
- `_Internal/authority-proposals/<YYYY-MM-DD>-<slug>/candidate-packets/*.packet.json`
- `_Internal/authority-proposals/<YYYY-MM-DD>-<slug>/draft-checks/`
- `_Internal/authority-proposals/<YYYY-MM-DD>-<slug>/repaired-packets/*.packet.json` when `--repair-blocked` is enabled
- `_Internal/authority-proposals/<YYYY-MM-DD>-<slug>/repair-draft-checks/` when `--repair-blocked` is enabled
- `_Internal/authority-proposals/<YYYY-MM-DD>-<slug>/proposal-report.md`

The proposer runs candidate packets through the existing private
emit/validate flow under the proposal's `draft-checks/` directory. It
does not add proposals to the operational registry unless a human later
runs `make authority-emit PACKET=...` on one selected candidate.
Each private draft-check gets a deterministic packet-specific slug, so
two enrichment candidates for the same public page can be inspected
separately.
It also does a live reachability check for public URLs in candidate
packets, so a model-invented GitHub or site URL blocks in the private
proposal report instead of graduating to a review queue. Evidence URLs
must also come from the deterministic `allowed_public_evidence_urls`
set built from the source page, sibling metadata, sitemap, llms.txt, and
registry. Target URLs are assigned by the wrapper: `enrich_existing`
always targets the source page, while `new_page` candidates are placed
under fixed lanes (`/blog/`, `/lab/`, or `/lab/toys/`) from the output
kind and title. Qwen can propose the move, but it cannot freehand public
URLs into the packet.

The proposer also assigns deterministic source-intent fields from the source
URL and run arguments:

- `source.source_page_role`: what kind of page is being read.
- `source.pass_intent`: what kind of sweep is being run.

By default, `pass_intent=source_native`, which resolves to the source page's
own role. A caller can run a different pass explicitly, for example an
identity-resolution sweep across a toy page. For `pass_intent=identity_resolution`,
allowed proposals are identity anchors, proof-trail corrections, `sameAs` /
`subjectOf` metadata, and name-collision fixes. New toy/tool/artifact pages
from that pass are blocked by the private safety scan even if their facts are
otherwise true.

Pass-specific evidence boundaries are tracked in
`tools/authority/policies/pass-evidence-policy.v0.json`. Treat that file as
Truth-state: when a public branch, external profile, or old release surface
becomes part of an identity sweep, update the policy instead of hardcoding a
new allow-list in Python.

Example:

```sh
make authority-propose SOURCE=content/lab/toys/chewgum-time-chime/index.frag.html \
  PROPOSE_ARGS="--pass-intent identity_resolution --repair-blocked"
```

Optional proposer flags can be passed through `PROPOSE_ARGS`:

```sh
make authority-propose SOURCE=content/lab/toys/phosphor/post.frag.html \
  PROPOSE_ARGS="--timeout 90 --url-timeout 6 --max-tokens 1024 --limit 2"
```

For a two-link loop, enable one private repair pass over blocked
candidates:

```sh
make authority-propose SOURCE=content/lab/toys/chewgum-time-chime/index.frag.html \
  PROPOSE_ARGS="--repair-blocked --repair-limit 2"
```

The repair pass receives the blocked packet, safety blockers, emit/validate
output, the same allowed evidence URLs, and the Qwen authority bible. It
must repair inside the same sandbox. Repaired packets are still private
suggestions and still require human selection plus `make authority-emit`.

If the shared local llama.cpp server is busy in another thread, the
proposer may time out. That is a failed-closed result: it still writes
`prompt.json`, `model-output.json`, and `proposal-report.md`, but writes
zero candidate packets.

```sh
make authority-trace PROPOSAL=_Internal/authority-proposals/YYYY-MM-DD-slug
```

Exports a private Chew/Gum workflow trace from one authority proposal
run. It writes only:

- `_Internal/authority-traces/<YYYY-MM-DD-slug>/trace.json`
- `_Internal/authority-traces/<YYYY-MM-DD-slug>/trace.md`
- `_Internal/authority-traces/<YYYY-MM-DD-slug>/training-records.jsonl`

The trace is dogfood infrastructure, not publication. It records two
separate but related metadata layers:

- `training_memory` is the machine-readable wall-memory layer. It is
  intended as future raw material for prompt tuning, preference data,
  LoRA/fine-tuning research, and workflow recall. It is story-independent
  and requires human labels before training use.
- `narrative_metadata` is the optional human-facing explanation of the
  same loop: Chew explores, Gum binds, human review decides. Public
  process notes can be derived from reviewed traces, but the training
  records must not depend on the story layer.

`training-records.jsonl` includes automatic Gum labels such as safety
blockers, validator warnings, and emit/validate pass state. Human labels
for taste, usefulness, truthfulness, and trainability remain blank until
reviewed.

Recursion guard: trace outputs are operational memory. They may improve
the proposer, validator, editor, or future training layer, but they are
not automatic source material for public pages about the creation of
public pages. Public process writing must be deliberate and attached to
first-order artifacts or synthesis pages a human approves.

```sh
make authority-trace-review TRACE=_Internal/authority-traces/YYYY-MM-DD-slug
```

Creates a private label template and review report for one exported trace.
It writes only:

- `_Internal/authority-trace-reviews/<YYYY-MM-DD-slug>/label-template.json`
- `_Internal/authority-trace-reviews/<YYYY-MM-DD-slug>/review-summary.json`
- `_Internal/authority-trace-reviews/<YYYY-MM-DD-slug>/review.md`
- `_Internal/authority-trace-reviews/<YYYY-MM-DD-slug>/reviewed-training-records.jsonl`

Without supplied labels, the reviewed JSONL remains untrainable. To apply
labels, pass a private labels file:

```sh
make authority-trace-review \
  TRACE=_Internal/authority-traces/YYYY-MM-DD-slug \
  LABELS=_Internal/path/to/labels.json
```

The labels file uses
`tools/authority/schemas/authority-trace-labels.v0.json`. A record may only
become trainable when the human label explicitly approves it, assigns a
non-`exclude` training role, and marks truthfulness, usefulness, and boundary
preservation as `pass`. Taste must be `pass` or `not_applicable`. Labels are
stored outside the raw trace so review never mutates original run memory.

```sh
make authority-memory-index
```

Runs the house-level memory sweep. It scans all private exported traces and
their private reviews, then writes:

- `_Internal/authority-memory/memory-index.json`
- `_Internal/authority-memory/memory-index.md`
- `_Internal/authority-memory/reviewed-training-records.jsonl`

Per-trace reviews are the room-level passes. The memory index is the
house-level view: it reports which traces exist, which are reviewed, which
still need labels, how many trainable records exist, and the distribution of
training roles such as `workflow_case`, `negative_blocker`, `repair_failure`,
and `repair_success`. The exported JSONL includes only records whose human
label explicitly approves training use. Unreviewed traces and excluded records
stay visible in the index but are not copied into the reviewed corpus.

```sh
make authority-editor-pass DRAFT=_Internal/authority-drafts/YYYY-MM-DD-slug
```

Runs a private llama.cpp/Qwen editor pass over `enrichment.frag.html` or
`post.frag.html`. It writes only:

- `_Internal/authority-editor-passes/<YYYY-MM-DD>/<draft-id>/editor-input.json`
- `_Internal/authority-editor-passes/<YYYY-MM-DD>/<draft-id>/editor-output.json`
- `_Internal/authority-editor-passes/<YYYY-MM-DD>/<draft-id>/editor-report.md`
- `_Internal/authority-editor-passes/<YYYY-MM-DD>/<draft-id>/rewritten.frag.html`

The default backend is the already-running local llama.cpp server at
`http://127.0.0.1:8080/v1/chat/completions` with model alias
`coder-comments`. The editor-pass tooling does not use Ollama.

### Emit a draft

```sh
PY=/opt/homebrew/bin/python3
$PY tools/authority/emit_authority_draft.py \
  tools/authority/fixtures/triangle-engines.packet.json
```

The adapter:

- creates `_Internal/authority-drafts/<YYYY-MM-DD>-triangle-engines/`
- writes `packet.json` (normalized copy of the input)
- writes `source-trail.json`
- for active `promotion_mode = "new_page"` candidates
  (`recommended_output` in `toy | index | note`): scaffolds
  `post.toml`, `post.frag.html`, and `post.jsonld`
- for active `promotion_mode = "enrich_existing"` candidates: writes
  private merge artifacts, `enrichment.frag.html` and
  `jsonld.enrichment.json`, and does not emit replacement `post.*` files
- writes `promotion-notes.md` with a manual promotion checklist
- runs the validator and writes `validation.md` + `validation.json`

For `recommended_output` of `hold` or `reject` the adapter still creates
the directory but emits **only** `packet.json`, `source-trail.json`,
`promotion-notes.md` (with reason), and the validation reports. No
public candidate files are produced for held or rejected packets.

### Validate a draft

```sh
$PY tools/authority/validate_authority_draft.py \
  _Internal/authority-drafts/2026-04-29-triangle-engines/
```

Returns nonzero on blocking failures.

### Optional flags

```sh
emit_authority_draft.py <packet> [--slug <slug>] [--kind toy|index|note|hold|reject] [--draft-root <private-root>]
```

`--kind` overrides `recommended_output` from the packet. `--slug`
overrides the slug derived from `target_public_path`. `--draft-root`
must stay under `_Internal/`; it exists so smoke tests can write to a
separate private test root.

### Packet promotion modes

Every active packet must set:

```json
"promotion_mode": "new_page"
```

or:

```json
"promotion_mode": "enrich_existing"
```

`new_page` means the packet is staging a new public page. If
`target_public_path` already maps to an existing `content/` page, the
validator blocks and asks for `enrich_existing` instead.

`enrich_existing` means the packet is staging public-safe material for a
page that already exists under `content/`. The validator requires the
target page to exist and requires merge artifacts:

- `enrichment.frag.html`
- `jsonld.enrichment.json`
- `promotion-notes.md`

It also blocks if replacement `post.toml`, `post.frag.html`,
`post.jsonld`, `post.extra-head.html`, or `post.extra-body.html` files
are present in an enrichment draft.

## What the validator checks

**Blocking:**

- `packet.json` exists and parses, with required fields
- `recommended_output` is one of `toy | index | note | hold | reject`
- `promotion_mode` is one of `new_page | enrich_existing`
- `human_promotion_required` is `true`
- `source_trail` is non-empty
- Every URL in `source_trail` (across `url` / `href` / `link` fields and
  URLs embedded in `text` / `note` prose) resolves to a publicly-routable
  host. Loopback, RFC 1918 / RFC 6598 (CGN) IPs, link-local, `.local`,
  `.internal`, and `localhost` are blocked.
- For active `new_page` candidates: `post.toml`, `post.frag.html`, and
  `post.jsonld` exist and parse
- For active `new_page` candidates: `target_public_path` must not map to
  an existing `content/` page
- For active `enrich_existing` candidates: `target_public_path` must map
  to an existing `content/` page
- For active `enrich_existing` candidates: `enrichment.frag.html` and
  `jsonld.enrichment.json` exist and parse, with no replacement `post.*`
  or `post.extra-*` files
- Canonical URL agrees across packet, `post.toml`, and `post.jsonld`
- Canonical URL agrees across packet and `jsonld.enrichment.json` for
  enrichments
- No private filesystem paths in public candidate files
  (`_swarmlab/`, `_Company/`, `_ChewGumAnimation/`, `_Internal/`,
  `/Users/<name>/`, `.swarmlab/runs/`)
- No non-public URLs in public candidate files. Every URL rendered into
  a candidate file (canonical, JSON-LD `mentions` / `about`,
  source_library, HTML hrefs / text) is checked against the same
  `_is_public_url` rule used for source_trail. Catches private URLs that
  came in through fields like `related_public_surfaces` or
  `source_library`, not just `source_trail`.
- No scaffold residue in public candidate files, including
  `Live demo placeholder`, `replace during promotion`,
  `describe visible change`, or `describe interaction`
- `post.toml` `kind` is not a status token
  (`draft | prototype | internal | private | wip`)
- `post.toml` description / blurb does not self-label as draft
  (e.g., `"A prototype draft of..."`, `"this draft"`)
- `post.frag.html` Status field (`<dt>Status</dt><dd>VALUE</dd>`) does
  not contain a status residue token
- `post.jsonld` description does not self-label as draft
- `jsonld.enrichment.json` description does not self-label as draft
- For toys: `what_changes_on_screen` and `user_interaction` are populated
- For indexes: `related_terms` and `preferred_citation` are populated

**Warnings (non-blocking):**

- `source_trail` is prose-only with no URL
- Fewer than two `related_public_surfaces`
- For toys: `demo_parameters` missing
- `post.frag.html` has no `/glossary/` cross-link
- `post.jsonld` or `jsonld.enrichment.json` has no `mentions` or `about`
  fields

The "draft / prototype / internal / private" check is **scoped**, not a
naive substring scan. It targets the TOML kind field, TOML
description / blurb (label-style patterns at start or as named phrases
like "prototype draft"), the rendered HTML Status field, and the
JSON-LD description. Innocent prose like "internal forces" or
"draft the hypothesis" is not flagged.

## Manual promotion

Promotion is **always** human-driven. The adapter and validator never
publish.

For `promotion_mode = "new_page"`:

1. Run the validator. Resolve all blocking failures and review warnings.
2. Inspect the scaffold. For toys only, replace the **Live Toy**
   placeholder with the real interactive demo. Note scaffolds do not get
   toy placeholders.
3. Add `post.extra-head.html` and `post.extra-body.html` by hand (e.g.,
   the inline `<script>` that drives the demo). These are not scaffolded.
4. Tighten any scaffold prose.
5. Move/adapt files into the chosen `content/` location:
   - For toys (target `/lab/toys/<slug>/`), rename `post.*` to `index.*`
     to match the build convention.
   - For posts/experiments (target `/blog/<slug>/`, `/animation/<slug>/`,
     etc.), keep `post.*`.
6. Run `make build` and review the rendered output locally.
7. Manually edit `site/sitemap.xml` and `site/llms.txt` only if the
   artifact is high-signal and ready to be promoted there. The adapter
   never touches these.
8. Commit the `content/` change as a single intentional change. Do not
   commit anything from `_Internal/`.

For `promotion_mode = "enrich_existing"`:

1. Run the validator. Resolve all blocking failures and review warnings.
2. Inspect `enrichment.frag.html` and manually merge useful sections into
   the existing page.
3. Inspect `jsonld.enrichment.json` and manually merge only useful
   public JSON-LD fields.
4. Preserve the existing page identity, title, canonical URL, and
   publication history unless a human intentionally changes them.
5. Run `make build` and review the rendered page locally.
6. Manually edit `site/sitemap.xml` and `site/llms.txt` only if the
   enrichment deserves a separate high-signal update.
7. Commit the `content/` change as a single intentional enrichment
   commit. Do not commit anything from `_Internal/`.

`shane-publish.el` is the Emacs blog-publish flow for Org-authored
posts; it is **not** part of this adapter's lane.

## Private Qwen editor pass

`run_authority_editor_pass.py` lets local Qwen2.5 suggest grammar, flow,
and tone improvements for a private authority draft. The rewritten
fragment is a review artifact only. It is never moved into `content/`
automatically.

The model is instructed to preserve claims, uncertainty, URLs, tags,
attributes, source claims, code names, numerical values, and
public/private boundary language. After generation, deterministic checks:

- block any HTML structure fingerprint change, including tag sequence,
  start/end nesting, tag names, attributes, attribute values, `href` /
  `src` values, section order, and protected code/link markup
- block new URLs
- block new numbers and constants
- block private filesystem paths
- block scaffold residue such as `Live demo placeholder` or
  `replace during promotion`
- flag new proper nouns or technical terms not present in the packet,
  source trail, or original fragment
- flag possible certainty upgrades such as hedged language becoming
  absolute language
- run the existing authority validator against a temporary copy of the
  rewritten private artifact

The editor report classifies the rewrite as `usable`,
`partially_usable`, or `rejected`. A `partially_usable` result means the
fragment may contain useful edits, but a human must inspect the flags
before merging anything by hand.

## What the adapter refuses to do

- run anything in `_swarmlab/`
- mutate SwarmLab ledgers
- edit any file under `content/`
- edit `site/sitemap.xml`
- edit `site/llms.txt`
- generate live demos or extra-body scripts
- claim "first" without external scan (call surfaces this as a warning,
  not a block; humans must verify)

## Relationship to SwarmLab

```
REAL WORK LANE          _swarmlab/
                        Engineering, Truth, Research, internal packets

ONLINE PRESENCE LANE    _00_Online_Presence/
                        public content, site build, lab toys, glossary

BRIDGE                  tools/authority/ (this adapter)
                        consumes packets, emits private drafts,
                        gates publication, never auto-publishes
```

The adapter borrows the conceptual shape of SwarmLab's authority-promotion
packet (`_swarmlab/templates/authority-promotion-packet.template.md`) but
runs entirely inside `_00_Online_Presence/`. It does not import from,
read mutably, or ledger into SwarmLab. Future SwarmLab outputs can feed
this adapter once the SwarmLab side ships JSON-shaped packets that match
the schema documented in fixtures/.
