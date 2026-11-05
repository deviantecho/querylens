"""Bounded spreadsheet parsing and explicit commerce-data normalization."""

import base64
import binascii
import csv
import io
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import PureWindowsPath
from zipfile import ZipFile

from querylens.errors import QueryError

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 10_000
MAX_COLUMNS = 50
MAX_CELLS = 100_000
CURRENCIES = {
    "USD": "$",
    "INR": "₹",
    "EUR": "€",
    "GBP": "£",
    "CAD": "$",
    "AUD": "$",
    "SGD": "$",
    "AED": "",
}
FIELDS = [
    ("order_date", "Order date", True, ["date", "order date", "created at", "purchase date"]),
    (
        "gross_amount",
        "Order amount before refunds",
        True,
        ["amount", "total", "gross", "gross amount", "order total", "sales"],
    ),
    ("order_id", "Order ID", False, ["order id", "order number", "order no", "invoice id"]),
    ("refund_amount", "Refund amount", False, ["refund", "refund amount", "refunded amount"]),
    ("status", "Order status", False, ["status", "order status", "payment status"]),
    ("customer_id", "Customer ID", False, ["customer id", "customer number", "buyer id"]),
    ("customer_name", "Customer name", False, ["customer", "customer name", "buyer name"]),
    ("region", "Customer region", False, ["region", "state", "customer region"]),
    ("channel", "Sales channel", False, ["channel", "sales channel", "source"]),
    ("segment", "Customer segment", False, ["segment", "customer segment"]),
    ("currency", "Currency code", False, ["currency", "currency code"]),
]
STATUS_DEFAULTS = {
    **dict.fromkeys(
        [
            "completed",
            "complete",
            "paid",
            "fulfilled",
            "delivered",
            "refunded",
            "partially refunded",
        ],
        "completed",
    ),
    **dict.fromkeys(["cancelled", "canceled", "void", "voided"], "cancelled"),
}


def clean_header(value):
    return " ".join(re.findall(r"[a-z0-9]+", str(value).lower()))


def cell_text(value):
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if len(text) > 500 or "\x00" in text:
        raise QueryError(
            "A cell is too long or contains a null character. Use a plain orders export."
        )
    return text


@dataclass
class Spreadsheet:
    id: str
    filename: str
    sheet: str
    sheets: list
    headers: list
    rows: list

    def inspection(self):
        mapping = {}
        for key, _, _, aliases in FIELDS:
            matches = [h for h in self.headers if clean_header(h) in {clean_header(key), *aliases}]
            mapping[key] = matches[0] if len(matches) == 1 else ""
        return {
            "upload_id": self.id,
            "filename": self.filename,
            "sheet": self.sheet,
            "sheets": self.sheets,
            "headers": self.headers,
            "row_count": len(self.rows),
            "preview": self.rows[:5],
            "mapping": mapping,
            "fields": [
                {"key": k, "label": label, "required": required} for k, label, required, _ in FIELDS
            ],
            "currencies": list(CURRENCIES),
        }


