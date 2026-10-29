# Yokogawa Product Manual Collector

Language / 语言: [中文](README.md) | **English**

A portable collector for ProSafe-RS and related products: official-library searches, supplemental public sources, accumulated catalogs, revision comparison and resumable downloads. Works with Codex, Claude Code, Cursor, other agents or standalone Python; no simulated browser clicks.

**Collect accessible candidates initially, then refresh discovery or resume downloads. Availability is not latest applicability.** The output includes traceable local RAG file indexes, not a vector database or an engineering approval system.

## 2026-10-30 Update

- No-search `resume`: continue saved catalogs without repeating searches, spending search-service credits or refreshing observation dates.
- Bounded official-page discovery: `seed_pages`, one document-page level, known extensionless PDF endpoints and explicit pending/error reports.
- Reference-driven gaps: extract document numbers, page evidence and hashes from actual PDFs; add reviewed leads to `document_numbers`.
- Version-safe RAG: preserve historical files separately from current local ingestion records.
- Reliability: hash validation, URL deduplication, stop repeated aliases after endpoint denial, same-URL revalidation and product-level failure isolation.

## Quick Start

Python 3.10+. Collection/downloading uses the standard library. Optional PDF reference inspection needs `pypdf` or PyMuPDF; optional `certifi` can supply a trusted CA bundle where the system store is incomplete.

```bash
git clone https://github.com/crytomato529/yokogawa-download-library.git
cd yokogawa-download-library
python scripts/manual_watch.py plan --config references/manual-watch.example.json --out web-query-plan.json
```

Have an agent execute the plan and export fresh results as `web-results.json` using the [result schema](references/manual-watch.md), then run:

```bash
python scripts/manual_watch.py run --config references/manual-watch.example.json --root manual-library --web-results web-results.json
```

The default downloads all accessible PDF candidates. Omit `--limit` and `--max-results` in normal collection: they are smoke-test caps, not rate limits. Other official item types stay in the catalog; `download_formats` can expand downloads. Reuse a stable output root outside the skill installation.

For standalone searches, `--web-provider tavily` can replace `--web-results`, with `TAVILY_API_KEY` in the process environment. Service credits may apply. Imported results need no separate key; the standalone Tavily backend was not live-tested with a dedicated key this round. Never commit credentials.

## Refresh Or Resume

Continue saved downloads without searches:

```bash
python scripts/manual_watch.py resume --config references/manual-watch.example.json --root manual-library
```

Check existing URLs for silent replacements:

```bash
python scripts/manual_watch.py resume --config references/manual-watch.example.json --root manual-library --revalidate
```

For new-document discovery, generate/execute a fresh plan and call `run` with fresh results. Recovery is file-level, not byte-range resume. Verified completed files are skipped; changed files retain prior versions. Search omissions do not delete records. Imported searches older than 24 hours are stale by default.

The original single-brand commands remain available:

```bash
python scripts/yokogawa_library.py search --keyword "prosafe-rs" --out manifest.json --csv manifest.csv
python scripts/yokogawa_library.py download --manifest manifest.json --dir downloads
```

The public Yokogawa Library API supports keyword pagination. The live `prosafe-rs` search returned 265 records and 134 direct-file entries; these are dated observations, not permanent totals. Detail pages can be WAF-blocked. Direct files remain the default; `--direct-only` is retained. Only explicit `--include-detail-pages` attempts public HTML archiving. An archived page is not a downloaded manual.

## Reference Gaps

Edit product aliases, `document_numbers` and optional `seed_pages` in the [example config](references/manual-watch.example.json). Preview public links or inspect an actual local PDF:

```bash
python scripts/manual_watch.py discover --config references/manual-watch.example.json --out public-links.json
python scripts/manual_references.py --brand yokogawa --pdf manual.pdf --catalog manifest.json --out reference-gaps.json
```

Inspection defaults to 40 pages and 100 identifiers; `--max-pages 0` scans all pages. No OCR is performed. Leads can include the source document itself, other products, languages and legacy releases. Review before launching searches; an unmatched reference is not a confirmed missing manual. See [deep collection](references/deep-collection.md) for sources and boundaries.

## Files And Indexes

Naming: `Document type - Document number - Document name - Version.extension`. Unknown fields are omitted, collisions preserve separate files, and empty/HTML/challenge/invalid-signature responses cannot complete.

| Output | Purpose |
| --- | --- |
| `catalog.json` / `catalog.csv` | Accumulated records, source and observation dates |
| `download-manifest.json` / `downloads/` | Candidates, files, atomic state and errors |
| `runs/` / `latest-report.json` | Discovery evidence, coverage and failures |
| `latest-resume-report.json` | Separate no-search recovery report |
| `rag-index.jsonl` | Validated current/historical file metadata, sources and hashes |
| `rag-current.jsonl` | Deduplicated current local records; known pending newer revisions excluded |

Current local does not mean latest applicable. The index does not rank releases across different URLs, languages or hardware/software versions. Classify manuals, specifications, training and marketing materials before RAG ingestion. Engineering review still needs applicable editions and source-page citations.

## Validation And Boundaries

```bash
python -B -m unittest discover -s scripts -p "test_*.py"
```

Each of the two repositories passed 54 tests before this GitHub update, including four published-CLI compatibility tests. [Validation evidence](VALIDATION.md) separates actual downloads from unresolved source restrictions. Official completeness is scoped to the query; web searches cannot establish entire-web completeness. Installation does not start a schedule, accept agreements or bypass authentication.

Load [SKILL.md](SKILL.md) for agent instructions; the skill name is `yokogawa-library`. Optional Codex UI metadata in `agents/` does not constrain other tools. Configure scheduling in the host after selecting products, cadence and output root; deterministic downloads and state handling do not require repeated model calls.
