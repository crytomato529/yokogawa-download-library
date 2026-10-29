---
name: yokogawa-library
description: Collect Yokogawa product manuals and specifications from the public Library API and supplemental web searches. Use for complete official-library manifests, product aliases and manual-number searches, recurring collection, version comparison, resumable downloads, and traceable local RAG corpus indexes, especially ProSafe-RS and CENTUM. Portable Python scripts work with Codex, Claude Code and other agents without browser clicking.
---

# Yokogawa Library

Use Python 3.10+ scripts for search, download and state handling. Run from this skill directory or resolve script paths against it. Keep collection output in a stable user-owned directory outside the skill. Read [references/manual-watch.md](references/manual-watch.md) for multi-product, web-wide or recurring collection; use [the example config](references/manual-watch.example.json) to start.

## Recurring product-manual workflow

Use `scripts/manual_watch.py` to combine complete official-library pagination with supplemental web queries. Search product aliases, official global/regional sites and attachment hosts, then public third-party sources. Inspect document guides/reference lists for additional exact document-number queries. Export the agent's web search results to the documented portable JSON format; import them for deterministic downloads. An optional Tavily backend supports scheduler-only runs.

```bash
python scripts/manual_watch.py plan --config watch.json --out web-query-plan.json
python scripts/manual_watch.py run --config watch.json --root manual-library --web-results web-results.json
```

The watcher downloads PDFs by default and retains all official item types in the catalog; `download_formats` config can expand formats. The first normal run downloads every accessible candidate; subsequent runs compare metadata, resume missing/failed files and keep older files. Do not pass `--limit` or `--max-results` unless testing. Add `--revalidate` for periodic same-URL content checks. Report official counts, web freshness/coverage, added/changed manuals, downloaded files, restricted/review items and failed sources separately. Failed API/missing or stale web runs are partial coverage, never success or zero manuals. Do not promise entire-web completeness.

## Single official-library search

For interruption recovery use `manual_watch.py resume --config watch.json --root manual-library`; it does not repeat discovery or change observation dates. Use `run` for a fresh search. Read [deep collection](references/deep-collection.md) for official-page parsing, extensionless downloads, PDF reference-number leads and catalog gap checks. `rag-current.jsonl` is a current local ingestion subset, never proof of the latest applicable edition.

```bash
python scripts/yokogawa_library.py search --keyword "prosafe-rs" --out manifest.json --csv manifest.csv
python scripts/yokogawa_library.py download --manifest manifest.json --dir downloads --direct-only
python scripts/yokogawa_library.py compare --old old_manifest.json --new new_manifest.json --out diff.json
python scripts/yokogawa_library.py sync --keyword "prosafe-rs" --manifest manifest.json --dir downloads --direct-only
```

API: `https://yc3.yokocms.com/api/technical-library/`; default Global region `--region-id 1`, relevance `--sort r`. Resource/product/industry filters: `--types`, `--products`, `--industries` comma-separated IDs. Keep the same scope for one manifest. A truncated/incomplete refresh preserves an existing full manifest and writes `_partial.json`; `_history/` retains previous snapshots. Removed results mean not observed, not confirmed withdrawal.

## Download invariants

- Direct files are the default; `--direct-only` remains compatible. Only explicit `--include-detail-pages` enables experimental HTML archiving, which can be blocked by AWS WAF (including empty HTTP 204). HTML is not a downloaded manual; failed/challenge/empty responses must not be marked completed.
- Locked, login-required and agreement-required entries remain documented but are skipped. Do not bypass authentication or accept agreements automatically.
- `.yokogawa_download_state.json` tracks SHA-256, metadata fingerprint, HTTP validators and retryable errors. Only valid nonempty files are skipped; a new edition/date at the same URL is downloaded again. State writes are atomic. Older state without fingerprints is conservatively redownloaded once.
- `--limit N` means at most N newly downloaded items; completed items do not consume it. `--force` redownloads; `--revalidate` checks validators/content even for completed files.
- Verified web metadata can update a known URL without creating a duplicate identity. Per-query timestamps prevent stale imports from appearing fresh. A refused local proxy can use a process-local direct fallback; remote HTTP denials remain failures. Optional `certifi` repairs incomplete CA trust stores while keeping TLS validation enabled. Read the workflow reference for explicit network modes.
- Naming: `<Document Type> - <Document Number> - <Document Name> - <Version>.<ext>`. API category/code/edition provide metadata; edition uses `Edition N`. Unknown fields are omitted; date is a fallback label, not a guessed edition. Collisions receive a short key suffix and never overwrite older files.

## Validation

```bash
python scripts/yokogawa_library.py sync --keyword "prosafe-rs" --manifest test-manifest.json --dir test-downloads --direct-only --limit 2
python scripts/yokogawa_library.py download --manifest test-manifest.json --dir test-downloads --direct-only --limit 2
python scripts/test_library.py
```

The second run must skip the first two and download the next two. Test counts are live, not fixed at an old 273. Verify PDF signatures, positive sizes, state/report records and failure visibility; never infer success just from finding an output filename.
