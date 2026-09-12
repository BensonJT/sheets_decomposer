"""Overwrite Google Docs with the generated markdown so a Gem linked to them stays current.

Docs API only (scope `documents`). Each push: read the doc's end index, delete
everything, insert the new text at index 1. Markdown arrives as plain text, which
is what the Gem reads anyway.
"""
from __future__ import annotations

import re
from pathlib import Path

DOC_URL = re.compile(r"/document/d/([A-Za-z0-9_-]+)")


def doc_id(url_or_id: str) -> str:
    m = DOC_URL.search(url_or_id)
    return m.group(1) if m else url_or_id.strip()


def replace_doc_text(docs, document_id: str, text: str) -> dict:
    doc = docs.documents().get(documentId=document_id, fields="title,body(content(endIndex))").execute()
    end = doc["body"]["content"][-1]["endIndex"]
    requests = []
    if end > 2:  # doc has content beyond the trailing newline
        requests.append({"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end - 1}}})
    requests.append({"insertText": {"location": {"index": 1}, "text": text}})
    docs.documents().batchUpdate(documentId=document_id, body={"requests": requests}).execute()
    return {"title": doc.get("title"), "chars": len(text)}


def push_folder(out_folder: Path, gem_doc: str, report_doc: str, auth_mode: str = "oauth") -> list[str]:
    from .auth import build_docs

    docs = build_docs(auth_mode)
    done = []
    for fname, target in (("gem_context.md", gem_doc), ("report.md", report_doc)):
        if not target:
            continue
        text = (out_folder / fname).read_text()
        r = replace_doc_text(docs, doc_id(target), text)
        done.append(f"{fname} -> '{r['title']}' ({r['chars']:,} chars)")
    return done
