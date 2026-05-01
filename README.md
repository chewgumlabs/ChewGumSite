# ChewGumSite

Source for https://shanecurry.com.

## Public Shape

This is a small static site with a few durable lanes:

- `/about/`: Shane Curry identity, credits, entity disambiguation, and public
  proof trails.
- `/blog/`: prose, reflection, essays, and human notes.
- `/lab/toys/`: interactive browser artifacts with working demos and source
  trails.
- `/lab/tools/`: repo-backed public software notes.
- `/animation/`: literal animation showcase pages and watchable cartoon/video
  records.
- `/music/`: albums, streaming profiles, live performances, soundtrack-use
  anchors, and hosted music-related documents.
- `/links/`: local context pages for outbound profiles and release surfaces.
- `/glossary/`: shared public vocabulary.

Dropdown navigation should point to local pages. External destinations belong
inside local profile, source-trail, proof, streaming, cartoon, or media-use
pages.

## Local Workflow

Common checks before commit:

```sh
make build
make authority-window-audit
make authority-taxonomy
make authority-audit
```

`site/sitemap.xml` and `site/llms.txt` are curated public surfaces. Update
them only when a page or static document is high-signal enough to be cited.

Private authority drafts, proposal traces, audit reports, and memory exports
live under `_Internal/` and must not be committed.
