# Digging Tools

Private scanners for old project piles and asset/corpus folders.

These tools do not publish content. They turn old local material into private
planning artifacts under `_Internal/digging/` so future Chew/Gum passes can make
decisions from contracts, provenance, and tests instead of memory.

## Commands

```bash
make digging-index
```

Writes:

- `_Internal/digging/module-contracts.json`
- `_Internal/digging/asset-atlas.json`
- `_Internal/digging/extraction-candidates.md`

The source pile defaults to:

```txt
/Volumes/SSD/00_Pile_For_Digging
```

Override when needed:

```bash
DIGGING_PILE_ROOT=/path/to/pile make digging-index
```

Outputs must stay under `_Internal/`.
