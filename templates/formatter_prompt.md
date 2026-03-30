# Formatter Prompt

Use this prompt when turning a raw thought dump into a machine-ready article draft.

```text
Turn the raw note below into a publication-ready draft for Shane Curry's canonical site.

Rules:
- Keep the draft focused on one topic only.
- Use a literal title, not a clever one.
- Put the answer in the first paragraph.
- Do not invent facts, credits, dates, or links.
- Separate production knowledge from theory or inference.
- Preserve uncertainty and caveats.
- Prefer explicit nouns over vague language.
- Define important terms plainly.
- Keep the writing citation-friendly.

Output format:
1. Suggested title
2. Suggested slug
3. One-paragraph summary
4. Metadata block
5. Main claim
6. Definitions
7. What I know from production
8. System-level explanation
9. Practical examples
10. Limitations and caveats
11. Related artifacts needed
12. Preferred citation

Raw note:
[paste the contents of templates/raw_thought_dump.md here]
```
