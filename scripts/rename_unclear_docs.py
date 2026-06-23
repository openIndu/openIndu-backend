"""Detect meaningless OSS doc filenames, extract title from PDF content, rename.

Usage:
    python scripts/rename_unclear_docs.py            # dry-run (preview only)
    python scripts/rename_unclear_docs.py --write    # rename in OSS + update DB
"""

import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz  # PyMuPDF

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.document import Document
from app.services.oss_service import oss_service

# ── Meaningless detection ────────────────────────────────────────────────────

def _meaningless_reason(stem: str) -> str:
    if re.search(r"[一-鿿぀-ヿ]", stem):
        return ""
    meaningful_en = re.search(
        r"\b(manual|guide|user|system|program|install|setup|catalog|datasheet|"
        r"spec|handbook|reference|overview|operation|hardware|software|function)\b",
        stem.lower(),
    )
    if meaningful_en:
        return ""
    if re.match(r"^[0-9a-f]{16,}$", stem.lower()):
        return "hex-hash"
    if re.search(r"\d{10,}", stem):
        return "timestamp"
    clean = re.sub(r"[-_\s\d]", "", stem).lower()
    if clean in {"pdf", "doc", "file", "a", "ab", "a5", "a4", "a6", "a3", "p", "c", "b"}:
        return "too-generic"
    if re.match(r"^[a-zA-Z]{2,4}\d{3,}[a-zA-Z0-9_-]*$", stem) and len(stem) <= 20:
        return "internal-code"
    if re.search(r"[｡-ﾟ゠-ヿ]", stem) and not re.search(r"[一-鿿]", stem):
        return "garbled-katakana"
    alpha_only = re.sub(r"[^a-zA-Z]", "", stem)
    if len(alpha_only) <= 3 and not re.search(r"[一-鿿]", stem):
        return "too-short"
    return ""


# ── PDF title extraction ─────────────────────────────────────────────────────

_BAD_TITLE_RE = re.compile(
    r"\.(fm|indd|doc|docx|psd|ai|qxd|idml)$"   # DTP source file artifacts
    r"|^\d{3,}_[A-Z]\d"                          # page ref like 15800_H1_H4
    r"|^[\d_\-]{4,}$"                            # pure numbers/dashes
    r"|^封面"                                     # cover-page label
    r"|^[\x00-\x1f]"                             # control characters
    r"|[．…]{3,}"                                 # dotdotdot (TOC entries)
    r"|\.{3,}",                                  # TOC "....." entries
    re.IGNORECASE,
)

_CHAPTER_NOISE_RE = re.compile(
    r"^(第.篇|第.章|附录|目录|索引|Contents|Index|Chapter\s+\d|\d+\s*[．.]\s*\w"
    r"|非常感谢|感谢您|ご購入|お買い上げ|Thank you for"
    r"|Specifications\s*[\[\(]|Specifications$)",
    re.IGNORECASE,
)

# Japanese katakana/hiragana heavy text is not a useful Chinese doc title
_KATAKANA_HEAVY_RE = re.compile(r"^[ｦ-ﾟ゠-ヿぁ-ん\s\d\-・。]+$")


def _is_bad_title(t: str) -> bool:
    if not t or len(t) < 4:
        return True
    if _BAD_TITLE_RE.search(t):
        return True
    if _CHAPTER_NOISE_RE.match(t):
        return True
    if re.match(r"^[\d\s\-\/\.]+$", t):
        return True
    if _KATAKANA_HEAVY_RE.match(t):
        return True
    # Text that starts with Chinese punctuation → mid-sentence fragment
    if re.match(r"^[，。、；：！？…（）【】]", t):
        return True
    # Leading 1-2 chars then full-width punctuation → sentence tail fragment
    if re.match(r"^.{1,2}[，、。；]", t):
        return True
    # Starts with a verb/instruction → description sentence, not a title
    if re.match(r"^(说明|介绍|描述|讲述|本手册|本书|请在|请仔细|请务必|注意|警告|危险)", t):
        return True
    # Starts with bullet/symbol → safety notice or list item
    if re.match(r"^[●•▪►◆◇■□★☆①②③]", t):
        return True
    # Contains 3+ ideographic commas → list/description text, not a title
    if t.count("、") >= 3 or t.count("，") >= 3:
        return True
    # Japanese-only word "仕様" (specification in Japanese, not Chinese) → Japanese doc
    if "仕様" in t or "仕掛" in t:
        return True
    # Any hiragana → Japanese text (Chinese docs don't use hiragana)
    if re.search(r"[ぁ-ん]", t):
        return True
    # Any fullwidth katakana → Japanese text (Chinese-market docs never use katakana)
    if re.search(r"[ァ-ヿ]", t):
        return True
    # Text ending with Chinese period → complete sentence, not a title
    if t.endswith("。") or t.endswith("．"):
        return True
    # 3+ isolated single uppercase letters → spec-table cell artifact ("D – H B 2")
    if len(re.findall(r"(?<!\w)[A-Z](?!\w)", t)) >= 3:
        return True
    return False


