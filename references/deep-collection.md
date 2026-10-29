# Deep Collection / 深度采集

## Discovery Or Recovery

`run` refreshes native APIs, configured official pages and imported/optional-provider searches, then downloads all candidates unless test-limited. After interruption:

```bash
python scripts/manual_watch.py resume --brand yokogawa --config watch.json --root manual-library
```

`resume` reads the saved catalog, checks hashes and downloads pending/changed files. No searches or refreshed observation dates; it writes `latest-resume-report.json` without replacing discovery reports. Add `--revalidate` deliberately for file-endpoint checks. Recovery is at file granularity: an interrupted individual file restarts, not HTTP byte-range resumes. No scheduled job is created.

## Official Entry Pages

Add product `seed_pages`. `run` reads public HTML and follows explicit PDF links or one level of recognized document-detail pages. Preview without downloads:

```bash
python scripts/manual_watch.py discover --brand honeywell --config references/honeywell.example.json --out public-links.json
```

Default budget: 12 pages per product (`--seed-page-budget`), with pending/failed pages reported. No general crawl, JavaScript, login, agreement acceptance or off-domain redirects. This does not enumerate private/dynamic catalogs. Public links do not imply access to gated documents on the same page.

Yokogawa `/document/download/` and explicit query-parameter PDF filenames work without a `.pdf` URL path. Arbitrary opaque endpoints need reviewed imports with `download_url`, `file_ext: "pdf"`, `verified: true`. File validation remains mandatory. Honeywell DAM cosmetic `download=true/false` flags are normalized; version/identity parameters stay intact. No guessing file URLs.

Starting points checked 2026-10-30:

- [Yokogawa document guide](https://library.yokogawa.com/document/download/AxkHnJ89/0000029746//EN/): actual cover edition 19; indexed snippets may still say edition 18.
- [Schneider M580 FAQ](https://www.schneider-electric.cn/zh/faqs/FA412664/): 17 document-page links in search fetch; local fetch returned 567. Useful source, not a proven unrestricted local crawler.
- [Honeywell Safety Manager](https://process.honeywell.com/us/en/products/process-automation/safety-systems/safety-manager): 25 distinct public PDF links after deduplication, including product notes/case studies, not 25 manuals. Additional account documents are explicitly gated.
- [Siemens manual collection](https://support.industry.siemens.com/cs/ww/en/view/86140384): referenced by official manuals, but research fetch returned 403. Public attachments and [TIA documentation](https://docs.tia.siemens.cloud/r/simatic_s7_1500_et_200mp_manual_collection_enus_20/basic-information/s7-1500) are other discovery sources, not a new full API.

## Reference-Driven Gaps

Optional inspection needs `pypdf` or PyMuPDF; collection still uses the standard library.

```bash
python scripts/manual_references.py --brand yokogawa --pdf manual.pdf --catalog catalog.json --max-pages 0 --max-references 300 --out reference-gaps.json
```

Default: first 40 pages, 100 unique references; limits/errors are reported. No OCR. Public PDFs opening with an empty user password are supported; real passwords stop extraction. Evidence records the PDF hash, physical 1-based page and short context. Patterns cover common brand formats, not every possible identifier. Leads can include this document, other products, language variants and old releases.

`--catalog` compares explicit document numbers, normalizing punctuation/spacing but preserving language suffixes. `not_in_catalog` does not mean unavailable, required for the project or absent from every library. Review relevant leads, then add selected numbers to `document_numbers`; `plan` generates exact-number official-domain queries. Do not automatically launch hundreds of searches or verify snippets. Keep gaps for review.

## Version-Safe RAG

- `rag-index.jsonl`: validated current/historical files, sources, hashes, language, metadata-verification state. Historical rows never inherit today's document identity/version.
- `rag-current.jsonl`: nonduplicate current local records, excluding a file whose catalog revision has changed but is not downloaded. This does not rank versions across different URLs, languages or product releases.
- `latest_applicability: "not_established"` is intentional. Engineering review must check edition, hardware/software release, language, errata and cited pages.
- A valid PDF is not necessarily a manual. Classify brochures/training/case studies before engineering RAG ingestion. These indexes do not implement embeddings, retrieval or engineering approval.

Availability is not freshness: the older iPortal QGH60283 remained accessible, while its [official page](https://www.se.com/ca/en/download/document/QGH60283/) listed version 11 dated 2026-07-01. The [QGH46982 page](https://www.se.com/za/en/download/document/QGH46982/) listed version 13; the tested file endpoint returned 403, so no new file was saved. These are version leads, not downloaded latest-file evidence.

中文：正常更新用 `run`，中断续传用 `resume`；先以官方文档目录建立查缺基准，再按精选文档号补搜。网页、候选链接、文件和手册分别计数。旧链接可下载不等于最新版；方案审核必须追到适用版本和原文页码。
