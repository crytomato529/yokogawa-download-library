# Recurring manual collection / 定期搜集产品手册

This workflow is vendor-neutral Python 3.10+ plus this package's public-library adapter. It works with Codex, Claude Code, other agents, or a scheduler. It needs no browser clicks. Use a stable user-owned output directory outside the skill installation.

## Brand routing and network reliability

`--brand yokogawa|schneider|honeywell|siemens` selects a profile in `brand-profiles.json`; the original brand skills retain their default. Yokogawa/Schneider have native API adapters. Honeywell/Siemens currently use web-search discovery only and report `official_enumeration: "not_implemented"`, not a full manufacturer-library count. Use separate roots or product IDs per brand; an existing catalog cannot be silently relabeled as another manufacturer. The installed `industrial-manual-library` skill includes product examples for cross-brand collection.

Configured proxies are honored by default. In `LIBRARY_NETWORK_MODE=auto`, a connection refusal from a loopback proxy allows one direct route retry for this process; the original request is cloned so proxy mutation/credentials do not carry into the direct retry. Remote HTTP 403/567 never triggers this fallback. `LIBRARY_NETWORK_MODE=default` requires the configured route; `direct` explicitly selects direct connections. No system proxy settings are changed.

TLS verification stays enabled. If the system CA store cannot validate a chain, an installed `certifi` bundle can be tried once; optional installation is `python -m pip install --upgrade certifi`. Explicit `SSL_CERT_FILE`/`SSL_CERT_DIR` settings are respected. If no trusted bundle succeeds, the file remains failed. Reports expose network mode and trust-store choice, not keys or proxy credentials.

Verified metadata updates at an already known URL are merged into the existing item, preserving identity and allowing revision changes to trigger downloads. Unverified web snippets cannot replace authoritative metadata. Each executed query may carry `searched_at`; a new batch timestamp cannot make an older individual query fresh. Unchanged-file revalidation preserves `downloaded_at` and updates `checked_at`.

## Search coverage

Read [deep-collection.md](deep-collection.md) for official seed pages, no-search resume, PDF reference extraction and RAG revision boundaries. New product fields are `seed_pages` and `document_numbers`. `run` includes configured seed discovery; `discover` previews it; `resume` only uses saved catalogs without refreshing search evidence. Queries include regional/document hosts from the brand profile.

1. Enumerate every page of the official library for every configured product alias. Retain all official results, including non-manual and restricted items, so filtering is auditable.
2. Generate web queries using `plan`. Search the manufacturer's global/regional sites, official attachment hosts, document-number queries, then unrestricted PDF/manual searches and public distributor mirrors. Use English and Chinese terms; add other languages when requested.
3. For a deep collection, read the PDF's document guide, related-documents section and references. Extract exact manual numbers, hardware/software release identifiers, search them, and add these durable queries to `extra_queries`. Do not invent document numbers or guess undocumented file URLs.
4. Search engines return bounded samples. A completed query plan is not proof of entire-web completeness. Do not apply recent-date filters to the only search: newly indexed historical manuals can be important. A version/date in a search snippet is not the file's version; leave metadata blank unless confirmed from the PDF or official document page.

API pagination failures, query truncation and failed web searches remain visible. Missing results mean "not observed", never confirmed withdrawal; keep previously downloaded versions. Yokogawa product-page HTML can return HTTP 204 from WAF, so use direct PDFs for the knowledge base. Schneider public-library API access can be blocked (HTTP 567 observed in validation); continue collecting independently verified public search results and report incomplete official enumeration. Login/agreement-protected materials go to the restricted list.

## Configuration and commands

Start from `references/manual-watch.example.json`. Each product has a stable safe `id`, `keywords` (product aliases), optional `extra_queries` (including known manual numbers), and `library_args` passed to the official `search` command. Extend aliases/document-number queries under the same ID; reports record the scope change. Use a different ID for changed official locale/filters. The watcher downloads PDFs by default while retaining all official item types in its catalog. Set `download_formats: ["pdf", "zip"]` if the user also wants public ZIP packages. The first normal run downloads all accessible files in the chosen formats; omit `--limit` and `--max-results`.

```bash
python scripts/manual_watch.py plan --config watch.json --out web-query-plan.json
python scripts/manual_watch.py run --config watch.json --root manual-library --web-results web-results.json
```

Run each planned query using the available web-search tool, then save portable JSON with the actual `generated_at` UTC timestamp. `executed_queries` contains only queries actually executed, including zero-result queries. Every result needs a `product` matching the config and its real `query`. Imported results older than 24 hours or without a valid timestamp are reported as stale; downloads may still resume, but this is not a fresh full search. Change `--web-max-age-hours` when deliberately using a different freshness window. Generate fresh web results each scheduled collection, rather than replaying an old export. Example schema (replace the illustrative URL with a discovered source):

