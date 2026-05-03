# Chew/Gum Site Builder Skills

Tracked capability notes for the online-presence lane. This document is for
humans and agents who need to remember what the site-building workflow can do.
It is not public copy and it is not a promise that any step publishes
automatically.

## Operating Split

Chew is the proposing/building side:

- names possible moves
- drafts packets
- sketches page changes
- proposes taxonomy corrections
- writes candidate prose or enrichment fragments

Gum is the verifying/protecting side:

- blocks unsupported claims
- rejects invented URLs
- checks category doctrine
- catches stale validation
- refuses thin pages
- records human corrections as memory

Codex and the human remain the promotion authority. A model proposal is never a
published artifact by itself.

## Reusable Skills

### Truth-Steward Proposal

Use when a real public artifact may support a new page, enrichment, held packet,
or rejection.

Inputs:

- one explicit source file
- allowed public evidence URLs
- pass intent

Outputs:

- private candidate packets
- validation reports
- proposal report
- optional repair pass

Current command:

```sh
make truth-steward-propose SOURCE=content/path/to/page.frag.html
```

### Source-Trail Enrichment

Use when an existing public page is real but under-explained. This is usually
better than creating a new page.

Good targets:

- demo parameters
- exact source links
- sibling artifact links
- repo/tag links
- JSON-LD mentions/about fields

Guardrail: enrichment must strengthen the existing page without turning it into
a page about the pipeline that enriched it.

### Identity Resolution Sweep

Use when a page needs clearer connection to Shane Curry, ChewGum Labs, ChewGum
Animation, Infinite Hush, external profiles, or name-collision handling.

This pass can run on any source page. The source page role does not matter;
identity-resolution intent overrides it.

Guardrail: do not propose toy/tool/artifact work during an identity pass unless
it directly resolves identity.

### Window Taxonomy Audit

Use when the visible page windows are drifting into inconsistent labels.

Current command:

```sh
make truth-steward-window-audit
```

Good outcomes:

- rename vague windows
- preserve expressive titles where intentional
- keep page role labels stable enough for humans and agents

### Navigation Architecture

Use when a top-level dropdown would otherwise point directly to an external
site. Dropdowns are local navigation, not outbound launchers.

Current rule:

- dropdown menu items point to local pages or local fragments only
- external URLs live inside local link, proof, source-trail, or profile pages
- top-level menu hotkeys should be unique where practical
- if an external link becomes important enough for navigation, create a local
  context page first

Applied structure:

- `/music/`: local music hub
- `/music/discography/`: album chronology
- `/music/live-performances/`: public live music, storytelling, and live
  coding performance index
- `/music/live-performances/i-know-how-much-you-like-to-be-alone/`: single
  live coding performance record with local PDF pamphlet link
- `/music/streaming-links/`: music platform links with availability notes
- `/music/uses-in-media/`: external media-use index
- `/music/uses-in-media/migration/`: Migration music/tool credit page
- `/animation/cartoons/`: local cartoon/video index
- `/animation/cartoons/wizard-saga/`: embedded Wizard Saga cartoon record
- `/links/`: local landing page for outbound profile and proof links

### Frozen Catalog Expansion

Use when a mostly historical lane gets a one-time public buildout: albums,
cartoons, streaming profiles, live performances, festival proof, or external
implementation records.

Good outcomes:

- create stable local pages for durable public facts
- keep external links inside local context pages
- update `sitemap.xml` and `llms.txt` only for high-signal pages or documents
- add static public documents under `site/assets/docs/` only when the document
  is intentionally hosted and citeable
- record author-supplied production notes as author-supplied, not third-party
  verification
- keep frozen/historical lanes from polluting blog, toy, or tool indexes

Guardrail: a catalog expansion is not permission to over-explain the pipeline.
The page should be about the first-order work: album, cartoon, performance,
festival record, or implementation.

### Public Surface Audit

Use before commit/push or after broad edits.

Current command:

```sh
make truth-steward-audit
```

Checks include:

- private path leaks
- non-public URL leaks
- sitemap/llms visibility risks
- public candidate warnings

### Editor Pass

Use when a draft has truthful content but awkward prose.

Current command:

```sh
make truth-steward-editor-pass DRAFT=_Internal/truth-steward-drafts/YYYY-MM-DD-slug
```

Guardrails:

- preserve HTML structure
- preserve links and code text
- do not add claims
- do not change the artifact's factual scope

### Taxonomy Migration Pass

Use when the site's current category or URL no longer matches the human meaning
of the work.

This is not part of normal publishing. It is a corrective room-sweep for when
the site architecture has learned something new.

Inputs:

- category doctrine
- current page inventory
- candidate reclassification proposal
- old URL handling plan

Current doctrine:

- `blog`: prose, reflection, essays, human notes
- `toy`: interactive browser artifact or playable demo
- `tool`: repo-backed reusable software or public extraction
- `animation`: literal animation showcase, personal cartoons, embedded
  watchable cartoon/video records, credits-adjacent animation work, and
  YouTube/portfolio material
- `music`: albums, streaming profiles, soundtrack-use anchors, live performance
  records, hosted audience documents, and music proof trails
- `links`: local landing pages for outbound profile, music, animation, code,
  and release links
- `about`: identity, proof trail, external profile resolution
- `glossary`: definitions used by public work
- `lab`: umbrella/methodology lane, not a junk drawer

Applied taxonomy corrections:

- Phosphor is a toy, not a blog post.
- Dead Beat is a toy, not a blog post.
- Falling Hall is a toy, not an animation showcase page.
- ChewGumTimeChime is a tool/repo; the originating live toy now uses the
  distinct public display name Stroke Chime.

Required checks:

- no invented URLs
- no silent canonical drift
- old URL has a redirect, pointer, or noindex/stub plan
- index pages update with the move
- sitemap and llms.txt impact is named
- blog index contains prose only
- toy index contains interactive artifacts only
- tool index contains repo-backed artifacts only
- animation entries for personal cartoons should name narrative premise,
  software used, skills used, public proof trail, video host, and any
  platform-bound audio limitation when those facts have evidence; otherwise
  limit the page to the public video facts and state the claim boundary

Current command:

```sh
make truth-steward-taxonomy
```

Private outputs:

- `_Internal/truth-steward-taxonomy/<YYYY-MM-DD>/taxonomy-report.md`
- `_Internal/truth-steward-taxonomy/<YYYY-MM-DD>/taxonomy-report.json`
- `_Internal/truth-steward-taxonomy/<YYYY-MM-DD>/memory-candidates.jsonl`

### Trace And Memory Capture

Use after a meaningful proposal/review loop so future passes inherit the
correction.

Current commands:

```sh
make truth-steward-trace PROPOSAL=_Internal/truth-steward-proposals/YYYY-MM-DD-slug
make truth-steward-trace-review TRACE=_Internal/truth-steward-traces/YYYY-MM-DD-slug
make truth-steward-memory-index
```

Good memory records include:

- human correction
- rejected model assumption
- accepted final rule
- exact evidence used
- final validation outcome

## When In Doubt

Prefer a private proposal, a held packet, or a taxonomy note over public churn.
The useful move is the one that leaves the public site clearer and leaves the
private memory layer smarter.
