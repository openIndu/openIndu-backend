# ruff: noqa: E402, I001
"""Add series tags for brands that currently have none, then auto-assign
series to documents based on filename keyword matching.

Usage:
    python scripts/add_series_tags.py           # dry-run
    python scripts/add_series_tags.py --write   # apply tags + assign series
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.document import Document
from app.models.resource_tag import ResourceTag


# ── Series definitions ──────────────────────────────────────────────────────

# Format: (brand_slug, category_slug, series_slug, label_zh, filename_patterns)
SERIES_TO_ADD = [
    # ── Siemens ──
    ("siemens", "plc-manual", "s7-1500", "S7-1500", [r"S7[-_]?1500"]),
    ("siemens", "plc-manual", "simatic-wincc", "SIMATIC WinCC Unified", [r"WinCC\s*Uni"]),
    ("siemens", "driver-manual", "sinamics-s200", "SINAMICS S200", [r"S200"]),
    ("siemens", "hardware-manual", "simicas-gateway", "SIMICAS 智能网关", [r"SIMICAS"]),
    ("siemens", "plc-manual", "s7-1200", "S7-1200", [r"simens.*s1200", r"S7[-_]?1200", r"SIMATIC\s*S7[-_]?1200"]),
    ("siemens", "plc-manual", "simatic-general", "SIMATIC 通用", [r"SIMATIC"]),
    ("siemens", "hardware-manual", "simatic-hw", "SIMATIC 硬件", [r"SIMATIC", r"ET\s?200", r"IOT", r"物联网"]),

    # ── Mitsubishi ──
    ("mitsubishi", "plc-manual", "fx5u", "FX5U", [r"FX5U?"]),
    ("mitsubishi", "plc-manual", "l-series", "MELSEC-L 系列", [r"MELSEC[-_]?L", r"L系列", r"LD75P?", r"LD77MH"]),
    ("mitsubishi", "plc-manual", "cclink", "CC-Link 通信", [r"CC[-_]?Link"]),
    ("mitsubishi", "plc-manual", "mx-component", "MX Component", [r"MX\s*Component"]),
    ("mitsubishi", "plc-manual", "ql-series", "MELSEC-Q/L 结构体", [r"MELSEC[-_]?QL"]),
    ("mitsubishi", "driver-manual", "mr-j4", "MR-J4 系列", [r"MR[-_]?J[34]", r"JE[-_]?A"]),
    ("mitsubishi", "plc-manual", "mr-j4-plc", "MR-J4 伺服", [r"MR[-_]?J[34]"]),
    ("mitsubishi", "plc-manual", "mr-j3-plc", "MR-J3 伺服", [r"MR[-_]?J3"]),
    ("mitsubishi", "plc-manual", "qd75-plc", "QD75 定位模块", [r"QD75"]),
    ("mitsubishi", "hardware-manual", "qd75-hw", "QD75 定位模块", [r"QD75"]),
    ("mitsubishi", "plc-manual", "gx-works2", "GX Works2", [r"Gx\s*Works?2", r"GX\s*Works?2"]),
    ("mitsubishi", "plc-manual", "melsec-comm", "MELSEC 通讯协议", [r"MELSEC通讯", r"MELSEC.*协议"]),
    ("mitsubishi", "plc-manual", "neza", "NEZA 系列", [r"Neza"]),
    ("mitsubishi", "hardware-manual", "motion-cpu", "运动控制器", [r"运动CPU", r"运动控制器", r"QD77MS"]),
    ("mitsubishi", "hardware-manual", "ethernet-wireless", "以太网/无线模块", [r"以太网无线", r"无线模块"]),
    ("mitsubishi", "plc-manual", "q-common", "Q 系列通用", [r"\bQ\b", r"QnU", r"QCPU", r"Q\d{2}", r"QQNA", r"Q_L"]),
    ("mitsubishi", "plc-manual", "qd77ms", "QD77MS", [r"QD77MS"]),
    ("mitsubishi", "plc-manual", "1pg", "1PG 模块", [r"1PG"]),
    ("mitsubishi", "plc-manual", "qd70", "QD70", [r"QD70"]),
    ("mitsubishi", "plc-manual", "fx-selection", "FX 选型/编程", [r"FX選型", r"FX編程", r"FX\s*系列"]),
    ("mitsubishi", "plc-manual", "simple-cpu", "Simple CPU", [r"Simple\s*CPU"]),
    ("mitsubishi", "plc-manual", "q-ethernet", "Q 以太网", [r"Q.*以太|Q.*乙太|內置乙太|UDECPU"]),
    ("mitsubishi", "plc-manual", "q-serial", "Q 串口", [r"Q.*串口"]),
    ("mitsubishi", "plc-manual", "q-ad-da", "Q 数模转换", [r"數模轉換|数模转换"]),
    ("mitsubishi", "plc-manual", "mitsubishi-catalog", "三菱 综合目录", [r"綜合型錄|综合目录|綜合目錄"]),
    ("mitsubishi", "plc-manual", "kingview", "组态王", [r"组态王"]),
    ("mitsubishi", "plc-manual", "motion-sfc", "运动CPU SFC", [r"运动CPU.*SFC|SFC"]),
    ("mitsubishi", "plc-manual", "l-wireless", "L 无线模块", [r"l08241ea"]),
    ("mitsubishi", "other", "mitsubishi-other", "三菱 其他", [r"接触器|断路器|线缆|编程电缆"]),
    ("mitsubishi", "driver-manual", "servo-catalog", "伺服综合样本", [r"伺服綜合|伺服综合"]),

    # ── Omron ──
    ("omron", "plc-manual", "nj-series", "NJ 系列", [r"NJ[-\s]?\d", r"NJ系列", r"NJ501", r"NJ301"]),
    ("omron", "plc-manual", "nx-series", "NX 系列", [r"NX[-\s]?\d", r"NX[-_]?PA", r"NX[-_]?PD"]),
    ("omron", "plc-manual", "cj-series", "CJ 系列", [r"CJ1[MW]", r"CJ1W", r"CS1W"]),
    ("omron", "plc-manual", "g-series-servo", "G 系列伺服", [r"G系列", r"g_series"]),
    ("omron", "driver-manual", "g5-series", "G5 系列", [r"G5"]),
    ("omron", "driver-manual", "1s-series", "1S 系列", [r"1[sS]系列"]),
    ("omron", "driver-manual", "r88m-series", "R88M 系列", [r"R88M", r"R88D"]),
    ("omron", "plc-manual", "mc-series", "MC 操作手册", [r"MC操作", r"MC_21"]),
    ("omron", "plc-manual", "1s-servo", "1S 伺服", [r"1[sS]系列"]),
    ("omron", "plc-manual", "nj-catalog", "NJ 目录", [r"NJ\s*catalog"]),
    ("omron", "plc-manual", "sysmac-studio", "Sysmac Studio", [r"Sysmac", r"SYSMAC"]),
    ("omron", "plc-manual", "nx-ecc", "NX ECC", [r"nx[-_]?ecc"]),
    ("omron", "plc-manual", "nx-eic", "NX EIC", [r"nx[-_]?eic"]),
    ("omron", "plc-manual", "nx-general", "NX 通用", [r"nxseries", r"nx[-_]"]),
    ("omron", "driver-manual", "1s-series-all", "1S 系列", [r"1[sS][-_]?series", r"1[sS]系列"]),
    ("omron", "driver-manual", "servo-tech", "伺服技术指南", [r"Servomotor.*Tech|伺服.*技术"]),
    ("omron", "plc-manual", "r88m-plc", "R88M 伺服", [r"R88M", r"R88D"]),

    # ── Fuji ──
    ("fuji", "plc-manual", "micrex-sx", "MICREX-SX 系列", [r"MICREX[-_]?SX", r"FCH\d{3}", r"FEH\d{3}"]),
    ("fuji", "plc-manual", "alpha5-smart", "ALPHA5 SMART", [r"ALPHA5", r"ALPHA.?5"]),
    ("fuji", "plc-manual", "d300win", "D300win 软件", [r"D300win"]),
    ("fuji", "hardware-manual", "micrex-sx-hw", "MICREX-SX 硬件", [r"FCH\d{3}"]),
    ("fuji", "hmi-manual", "micrex-sx-hmi", "MICREX-SX HMI", [r"MONITOUCH", r"V[89]\d\d"]),
    ("fuji", "plc-manual", "sx-common", "MICREX-SX 通用", [r"MICREX", r"SX系列", r"FCH", r"FEH"]),

    # ── Delta ──
    ("delta", "plc-manual", "ah500", "AH500 系列", [r"AH500"]),
    ("delta", "driver-manual", "m-series", "M 系列变频器", [r"M系列"]),

    # ── Keyence ──
    ("keyence", "plc-manual", "kv-x", "KV-X 系列", [r"KV[-_]?X", r"KV75", r"KV[-_]?EIP"]),
    ("keyence", "plc-manual", "xmotion", "XMOTION", [r"XMOTION"]),

    # ── Panasonic ──
    ("panasonic", "driver-manual", "minas-a4", "MINAS A4", [r"Minas\s*A4", r"minas[-_]?a4"]),
    ("panasonic", "driver-manual", "minas-a5", "MINAS A5", [r"Minas\s*A5", r"minas[-_]?a5", r"PANATERM.*[Aa]5"]),
    ("panasonic", "driver-manual", "minas-a6", "MINAS A6", [r"Minas\s*A6", r"minas[-_]?a6"]),

    # ── Oriental Motor ──
    ("oriental-motor", "driver-manual", "az-series", "AZ 系列", [r"AZ\s*系列"]),
    ("oriental-motor", "driver-manual", "stepper-combo", "步进电动机组合", [r"步进电动机"]),

    # ── Nachi (robot-manual) ──
    ("nachi", "robot-manual", "cfd-series", "CFD 系列", [r"CFD"]),
    ("nachi", "robot-manual", "tfd-series", "TFD 系列", [r"TFD"]),
    ("nachi", "robot-manual", "nachi-general", "不二越 通用", [r"不二越", r"Socket", r"外部", r"入门", r"初级"]),

    # ── Inovance ──
    ("inovance", "plc-manual", "autoshop", "AutoShop", [r"AutoShop"]),

    # ── CKD ──
    ("ckd", "driver-manual", "smb-series", "SMB 系列", [r"SMB"]),
    ("ckd", "driver-manual", "ts-series", "TS 型", [r"TS型"]),

    # ── Cognex ──
    ("cognex", "robot-manual", "dataman-260", "DataMan 260", [r"DataMan\s*260"]),
    ("cognex", "robot-manual", "dataman-general", "DataMan 通用", [r"DataMan", r"康耐视"]),

    # ── Single-doc brands (generic series) ──
    ("abb", "plc-manual", "abb-robot", "ABB 机器人", [r"ABB", r"机器人"]),
    ("beckhoff", "plc-manual", "beckhoff-general", "倍福 通用", [r"Beckhoff", r"倍福"]),
    ("hokuyo", "other", "hokuyo-catalog", "北阳 选型目录", [r"北阳", r"HOKUYO", r"选型"]),
    ("xinje", "plc-manual", "xinje-plc", "信捷 可编程控制器", [r"信捷", r"XINJE"]),

    # ── Panasonic remaining ──
    ("panasonic", "driver-manual", "minas-general", "MINAS 通用", [r"交流伺服", r"Minas", r"minas", r"PANATERM"]),

    # ── Keyence remaining ──
    ("keyence", "plc-manual", "kv-general", "KV 通用", [r"KV[-\s]?\d", r"KV[-\s]?[A-Z]", r"KV系列"]),
]


# ── Category migration: nachi from other → robot-manual ─────────────────────
# Nachi docs are all robot manuals, should be robot-manual not other
CATEGORY_FIXES = {
    "nachi": ("other", "robot-manual"),
}


def main(write: bool = False):
    mode = "WRITE" if write else "DRY-RUN"
    print(f"=== add_series_tags [{mode}] ===\n")

    db = SessionLocal()

    # ── Step 1: Fix nachi category ──
    print("=== Step 1: Fix nachi category (other → robot-manual) ===\n")
    for brand, (old_cat, new_cat) in CATEGORY_FIXES.items():
        docs = db.query(Document).filter(
            Document.brand == brand,
            Document.category == old_cat,
        ).all()
        print(f"  {brand}: {len(docs)} docs need category change ({old_cat} → {new_cat})")
        if write and docs:
            for d in docs:
                d.category = new_cat
            print("    Applied.")
        if docs:
            for d in docs[:3]:
                print(f"    {d.filename}")

    # Ensure robot-manual category tag exists
    robot_cat = db.query(ResourceTag).filter(
        ResourceTag.type == "doc_category",
        ResourceTag.value == "robot-manual",
    ).first()
    if not robot_cat:
        print("\n  Creating robot-manual category tag...")
        if write:
            db.add(ResourceTag(
                type="doc_category",
                value="robot-manual",
                label_zh="机器人手册",
                is_active=True,
                sort_order=7,
            ))
            db.flush()
            print("    Created.")

    # ── Step 2: Add new series tags ──
    print("\n=== Step 2: Add new series tags ===\n")
    existing_series = {
        (s.brand_value, s.parent_value, s.value): s
        for s in db.query(ResourceTag).filter(ResourceTag.type == "doc_series").all()
    }
    # Also track by value only (cross-cat duplicates are not allowed: unique on type+value)
    existing_values = {
        (s.type, s.value): s
        for s in db.query(ResourceTag).filter(ResourceTag.type == "doc_series").all()
    }

    new_tags_created = 0
    for brand, cat, slug, label, patterns in SERIES_TO_ADD:
        key = (brand, cat, slug)
        if key in existing_series:
            print(f"  SKIP (exists): {brand}/{cat}/{slug} = {label}")
            continue
        # Also skip if value already exists with different brand/cat
        val_key = ("doc_series", slug)
        if val_key in existing_values:
            existing = existing_values[val_key]
            print(f"  SKIP (value exists as {existing.brand_value}/{existing.parent_value}/{slug}): {brand}/{cat}/{slug} = {label}")
            continue
        print(f"  NEW: {brand}/{cat}/{slug} = {label}")
        if write:
            db.add(ResourceTag(
                type="doc_series",
                value=slug,
                label_zh=label,
                brand_value=brand,
                parent_value=cat,
                is_active=True,
                sort_order=99,
            ))
            new_tags_created += 1

    if write and new_tags_created:
        db.flush()
    print(f"\n  New tags: {new_tags_created}")

    if write:
        db.flush()

    # ── Step 3: Auto-assign series to documents ──
    print("\n=== Step 3: Auto-assign series to documents ===\n")
    unassigned = db.query(Document).filter(
        Document.series.is_(None),
        Document.brand.isnot(None),
    ).all()

    print(f"  Documents without series: {len(unassigned)}")
    assigned = 0
    unmatched = []

    for doc in unassigned:
        matched = False
        for brand, cat, slug, label, patterns in SERIES_TO_ADD:
            if doc.brand != brand or doc.category != cat:
                continue
            for pat in patterns:
                if re.search(pat, doc.filename, re.IGNORECASE):
                    doc.series = slug
                    matched = True
                    assigned += 1
                    print(f"  {doc.brand}/{doc.category}: {doc.filename[:60]}...")
                    print(f"    → series={slug} ({label})")
                    break
            if matched:
                break
        if not matched:
            unmatched.append(doc)

    print(f"\n  Assigned: {assigned}")
    print(f"  Still unmatched: {len(unmatched)}")
    if unmatched:
        print("\n  Unmatched documents:")
        for d in unmatched[:30]:
            print(f"    [{d.brand}/{d.category}] {d.filename[:80]}")
        if len(unmatched) > 30:
            print(f"    ... and {len(unmatched) - 30} more")

    if write:
        db.commit()
        print("\n=== Committed ===")
    else:
        print("\n[DRY-RUN] No changes applied.")

    db.close()


if __name__ == "__main__":
    main(write="--write" in sys.argv)