```json
{
  "generated_at": "2026-10-11T00:00:00Z",
  "provider": "available-search-tool",
  "executed_queries": [{"product": "prosafe-rs", "query": "ProSafe-RS manual", "searched_at": "2026-10-11T00:00:00Z"}],
  "results": [{
    "product": "prosafe-rs",
    "query": "ProSafe-RS manual",
    "url": "https://example.org/public-manual.pdf",
    "title": "ProSafe-RS hardware manual",
    "document_type": "Instruction Manual",
    "document_number": "",
    "version": "",
    "verified": false
  }],
  "errors": []
}
```

Search-result URLs ending in `.pdf` on official hosts can enter the candidate download list if product relevance is supported. Non-PDF pages remain evidence requiring inspection: follow their public PDF links with the search/fetch tool and add a new result with the source page `url`, actual `download_url`, `file_ext: "pdf"`, and `verified: true`. This also supports Schneider's extensionless `/files?...` endpoint. Set `verified: true` only after checking product/document identity from the source, especially for third-party mirrors. Content signatures validate the file format, not authenticity. Unknown type defaults to `Document`; unknown version/number is omitted. Never mark a challenge, login page, sales page, or a snippet as a verified manual.

For a standalone scheduled process, use the optional Tavily HTTP backend:

```bash
python scripts/manual_watch.py run --config watch.json --root manual-library --web-provider tavily
```

Set `TAVILY_API_KEY` in the process environment; never put secrets in config/output/skill files. It uses bounded basic searches (`--web-max-results 10`, configurable 1-20) and records individual failures. The script requires no paid API when results are exported by another search tool. Tavily live execution requires the user's available key; do not claim it was tested if only import mode was tested. API: https://docs.tavily.com/documentation/api-reference/endpoint/search

For lightweight resume, use `manual_watch.py resume` with the same config/root and no web-search flags. For periodic checks of files silently replaced at the same URL, add `--revalidate`; HTTP ETag/Last-Modified reduce traffic where supported, otherwise the response is fetched and hashed. Identical bytes are skipped. Changed versions/content are saved separately so older files survive. `--search-only` skips downloads on `run`. `--limit 2` and `--max-results 3` are tests only; reports mark truncated coverage.

## Outputs and monitoring

- `<product>/catalog.json` and `catalog.csv`: accumulated known items with `first_seen`, `last_seen`, `seen_this_run`, source tier and original metadata. Search omissions do not delete records.
- `<product>/download-manifest.json`: file-format-filtered candidate manifest; default PDF only. Catalog counts include non-file/other-format items and are not downloaded-file counts.
- `<product>/runs/<UTC stamp>/`: official query snapshots, previous catalog, web evidence, executed query list and per-run report.
- `<product>/downloads/`: named files, atomic state, persistent retryable errors and `download_report.json`. Empty responses, invalid signatures and HTML masquerading as files cannot be completed. SHA-256 is checked before trusting existing files.
- `<product>/latest-report.json` and root `latest-report.json`: added/changed/not-observed lists, each source's status, query coverage, review/restricted counts and download status.
- `<product>/rag-index.jsonl`: validated current and preserved historical file paths, hashes, document metadata and sources for later local parsing/embedding. Hash-identical rows have `duplicate_of`; this deduplicates RAG ingestion, not network transfers. A corpus index does not itself create a RAG service or decide the newest technically applicable revision. Limited smoke runs are marked `test_limited` in reports.

Exit codes: `0` planned sources succeeded, `2` partial sources/coverage/download failures (inspect report), `1` config/runtime error. One root lock prevents overlapping runs; after an abrupt kill inspect the recorded PID before removing a stale lock. Do not delete an active run's lock. Ordinary exceptions/interruption release it. Atomic replace protects state/catalog saves from interrupted writes.

A product-level runtime error is saved in its latest report and the remaining configured products still run. The root report retains both failures and successes and exits `1`; an individual damaged state file cannot silently prevent every later product from being checked.

When the user requests a real schedule, choose the schedule with them or use an explicitly supplied cadence, and attach the same config/root to their scheduler. Keep routine unchanged runs quiet and notify on new/changed manuals, failures or required review. Updating this skill does not create a schedule automatically. On Codex use its supported automation tool; outside Codex use the host's scheduler. Avoid any model call for already deterministic download/state operations.

中文要点：官网全量检索 + 全网补搜 + 累积清单 + 版本/校验值比对 + 断点续传。首次全量，后续补齐；限量参数仅用于测试。官网接口失败、搜索引擎覆盖不足、登录限制都要如实报告。只把真实下载文件及其可追溯元数据交给后续 RAG，不把网页条目数量当成已下载手册数量。
