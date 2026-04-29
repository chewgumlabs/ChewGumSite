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
  fixtures/
    triangle-engines.packet.json
                                          known-good fixture
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
  `/opt/homebrew/bin/python3`; both scripts hard-fail with a clear
  message if invoked under an older Python (e.g., macOS system
  `/usr/bin/python3` 3.9). Use the same Python that runs `make build`.
- No third-party dependencies.

## Usage

### Make targets

All authority targets use the Makefile `PYTHON` variable, which defaults
to `/opt/homebrew/bin/python3`.

```sh
make authority-smoke
```

Runs the full fixture matrix:

- the triangle fixture must pass
- all bad fixtures must block
- the triangle fixture emitted as `--kind hold` must leave zero `post.*`
  files
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
- for active candidates (`recommended_output` in `toy | index | note`):
  scaffolds `post.toml`, `post.frag.html`, and `post.jsonld`
- writes `promotion-notes.md` with a manual promotion checklist
- runs the validator and writes `validation.md` + `validation.json`

For `recommended_output` of `hold` or `reject` the adapter still creates
the directory but emits **only** `packet.json`, `source-trail.json`,
`promotion-notes.md` (with reason), and the validation reports. No
`post.*` files are produced for held or rejected packets.

### Validate a draft

```sh
$PY tools/authority/validate_authority_draft.py \
  _Internal/authority-drafts/2026-04-29-triangle-engines/
```

Returns nonzero on blocking failures.

### Optional flags

```sh
emit_authority_draft.py <packet> [--slug <slug>] [--kind toy|index|note|hold|reject]
```

`--kind` overrides `recommended_output` from the packet. `--slug`
overrides the slug derived from `target_public_path`.

## What the validator checks

**Blocking:**

- `packet.json` exists and parses, with required fields
- `recommended_output` is one of `toy | index | note | hold | reject`
- `human_promotion_required` is `true`
- `source_trail` is non-empty
- Every URL in `source_trail` (across `url` / `href` / `link` fields and
  URLs embedded in `text` / `note` prose) resolves to a publicly-routable
  host. Loopback, RFC 1918 / RFC 6598 (CGN) IPs, link-local, `.local`,
  `.internal`, and `localhost` are blocked.
- For active candidates: `post.toml`, `post.frag.html`, `post.jsonld`
  exist and parse
- Canonical URL agrees across packet, `post.toml`, and `post.jsonld`
- No private filesystem paths in `post.*` files
  (`_swarmlab/`, `_Company/`, `_ChewGumAnimation/`, `_Internal/`,
  `/Users/<name>/`, `.swarmlab/runs/`)
- No non-public URLs in `post.*` files. Every URL rendered into a
  candidate file (canonical, JSON-LD `mentions` / `about`, source_library,
  HTML hrefs / text) is checked against the same `_is_public_url` rule
  used for source_trail. Catches private URLs that came in through
  fields like `related_public_surfaces` or `source_library`, not just
  `source_trail`.
- `post.toml` `kind` is not a status token
  (`draft | prototype | internal | private | wip`)
- `post.toml` description / blurb does not self-label as draft
  (e.g., `"A prototype draft of..."`, `"this draft"`)
- `post.frag.html` Status field (`<dt>Status</dt><dd>VALUE</dd>`) does
  not contain a status residue token
- `post.jsonld` description does not self-label as draft
- For toys: `what_changes_on_screen` and `user_interaction` are populated
- For indexes: `related_terms` and `preferred_citation` are populated

**Warnings (non-blocking):**

- `source_trail` is prose-only with no URL
- Fewer than two `related_public_surfaces`
- `post.frag.html` has no `/glossary/` cross-link
- `post.jsonld` has no `mentions` or `about` fields
- For toys: `demo_parameters` missing
- `target_public_path` overlaps an existing canonical page (probably
  belongs as enrichment, not a new page)

The "draft / prototype / internal / private" check is **scoped**, not a
naive substring scan. It targets the TOML kind field, TOML
description / blurb (label-style patterns at start or as named phrases
like "prototype draft"), the rendered HTML Status field, and the
JSON-LD description. Innocent prose like "internal forces" or
"draft the hypothesis" is not flagged.

## Manual promotion

Promotion is **always** human-driven. The adapter and validator never
publish.

1. Run the validator. Resolve all blocking failures and review warnings.
2. Inspect the scaffold. Replace the **Live Toy** placeholder with the
   real interactive demo. The adapter does not generate live demos.
3. Add `post.extra-head.html` and `post.extra-body.html` by hand (e.g.,
   the inline `<script>` that drives the demo). These are not scaffolded.
4. Tighten any prose marked `(replace during promotion)`.
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

`shane-publish.el` is the Emacs blog-publish flow for Org-authored
posts; it is **not** part of this adapter's lane.

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