def parse_spreadsheet(body):
    filename, encoded = body.get("filename"), body.get("content")
    if not isinstance(filename, str) or not isinstance(encoded, str):
        raise QueryError("Choose a CSV or XLSX file.")
    filename = PureWindowsPath(filename).name[:120]
    extension = filename.lower().rsplit(".", 1)[-1]
    if extension not in {"csv", "xlsx"}:
        raise QueryError(
            "Use a .csv or .xlsx orders spreadsheet. Older .xls and macro files are not supported."
        )
    if len(encoded) > ((MAX_FILE_BYTES + 2) // 3) * 4:
        raise QueryError("The file exceeds the 2 MB upload limit.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise QueryError("The upload is incomplete. Choose the file again.") from error
    if not content or len(content) > MAX_FILE_BYTES:
        raise QueryError("Choose a non-empty file no larger than 2 MB.")
    sheet, sheets = "CSV", ["CSV"]
    if extension == "csv":
        try:
            text = content.decode("utf-8-sig")
            try:
                dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            return _collect(
                filename, sheet, sheets, csv.reader(io.StringIO(text), dialect, strict=True)
            )
        except (UnicodeError, csv.Error) as error:
            raise QueryError(
                "Save the sheet as UTF-8 CSV, or upload the original XLSX workbook."
            ) from error
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 256 or sum(e.file_size for e in entries) > 16 * 1024 * 1024:
                raise QueryError(
                    "This workbook expands beyond the upload limit. Export just the orders sheet as CSV."
                )
            if any(
                e.flag_bits & 1
                or "vbaproject" in e.filename.lower()
                or "externallinks/" in e.filename.lower()
                for e in entries
            ):
                raise QueryError(
                    "Use a workbook without encryption, macros, or external workbook links."
                )
        from openpyxl import load_workbook

        book = load_workbook(io.BytesIO(content), read_only=True, data_only=False, keep_links=False)
        try:
            sheets = [s.title for s in book.worksheets if s.sheet_state == "visible"]
            if not sheets or len(sheets) > 20:
                raise QueryError("Use a workbook with 1 to 20 visible worksheets.")
            sheet = body.get("sheet") or sheets[0]
            if not isinstance(sheet, str) or sheet not in sheets:
                raise QueryError("Choose one of the workbook's visible sheets.")
            worksheet = book[sheet]
            # Do not trust a worksheet's cached dimensions or allocate a huge sparse rectangle.
            worksheet.reset_dimensions()

            def values():
                for row in worksheet.iter_rows(max_col=MAX_COLUMNS + 1):
                    if any(c.data_type in {"f", "e"} for c in row):
                        raise QueryError(
                            "The sheet contains a formula or an Excel error. Export calculated values as CSV first."
                        )
                    yield [c.value for c in row]

            return _collect(filename, sheet, sheets, values())
        finally:
            book.close()
    except QueryError:
        raise
    except Exception as error:
        raise QueryError(
            "This XLSX file could not be read. Try a plain orders export saved as CSV."
        ) from error


def _collect(filename, sheet, sheets, records):
    headers, rows, cells, characters = None, [], 0, 0
    for line, raw in enumerate(records, 1):
        if line > MAX_ROWS + 101:
            raise QueryError(
                "The sheet has too many rows, including blank rows. Keep up to 10,000 orders."
            )
        row = [cell_text(v) for v in raw]
        while row and not row[-1]:
            row.pop()
        if not row:
            continue
        if len(row) > MAX_COLUMNS:
            raise QueryError("Keep no more than 50 columns in the orders sheet.")
        if headers is None:
            if line != 1:
                raise QueryError(
                    "Put column names in the first row, with no title or blank rows above them."
                )
            if any(not h for h in row) or len({h.casefold() for h in row}) != len(row):
                raise QueryError("Each column needs a unique, non-empty name in the first row.")
            headers = row
            continue
        if len(row) > len(headers):
            raise QueryError(
                f"Row {line} has more cells than the header. Check the CSV separator or missing column names."
            )
        cells += len(headers)
        characters += sum(map(len, row))
        if len(rows) >= MAX_ROWS or cells > MAX_CELLS or characters > 2_000_000:
            raise QueryError("Keep up to 10,000 orders and 100,000 cells in a single upload.")
        rows.append(
            {
                "line": line,
                "values": row + [""] * (len(headers) - len(row)),
                "numeric_columns": [
                    i
                    for i, v in enumerate(raw)
                    if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)
                ],
            }
        )
    if headers is None or not rows:
        raise QueryError("The sheet needs column names and at least one order.")
    return Spreadsheet(uuid.uuid4().hex, filename, sheet, sheets, headers, rows)


def status_values(sheet, column):
    if column not in sheet.headers:
        return []
    index = sheet.headers.index(column)
    return sorted({r["values"][index] for r in sheet.rows})[:51]


def _amount(value, currency, decimal_mark):
    text = value.strip().replace("\u00a0", "").replace(" ", "")
    symbol = CURRENCIES[currency]
    if text.upper().startswith(currency):
        text = text[len(currency) :]
    if symbol and text.startswith(symbol):
        text = text[len(symbol) :]
    # A selected number format makes 1,234 and 1.234 unambiguous.
    pattern = (
        r"\d+(?:,\d{3})*(?:\.\d{1,2})?" if decimal_mark == "." else r"\d+(?:\.\d{3})*(?:,\d{1,2})?"
    )
    if not re.fullmatch(pattern, text):
        raise ValueError(
            "Use a non-negative amount with at most two decimal places in the selected number format."
        )
    text = text.replace("," if decimal_mark == "." else ".", "")
    if decimal_mark == ",":
        text = text.replace(",", ".")
    try:
        amount = Decimal(text)
    except InvalidOperation as error:
        raise ValueError("Enter a valid amount.") from error
    if not amount.is_finite() or amount > Decimal("1000000000"):
        raise ValueError("Amounts must be between zero and 1,000,000,000.")
    return amount


def _date(value, date_format):
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ].*)?", value):
        return (
            date.fromisoformat(value)
            if len(value) == 10
            else datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        )
    patterns = {"dmy": "%d/%m/%Y", "mdy": "%m/%d/%Y"}
    if date_format not in patterns:
        raise ValueError("Use YYYY-MM-DD dates, or select the matching day/month date format.")
    return datetime.strptime(value, patterns[date_format]).date()


