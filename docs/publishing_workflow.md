# Publishing Workflow

## Goal

Take raw thought material from Shane and convert it into a machine-ready page with minimal interpretation loss.

## Input Standard

The raw input does not need to be polished.

It can be:

- fragments
- bullet points
- voice-note transcription
- rough explanation
- argument sketch
- messy working notes

The only requirement is that the note should mostly be about one topic.

## Workflow

1. Copy `templates/raw_thought_dump.md`.
2. Paste Shane's raw material into the template.
3. Fill in whatever is easy: topic guess, key claims, examples, caveats, related links.
4. Run the formatter prompt from `templates/formatter_prompt.md`.
5. Review the output for factual accuracy and overstatement.
6. Turn the approved draft into a static HTML page under `site/blog/<slug>/index.html` by default.
7. If the piece becomes a durable topic reference, also promote or adapt it into `site/animation/<slug>/index.html`.
8. Update the topic hub, blog index, `sitemap.xml`, `feed.xml`, and `llms.txt`.

## Editorial Rules For The Formatter

The formatter should:

- keep one topic per page
- move the answer up front
- define terms plainly
- separate production knowledge from inference
- preserve uncertainty
- avoid marketing language
- avoid adding unsupported claims
- avoid smoothing away useful specificity

## What To Do With Mixed Notes

If one raw note contains multiple topics:

1. split it into separate candidate pages
2. choose one primary page for publication
3. move the remaining ideas into future notes

## Publication Labels

Use a visible status on the page:

- `Published`
- `Draft`
- `Working Note`

Do not pretend a working note is a polished article.

## Required Review Pass

Before publishing, check:

- does the first paragraph clearly answer the topic?
- does the title use literal language?
- does the page separate observed production knowledge from theory?
- are caveats visible?
- do the metadata fields match the visible page?
- is the URL stable and specific?

## Update Workflow

When a page changes materially:

1. update the visible `Updated` date
2. update JSON-LD `dateModified`
3. update `sitemap.xml`
4. optionally add a feed item if the change matters to subscribers

## Working Principle

The raw note can be messy.

The published page cannot be ambiguous.
