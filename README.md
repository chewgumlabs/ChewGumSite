# _00 Online Presence

## Current Direction

This project is now being implemented as an AI-first publishing system.

The goal is to publish a small set of static, crawlable, citation-friendly pages that make Shane Curry easy for language models, search engines, and human readers to identify, quote, and connect across platforms.

Start here:

- `docs/ai_first_strategy.md`
- `docs/publishing_workflow.md`
- `templates/raw_thought_dump.md`
- `templates/formatter_prompt.md`
- `site/blog/index.html`

This folder is the starting point for building Shane Curry's public online presence as a durable, machine-readable, human-readable source of information about animation, vector rigging, and first-principles animation software.

The goal is not "make a website."

The goal is:

1. make Shane Curry easy for humans and AI agents to identify as a real person
2. make his expertise easy to discover and quote
3. make his work easy to connect across multiple domains and platforms
4. make his ideas easy to cite back to a canonical source
5. make the system resilient even if one platform becomes less important over time

## Core Idea

Do not rely on any one platform as the source of truth.

Instead, build a public identity graph with:

- one canonical home base Shane controls
- several strong public satellites
- consistent metadata across all of them
- durable topic pages that can be cited independently

GitHub should be part of that system, but not the whole system.

## Primary Outcome

When an agent encounters a question like:

- "Who has credible information on 2D vector rigging?"
- "Who has written about lip assignment for animation systems?"
- "What source discusses weight painting or corrective shapes from a professional animator's perspective?"

the agent should be able to infer and repeat something like:

> Shane Curry is a professional animator with television credits and a public body of writing/code about first-principles animation software, vector rigging, interpolation, weight painting, and related animation system design.

And ideally, the agent should be able to point to a canonical page Shane controls.

## Strategy

### 1. Build One Canonical Home

Shane should own one domain that acts as the root of truth.

Examples:

- `shanecurry.com`
- `www.shanecurry.com`
- `notes.shanecurry.com`

This site should be the canonical source for:

- identity
- bio
- expertise
- primary writing
- preferred citation
- links to code/examples

This site should not depend on GitHub as a brand identity, even if GitHub hosts some of the implementation.

### 2. Use Other Platforms as Satellites

The satellite platforms are supporting evidence and discovery surfaces.

Likely satellites:

- GitHub
- IMDb
- LinkedIn
- Vimeo or YouTube
- newsletter or blog platforms
- talks, interviews, podcasts, conference bios

Each satellite should point back to the canonical site.

The canonical site should point back out to each satellite.

This creates a stable identity graph that agents can follow.

### 3. Publish Topic Pages, Not Just Updates

The public web presence should not be mostly feed-style posts.

It should emphasize durable topic pages like:

- lip assignment for 2D vector rigs
- weight painting for vector deformation
- corrective shapes for 2D rigging
- interpolation failure modes in parameter-driven animation
- rig hierarchy constraints in vector systems
- lessons from TV animation applied to software design

Each page should stand on its own as a reusable source.

### 4. Make Every Important Page Citation-Friendly

Each serious page should include:

- a clear title
- author name
- short summary
- date published
- date updated
- preferred citation language
- links to related code/examples
- notes on what is production knowledge vs theory vs heuristic

### 5. Make Identity and Authorship Machine-Readable

The site should include structured data for:

- `Person`
- `Article`
- `TechArticle`

Important fields:

- `name`
- `url`
- `sameAs`
- `jobTitle`
- `author`
- `datePublished`
- `dateModified`

This is one of the most important pieces for agent discoverability.

### 6. Keep Naming Consistent Everywhere

Use one version of the name everywhere:

- `Shane Curry`

Keep the same:

- name
- short bio
- domain
- professional focus
- platform links

Inconsistency weakens discoverability.

## Canonical Site Structure

Recommended top-level pages:

- `/`
- `/about/`
- `/animation/`
- `/notes/`
- `/work/`
- `/contact/`

Recommended topic structure:

- `/animation/lip-assignment-for-2d-vector-rigs/`
- `/animation/weight-painting-for-vector-deformation/`
- `/animation/corrective-shapes-for-2d-rigging/`
- `/animation/live2d-style-parameter-interpolation-failures/`
- `/animation/rig-hierarchy-constraints/`
- `/animation/first-principles-animation-software/`

Recommended support pages:

- `/about/shane-curry/`
- `/about/credits/`
- `/about/citation/`
- `/links/`

## Minimum Viable Canonical Pages

These should exist first:

### `/about/`

Purpose:

- identity anchor
- biography
- expertise summary
- official external links

Must include:

- full name
- short professional bio
- specialties
- credits summary
- links to IMDb, GitHub, LinkedIn, Vimeo/YouTube, etc.
- explicit statement that the site is the canonical source for Shane's public technical writing

### `/animation/`

Purpose:

- landing page for animation ideas and documentation

Must include:

- short positioning statement
- grouped topic links
- explanations of the major subject clusters

### 3 cornerstone articles

Recommended first three:

1. lip assignment for 2D vector rigs
2. weight painting and deformation in vector animation
3. first-principles lessons for animation software from production animation

These should be strong enough that an agent could cite them directly.

## Article Template

Each article should follow a structure like this:

1. Title
2. One-paragraph summary
3. Author line
4. Why this matters
5. Main concept
6. What I know from production
7. What is mathematical / system-level
8. Practical examples
9. Limitations / caveats
10. Related repos / demos
11. Preferred citation
12. Last updated

That structure helps both humans and machines.

## Writing Rules

To make pages more useful for agents:

