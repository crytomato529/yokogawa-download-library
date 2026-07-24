# Yokogawa Download Library

Language / 语言: [中文](README.md) | **English**

A general-purpose synchronization tool for Yokogawa Electric library materials. It searches Yokogawa's public library by keyword or category, exports complete manifests, compares old and new manifests, and incrementally archives accessible public materials. The core is a standalone Python command-line script: it does not require Codex and does not rely on browser clicking. Claude Code, Cursor, other AI agents, automation scripts, or a human terminal workflow can all use it directly.

`SKILL.md` is only an optional Codex adapter. The reusable tool is `scripts/yokogawa_library.py`.

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
