# Aronium → NUMU POS product import

One-off converter that turns an **Aronium POS** product CSV export into a CSV the **NUMU POS** "Import Products" feature accepts.

---

## What's in this folder

| File | Purpose |
| --- | --- |
| `aronium_to_grocerypos.py` | The converter (Python 3.9+). |
| `build.bat` | Builds a standalone Windows `.exe` from the script. |
| `README.md` | This file. |

---

## Quick start (using the `.exe`)

If you already have `aronium-to-grocerypos.exe`:

1. Export products from Aronium to a CSV file (e.g. `products.csv`).
2. Drag that CSV onto `aronium-to-grocerypos.exe` **or** open Command Prompt in the same folder and run:
   ```
   aronium-to-grocerypos.exe products.csv
   ```
3. A new file `products-grocerypos.csv` appears next to the input.
4. *(Optional)* Open `products-grocerypos.csv` in Excel and translate the `name_ar` and `category_ar` columns into Arabic.
5. In NUMU POS: **Products → Bulk Actions → Import Products** → pick `products-grocerypos.csv`.
6. Review the preview dialog, then confirm.

---

## Building the `.exe` (one-time, on Windows)

You only need to do this once.

1. Install Python 3.9+ from <https://www.python.org/downloads/> (tick *"Add Python to PATH"* during install).
2. Double-click `build.bat`.
3. When it finishes, the executable is at `dist\aronium-to-grocerypos.exe`. Copy it anywhere you like — it's self-contained.

---

## Running the Python script directly (no build step)

If Python 3.9+ is installed:

```
python aronium_to_grocerypos.py products.csv
python aronium_to_grocerypos.py products.csv -o converted.csv
```

---

## What gets mapped

Verified against a real Aronium export with these columns:
`Name, ProductGroup, SKU, Barcode, MeasurementUnit, Cost, Markup, Price, Tax, IsTaxInclusivePrice, IsPriceChangeAllowed, IsUsingDefaultQuantity, IsService, IsEnabled, Description, Quantity, Supplier, ReorderPoint, PreferredQuantity, LowStockWarning, WarningQuantity`

| Aronium column (case-insensitive) | NUMU POS column(s) |
| --- | --- |
| `Name` *(required)* | `name_ar` (Arabic names go here); `name_en` left blank for Arabic names |
| `ProductGroup` (often `English / Arabic`) | `category_ar`, `category_en`, `category_key` (split into the two languages) |
| `SKU` / `Code` / `Item Code` | `sku` (auto-generated as `ARN-0001` if missing) |
| `Barcode` (pipe-separated `123\|456\|789`) | `barcode` (one row per barcode, sharing the SKU) |
| `Price` | `price` |
| `Cost` / `Buy Price` | `cost` |
| `Quantity` / `Stock` | `stock_quantity` (negative values clamped to `0`) |
| `MeasurementUnit` / `Unit` | `unit` (normalized: pcs/komad/each → `piece`, kilogram → `kg`, …) |
| `Tax` / `VAT` | `vat_exempt = true` if tax is `0`, else `false` |
| `IsService` | `track_inventory = false` when `1` (services hold no stock) |
| `IsEnabled` | rows with `0` are skipped |
| `Description` | `description_en` |

The `Markup`, `IsTaxInclusivePrice`, `Supplier`, `ReorderPoint`, and warning columns are ignored.

Defaults applied to every product: `low_stock_threshold=5`, `track_inventory=true`, `has_expiry=false`, `quantity_multiplier=1`.

---

## Important notes

- **Arabic names**: Aronium product names are usually already Arabic, so they map straight to `name_ar` (which the app requires) and `name_en` is left blank. If a name happens to be Latin, it is placed in both fields as a fallback. Translate/fill `name_en` in Excel afterwards only if you want English display too.
- **Categories**: `ProductGroup` is frequently bilingual (`Candy & Chips / الحلويات ورقائق البطاطس`). The script learns the Arabic↔English pairing from every bilingual row and applies one **canonical** label to all rows, so a category that appears as English-only on some rows and Arabic-only on others still merges into a single clean category on import.
- **Multiple barcodes**: Aronium joins multiple barcodes with a pipe (`|`); `;`, `,`, `/`, and spaces are also tolerated. Each barcode becomes its own CSV row sharing the SKU, which NUMU POS treats as multi-barcode entries on one product.
- **Decimal format**: Handles both `12.34` and EU-style `12,34` / `1.234,56`.
- **Encoding**: Auto-detects UTF-8 (with/without BOM), Windows-1256 (Arabic), Windows-1252, Latin-1. Output is UTF-8 with BOM so Arabic displays correctly in Excel; the app strips the BOM on import.
- **Existing products**: The NUMU POS importer matches by `sku`. If a SKU already exists in the database, it is **updated** (not duplicated). Importing also **replaces all barcodes** for that SKU.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ERROR: could not find a 'Name' column` | Open the Aronium CSV and confirm the first row has column headers. Rename the product-name column to `Name` if it has a different label. |
| Arabic text shows as `???` after conversion | The input was probably saved as Windows-1252. Re-export from Aronium as UTF-8, or open in Excel and re-save as **CSV UTF-8**. |
| Import preview in NUMU POS says "Missing required CSV column" | Don't edit the header row of the converted file. The 23 column names must stay exactly as the script wrote them. |
| Some rows skipped with "missing Name" | Rows without a product name are skipped on purpose. Add a name in the Aronium export and re-run. |