def validate_sheet(sheet, body):
    mapping = body.get("mapping")
    options = body.get("options")
    if not isinstance(mapping, dict) or not isinstance(options, dict):
        raise QueryError("Match the spreadsheet columns before checking your data.")
    known = {f[0] for f in FIELDS}
    if any(
        k not in known or not isinstance(v, str) or (v and v not in sheet.headers)
        for k, v in mapping.items()
    ):
        raise QueryError("A selected column is not in this sheet. Match the columns again.")
    selected = [v for v in mapping.values() if v]
    if len(selected) != len(set(selected)):
        raise QueryError("Use a different spreadsheet column for each field.")
    if any(not mapping.get(key) for key in ("order_date", "gross_amount")):
        raise QueryError("Match both the order date and the order amount.")
    if mapping.get("customer_name") and not mapping.get("customer_id"):
        raise QueryError(
            "Match a customer ID column before using customer names, or leave customer names unused."
        )
    if options.get("one_row_per_order") is not True or options.get("confirm_defaults") is not True:
        raise QueryError("Confirm one row per order and review the missing-column assumptions.")
    currency = options.get("currency", "USD")
    decimal_mark = options.get("decimal_mark", ".")
    date_format = options.get("date_format", "iso")
    if not all(isinstance(v, str) for v in (currency, decimal_mark, date_format)) or (
        currency not in CURRENCIES
        or decimal_mark not in {".", ","}
        or date_format not in {"iso", "dmy", "mdy"}
    ):
        raise QueryError("Choose one of the listed currencies, number formats, and date formats.")
    shop = options.get("shop_name", "My shop")
    if not isinstance(shop, str) or not 1 <= len(shop.strip()) <= 80:
        raise QueryError("Enter a shop name of 1 to 80 characters.")
    status_map = options.get("status_map", {})
    if (
        not isinstance(status_map, dict)
        or len(status_map) > 50
        or any(
            not isinstance(k, str) or v not in {"completed", "cancelled"}
            for k, v in status_map.items()
        )
    ):
        raise QueryError("Map every order status to completed or cancelled.")
    indices = {key: sheet.headers.index(column) for key, column in mapping.items() if column}
    customers, seen_orders, orders, errors = {}, set(), [], []
    total_gross = total_refunds = total_net = Decimal(0)
    completed = 0
    for record in sheet.rows:

        def value(key, default=""):
            return record["values"][indices[key]] if key in indices else default

        def amount(key, default=""):
            mark = "." if indices.get(key) in record.get("numeric_columns", []) else decimal_mark
            return _amount(value(key, default), currency, mark)

        try:
            order_key = value("order_id", str(record["line"]))
            if not order_key or order_key in seen_orders:
                raise ValueError(
                    "Order IDs must be non-empty and unique. Combine line items into one row per order."
                )
            seen_orders.add(order_key)
            ordered = _date(value("order_date"), date_format)
            gross = amount("gross_amount")
            refund = amount("refund_amount", "0")
            if refund > gross:
                raise ValueError("The refund is larger than the order amount.")
            if "currency" in indices and value("currency").upper() != currency:
                raise ValueError(
                    f"Every row must use {currency}. Mixed currencies need separate uploads."
                )
            raw_status = value("status", "completed")
            status = (
                (status_map.get(raw_status) or STATUS_DEFAULTS.get(raw_status.lower()))
                if "status" in indices
                else "completed"
            )
            if status is None:
                raise ValueError(
                    "Choose completed or cancelled for this order status in the column-matching step."
                )
            customer_key = value("customer_id", "unspecified")
            if not customer_key:
                raise ValueError(
                    "Customer IDs must be non-empty when a customer ID column is selected."
                )
            name = value(
                "customer_name",
                f"Customer {customer_key}" if "customer_id" in indices else "Unspecified customer",
            )
            region, segment = value("region", "Unspecified"), value("segment", "Unspecified")
            channel = value("channel", "Unspecified")
            if not all([name, region, segment, channel]):
                raise ValueError(
                    "Selected customer, region, segment, and channel columns cannot contain blank cells."
                )
            # When customer IDs are absent, preserve region grouping without inventing repeat buyers.
            identity = customer_key if "customer_id" in indices else (customer_key, region, segment)
            details = (name, region, segment)
            if identity in customers and customers[identity][1:] != details:
                raise ValueError(
                    "The same customer ID has conflicting names, regions, or segments."
                )
            if identity not in customers:
                customers[identity] = (len(customers) + 1, *details)
            orders.append(
                (
                    len(orders) + 1,
                    customers[identity][0],
                    ordered,
                    channel,
                    status,
                    float(gross),
                    float(refund),
                )
            )
            if status == "completed":
                completed += 1
                total_gross += gross
                total_refunds += refund
                total_net += gross - refund
        except (ValueError, OverflowError) as error:
            errors.append({"row": record["line"], "message": str(error)[:250]})
    if errors:
        return {"valid": False, "error_count": len(errors), "errors": errors[:20]}, None
    dates = [o[2] for o in orders]
    if (max(dates) - min(dates)).days > 3660:
        raise QueryError("Use a reporting window of no more than ten years per upload.")
    warnings = []
    defaults = {
        "order_id": "Internal order IDs will be generated; duplicate orders cannot be identified without your order IDs.",
        "refund_amount": "No refund column: every refund is assumed to be zero.",
        "status": "No status column: every order is assumed to be completed.",
        "customer_id": "No customer IDs: repeat customers and customer rankings are unavailable. Names alone are not treated as identities.",
        "channel": "No sales channel: the channel breakdown is unavailable.",
        "region": "No customer region: the regional breakdown is unavailable.",
    }
    for key, message in defaults.items():
        if key not in indices:
            warnings.append(message)
    if "status" in indices and any(o[4] == "cancelled" and o[6] for o in orders):
        warnings.append(
            "Cancelled orders and their refunds contribute zero to the revenue and refund-rate reports."
        )
    info = {
        "id": uuid.uuid4().hex,
        "kind": "upload",
        "shop_name": shop.strip(),
        "filename": sheet.filename,
        "sheet": sheet.sheet,
        "currency": currency,
        "start": min(dates).isoformat(),
        "end": max(dates).isoformat(),
        "order_count": len(orders),
        "customer_count": len(customers) if "customer_id" in indices else None,
        "channels": sorted({o[3] for o in orders}),
        "regions": sorted({c[2] for c in customers.values()}),
        "unavailable_fields": [
            key for key in ("channel", "region", "segment") if key not in indices
        ]
        + ([] if "customer_id" in indices else ["customer_name"]),
        "warnings": warnings,
    }
    metrics = {
        "net_revenue": float(total_net),
        "completed_orders": completed,
        "average_order_value": round(float(total_net / completed), 2) if completed else None,
        "refund_rate_pct": round(float(total_refunds / total_gross * 100), 2)
        if total_gross
        else None,
    }
    preview = {
        "valid": True,
        "preview_id": info["id"],
        "dataset": info,
        "metrics": metrics,
        "sample": [list(o[:2]) + [o[2].isoformat()] + list(o[3:]) for o in orders[:5]],
    }
    return preview, {"orders": orders, "customers": list(customers.values()), "info": info}


