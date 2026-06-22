"""Batch-rename ALL OSS doc/ PDFs to follow 品牌-类型-内容.pdf convention.

Strategy:
  - Brand and type come from the OSS folder path: doc/{brand_cn}/{type_cn}/
  - Content title comes from the current filename stem (fast path) unless
    the stem is meaningless (hex/timestamp/generic/code), in which case
    the PDF is downloaded and the title extracted via PyMuPDF.
  - Skips files already in {brand_cn}-{type_cn}-* format.

Usage:
    python scripts/batch_rebrand_docs.py           # dry-run
    python scripts/batch_rebrand_docs.py --write   # apply
"""

import io
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz  # PyMuPDF

from app.core.database import SessionLocal
from app.models.document import Document
from app.services.oss_service import oss_service
from app.core.config import settings

# ── Helpers ──────────────────────────────────────────────────────────────────

def _sanitize(name: str) -> str:
    """Remove filesystem-unsafe chars and collapse whitespace."""
    name = re.sub(r'[\\/:*?"<>|&·]', " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:120]


def _is_bad_title(t: str) -> bool:
    if not t or len(t) < 4:
        return True
    if re.search(r"\.(fm|indd|doc|docx|psd|ai)$", t, re.I):
        return True
    if re.match(r"^(第.篇|第.章|附录|目录|Contents|Index|Chapter\s*\d)", t, re.I):
        return True
    if re.match(r"^[\d\s\-\/\.]+$", t):
        return True
    if t.endswith("。") or t.endswith("．"):
        return True
    if re.match(r"^(说明|介绍|描述|请在|请仔细|注意|警告|危险|●|•|▪)", t):
        return True
    if t.count("、") >= 3 or t.count("，") >= 3:
        return True
    if re.search(r"[ぁ-ん]", t):
        return True
    if re.search(r"[ァ-ヿ]", t):
        return True
    if re.search(r"面向未来|从现在开始|非常感谢|感谢您购买|Thank you for", t):
        return True
    if re.search(r"[．…]{3,}|\.{3,}", t):
        return True
    if len(re.findall(r"(?<!\w)[A-Z](?!\w)", t)) >= 3:
        return True
    if re.match(r"^(说明|介绍|描述|请在|请仔细|本手册|本书)", t):
        return True
    if re.match(r"^[●•▪►◆◇■□★☆①②③]", t):
        return True
    if "仕様" in t:
        return True
    return False


def _dedup(t: str) -> str:
    words = t.split()
    n = len(words)
    for half in range(n // 2, 0, -1):
        if words[:half] == words[n - half:]:
            t = " ".join(words[:half])
            break
    words = t.split()
    seen: set = set()
    result: list = []
    for w in words:
        if w not in seen:
            result.append(w)
            seen.add(w)
    final: list = []
    for w in result:
        if not any(w in other and w != other for other in result):
            final.append(w)
    return " ".join(final).strip()


def _meaningless_reason(stem: str) -> str:
    """Return reason string if stem is meaningless, else empty string."""
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


def _extract_title_from_pdf(pdf_bytes: bytes, brand_cn: str = "") -> str:
    """Extract best human-readable title from PDF bytes."""
    doc = fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf")

    meta = (doc.metadata or {}).get("title", "").strip()
    if meta and not _is_bad_title(meta) and len(meta) > 4:
        doc.close()
        return _sanitize(_dedup(meta))

    # Siemens: look for SIMATIC product names across first 10 pages
    if brand_cn == "西门子":
        for page_num in range(min(10, doc.page_count)):
            for line in doc[page_num].get_text().splitlines():
                line = line.strip()
                if re.search(r"SIMATIC|精智|精简|SINUMERIK|SINAMICS|S7-|ET\s?200", line):
                    if not _is_bad_title(line) and len(line) >= 5:
                        cand = line.split(" 是 ")[0].strip()
                        doc.close()
                        return _sanitize(_dedup(cand))

    # Largest-font candidates across first 5 pages
    candidates: list[tuple[float, str]] = []
    for page_num in range(min(5, doc.page_count)):
        page = doc[page_num]
        for b in page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]:
            if b.get("type") != 0:
                continue
            for line in b.get("lines", []):
                text = " ".join(s.get("text", "").strip() for s in line.get("spans", []))
                size = max((s.get("size", 0) for s in line.get("spans", [])), default=0)
                text = text.strip()
                if len(text) >= 4 and not _is_bad_title(text):
                    candidates.append((size, text))

    if candidates:
        candidates.sort(key=lambda x: (-x[0], -sum(1 for c in x[1] if "一" <= c <= "鿿")))
        top = candidates[:10]
        top.sort(key=lambda x: -sum(1 for c in x[1] if "一" <= c <= "鿿"))
        best = top[0][1]
        if len(top) > 1 and len(best) < 15:
            second = top[1][1]
            if not _is_bad_title(second):
                best = f"{best} {second}"
        doc.close()
        return _sanitize(_dedup(best))

    for page_num in range(min(5, doc.page_count)):
        for line in doc[page_num].get_text().splitlines():
            line = line.strip()
            if line and not _is_bad_title(line) and len(line) >= 5:
                doc.close()
                return _sanitize(_dedup(line))

    doc.close()
    return ""


def _content_from_stem(stem: str, brand_cn: str, type_cn: str) -> str:
    """Clean up a meaningful stem for use as the content part of the filename."""
    content = _sanitize(stem)
    # Strip leading brand_cn if already there
    if content.startswith(brand_cn):
        content = content[len(brand_cn):].lstrip(" -")
    # Strip leading type_cn if already there
    if content.startswith(type_cn):
        content = content[len(type_cn):].lstrip(" -")
    # Remove standalone type_cn word from content (already in prefix)
    content = re.sub(r"(?<![^\s])" + re.escape(type_cn) + r"(?![^\s])", "", content)
    content = _dedup(content)
    content = re.sub(r"\s+", " ", content).strip()
    return content


# ── Main ─────────────────────────────────────────────────────────────────────

def main(write: bool = False) -> None:
    mode = "WRITE" if write else "DRY-RUN"
    print(f"=== batch_rebrand_docs [{mode}] ===\n")

    db = SessionLocal()
    db_docs: dict[str, Document] = {
        d.oss_key: d
        for d in db.query(Document).filter(Document.oss_key.like("doc/%")).all()
    }

    all_objs = oss_service.list_objects("doc")
    pdfs = [
        o for o in all_objs
        if o["key"].lower().endswith(".pdf") and "/_index/" not in o["key"]
    ]
    print(f"Total PDFs in OSS doc/: {len(pdfs)}")

    renames: list[tuple[str, str, object]] = []  # (old_key, new_key, doc|None)
    skipped_already = 0
    need_pdf_download: list[tuple] = []  # items needing PDF extraction

    for obj in pdfs:
        key = obj["key"]
        parts = key.split("/")
        if len(parts) < 4:
            continue  # unexpected path depth

        brand_cn = parts[1]
        type_cn  = parts[2]
        filename = parts[-1]
        stem = filename.rsplit(".", 1)[0]
        prefix = "/".join(parts[:-1])

        # Already in brand-type-content format
        if filename.startswith(f"{brand_cn}-{type_cn}-"):
            skipped_already += 1
            continue

        reason = _meaningless_reason(stem)

        if reason:
            # Defer: needs PDF download
            need_pdf_download.append((obj, parts, reason))
        else:
            # Fast path: meaningful stem, just add prefix
            content = _content_from_stem(stem, brand_cn, type_cn)
            if not content:
                content = stem
            new_filename = _sanitize(f"{brand_cn}-{type_cn}-{content}") + ".pdf"
            new_key = f"{prefix}/{new_filename}"
            if new_key != key:
                renames.append((key, new_key, db_docs.get(key), "prefix"))

    print(f"Already formatted:        {skipped_already}")
    print(f"Need prefix only:         {len(renames)}")
    print(f"Need PDF title extract:   {len(need_pdf_download)}")
    print()

    # PDF download + title extraction pass
    for obj, parts, reason in need_pdf_download:
        key = obj["key"]
        brand_cn = parts[1]
        type_cn  = parts[2]
        filename = parts[-1]
        stem = filename.rsplit(".", 1)[0]
        prefix = "/".join(parts[:-1])

        print(f"[{reason}] {key}")
        print(f"  Downloading ({obj['size'] // 1024} KB)…", end=" ", flush=True)
        try:
            resp = oss_service.client.get_object(Bucket=settings.OSS_BUCKET, Key=key)
            pdf_bytes = resp["Body"].read()
        except Exception as e:
            print(f"FAILED: {e}")
            continue
        print("done")

        # For garbled-katakana: only accept title if it has Chinese chars
        title = _extract_title_from_pdf(pdf_bytes, brand_cn=brand_cn)
        if reason == "garbled-katakana" and title:
            if sum(1 for c in title if "一" <= c <= "鿿") < 4:
                clean_stem = re.sub(r"[｡-ﾟ゠-ヿぁ-ん]", "", stem)
                clean_stem = re.sub(r"[_\-]", " ", clean_stem).strip()
                title = _sanitize(f"{brand_cn} {clean_stem}") if brand_cn else _sanitize(clean_stem)

        if not title:
            title = f"{brand_cn} 文档"
        content = _content_from_stem(title, brand_cn, type_cn)
        if not content:
            content = title

        # Truncate at " 是 " for Siemens product descriptions
        if " 是 " in content:
            content = content.split(" 是 ")[0].strip()

        new_filename = _sanitize(f"{brand_cn}-{type_cn}-{content}") + ".pdf"
        new_key = f"{prefix}/{new_filename}"
        print(f"  Title: {content!r}")
        print(f"  → {filename!r} → {new_filename!r}")
        print()
        if new_key != key:
            renames.append((key, new_key, db_docs.get(key), reason))

    # Collision de-conflict within proposed rename set
    proposed_keys: set[str] = set()
    final_renames: list[tuple[str, str, object]] = []
    for item in renames:
        old_key, new_key, doc, *_ = item
        if new_key in proposed_keys:
            base, ext = new_key.rsplit(".", 1)
            suffix = 2
            while f"{base} ({suffix}).{ext}" in proposed_keys:
                suffix += 1
            new_key = f"{base} ({suffix}).{ext}"
        proposed_keys.add(new_key)
        final_renames.append((old_key, new_key, doc))

    print(f"\n{'='*60}")
    print(f"Total renames planned: {len(final_renames)}")

    if not write:
        # Print summary table
        if len(final_renames) <= 60:
            for old_key, new_key, _ in final_renames:
                old_f = old_key.split("/")[-1]
                new_f = new_key.split("/")[-1]
                print(f"  {old_f!r}")
                print(f"    → {new_f!r}")
        else:
            print(f"  (showing first 30 of {len(final_renames)})")
            for old_key, new_key, _ in final_renames[:30]:
                old_f = old_key.split("/")[-1]
                new_f = new_key.split("/")[-1]
                print(f"  {old_f!r:50s} → {new_f!r}")
        print("\n[DRY-RUN] No changes applied.")
        db.close()
        return

    print("\nApplying renames…")
    ok = err = 0
    for old_key, new_key, doc in final_renames:
        # OSS collision check
        try:
            oss_service.client.head_object(Bucket=settings.OSS_BUCKET, Key=new_key)
            base, ext = new_key.rsplit(".", 1)
            new_key = f"{base} (2).{ext}"
        except Exception:
            pass

        try:
            oss_service.client.copy_object(
                Bucket=settings.OSS_BUCKET,
                CopySource={"Bucket": settings.OSS_BUCKET, "Key": old_key},
                Key=new_key,
            )
            oss_service.client.delete_object(Bucket=settings.OSS_BUCKET, Key=old_key)
            if doc:
                new_filename = new_key.split("/")[-1]
                doc.oss_key = new_key
                doc.filename = new_filename
                doc.original_name = new_filename
            ok += 1
        except Exception as e:
            print(f"  ERROR {old_key}: {e}")
            err += 1

    db.commit()
    db.close()
    print(f"\nDone: {ok} renamed, {err} errors.")


if __name__ == "__main__":
    main(write="--write" in sys.argv)