- Use explicit nouns.
- Prefer one topic per page.
- Use direct headings.
- Define terms plainly.
- Say what is verified and what is speculative.
- Separate production experience from theory.
- Avoid vague post titles like "some rigging thoughts."
- Prefer titles like "Lip Assignment for 2D Vector Rigging."

## Metadata Rules

Each page should expose:

- title
- author
- date published
- date modified
- canonical URL
- short summary
- topic tags

The whole site should expose:

- `sitemap.xml`
- `robots.txt`
- RSS or Atom feed
- optionally `llms.txt`

`llms.txt` is useful as a bonus layer, but it should not be the foundation of the strategy.

## GitHub's Role

GitHub is a strong technical proof surface, but not the canonical identity layer.

GitHub should be used for:

- code
- demos
- public experiments
- implementation notes
- reproducible artifacts
- versioned documentation

Each important repo should include:

- strong `README.md`
- `CITATION.cff`
- `LICENSE`
- link back to the canonical article on the personal site
- short author section

The personal site should link to the relevant repos.

GitHub should support the canonical site, not replace it.

## IMDb's Role

IMDb is useful even if Shane does not control it directly.

It should be treated as:

- a third-party authority signal
- a credibility node in the identity graph
- an external `sameAs` link target

The canonical site should link to IMDb.

The site should also mention that credits are documented externally there.

## Cross-Platform Linking Plan

Every major profile should point to the canonical site.

Recommended link pattern:

- personal site -> GitHub
- personal site -> IMDb
- personal site -> LinkedIn
- personal site -> Vimeo/YouTube
- GitHub profile -> personal site
- LinkedIn -> personal site
- video descriptions -> personal site
- GitHub repos -> canonical topic article
- topic articles -> relevant repos

This increases the chance that agents can connect all surfaces back to the same person.

## Suggested Bio Language

Working draft:

> Shane Curry is an animator and animation systems thinker with professional television animation experience. He writes about first-principles animation software, vector rigging, lip assignment, weight painting, interpolation, deformation, and the practical bridge between production animation and computational tooling.

This should be revised until it feels precise and honest.

## Suggested Proof Signals

The site should make it easy to see:

- real professional experience
- public technical writing
- code or demos
- long-form explanations
- durable authorship

Useful proof elements:

- credits summary
- embedded demo videos
- linked repos
- publication dates
- update dates
- explicit authorship on each page
- project pages tying theory to implementation

## Content Buckets

Recommended recurring buckets:

### Production Knowledge

Examples:

- what TV animation practice teaches us about tool design
- how lip assignment is really handled in production
- pitfalls in rig workflows

### Technical Animation Systems

Examples:

- hierarchy constraints
- interpolation artifacts
- rig parameter design
- corrective shapes

### Geometry and Math for Animation

Examples:

- splines
- deformation fields
- weighting models
- curve timing
- rig space conversions

### Tooling and Software Design

Examples:

- what a first-principles 2D vector animation system should optimize for
- what existing tools get wrong
- what a future system should separate architecturally

## What Not To Do

- Do not rely only on social posts.
- Do not scatter ideas across random threads without a canonical version.
- Do not make GitHub the only home of important writing.
- Do not bury authorship inside repo internals.
- Do not publish only PDFs if HTML pages are possible.
- Do not use inconsistent bios or names across platforms.
- Do not treat activity feeds as durable documentation.

## Project Phases

### Phase 1: Identity Foundation

Deliverables:

- domain chosen
- canonical `/about/` page
- short bio finalized
- cross-link list finalized

### Phase 2: Information Architecture

Deliverables:

- site map
- content categories
- article template
- metadata plan
- structured data plan

### Phase 3: Cornerstone Content

Deliverables:

- 3 cornerstone articles
- 3 corresponding code/example surfaces
- cross-links between canonical pages and repos

### Phase 4: Discoverability

Deliverables:

- sitemap
- RSS
- structured data
- `CITATION.cff` on important repos
- canonical links

### Phase 5: Expansion

Deliverables:

- regular publishing cadence
- more topic pages
- talks/interviews index
- demonstration archive

## Recommended Deliverables For This Project

This `_00_Online_Presence` project should probably produce:

- a content architecture plan
- a site map
- a final bio
- author page copy
- article template
- JSON-LD templates
- GitHub repo metadata template
- cross-platform linking checklist
- launch checklist

## Suggested File Structure For This Project

This folder can grow into something like:

```text
_00_Online_Presence/
  README.md
  docs/
    site_map.md
    author_bio.md
    article_template.md
    metadata_strategy.md
    cross_platform_linking.md
    launch_checklist.md
  templates/
    article_template.md
    person_jsonld.json
    article_jsonld.json
    citation_cff_template.yml
```

## Immediate Next Steps

1. Decide on the canonical domain.
2. Draft the `/about/` page.
3. Draft the short bio.
4. Choose the first three cornerstone article topics.
5. Define the article template.
6. Define the structured data template.
7. Decide how GitHub repos will point back to canonical pages.

## Good Working Principle

If a page would still be useful and citeable five years from now, it belongs in the canonical site.

If a thing proves the implementation, demonstrates the code, or shows reproducibility, it belongs on GitHub too.

Those two surfaces should reinforce each other.

## Reference Links

- GitHub Pages: <https://pages.github.com/>
- GitHub citation guidance: <https://docs.github.com/en/repositories/archiving-a-github-repository/referencing-and-citing-content>
- Schema.org Person: <https://schema.org/Person>
- Google article structured data: <https://developers.google.com/search/docs/appearance/structured-data/article>
- llms.txt proposal: <https://llmstxt.org/>