def dataset_rules(info):
    return [
        {
            "id": "net-revenue",
            "title": "Net revenue",
            "text": f"Net revenue is gross_amount minus refund_amount for completed orders only; cancelled orders contribute zero. All money uses {info['currency']}.",
        },
        {
            "id": "average-order",
            "title": "Average order value",
            "text": "Divide total net revenue by the number of completed orders; exclude cancelled orders from the denominator.",
        },
        {
            "id": "refund-rate",
            "title": "Refund rate",
            "text": "Refunded amount divided by gross amount among completed orders, multiplied by 100; this is an amount ratio, not an order count.",
        },
        {
            "id": "customers",
            "title": "Customer relationships",
            "text": "Join orders.customer_id to customers.customer_id. Imported identifiers are translated to internal numeric IDs. Missing dimensions are labelled Unspecified; do not infer missing business facts.",
        },
        {
            "id": "time",
            "title": "Reporting window",
            "text": f"This uploaded shop dataset covers {info['start']} through {info['end']}. Group months using DATE_TRUNC('month', order_date).",
        },
        {
            "id": "channels",
            "title": "Uploaded data coverage",
            "text": f"Channels: {', '.join(info['channels'][:20])}. Regions: {', '.join(info['regions'][:20])}. Unavailable columns: {', '.join(info['unavailable_fields']) or 'none'}. No product, cost, advertising, or forecasting data is supplied.",
        },
    ]
