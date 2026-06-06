"""Convert an Aronium POS product CSV export into the NUMU POS import CSV.

Usage:
    aronium_to_grocerypos.py <aronium-export.csv> [-o <output.csv>]

If -o is omitted, the output is written next to the input with the suffix
"-grocerypos.csv".

Verified against a real Aronium export with the columns:
    Name, ProductGroup, SKU, Barcode, MeasurementUnit, Cost, Markup, Price,
    Tax, IsTaxInclusivePrice, IsPriceChangeAllowed, IsUsingDefaultQuantity,
    IsService, IsEnabled, Description, Quantity, Supplier, ReorderPoint,
    PreferredQuantity, LowStockWarning, WarningQuantity

Notes on Aronium's format:
  - Barcodes are PIPE-separated ("123|456|789") -> one row per barcode.
  - ProductGroup is often bilingual "English / Arabic" -> split into en/ar.
  - Product names are usually Arabic -> mapped to name_ar.
  - Negative stock quantities are clamped to 0.
"""

import argparse
import csv
import os
import re
import sys
from collections import OrderedDict

OUTPUT_HEADERS = [
    "sku", "name_ar", "name_en", "description_ar", "description_en",
    "category_ar", "category_en", "category_key", "price", "cost", "unit",
    "stock_quantity", "low_stock_threshold", "track_inventory",
    "vat_exempt", "has_expiry", "nearest_expiry_date", "barcode",
    "label_ar", "label_en", "sale_unit", "quantity_multiplier",
    "price_override",
]

ALIASES = {
    "sku":         ["sku", "code", "item code", "product code", "id"],
    "name":        ["name", "product name", "item name", "title"],
    "barcode":     ["barcode", "barcodes", "ean", "ean13", "gtin", "upc"],
    "price":       ["price", "sell price", "sale price", "selling price", "retail price"],
    "cost":        ["cost", "buy price", "purchase price", "cost price"],
    "quantity":    ["quantity", "qty", "stock", "stock quantity", "on hand", "inventory"],
    "category":    ["productgroup", "product group", "category", "group", "department", "section"],
    "description": ["description", "notes", "comment"],
    "unit":        ["measurementunit", "measurement unit", "unit", "measure", "uom", "unit of measure"],
    "tax":         ["tax", "vat", "vat rate", "tax rate"],
    "is_service":  ["isservice", "is service", "service"],
    "is_enabled":  ["isenabled", "is enabled", "enabled", "active"],
}

ARABIC_RE = re.compile(r"[؀-ۿ]")

UNIT_NORMALIZATION = {
    "piece": "piece", "pc": "piece", "pcs": "piece", "ea": "piece",
    "each": "piece", "unit": "piece", "komad": "piece", "kom": "piece",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg",
    "g": "g", "gram": "g", "grams": "g",
    "l": "l", "liter": "l", "litre": "l", "liters": "l", "litres": "l",
    "ml": "ml", "milliliter": "ml", "millilitre": "ml",
    "box": "box", "carton": "box", "case": "box",
}


def find_header(headers, candidates):
    norm = {h.strip().lower(): h for h in headers if h is not None}
    for c in candidates:
        if c in norm:
            return norm[c]
    return None


def detect_encoding(path):
    for enc in ("utf-8-sig", "utf-8", "cp1256", "cp1252", "latin-1"):
        try:
            with open(path, encoding=enc, newline="") as fh:
                fh.read()
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"


def detect_delimiter(sample):
    candidates = [",", ";", "\t", "|"]
    counts = {d: sample.count(d) for d in candidates}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def parse_number(value, default=0.0):
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    text = text.replace(" ", "")
    if "," in text and "." in text:
        # 1.234,56 (EU) → strip thousands dot, swap decimal comma
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    text = re.sub(r"[^0-9.\-]", "", text)
    if not text or text in {"-", ".", "-."}:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def format_number(value):
    if value == int(value):
        return str(int(value))
    return ("%.4f" % value).rstrip("0").rstrip(".")


