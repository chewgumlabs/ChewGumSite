# <TITLE>

## The idea

<IDEA>

## Where code lives

- `main.js` — mounts to `#<SLUG>-mount` (the container div in `index.html`).
- `style.css` — styles the mount element and anything inside it.
- `index.html` — the dev harness. Served at `http://localhost:8765/assets/<SLUG>/` while `make watch` runs. Do not add new files outside this directory.

Single page. No bundler. No dependencies. Pure browser JS and CSS.

## Constraints

- Everything must run from the files in this directory, served statically by GitHub Pages in production.
- No npm, no build step, no TypeScript, no frameworks. Vanilla JS and CSS only.
- Keep the mount element's ID (`<SLUG>-mount`) stable — the published blog post references it by that exact ID.
- Degrade gracefully if audio / pointer lock / WebGL / any permissioned API is refused. The page must still render something sensible.
- Do not rely on a web server feature beyond static file serving. In production this lives on GitHub Pages.

## When done

The voice paragraph in `content/blog/<SLUG>/post.org` will be written AFTER this experiment is working — Shane writes it as a reflection on the finished thing. At that point Shane will run `M-x shane/ai-draft-machine-sections`, which drafts the "What It Is", "Controls", "Build Notes", and "Preferred Citation" windows of the post by reading:

1. The voice paragraph.
2. The contents of `main.js` and `style.css` (this directory).
3. This file.

So: write code that reads well when the drafter walks through it. Comments explaining *why*, not *what*, help that pass.
