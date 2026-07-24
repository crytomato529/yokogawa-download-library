---
name: yokogawa-library
description: Search Yokogawa Electric's public Library at https://www.yokogawa.com/library/ by keyword or category, export complete result manifests, compare old/new manifests, and incrementally archive accessible public materials with normalized filenames. Use when Codex needs Yokogawa product manuals, specifications, guides, technical documents, bulletins, PDFs, ZIPs, software downloads, detail-page archives, or recurring synchronization of Yokogawa library search results without browser clicking.
---

# Yokogawa Library

Use the bundled script for deterministic access to Yokogawa's public library search API. Do not automate browser clicks for normal searches; the website's Angular app calls the same JSON endpoint directly.

## Core Workflow

1. Search by keyword and save a manifest:

```bash
python scripts/yokogawa_library.py search --keyword "prosafe-rs" --out manifest.json
```

2. Archive accessible public items from a manifest:

```bash
python scripts/yokogawa_library.py download --manifest manifest.json --dir downloads
```

3. Compare a previous manifest with a new manifest:

```bash
python scripts/yokogawa_library.py compare --old old_manifest.json --new new_manifest.json --out diff.json
```

4. Search and archive in one run. Use this for normal full synchronization:

```bash
python scripts/yokogawa_library.py sync --keyword "prosafe-rs" --manifest manifest.json --dir downloads
```

Do not pass `--limit` for normal first-time runs. The first run should refresh the full manifest and archive every accessible public item. If the run is interrupted, rerun the same command; the state file makes it skip completed files/pages and continue the unfinished work.

Use `--limit N` only for smoke tests, temporary throttling, or controlled validation. The limit means "download at most N new accessible items in this run"; already completed items do not consume the limit.

## Search Notes

- The script calls `https://yc3.yokocms.com/api/technical-library/`.
- Default region is Global, `region_id=1`.
- Keyword searches use relevance sort by default. Use `--sort d` for the site's default/date style sort.
- Category filters can be passed as comma-separated IDs:
  - `--types` for library/resource type IDs (`t`)
  - `--products` for product/category IDs (`p`)
  - `--industries` for industry IDs (`i`)
- For broad or recurring jobs, keep the manifest JSON as the source of truth. Every `sync` refreshes the full manifest first. If a later search reports 274 items instead of 273, the manifest is replaced with the new full list and a `_diff.json` file records added, removed, and changed items.
- Manifest summary fields include `count`, `direct_download_count`, `detail_page_count`, `accessible_archive_count`, and `manual_required_count`.

## Download Behavior

- Download public direct file URLs discovered in search results.
- Save public detail-page results as `.html` archives by default. Use `--direct-only` when only original direct-download files should be saved.
- Skip locked, login-required, and software-agreement results unless a future workflow explicitly handles authentication or agreements.
- Omit `--limit` for production/full downloads. Use `--limit N` only for validation runs so a test does not pull the full library.
- The downloader records state in `.yokogawa_download_state.json` inside the download directory and skips already downloaded files when URL and local file metadata match.
- Use `--force` to redownload known files.

## Filename Rule

Save downloaded files and page archives using:

```text
<Document Type> - <Document Number> - <Document Name> - <Version>.<ext>
```

- Document type comes from Yokogawa's category, such as `General Specification`, `Instruction Manual`, `Technical Information`, `Application Note`, `White Paper`, `Brochure`, `Certificate`, `Drawing`, or `Software`.
- Document number comes from the `code` field when present.
- Version uses `Edition <number>` when the item has an edition; otherwise it falls back to Yokogawa's displayed update date.
- If two items produce the same filename, append the item key to the duplicate file only.

## Validation Example

For a quick smoke test, run:

```bash
python scripts/yokogawa_library.py sync --keyword "prosafe-rs" --manifest prosafe-rs_manifest.json --dir prosafe-rs_downloads --limit 2
```

Expect the search to report hundreds of results, while this validation command saves only two new accessible items. For real use, remove `--limit`; rerunning the same full command after an interruption fills in the remaining accessible items and skips everything already completed.
