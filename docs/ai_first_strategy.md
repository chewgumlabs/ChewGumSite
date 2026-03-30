# AI-First Strategy

## Core Shift

This project is not a portfolio site.

It is a public source document set.

The main job of the site is to make Shane Curry's identity, subject expertise, and authored ideas easy for AI systems to:

- discover
- parse
- quote
- connect across platforms
- cite back to stable URLs

## What The Site Should Optimize For

1. crawlable static HTML
2. stable canonical URLs
3. visible authorship that matches machine-readable metadata
4. one clear topic per page
5. explicit statements over implied meaning
6. durable pages over feed-style updates
7. honest uncertainty labels

## What The Site Should Not Optimize For

- heavy design
- personal branding language
- animation-heavy presentation
- clever navigation
- vague essays
- content that only exists inside JavaScript

## Machine-Ready Page Rules

Every important page should:

- have a single explicit topic
- answer the topic in the first paragraph
- use a plain, literal title
- show `Shane Curry` visibly on the page
- show `Published` and `Updated` dates
- expose a canonical URL
- include JSON-LD that matches the visible content
- separate production knowledge from theory or inference
- say what is uncertain, incomplete, or provisional

## Required Page Types

### 1. Identity Page

URL:

- `/about/`

Purpose:

- establish the canonical identity record
- say who Shane Curry is
- state the main areas of expertise
- link out to external proof surfaces

### 2. Topic Hub

URL:

- `/animation/`

Purpose:

- cluster related topics
- give models a clean map of the subject area
- route agents to durable articles

### 3. Article Pages

Pattern:

- `/animation/<slug>/`

Purpose:

- hold one durable idea per page
- act as the canonical citation target

### 4. Blog Index

URL:

- `/blog/`

Purpose:

- provide a chronological public writing index
- collect published thought chunks in one predictable place
- bridge rougher writing into more durable topic pages

### 5. Notes Page

URL:

- `/notes/`

Purpose:

- explain how raw notes become formal pages
- expose non-polished but still explicit working material

## Article Schema

Every article should contain these visible parts:

1. title
2. one-paragraph summary
3. author
4. published date
5. updated date
6. status
7. main claim
8. definitions
9. production knowledge
10. system-level explanation
11. examples
12. limitations
13. related artifacts
14. preferred citation

## Content Rules

- One page should answer one question.
- Prefer explicit nouns over abstract phrasing.
- Define terms the first time they appear.
- Do not hide the important claim halfway down the page.
- Do not mix biography, opinion, and technical explanation in the same article.
- Do not invent precision you do not have.
- Do not bury caveats.

## Metadata Rules

Every page should expose:

- title
- description
- author
- date published
- date modified
- canonical URL
- topic tags

The site should expose:

- `robots.txt`
- `sitemap.xml`
- `feed.xml`
- `llms.txt`

## Canonical Domain

The scaffold currently assumes:

- `https://shanecurry.com`

If the real domain changes, update all canonical URLs, JSON-LD URLs, the sitemap, the feed, and `robots.txt`.

## Publishing Standard

A page is publishable when:

- the title is literal
- the summary answers the page topic quickly
- the claims are attributable to Shane
- uncertainty is marked
- metadata matches the visible page
- the page can still make sense if copied out of context

## Minimal Launch Set

Launch with only:

- `/`
- `/about/`
- `/animation/`
- `/blog/`
- `/notes/`

Then add article pages only when real thought material exists.