def _dedup_title(t: str) -> str:
    """Remove immediately repeated phrases."""
    words = t.split()
    n = len(words)
    # Remove trailing repeat (last N/2 words == first N/2 words)
    for half in range(n // 2, 0, -1):
        if words[:half] == words[n - half:]:
            t = " ".join(words[:half])
            break
    # Remove exact duplicate standalone words (keep first occurrence)
    words = t.split()
    seen: set[str] = set()
    deduped: list[str] = []
    for w in words:
        if w not in seen:
            deduped.append(w)
            seen.add(w)
    # Remove standalone words that are substrings of longer already-present compounds
    final: list[str] = []
    for w in deduped:
        is_sub = any(w in other and w != other for other in deduped)
        if not is_sub:
            final.append(w)
    t = " ".join(final)
    # Char-level repeat
    mid = len(t) // 2
    if len(t) >= 8 and t[:mid].strip() == t[mid:].strip():
        t = t[:mid].strip()
    return t.strip()


def _post_process(title: str, brand_folder: str, orig_stem: str) -> str:
    """Final cleanup and fallback logic."""
    title = _dedup_title(title)
    # If still too generic (only 2 unique words and all Chinese and < 10 chars), prepend brand
    zh_chars = sum(1 for c in title if "一" <= c <= "鿿")
    if zh_chars > 0 and len(title) <= 10 and brand_folder:
        title = f"{brand_folder} {title}"
    # Limit length but keep meaningful part
    title = title[:100].strip()
    return title


def _sanitize(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|&]', " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:120]


def _font_candidates(doc, page_count: int = 3) -> list[tuple[float, str]]:
    """Collect (font_size, text) pairs from first N pages."""
    candidates: list[tuple[float, str]] = []
    for page_num in range(min(page_count, doc.page_count)):
        page = doc[page_num]
        for b in page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]:
            if b.get("type") != 0:
                continue
            for line in b.get("lines", []):
                merged = " ".join(s.get("text", "").strip() for s in line.get("spans", []))
                size = max((s.get("size", 0) for s in line.get("spans", [])), default=0)
                merged = merged.strip()
                if len(merged) >= 4 and not _is_bad_title(merged):
                    candidates.append((size, merged))
    return candidates


def _extract_title(pdf_bytes: bytes, brand_folder: str = "", orig_stem: str = "") -> str:
    """Return the best human-readable title for this PDF."""
    doc = fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf")

    # 1. PDF metadata title (skip if looks like a DTP artifact)
    meta_title = (doc.metadata or {}).get("title", "").strip()
    if meta_title and not _is_bad_title(meta_title) and len(meta_title) > 4:
        doc.close()
        return _post_process(_sanitize(meta_title), brand_folder, orig_stem)

    # 2. Largest-font text across first 3 pages
    candidates = _font_candidates(doc, page_count=3)
    if candidates:
        candidates.sort(key=lambda x: (-x[0], -len(x[1])))
        # Among top-5 largest, prefer the one with most Chinese/meaningful chars
        top5 = candidates[:5]
        top5.sort(key=lambda x: -sum(1 for c in x[1] if "一" <= c <= "鿿"))
        best = top5[0][1]
        # Merge with next line if it looks like a continuation
        if len(top5) > 1 and len(best) < 20:
            second = top5[1][1]
            if not _is_bad_title(second) and not _KATAKANA_HEAVY_RE.match(second):
                best = f"{best} {second}"
        doc.close()
        return _post_process(_sanitize(best), brand_folder, orig_stem)

    # 3. First meaningful plain-text lines
    title_lines: list[str] = []
    for page_num in range(min(3, doc.page_count)):
        for line in doc[page_num].get_text().splitlines():
            line = line.strip()
            if line and not _is_bad_title(line) and len(line) >= 5:
                title_lines.append(line)
            if len(title_lines) >= 2:
                break
        if title_lines:
            break
    if title_lines:
        doc.close()
        combined = " ".join(title_lines[:2])
        return _post_process(_sanitize(combined), brand_folder, orig_stem)

    doc.close()

    # 4. Fallback: brand + original stem cleaned up
    clean_stem = re.sub(r"[｡-ﾟ゠-ヿぁ-ん]", "", orig_stem)  # strip kana
    clean_stem = re.sub(r"[_\-]", " ", clean_stem).strip()
    if brand_folder:
        return _sanitize(f"{brand_folder} {clean_stem}")
    return _sanitize(clean_stem) or "未知文档"


