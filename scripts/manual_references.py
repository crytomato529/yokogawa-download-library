"""Extract document-number leads from a local PDF with page evidence; never guess versions."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from library_common import atomic_json, configure_console


PATTERNS = {
    "yokogawa": r"\b(?:IM|GS|TI)\s*\d{2}[A-Z]\d{2}[A-Z]\d{2}-\d{2}[A-Z][A-Z0-9]*\b",
    "schneider": r"\b(?:EIO\d{10}|(?:QGH|NHA|HRB|S1A|S1B|NVE|NNZ)\d{5})\b",
    "honeywell": r"\bEP[-\s]?(?:SM|SC)\s*[.\-]\s*(?:MAN|DOC|SPEC)\s*[.\-]\s*\d{4,6}\b",
    "siemens": r"\bA5E\d{8}(?:-[A-Z]{2})?\b",
}


def extract(text, brand):
    normalized = text.replace("\u2011", "-").replace("\u2013", "-").replace("\u00ad", "")
    matches = []
    for found in re.finditer(PATTERNS[brand], normalized, re.I):
        value = re.sub(r"\s+", "", found.group()).upper()
        if brand == "yokogawa":
            value = value[:2] + " " + value[2:]
        elif brand == "honeywell":
            value = re.sub(r"^EP-?", "EP-", value)
            value = re.sub(r"(SM|SC)[.-](MAN|DOC|SPEC)[.-]", r"\1.\2.", value)
        excerpt = " ".join(normalized[max(0, found.start() - 55):found.end() + 100].split())
        matches.append((value, excerpt))
    return matches


def inspect_pdf(path, brand, max_pages=40, max_references=100):
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("PDF inspection needs optional pypdf or PyMuPDF; normal collection needs neither") from exc
        document = fitz.open(path)
        if document.needs_pass:
            document.close()
            raise ValueError("Password-protected PDF requires review")
        total = len(document)
        get_text = lambda index: document[index].get_text()
        close = document.close
    else:
        document = PdfReader(str(path))
        if document.is_encrypted and not document.decrypt(""):
            raise ValueError("Password-protected PDF requires review")
        total = len(document.pages)
        get_text = lambda index: document.pages[index].extract_text() or ""
        close = lambda: None
    references, errors = {}, []
    examined = min(total, max_pages) if max_pages else total
    text_pages, overflow = 0, False
    try:
        for index in range(examined):
            try:
                text = get_text(index)
            except Exception as exc:
                errors.append({"page": index + 1, "error": str(exc)})
                continue
            text_pages += bool(text.strip())
            for number, excerpt in extract(text, brand):
                if number not in references and len(references) >= max_references:
                    overflow = True
                    continue
                record = references.setdefault(number, {"document_number": number, "pages": [], "excerpt": excerpt,
                    "query": '"' + number + '"', "status": "unverified_search_lead"})
                if index + 1 not in record["pages"]:
                    record["pages"].append(index + 1)
    finally:
        close()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"source_pdf": str(path.resolve()), "sha256": digest.hexdigest(), "brand": brand,
            "total_pages": total, "examined_pages": examined, "text_pages": text_pages,
            "page_limit_reached": examined < total, "reference_limit_reached": overflow,
            "errors": errors, "references": list(references.values()),
            "note": "Leads may include this document itself and unrelated references. Review before adding document_numbers; no edition or applicability inferred."}


def compare_catalog(result, catalog):
    normalize = lambda value: re.sub(r"[^A-Z0-9]", "", str(value).upper())
    known = {}
    for item in catalog.get("items", []):
        number = normalize(item.get("code") or item.get("reference") or "")
        if number:
            known.setdefault(number, []).append(item.get("key") or item.get("id"))
    for record in result["references"]:
        matches = known.get(normalize(record["document_number"]), [])
        record["catalog_keys"] = matches
        record["catalog_status"] = "catalogued" if matches else "not_in_catalog"
    result["catalog_comparison"] = {"catalog_generated_at": catalog.get("generated_at"),
        "catalogued": sum(bool(row["catalog_keys"]) for row in result["references"]),
        "not_in_catalog": sum(not row["catalog_keys"] for row in result["references"]),
        "note": "Exact document-number comparison only; language codes stay separate. Not in this catalog does not mean unavailable, missing from all libraries, or required by your project."}


def main(argv=None):
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--brand", required=True, choices=PATTERNS)
    parser.add_argument("--out", required=True)
    parser.add_argument("--catalog", help="Optional accumulated catalog or native manifest for exact-number gap comparison")
    parser.add_argument("--max-pages", type=int, default=40, help="0 scans all pages")
    parser.add_argument("--max-references", type=int, default=100)
    args = parser.parse_args(argv)
    if args.max_pages < 0 or args.max_references < 1:
        parser.error("max-pages must be nonnegative and max-references positive")
    result = inspect_pdf(Path(args.pdf), args.brand, args.max_pages, args.max_references)
    if args.catalog:
        compare_catalog(result, json.loads(Path(args.catalog).read_text(encoding="utf-8-sig")))
    atomic_json(Path(args.out), result)
    print(f"{len(result['references'])} document-number leads from {result['examined_pages']}/{result['total_pages']} pages")
    return 2 if result["errors"] or not result["text_pages"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
