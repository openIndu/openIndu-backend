"""Reformat three specific documents to follow 品牌-类型-内容.pdf naming convention.

Usage:
    python scripts/reformat_three_docs.py           # dry-run
    python scripts/reformat_three_docs.py --write   # apply
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

TARGET_IDS = [132, 166, 239]


def _sanitize(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|&·]', " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _is_bad(t: str) -> bool:
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
    # Pure spec-table row: 3+ isolated single uppercase letters
    if len(re.findall(r"(?<!\w)[A-Z](?!\w)", t)) >= 3:
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
    # Remove standalone words that are substrings of a compound already present
    final: list = []
    for w in result:
        if not any(w in other and w != other for other in result):
            final.append(w)
    return " ".join(final).strip()


def _font_candidates(doc, start_page: int = 0, page_count: int = 5):
    candidates = []
    end = min(start_page + page_count, doc.page_count)
    for page_num in range(start_page, end):
        page = doc[page_num]
        for b in page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]:
            if b.get("type") != 0:
                continue
            for line in b.get("lines", []):
                text = " ".join(s.get("text", "").strip() for s in line.get("spans", []))
                size = max((s.get("size", 0) for s in line.get("spans", [])), default=0)
                text = text.strip()
                if len(text) >= 4 and not _is_bad(text):
                    candidates.append((size, text))
    return candidates


def _best_from_candidates(candidates) -> str:
    if not candidates:
        return ""
    candidates.sort(key=lambda x: (-x[0], -sum(1 for c in x[1] if "一" <= c <= "鿿")))
    top = candidates[:10]
    top.sort(key=lambda x: -sum(1 for c in x[1] if "一" <= c <= "鿿"))
    best = top[0][1]
    if len(top) > 1 and len(best) < 15:
        second = top[1][1]
        if not _is_bad(second):
            best = f"{best} {second}"
    return _sanitize(_dedup(best))


def extract_content_title(pdf_bytes: bytes, brand_cn: str = "") -> str:
    doc = fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf")

    # 1. PDF metadata (skip if looks generic)
    meta = (doc.metadata or {}).get("title", "").strip()
    if meta and not _is_bad(meta) and len(meta) > 4:
        doc.close()
        return _sanitize(_dedup(meta))

    # 2. For Siemens, search specifically for SIMATIC product lines across more pages
    if brand_cn == "西门子":
        simatic_candidates = []
        for page_num in range(min(10, doc.page_count)):
            for line in doc[page_num].get_text().splitlines():
                line = line.strip()
                if re.search(r"SIMATIC|精智|精简|SINUMERIK|SINAMICS|S7-|ET\s?200", line):
                    if not _is_bad(line) and len(line) >= 5:
                        simatic_candidates.append(line)
        if simatic_candidates:
            # Prefer the one with most content
            best = max(simatic_candidates, key=len)
            doc.close()
            return _sanitize(_dedup(best))

    # 3. Largest-font text from first 5 pages
    candidates = _font_candidates(doc, start_page=0, page_count=5)
    result = _best_from_candidates(candidates)
    if result:
        doc.close()
        return result

    # 4. Plain text fallback
    for page_num in range(min(5, doc.page_count)):
        for line in doc[page_num].get_text().splitlines():
            line = line.strip()
            if line and not _is_bad(line) and len(line) >= 5:
                doc.close()
                return _sanitize(_dedup(line))

    doc.close()
    return ""


def main(write: bool = False):
    mode = "WRITE" if write else "DRY-RUN"
    print(f"=== reformat_three_docs [{mode}] ===\n")

    db = SessionLocal()
    docs = {d.id: d for d in db.query(Document).filter(Document.id.in_(TARGET_IDS)).all()}

    for doc_id in TARGET_IDS:
        doc = docs.get(doc_id)
        if not doc:
            print(f"[SKIP] id={doc_id} not found in DB")
            continue

        old_key = doc.oss_key
        parts = old_key.split("/")
        brand_cn = parts[1]
        type_cn = parts[2]
        prefix = "/".join(parts[:-1])

        print(f"[id={doc_id}] {old_key}")
        print(f"  Brand: {brand_cn}  Type: {type_cn}")

        print(f"  Downloading…", end=" ", flush=True)
        try:
            resp = oss_service.client.get_object(Bucket=settings.OSS_BUCKET, Key=old_key)
            pdf_bytes = resp["Body"].read()
        except Exception as e:
            print(f"FAILED: {e}")
            continue
        print("done")

        content_title = extract_content_title(pdf_bytes, brand_cn=brand_cn)
        if not content_title:
            print(f"  WARNING: no content title extracted, skipping\n")
            continue

        # Truncate at " 是 " / " was " in product descriptions → keep product name only
        if " 是 " in content_title:
            content_title = content_title.split(" 是 ")[0].strip()
        # Remove standalone type_cn word from content (already in prefix)
        content_title = re.sub(r"(?<![^\s])" + re.escape(type_cn) + r"(?![^\s])", "", content_title)
        content_title = re.sub(r"\s+", " ", content_title).strip()

        print(f"  Content title: {content_title!r}")

        new_filename = _sanitize(f"{brand_cn}-{type_cn}-{content_title}") + ".pdf"
        new_key = f"{prefix}/{new_filename}"

        if new_key == old_key:
            print(f"  → No change needed\n")
            continue

        # Collision check
        try:
            oss_service.client.head_object(Bucket=settings.OSS_BUCKET, Key=new_key)
            base, ext = new_key.rsplit(".", 1)
            new_key = f"{base} (2).{ext}"
            new_filename = new_key.split("/")[-1]
            print(f"  ⚠ Collision, appending (2)")
        except Exception:
            pass

        print(f"  → {parts[-1]!r}")
        print(f"     → {new_filename!r}")

        if write:
            try:
                oss_service.client.copy_object(
                    Bucket=settings.OSS_BUCKET,
                    CopySource={"Bucket": settings.OSS_BUCKET, "Key": old_key},
                    Key=new_key,
                )
                oss_service.client.delete_object(Bucket=settings.OSS_BUCKET, Key=old_key)
                doc.oss_key = new_key
                doc.filename = new_filename
                doc.original_name = new_filename
                print(f"  OSS ✓  DB ✓")
            except Exception as e:
                print(f"  ERROR: {e}")

        print()

    if write:
        db.commit()
        print("Committed.")
    else:
        print("[DRY-RUN] No changes applied.")
    db.close()


if __name__ == "__main__":
    main(write="--write" in sys.argv)