# ── Main ─────────────────────────────────────────────────────────────────────

def main(write: bool = False) -> None:
    mode_label = "WRITE" if write else "DRY-RUN"
    print(f"=== rename_unclear_docs [{mode_label}] ===\n")

    db = SessionLocal()

    # Build DB lookup: oss_key → Document
    db_docs: dict[str, Document] = {
        d.oss_key: d
        for d in db.query(Document).filter(Document.oss_key.like("doc/%")).all()
    }

    all_objs = oss_service.list_objects("doc")
    pdfs = [
        o for o in all_objs
        if o["key"].lower().endswith(".pdf") and "/_index/" not in o["key"]
    ]

    renames: list[tuple[str, str, Document | None]] = []  # (old_key, new_key, doc)

    for obj in pdfs:
        key = obj["key"]
        parts = key.split("/")
        filename = parts[-1]
        stem = filename.rsplit(".", 1)[0]
        reason = _meaningless_reason(stem)
        if not reason:
            continue

        prefix = "/".join(parts[:-1])  # e.g. doc/信捷/PLC
        print(f"[{reason}] {key}")

        # Download PDF (limited to first 5 MB for speed if large)
        print(f"  Downloading ({obj['size'] // 1024} KB)…", end=" ", flush=True)
        try:
            resp = oss_service.client.get_object(Bucket=settings.OSS_BUCKET, Key=key)
            pdf_bytes = resp["Body"].read()
        except Exception as e:
            print(f"FAILED: {e}")
            continue
        print("done")

        title = _extract_title(pdf_bytes, brand_folder=parts[1], orig_stem=stem)
        # For garbled-katakana files (Japanese catalog), only accept title if it has Chinese chars
        if reason == "garbled-katakana" and title:
            zh_chars = sum(1 for c in title if "一" <= c <= "鿿")
            if zh_chars < 4:
                # Fall back to brand + cleaned stem (strips halfwidth kana from original name)
                clean_stem = re.sub(r"[｡-ﾟ゠-ヿぁ-ん]", "", stem)
                clean_stem = re.sub(r"[_\-]", " ", clean_stem).strip()
                title = _sanitize(f"{parts[1]} {clean_stem}") if parts[1] else _sanitize(clean_stem)
                print(f"  Warning: Japanese catalog, using stem fallback: {title!r}")
        if not title:
            title = f"{parts[1]}-文档"  # last-resort fallback
            print(f"  Warning: no title extracted, using fallback: {title!r}")
        else:
            print(f"  Extracted title: {title!r}")

        new_filename = f"{title}.pdf"
        new_key = f"{prefix}/{new_filename}"

        if new_key == key:
            print("  → No change needed\n")
            continue

        # Avoid collision with existing OSS objects
        try:
            oss_service.client.head_object(Bucket=settings.OSS_BUCKET, Key=new_key)
            # Already exists — append suffix
            base, ext = new_key.rsplit(".", 1)
            new_key = f"{base} (2).{ext}"
            print(f"  ⚠ Collision detected, using: {new_key.split('/')[-1]!r}")
        except Exception:
            pass  # 404 = does not exist, good

        print(f"  → Rename: {filename!r}")
        print(f"         → {new_filename!r}\n")
        renames.append((key, new_key, db_docs.get(key)))

    if not renames:
        print("Nothing to rename.")
        db.close()
        return

    print(f"\n{'='*60}")
    print(f"Total to rename: {len(renames)}")

    if not write:
        print("\n[DRY-RUN] No changes applied.")
        db.close()
        return

    print("\nApplying renames…")
    ok = 0
    for old_key, new_key, doc in renames:
        try:
            # OSS: copy to new key then delete old
            oss_service.client.copy_object(
                Bucket=settings.OSS_BUCKET,
                CopySource={"Bucket": settings.OSS_BUCKET, "Key": old_key},
                Key=new_key,
            )
            oss_service.client.delete_object(Bucket=settings.OSS_BUCKET, Key=old_key)
            print(f"  OSS ✓  {old_key} → {new_key}")

            # DB: update oss_key, filename, original_name
            if doc:
                new_filename = new_key.split("/")[-1]
                doc.oss_key = new_key
                doc.filename = new_filename
                doc.original_name = new_filename
                print(f"  DB  ✓  id={doc.id} updated")
            else:
                print(f"  DB  ⚠  no DB record found for {old_key}, skipped")
            ok += 1
        except Exception as e:
            print(f"  ERROR: {old_key}: {e}")

    db.commit()
    db.close()
    print(f"\nDone: {ok}/{len(renames)} renamed successfully.")


if __name__ == "__main__":
    write_mode = "--write" in sys.argv
    main(write=write_mode)