def slugify(text):
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return s or "general"


def split_barcodes(raw):
    if not raw:
        return [""]
    # Aronium joins multiple barcodes with "|"; also tolerate ; , / whitespace.
    parts = re.split(r"[|;,/\s]+", raw.strip())
    parts = [p for p in parts if p]
    return parts or [""]


def has_arabic(text):
    return bool(ARABIC_RE.search(text or ""))


def split_category(raw):
    """Return (category_ar, category_en) for an Aronium ProductGroup value.

    Handles bilingual "English / Arabic" (either order), single-language, and
    empty values.
    """
    text = (raw or "").strip()
    if not text:
        return "عام", "General"
    if " / " in text:
        left, right = (s.strip() for s in text.split(" / ", 1))
        if has_arabic(left) and not has_arabic(right):
            return left, right
        if has_arabic(right) and not has_arabic(left):
            return right, left
        # Both or neither Arabic: keep left as the primary (ar) label.
        return left, right
    if has_arabic(text):
        return text, ""
    return text, text


def normalize_unit(raw):
    if not raw:
        return "piece"
    key = raw.strip().lower()
    return UNIT_NORMALIZATION.get(key, "piece")


def convert(input_path, output_path):
    encoding = detect_encoding(input_path)
    with open(input_path, encoding=encoding, newline="") as fh:
        sample = fh.read(8192)
    delimiter = detect_delimiter(sample)

    with open(input_path, encoding=encoding, newline="") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        headers = reader.fieldnames or []
        col = {key: find_header(headers, aliases) for key, aliases in ALIASES.items()}
        if col["name"] is None:
            sys.exit(
                "ERROR: could not find a 'Name' column in the Aronium CSV.\n"
                f"Headers seen: {headers}"
            )
        source_rows = list(reader)

    # First pass: learn canonical Arabic<->English category pairs from the
    # bilingual ProductGroup values, so every variant maps to one clean label.
    ar_to_pair = {}
    en_to_pair = {}
    if col["category"]:
        for row in source_rows:
            ar, en = split_category(row.get(col["category"]))
            if ar and en and ar != en and has_arabic(ar) and not has_arabic(en):
                ar_to_pair.setdefault(ar.lower(), (ar, en))
                en_to_pair.setdefault(en.lower(), (ar, en))

    def canonical_category(raw):
        ar, en = split_category(raw)
        pair = ar_to_pair.get(ar.lower()) or en_to_pair.get(en.lower())
        if pair:
            return pair
        return ar, en

    warnings = []
    grouped = OrderedDict()
    skipped_disabled = 0
    clamped_stock = 0

    for idx, row in enumerate(source_rows, start=1):
        name = (row.get(col["name"]) or "").strip()
        if not name:
            warnings.append(f"Row {idx}: missing Name, skipped.")
            continue

        # Skip explicitly disabled items (IsEnabled = 0), if the column exists.
        if col["is_enabled"]:
            enabled = (row.get(col["is_enabled"]) or "").strip()
            if enabled in {"0", "false", "False", "no", "No"}:
                skipped_disabled += 1
                continue

        sku = (row.get(col["sku"]) or "").strip() if col["sku"] else ""
        if not sku:
            sku = f"ARN-{idx:04d}"
            warnings.append(f"Row {idx}: missing SKU, generated '{sku}'.")

        category_ar, category_en = canonical_category(
            row.get(col["category"]) if col["category"] else ""
        )
        # Only emit a key when we have a Latin label to slugify; otherwise the
        # app matches the category by its Arabic name.
        category_key = slugify(category_en) if category_en and not has_arabic(category_en) else ""

        price = parse_number(row.get(col["price"])) if col["price"] else 0.0
        cost = parse_number(row.get(col["cost"])) if col["cost"] else 0.0
        qty = parse_number(row.get(col["quantity"])) if col["quantity"] else 0.0
        if qty < 0:
            clamped_stock += 1
            qty = 0.0

        unit = normalize_unit(row.get(col["unit"]) if col["unit"] else "")
        desc = (row.get(col["description"]) or "").strip() if col["description"] else ""

        # A service item carries no stock.
        is_service = False
        if col["is_service"]:
            is_service = (row.get(col["is_service"]) or "").strip() in {"1", "true", "True", "yes", "Yes"}
        track_inventory = "false" if is_service else "true"
        if is_service:
            qty = 0.0

        if col["tax"]:
            tax = parse_number(row.get(col["tax"]), default=-1)
            vat_exempt = "true" if tax == 0 else "false"
        else:
            vat_exempt = "false"

        raw_barcodes = (row.get(col["barcode"]) or "").strip() if col["barcode"] else ""
        barcodes = split_barcodes(raw_barcodes)

        base = {
            "sku": sku,
            "name_ar": name,
            "name_en": "" if has_arabic(name) else name,
            "description_ar": "",
            "description_en": desc,
            "category_ar": category_ar,
            "category_en": category_en,
            "category_key": category_key,
            "price": format_number(price),
            "cost": format_number(cost),
            "unit": unit,
            "stock_quantity": format_number(qty),
            "low_stock_threshold": "5",
            "track_inventory": track_inventory,
            "vat_exempt": vat_exempt,
            "has_expiry": "false",
            "nearest_expiry_date": "",
            "label_ar": "",
            "label_en": "",
            "sale_unit": "",
            "quantity_multiplier": "1",
            "price_override": "0",
        }

        for bc in barcodes:
            out_row = dict(base)
            out_row["barcode"] = bc
            grouped.setdefault(sku, []).append(out_row)

    total_rows = 0
    with open(output_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_HEADERS)
        writer.writeheader()
        for rows in grouped.values():
            for r in rows:
                writer.writerow(r)
                total_rows += 1

    return {
        "products": len(grouped),
        "rows": total_rows,
        "warnings": warnings,
        "skipped_disabled": skipped_disabled,
        "clamped_stock": clamped_stock,
        "delimiter": delimiter,
        "encoding": encoding,
        "mapped_columns": col,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert an Aronium CSV export to NUMU POS import CSV."
    )
    parser.add_argument("input", help="Path to the Aronium-exported CSV file.")
    parser.add_argument(
        "-o", "--output",
        help="Path for the converted CSV (default: <input>-grocerypos.csv)",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        sys.exit(f"ERROR: file not found: {args.input}")

    output_path = args.output or (
        os.path.splitext(args.input)[0] + "-grocerypos.csv"
    )

    info = convert(args.input, output_path)

    print(f"Input encoding : {info['encoding']}")
    print(f"Input delimiter: '{info['delimiter']}'")
    print(f"Mapped columns : {info['mapped_columns']}")
    print()
    print(f"Converted: {info['products']} product(s), {info['rows']} CSV row(s).")
    if info["skipped_disabled"]:
        print(f"Skipped:   {info['skipped_disabled']} disabled item(s) (IsEnabled=0).")
    if info["clamped_stock"]:
        print(f"Clamped:   {info['clamped_stock']} negative stock value(s) to 0.")
    print(f"Output:    {output_path}")

    if info["warnings"]:
        print(f"Warnings ({len(info['warnings'])}):")
        for w in info["warnings"][:20]:
            print(f"  - {w}")
        if len(info["warnings"]) > 20:
            print(f"  ... and {len(info['warnings']) - 20} more.")

    print()
    print("Next steps:")
    print("  1. (Optional) Open the converted CSV in Excel to review names,")
    print("     categories, and prices. Fill name_en if you want English labels.")
    print("  2. In NUMU POS: Products -> Bulk Actions -> Import Products,")
    print("     then pick the converted CSV.")


if __name__ == "__main__":
    main()
