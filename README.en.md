# Yokogawa Download Library Skill

Language / 语言: [中文](README.md) | **English**

This is a Codex skill for searching Yokogawa Electric's public Library by keyword or category, exporting complete manifests, comparing old and new manifests, and incrementally archiving accessible public materials. It calls the public JSON endpoint used by the library page instead of automating browser clicks.

## Use Cases

- Search and archive Yokogawa product materials such as `prosafe-rs`
- Export JSON/CSV manifests
- Compare two manifest snapshots for added, removed, and changed records
- Download public direct-link files such as PDFs, ZIPs, and software packages
- Save public detail pages as HTML archives
- Resume after interruption by skipping completed files/pages

## Common Commands

Search and write a manifest:

```bash
python scripts/yokogawa_library.py search --keyword "prosafe-rs" --out prosafe-rs_manifest.json --csv prosafe-rs_manifest.csv
```

Full synchronization. For a real first run, do not pass `--limit`:

```bash
python scripts/yokogawa_library.py sync --keyword "prosafe-rs" --manifest prosafe-rs_manifest.json --csv prosafe-rs_manifest.csv --dir prosafe-rs_downloads
```

Resume after interruption:

```bash
python scripts/yokogawa_library.py sync --keyword "prosafe-rs" --manifest prosafe-rs_manifest.json --csv prosafe-rs_manifest.csv --dir prosafe-rs_downloads
```

Smoke test or throttled archive run:

```bash
python scripts/yokogawa_library.py sync --keyword "prosafe-rs" --manifest prosafe-rs_manifest.json --csv prosafe-rs_manifest.csv --dir prosafe-rs_downloads --limit 2
```

Download only original direct-link files, without saving detail pages as HTML:

```bash
python scripts/yokogawa_library.py sync --keyword "prosafe-rs" --manifest prosafe-rs_manifest.json --dir prosafe-rs_downloads --direct-only
```

## Filename Rule

Saved files and page archives use:

```text
<Document Type> - <Document Number> - <Document Name> - <Version>.<ext>
```

Example:

```text
Technical Information - TI 32S01J30-01E - Explosion Protection (ProSafe-RS) - Edition 26.pdf
```

## Notes

- `--limit` is for smoke tests, temporary throttling, or resume validation. Do not use it for a real first full archive.
- Download state is stored in `.yokogawa_download_state.json` inside the download directory.
- The script skips login-required, locked, and software-agreement records unless an authorized workflow is implemented later.
