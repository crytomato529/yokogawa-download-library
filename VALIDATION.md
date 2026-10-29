# Validation / 验收记录

## 2026-10-30 GitHub Sync

Integrated the research upgrade with the current public repository, preserving its Chinese README / English toggle. Both release checkouts passed 54 tests: the prior 50 plus four compatibility checks for the published Yokogawa default-direct behavior, explicit detail-page opt-in, conflicting flags and WAF rejection. The older `download_target_count` manifest field remains available alongside the expanded counts. Earlier dated "no GitHub push" notes describe the research stage before this separately authorized sync.

Merged code, examples, bilingual usage instructions and validation evidence only. Downloaded manuals, private history, credentials, runtime catalogs/state and bytecode are excluded.

## 2026-10-30 Research Upgrade

- 50 tests passed in this package. The same suite passed in all three installed entrypoints (150 executions, not 150 distinct scenarios).
- Yokogawa: complete 265-item search, 134 direct files; no item/metadata changes against the 2026-10-25 snapshot. A public extensionless guide was downloaded (693,929 bytes, 60 pages, edition 19) and correctly skipped on repeat. Its 111 extracted reference leads matched only 5 exact document numbers in that keyword manifest; the other 106 are review leads, not confirmed missing manuals.
- Schneider: no-search resume/revalidation of two existing PDFs returned 0 new files, 2 skips, 0 failures; catalog bytes stayed unchanged. Official pages listed QGH60283 v11 and QGH46982 v13, while the old iPortal test copy of QGH60283 was from 2019. Local FAQ fetch returned 567; the QGH46982 file endpoint returned 403 and saved no file. Do not claim newest-manual collection or full current native API access.
- Honeywell: official HTML exposed 75 link occurrences, 50 URL variants, 25 distinct PDF links after DAM flag normalization. A live 714,156-byte sample was hash-identical with/without the flag. Limited integration added 23 catalog candidates (31 accumulated), skipped the previously verified hardware reference and downloaded one 5-page product note; these are not 31 manuals. Old imported searches stayed stale despite fresh seed-page discovery.
- Siemens: optional reference inspection read 40/112 pages of the previously downloaded operating instructions and produced one identifier lead. No fresh full Siemens search or new Siemens PDF download was claimed this round.
- New guards cover refused proxy plus failed direct route, unsolicited HTTP 206, off-domain discovery redirects, empty/challenge listings, restricted links, no-search resume, multi-file metadata preservation and immutable historical RAG metadata.
- No full bulk download, new schedule or GitHub push in this round. PDF parsing is optional, regex coverage is bounded, and no OCR/latest-applicability determination is implemented.

Earlier validation follows and describes its own dates, not current API availability.

Date: 2026-10-11 (Asia/Shanghai)

- Offline regressions: 17/17 passed. Skill format validation passed.
- Live official search: ProSafe-RS returned 267 items and all 267 were enumerated.
- Supplemental web search: 3 real queries executed using the available Tavily search connector; 5 additional public-file candidates were merged. Accumulated catalog: 272 items; default PDF candidates: 139. These are item/candidate counts, not claims that 272 manuals were downloaded or that the entire web is complete.
- Live downloads were deliberately limited: first run downloaded 1 file; second run skipped that file and downloaded 1 more. Both passed SHA-256 state checks, PDF magic checks and PDF parser opening.
- Actual files: TI 32S01J30-01E, Edition 26 (4,120,882 bytes, 119 pages); Bulletin 32Q01M20-01E, Edition 4 (1,668,578 bytes, 2 pages). One technical document and one brochure validate the adapter; this is not a full manual-corpus download.
- Local RAG index exported 2 validated file records.
- Regressions cover two-then-next-two resume, completion, same-URL new metadata, HTTP conditional revalidation and changed content, same-size local corruption, filename collisions, long-title version preservation, legacy empty state, invalid PDF/HTML/204 responses, partial manifest protection, source failure, URL deduplication, query expansion, stale web results, PDF-only defaults and historical RAG versions.
- The optional standalone Tavily HTTP API backend was checked against official documentation but was not live-tested with a dedicated API key. Live supplemental searches used connector-export/import mode.
- A concrete recurring schedule has not been created. Detail-page WAF handling is covered by deterministic failure fixtures; successful file tests use public PDFs.

中文：此版不是只改提示词，脚本、状态和校验流程均已更新。官网全量清单和全网补搜经过实测；下载只取两份验证。单文件版本替换、断点继续和空页面误判都有回归检查。定时任务周期和独立搜索服务密钥尚未配置。

## 2026-10-25 Revalidation

- 26/26 offline regressions passed for this brand; 5 cross-brand regressions passed separately. Total: 57 executed test cases across the two native suites and the cross-brand suite; shared scenarios were exercised once for each native brand.
- Live native search enumerated all 265 ProSafe-RS results, including 134 direct-file candidates. Versus the 2026-10-11 native manifest: 0 added, 2 not observed, 0 changed. Omissions are not declared withdrawals. Live continuation first retained previous completed items and saved a brochure; after correcting request cloning, it saved TI 32S01J10-01E Edition 22 while skipping 3 completed files, with 0 current failures. Test downloads remained limited; the accumulated local test state now contains 4 files.
- Real network testing exposed urllib request mutation after an unavailable loopback proxy; the direct retry now uses the original request and does not carry proxy-only headers. TLS fallback uses a trusted CA bundle without disabling verification or retrying HTTP access denials.
- Same-URL verified web revision updates and per-query stale timestamps have dedicated regressions. Runtime failure of one product no longer aborts later products. Existing download timestamps are retained on unchanged revalidation.
- Cross-brand discovery was exercised with real public Honeywell/Siemens PDFs. Their current source mode is `web_search`; official-library enumeration is `not_implemented`. The optional standalone Tavily HTTP backend still has no dedicated API-key live test; connector-export/import mode was used.
