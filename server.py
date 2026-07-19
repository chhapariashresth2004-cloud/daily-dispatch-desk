from __future__ import annotations

import base64
import cgi
import hashlib
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency safety
    PdfReader = None

ROOT = Path(__file__).resolve().parent


def first_usable_dir(*candidates: Path) -> Path:
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError:
            continue
    fallback = Path(tempfile.gettempdir()) / "daily-dispatch-desk-data"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def configured_data_dir() -> Path:
    candidates = []
    env_dir = os.environ.get("DISPATCH_DATA_DIR") or os.environ.get("DATA_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    if os.environ.get("RENDER"):
        candidates.append(Path("/var/data"))
    candidates.extend([ROOT / "data", Path(tempfile.gettempdir()) / "daily-dispatch-desk-data"])
    return first_usable_dir(*candidates)


DATA_DIR = configured_data_dir()
UPLOAD_DIR = first_usable_dir(DATA_DIR / "uploads", ROOT / "uploads", Path(tempfile.gettempdir()) / "daily-dispatch-desk-uploads")
BILLS_DIR = UPLOAD_DIR / "bills"
PRODUCT_PHOTOS_DIR = UPLOAD_DIR / "product-photos"
BILTY_PHOTOS_DIR = UPLOAD_DIR / "bilty-photos"
LEGACY_JSON_PATH = DATA_DIR / "dispatches.json"
DB_PATH = DATA_DIR / "dispatches.db"
SESSION_COOKIE = "dispatch_session"
SESSION_TTL_SECONDS = 60 * 60 * 12
MAX_FILE_SIZE = 18 * 1024 * 1024
ACTIVE_DISPATCHER_STATUSES = {
    "assigned",
    "goods-photo-uploaded",
    "goods-submitted-for-review",
    "goods-needs-correction",
    "goods-approved",
    "packing",
    "product-photo-uploaded",
    "needs-correction",
}
SUBMITTED_STATUSES = {
    "submitted-for-review",
    "approved-by-reviewer",
    "dispatch-pending",
    "dispatched",
    "delivered",
    "completed",
    "cancelled",
}
DEFAULT_USERS = [
    ("admin-1", "Admin", "admin", "admin123", "admin"),
    ("reviewer-1", "Reviewer 1", "reviewer1", "reviewer123", "reviewer"),
    ("reviewer-2", "Reviewer 2", "reviewer2", "reviewer123", "reviewer"),
    ("dispatcher-1", "Dispatcher 1", "dispatcher1", "dispatcher123", "dispatcher"),
    ("dispatcher-2", "Dispatcher 2", "dispatcher2", "dispatcher123", "dispatcher"),
    ("dispatcher-3", "Dispatcher 3", "dispatcher3", "dispatcher123", "dispatcher"),
    ("dispatcher-4", "Dispatcher 4", "dispatcher4", "dispatcher123", "dispatcher"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upload_url_to_path(file_url: str) -> Path:
    clean = (file_url or "").split("?", 1)[0]
    if clean.startswith("/uploads/"):
        return UPLOAD_DIR / clean.removeprefix("/uploads/")
    return ROOT / clean.lstrip("/")


def upload_member_relative_path(member_name: str) -> Path | None:
    clean = member_name.replace("\\", "/").lstrip("/")
    parts = [part for part in clean.split("/") if part]
    if "uploads" not in parts:
        return None
    upload_index = parts.index("uploads")
    relative_parts = parts[upload_index + 1 :]
    if not relative_parts:
        return None
    return Path(*relative_parts)


def switch_to_ephemeral_storage() -> None:
    """Fallback for free Render when /var/data is configured but no paid disk exists."""
    global DATA_DIR, UPLOAD_DIR, BILLS_DIR, PRODUCT_PHOTOS_DIR, BILTY_PHOTOS_DIR, LEGACY_JSON_PATH, DB_PATH
    DATA_DIR = first_usable_dir(ROOT / "data", Path(tempfile.gettempdir()) / "daily-dispatch-desk-data")
    UPLOAD_DIR = first_usable_dir(DATA_DIR / "uploads", ROOT / "uploads", Path(tempfile.gettempdir()) / "daily-dispatch-desk-uploads")
    BILLS_DIR = UPLOAD_DIR / "bills"
    PRODUCT_PHOTOS_DIR = UPLOAD_DIR / "product-photos"
    BILTY_PHOTOS_DIR = UPLOAD_DIR / "bilty-photos"
    LEGACY_JSON_PATH = DATA_DIR / "dispatches.json"
    DB_PATH = DATA_DIR / "dispatches.db"


def ensure_storage() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        BILLS_DIR.mkdir(parents=True, exist_ok=True)
        PRODUCT_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
        BILTY_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        switch_to_ephemeral_storage()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        BILLS_DIR.mkdir(parents=True, exist_ok=True)
        PRODUCT_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
        BILTY_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    migrate_legacy_json_if_needed()


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with db_connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email_or_mobile TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('reviewer', 'dispatcher', 'admin')),
                active_status INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS dispatch_jobs (
                id TEXT PRIMARY KEY,
                daily_entry_no INTEGER,
                dispatch_date TEXT,
                invoice_number TEXT,
                party_name TEXT NOT NULL,
                party_city TEXT,
                party_mobile_number TEXT,
                place TEXT NOT NULL,
                bill_date TEXT,
                bill_file_url TEXT,
                extracted_bill_data_json TEXT,
                total_cases INTEGER NOT NULL DEFAULT 0,
                total_packages INTEGER NOT NULL DEFAULT 0,
                total_packed_cases INTEGER NOT NULL DEFAULT 0,
                total_amount REAL,
                bill_items_json TEXT,
                current_status TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'normal',
                uploaded_by TEXT,
                dispatcher_id TEXT,
                reviewer_id TEXT,
                transporter_delivery_partner_name TEXT,
                delivery_partner_name TEXT,
                transport_mode TEXT,
                transport_name TEXT,
                delivery_route TEXT,
                route_sequence INTEGER,
                route_batch_id TEXT,
                package_count_difference INTEGER,
                package_difference_reason TEXT,
                package_difference_note TEXT,
                shortage_reason TEXT,
                shortage_note TEXT,
                shortage_items_json TEXT,
                optional_reference_number TEXT,
                bilty_photo_url TEXT,
                bilty_date TEXT,
                bilty_package_count INTEGER,
                bilty_value REAL,
                freight_amount REAL,
                dispatcher_note TEXT,
                reviewer_note TEXT,
                admin_note TEXT,
                admin_override_by TEXT,
                whatsapp_sent_status TEXT,
                whatsapp_sent_at TEXT,
                whatsapp_message_id TEXT,
                whatsapp_failed_reason TEXT,
                ai_check_status TEXT,
                ai_detected_box_count INTEGER,
                ai_detected_party_marking TEXT,
                ai_detected_package_count INTEGER,
                ai_detected_bilty_number TEXT,
                ai_detected_bilty_transport_name TEXT,
                ai_detected_bilty_package_count INTEGER,
                ai_detected_bilty_date TEXT,
                ai_photo_quality_score REAL,
                ai_match_score REAL,
                ai_risk_level TEXT,
                ai_summary TEXT,
                ai_checked_at TEXT,
                ai_model_version TEXT,
                bill_uploaded_at TEXT,
                job_claimed_at TEXT,
                packing_started_at TEXT,
                product_photo_uploaded_at TEXT,
                submitted_for_review_at TEXT,
                reviewed_at TEXT,
                correction_sent_at TEXT,
                correction_resubmitted_at TEXT,
                reviewer_approved_at TEXT,
                dispatched_at TEXT,
                delivered_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS packing_breakup (
                id TEXT PRIMARY KEY,
                dispatch_job_id TEXT NOT NULL,
                packing_type TEXT NOT NULL,
                no_of_packages INTEGER NOT NULL DEFAULT 0,
                cases_per_package INTEGER NOT NULL DEFAULT 0,
                total_cases INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(dispatch_job_id) REFERENCES dispatch_jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS packing_details (
                id TEXT PRIMARY KEY,
                dispatch_job_id TEXT NOT NULL UNIQUE,
                packing_breakup_json TEXT,
                number_of_boxes INTEGER,
                number_of_cases INTEGER,
                dispatcher_note TEXT,
                product_photo_url TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(dispatch_job_id) REFERENCES dispatch_jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS review_details (
                id TEXT PRIMARY KEY,
                dispatch_job_id TEXT NOT NULL,
                reviewer_id TEXT,
                review_decision TEXT,
                reviewer_note TEXT,
                transporter_delivery_partner_name TEXT,
                reviewed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(dispatch_job_id) REFERENCES dispatch_jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS bilty_details (
                id TEXT PRIMARY KEY,
                dispatch_job_id TEXT NOT NULL UNIQUE,
                bilty_number TEXT,
                bilty_photo_url TEXT,
                delivery_partner_name TEXT,
                bilty_uploaded_by TEXT,
                bilty_uploaded_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(dispatch_job_id) REFERENCES dispatch_jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS photos (
                id TEXT PRIMARY KEY,
                dispatch_job_id TEXT NOT NULL,
                photo_type TEXT NOT NULL,
                file_url TEXT NOT NULL,
                uploaded_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(dispatch_job_id) REFERENCES dispatch_jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS activity_logs (
                id TEXT PRIMARY KEY,
                dispatch_job_id TEXT,
                user_id TEXT,
                user_role TEXT,
                action_type TEXT NOT NULL,
                old_status TEXT,
                new_status TEXT,
                remarks TEXT,
                metadata_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(dispatch_job_id) REFERENCES dispatch_jobs(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS ai_photo_checks (
                id TEXT PRIMARY KEY,
                dispatch_job_id TEXT NOT NULL UNIQUE,
                ai_check_status TEXT,
                ai_match_score REAL,
                ai_risk_level TEXT,
                ai_detected_items_json TEXT,
                ai_missing_items_json TEXT,
                ai_extra_items_json TEXT,
                ai_quantity_mismatch_json TEXT,
                ai_photo_quality_score REAL,
                ai_summary TEXT,
                ai_checked_at TEXT,
                ai_model_version TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(dispatch_job_id) REFERENCES dispatch_jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS auth_sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS delivery_partners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                active_status INTEGER NOT NULL DEFAULT 1,
                cost_per_package REAL NOT NULL DEFAULT 10,
                cost_per_bora REAL NOT NULL DEFAULT 40,
                munshiyana_per_transport REAL NOT NULL DEFAULT 20,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                active_status INTEGER NOT NULL DEFAULT 1,
                default_route TEXT,
                default_delivery_partner TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS route_names (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS route_batches (
                id TEXT PRIMARY KEY,
                route_name TEXT NOT NULL,
                delivery_partner_name TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        migrate_schema(conn)
        seed_users(conn)
        seed_directory(conn)
        seed_routes(conn)


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def migrate_schema(conn: sqlite3.Connection) -> None:
    job_columns = table_columns(conn, "dispatch_jobs")
    additions = {
        "daily_entry_no": "INTEGER",
        "dispatch_date": "TEXT",
        "party_city": "TEXT",
        "party_mobile_number": "TEXT",
        "invoice_number": "TEXT",
        "total_amount": "REAL",
        "bill_items_json": "TEXT",
        "total_packages": "INTEGER NOT NULL DEFAULT 0",
        "total_packed_cases": "INTEGER NOT NULL DEFAULT 0",
        "delivery_partner_name": "TEXT",
        "transport_mode": "TEXT",
        "transport_name": "TEXT",
        "delivery_route": "TEXT",
        "route_sequence": "INTEGER",
        "route_batch_id": "TEXT",
        "package_count_difference": "INTEGER",
        "package_difference_reason": "TEXT",
        "package_difference_note": "TEXT",
        "shortage_reason": "TEXT",
        "shortage_note": "TEXT",
        "shortage_items_json": "TEXT",
        "optional_reference_number": "TEXT",
        "bilty_photo_url": "TEXT",
        "bilty_date": "TEXT",
        "bilty_package_count": "INTEGER",
        "bilty_value": "REAL",
        "freight_amount": "REAL",
        "admin_note": "TEXT",
        "admin_override_by": "TEXT",
        "whatsapp_sent_status": "TEXT",
        "whatsapp_sent_at": "TEXT",
        "whatsapp_message_id": "TEXT",
        "whatsapp_failed_reason": "TEXT",
        "ai_check_status": "TEXT",
        "ai_detected_box_count": "INTEGER",
        "ai_detected_party_marking": "TEXT",
        "ai_detected_package_count": "INTEGER",
        "ai_detected_bilty_number": "TEXT",
        "ai_detected_bilty_transport_name": "TEXT",
        "ai_detected_bilty_package_count": "INTEGER",
        "ai_detected_bilty_date": "TEXT",
        "ai_photo_quality_score": "REAL",
        "ai_match_score": "REAL",
        "ai_risk_level": "TEXT",
        "ai_summary": "TEXT",
        "ai_checked_at": "TEXT",
        "ai_model_version": "TEXT",
        "bill_uploaded_at": "TEXT",
        "job_claimed_at": "TEXT",
        "packing_started_at": "TEXT",
        "product_photo_uploaded_at": "TEXT",
        "submitted_for_review_at": "TEXT",
        "reviewed_at": "TEXT",
        "correction_sent_at": "TEXT",
        "correction_resubmitted_at": "TEXT",
        "reviewer_approved_at": "TEXT",
        "dispatched_at": "TEXT",
        "delivered_at": "TEXT",
        "completed_at": "TEXT",
    }
    for column, definition in additions.items():
        if column not in job_columns:
            conn.execute(f"ALTER TABLE dispatch_jobs ADD COLUMN {column} {definition}")

    if "bill_date" in job_columns and "invoice_number" in additions:
        conn.execute("UPDATE dispatch_jobs SET dispatch_date = COALESCE(dispatch_date, bill_date)")
    conn.execute("UPDATE dispatch_jobs SET party_city = COALESCE(NULLIF(party_city, ''), place)")
    conn.execute("UPDATE dispatch_jobs SET total_packages = COALESCE(total_packages, 0), total_packed_cases = COALESCE(total_packed_cases, 0)")
    conn.execute("UPDATE dispatch_jobs SET dispatch_date = COALESCE(dispatch_date, substr(created_at, 1, 10))")

    partner_columns = table_columns(conn, "delivery_partners")
    partner_additions = {
        "cost_per_package": "REAL NOT NULL DEFAULT 10",
        "cost_per_bora": "REAL NOT NULL DEFAULT 40",
        "munshiyana_per_transport": "REAL NOT NULL DEFAULT 20",
    }
    for column, definition in partner_additions.items():
        if column not in partner_columns:
            conn.execute(f"ALTER TABLE delivery_partners ADD COLUMN {column} {definition}")

    transport_columns = table_columns(conn, "transports")
    for column, definition in {"default_route": "TEXT", "default_delivery_partner": "TEXT"}.items():
        if column not in transport_columns:
            conn.execute(f"ALTER TABLE transports ADD COLUMN {column} {definition}")

    packing_columns = table_columns(conn, "packing_details")
    if "product_photo_url" not in packing_columns:
        conn.execute("ALTER TABLE packing_details ADD COLUMN product_photo_url TEXT")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"sha256${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split("$", 2)
    except ValueError:
        return False
    if scheme != "sha256":
        return False
    check = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return secrets.compare_digest(check, digest)


def seed_users(conn: sqlite3.Connection) -> None:
    timestamp = now_iso()
    for user_id, name, login, password, role in DEFAULT_USERS:
        existing = conn.execute("SELECT id FROM users WHERE id = ? OR email_or_mobile = ?", (user_id, login)).fetchone()
        if existing:
            continue
        conn.execute(
            """
            INSERT INTO users (id, name, email_or_mobile, password_hash, role, active_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (user_id, name, login, hash_password(password), role, timestamp, timestamp),
        )


def seed_directory(conn: sqlite3.Connection) -> None:
    timestamp = now_iso()
    for name in ["Ravi", "Shubham", "Janak", "Shiva", "Bajrang", "Self"]:
        conn.execute(
            """
            INSERT OR IGNORE INTO delivery_partners (name, active_status, cost_per_package, cost_per_bora, munshiyana_per_transport, created_at, updated_at)
            VALUES (?, 1, 10, 40, 20, ?, ?)
            """,
            (name, timestamp, timestamp),
        )
    for name, route, partner in [
        ("New Bajrang Transport", "Route 1", "Ravi"),
        ("Vikash Roadways", "Route 2", "Shubham"),
        ("Shubham Transport", "Route 3", "Shubham"),
        ("Bhardwaj Transport", "Route 1", "Janak"),
        ("Janta", "Route 2", "Janak"),
        ("Self", "Route 1", "Self"),
    ]:
        conn.execute(
            """
            INSERT OR IGNORE INTO transports (name, active_status, default_route, default_delivery_partner, created_at, updated_at)
            VALUES (?, 1, ?, ?, ?, ?)
            """,
            (name, route, partner, timestamp, timestamp),
        )


def seed_routes(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) FROM route_names").fetchone()[0]:
        return
    conn.executemany("INSERT INTO route_names (id, name) VALUES (?, ?)", [(1, "Route 1"), (2, "Route 2"), (3, "Route 3")])


def json_loads(value, fallback):
    if value is None or value == "":
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def normalize_status(value: str) -> str:
    value = (value or "Ready").strip().lower().replace(" ", "-").replace("_", "-")
    aliases = {
        "approved": "approved-by-reviewer",
        "ready-for-dispatch": "dispatch-pending",
        "bilty-pending": "dispatch-pending",
        "product-photo-uploaded": "product-photo-uploaded",
    }
    return aliases.get(value, value or "ready")


def normalize_photo_type(value: str) -> str:
    value = (value or "packing").strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "product": "packing",
        "product-photo": "packing",
        "pre-dispatch": "pre-dispatch",
        "pre-dispatch-photo": "pre-dispatch",
        "final-packing": "packing",
        "packing-photo": "packing",
        "closeup": "close-up-marking",
        "close-up": "close-up-marking",
        "goods": "goods-check",
        "goods-photo": "goods-check",
        "picked-goods": "goods-check",
        "picked-goods-photo": "goods-check",
        "bilty": "bilty",
        "bilty-photo": "bilty",
        "delivery-proof": "delivery-proof",
    }
    return aliases.get(value, value)


def normalize_bill_items(raw_items) -> list[dict]:
    items = []
    if not isinstance(raw_items, list):
        return items
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("productName") or item.get("description") or "").strip()
        qty = item.get("quantity", item.get("billedQuantity", item.get("cases", item.get("qty", 0))))
        try:
            qty = int(float(qty or 0))
        except (TypeError, ValueError):
            qty = 0
        if name:
            items.append({"id": item.get("id") or str(uuid.uuid4()), "name": name, "quantity": qty})
    return items


def normalize_exception_items(raw_items) -> list[dict]:
    items = []
    if not isinstance(raw_items, list):
        return items
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("productName") or "").strip()
        if not name:
            continue
        exception_type = str(item.get("exceptionType") or item.get("type") or "short").strip() or "short"
        reason = str(item.get("reason") or "").strip()
        note = str(item.get("note") or "").strip()
        try:
            billed = int(float(item.get("billedQuantity", item.get("quantity", 0)) or 0))
        except (TypeError, ValueError):
            billed = 0
        try:
            actual = int(float(item.get("actualQuantity", billed) or 0))
        except (TypeError, ValueError):
            actual = billed
        try:
            short_qty = int(float(item.get("shortQuantity", abs(billed - actual)) or 0))
        except (TypeError, ValueError):
            short_qty = abs(billed - actual)
        items.append({
            "id": item.get("id") or str(uuid.uuid4()),
            "name": name,
            "exceptionType": exception_type,
            "billedQuantity": billed,
            "actualQuantity": actual,
            "shortQuantity": short_qty,
            "reason": reason,
            "note": note,
        })
    return items


def exception_item_delta(item: dict) -> int:
    billed = int(item.get("billedQuantity") or 0)
    actual = int(item.get("actualQuantity") or 0)
    short_qty = int(item.get("shortQuantity") or 0)
    exception_type = str(item.get("exceptionType") or "short").lower()
    if exception_type == "extra":
        return abs(short_qty) if short_qty else max(0, actual - billed)
    if exception_type in {"mrp_mismatch", "substitute"}:
        return 0
    if short_qty:
        return -abs(short_qty)
    return actual - billed


def exception_items_match_delta(raw_items, expected_delta: int) -> bool:
    items = normalize_exception_items(raw_items)
    if not expected_delta:
        return True
    actual_delta = sum(
        exception_item_delta(item)
        for item in items
        if str(item.get("exceptionType") or "short").lower() not in {"mrp_mismatch", "substitute"}
    )
    return actual_delta == expected_delta


def packing_summary(packing) -> str:
    lines = normalize_packing_lines(packing)
    parts = [
        f"{line['packageType']} | {line['packageCount']} x {line['casesPerPackage']} = {line['totalCases']} cases"
        for line in lines
    ]
    return ", ".join(parts) if parts else "No packing breakup added yet."


def extract_invoice_from_pdf(file_path: Path) -> dict:
    if PdfReader is None:
        return {"error": "PDF extraction dependency not available"}
    try:
        reader = PdfReader(str(file_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # pragma: no cover - third-party parser
        return {"error": str(exc)}

    compact = re.sub(r"[ \t]+", " ", text)
    upper = compact.upper()

    def first_match(patterns):
        for pattern in patterns:
            match = re.search(pattern, compact, re.IGNORECASE)
            if match:
                return match.group(1).strip(" :-#\n\t")
        return ""

    invoice_number = first_match([
        r"Invoice\s*(?:No\.?|Number)?\s*[:#-]?\s*([A-Z0-9/-]+)",
        r"Inv\.?\s*No\.?\s*[:#-]?\s*([A-Z0-9/-]+)",
    ])
    invoice_date = first_match([
        r"Invoice\s*Date\s*[:#-]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
        r"Date\s*[:#-]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
    ])
    party_name = first_match([
        r"Party\s*Name\s*[:#-]?\s*(.+?)(?:\n|GST|State|Place|City)",
        r"Bill\s*To\s*[:#-]?\s*(.+?)(?:\n|GST|State|Place|City)",
        r"Buyer\s*[:#-]?\s*(.+?)(?:\n|GST|State|Place|City)",
    ])
    party_city = first_match([
        r"(?:City|Place|Station)\s*[:#-]?\s*([A-Za-z ]{2,40})",
        r"\bTO\s*[:#-]?\s*([A-Za-z ]{2,40})",
    ])
    amount = first_match([
        r"(?:Grand\s*Total|Invoice\s*Total|Net\s*Amount|Total)\s*[:#-]?\s*₹?\s*([0-9,]+(?:\.\d+)?)",
    ])
    freight = first_match([
        r"(?:Freight|Freight\s*Amount|Transport\s*Charge|Delivery\s*Charge)\s*[:#-]?\s*₹?\s*([0-9,]+(?:\.\d+)?)",
    ])

    item_rows = []
    total_cases = 0
    for line in text.splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        if not clean or len(clean) < 5:
            continue
        qty_match = re.search(r"(.+?)\s+(\d+)\s*(?:CS|CASE|CASES|C/S|PCS)?\s*$", clean, re.IGNORECASE)
        if qty_match and not re.search(r"TOTAL|AMOUNT|GST|INVOICE", clean, re.IGNORECASE):
            name = qty_match.group(1).strip(" -|:")
            qty = int(qty_match.group(2))
            if name and qty < 10000:
                item_rows.append({"id": str(uuid.uuid4()), "name": name[:120], "quantity": qty})
                total_cases += qty

    case_match = re.search(r"(?:Total\s*)?(?:Cases|Case|C/S|Cs)\s*[:#-]?\s*(\d+)", compact, re.IGNORECASE)
    if case_match:
        total_cases = int(case_match.group(1))

    if not party_name:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        party_name = next((line for line in lines if len(line) > 5 and not re.search(r"invoice|tax|gst|phone|amount", line, re.I)), "")

    return {
        "invoiceNumber": invoice_number,
        "invoiceDate": invoice_date,
        "partyName": party_name[:80],
        "partyCity": party_city[:40],
        "orderCaseCount": total_cases,
        "invoiceAmount": float(amount.replace(",", "")) if amount else None,
        "freightAmount": float(freight.replace(",", "")) if freight else None,
        "billItems": item_rows[:80],
        "rawTextPreview": text[:1500],
        "transportHint": "Transport" in upper or "LR" in upper or "BILTY" in upper,
    }


def serialize_user(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "emailOrMobile": row["email_or_mobile"],
        "role": row["role"],
        "activeStatus": bool(row["active_status"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def calculate_hisaab(job: dict, partners: list[dict]) -> dict:
    partner_name = job.get("deliveryPartnerName") or job.get("delivery_partner_name") or ""
    partner = next((item for item in partners if item.get("name") == partner_name), {})
    cost_per_package = float(partner.get("costPerPackage") or partner.get("cost_per_package") or 10)
    cost_per_bora = float(partner.get("costPerBora") or partner.get("cost_per_bora") or 40)
    munshiyana = float(partner.get("munshiyanaPerTransport") or partner.get("munshiyana_per_transport") or 20)
    packing_lines = job.get("packingDetails", {}).get("packingBreakup", []) if isinstance(job.get("packingDetails"), dict) else []
    bora_count = sum(int(line.get("packageCount") or 0) for line in packing_lines if str(line.get("packageType") or "").lower() == "bora")
    total_packages = int(job.get("totalPackages") or 0)
    non_bora_packages = max(0, total_packages - bora_count)
    package_cost = non_bora_packages * cost_per_package
    bora_cost = bora_count * cost_per_bora
    transport_fee = munshiyana if str(job.get("transportMode") or "").lower() == "transport" else 0
    return {
        "deliveryPartnerName": partner_name,
        "partyName": job.get("partyName") or job.get("party_name"),
        "transportName": job.get("transportName") or job.get("transport_name") or "",
        "totalPackages": total_packages,
        "boraCount": bora_count,
        "packageCost": package_cost,
        "boraCost": bora_cost,
        "munshiyana": transport_fee,
        "totalCost": package_cost + bora_cost + transport_fee,
    }


def serialize_job(row: sqlite3.Row, conn: sqlite3.Connection | None = None) -> dict:
    job = {
        "id": row["id"],
        "dailyEntryNo": row["daily_entry_no"],
        "dispatchDate": row["dispatch_date"],
        "partyName": row["party_name"],
        "partyCity": row["party_city"] or row["place"],
        "partyMobileNumber": row["party_mobile_number"] or "",
        "place": row["place"],
        "invoiceNumber": row["invoice_number"] or "",
        "billDate": row["bill_date"],
        "invoiceDate": row["bill_date"],
        "billFileUrl": row["bill_file_url"],
        "extractedBillData": json_loads(row["extracted_bill_data_json"], {}),
        "orderCaseCount": row["total_cases"],
        "totalCases": row["total_cases"],
        "totalAmount": row["total_amount"],
        "invoiceAmount": row["total_amount"],
        "billItems": json_loads(row["bill_items_json"], []),
        "totalPackages": row["total_packages"],
        "totalPackedCases": row["total_packed_cases"],
        "currentStatus": row["current_status"],
        "priority": row["priority"],
        "uploadedBy": row["uploaded_by"],
        "dispatcherId": row["dispatcher_id"],
        "reviewerId": row["reviewer_id"],
        "deliveryPartnerName": row["delivery_partner_name"] or row["transporter_delivery_partner_name"] or "",
        "transporterDeliveryPartnerName": row["transporter_delivery_partner_name"] or "",
        "transportMode": row["transport_mode"] or "",
        "transportName": row["transport_name"] or "",
        "deliveryRoute": row["delivery_route"] or "",
        "routeSequence": row["route_sequence"],
        "routeBatchId": row["route_batch_id"],
        "packageCountDifference": row["package_count_difference"],
        "packageDifferenceReason": row["package_difference_reason"] or "",
        "packageDifferenceNote": row["package_difference_note"] or "",
        "shortageReason": row["shortage_reason"] or "",
        "shortageNote": row["shortage_note"] or "",
        "shortageItems": json_loads(row["shortage_items_json"], []),
        "dispatcherNote": row["dispatcher_note"] or "",
        "reviewerNote": row["reviewer_note"] or "",
        "adminNote": row["admin_note"] or "",
        "adminOverrideBy": row["admin_override_by"] or "",
        "optionalReferenceNumber": row["optional_reference_number"] or "",
        "biltyPhotoUrl": row["bilty_photo_url"] or "",
        "biltyPackageCount": row["bilty_package_count"],
        "biltyDate": row["bilty_date"] or "",
        "biltyValue": row["bilty_value"],
        "freightAmount": row["freight_amount"],
        "whatsappSentStatus": row["whatsapp_sent_status"] or "not_ready",
        "aiCheckStatus": row["ai_check_status"] or "not_checked",
        "aiPhotoQualityScore": row["ai_photo_quality_score"],
        "aiMatchScore": row["ai_match_score"],
        "aiRiskLevel": row["ai_risk_level"],
        "aiSummary": row["ai_summary"],
        "timestamps": {
            "billUploadedAt": row["bill_uploaded_at"],
            "jobClaimedAt": row["job_claimed_at"],
            "packingStartedAt": row["packing_started_at"],
            "productPhotoUploadedAt": row["product_photo_uploaded_at"],
            "submittedForReviewAt": row["submitted_for_review_at"],
            "reviewedAt": row["reviewed_at"],
            "correctionSentAt": row["correction_sent_at"],
            "correctionResubmittedAt": row["correction_resubmitted_at"],
            "reviewerApprovedAt": row["reviewer_approved_at"],
            "dispatchedAt": row["dispatched_at"],
            "deliveredAt": row["delivered_at"],
            "completedAt": row["completed_at"],
        },
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "packingDetails": {"packingBreakup": [], "packingPhotos": [], "dispatcherNote": row["dispatcher_note"] or ""},
        "goodsCheck": {"photos": []},
        "biltyDetails": {"biltyPhotoUrl": row["bilty_photo_url"] or "", "optionalReferenceNumber": row["optional_reference_number"] or ""},
    }

    if conn:
        packing_rows = conn.execute(
            "SELECT * FROM packing_breakup WHERE dispatch_job_id = ? ORDER BY created_at, id",
            (row["id"],),
        ).fetchall()
        job["packingDetails"]["packingBreakup"] = [
            {
                "id": item["id"],
                "packageType": item["packing_type"],
                "packageCount": item["no_of_packages"],
                "casesPerPackage": item["cases_per_package"],
                "totalCases": item["total_cases"],
            }
            for item in packing_rows
        ]
        photo_rows = conn.execute(
            "SELECT * FROM photos WHERE dispatch_job_id = ? ORDER BY created_at",
            (row["id"],),
        ).fetchall()
        job["packingDetails"]["packingPhotos"] = [
            {"id": item["id"], "fileUrl": item["file_url"], "photoType": item["photo_type"], "createdAt": item["created_at"]}
            for item in photo_rows
            if item["photo_type"] in {"packing", "pre-dispatch", "final-packing", "product-photo"}
        ]
        job["goodsCheck"] = {
            "photos": [
                {"id": item["id"], "fileUrl": item["file_url"], "photoType": item["photo_type"], "createdAt": item["created_at"]}
                for item in photo_rows
                if item["photo_type"] == "goods-check"
            ]
        }
    return job


def bootstrap_payload(user: sqlite3.Row) -> dict:
    with db_connect() as conn:
        if user["role"] == "dispatcher":
            rows = conn.execute(
                """
                SELECT * FROM dispatch_jobs
                WHERE current_status = 'ready'
                   OR dispatcher_id = ?
                ORDER BY dispatch_date DESC, COALESCE(daily_entry_no, 999999), created_at DESC
                """,
                (user["id"],),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM dispatch_jobs ORDER BY dispatch_date DESC, COALESCE(daily_entry_no, 999999), created_at DESC").fetchall()
        jobs = [serialize_job(row, conn) for row in rows]
        payload = {"user": serialize_user(user), "jobs": jobs, "metrics": calculate_metrics(jobs)}
        if user["role"] in {"admin", "reviewer"}:
            payload["logs"] = [dict(item) for item in conn.execute("SELECT * FROM activity_logs ORDER BY created_at DESC LIMIT 300")]
            payload["routes"] = [dict(item) for item in conn.execute("SELECT * FROM route_names ORDER BY id")]
            payload["routeBatches"] = [dict(item) for item in conn.execute("SELECT * FROM route_batches ORDER BY created_at DESC")]
            payload["deliveryPartners"] = [serialize_partner(item) for item in conn.execute("SELECT * FROM delivery_partners ORDER BY name")]
            payload["transports"] = [serialize_transport(item) for item in conn.execute("SELECT * FROM transports ORDER BY name")]
        if user["role"] == "admin":
            payload["users"] = [serialize_user(item) for item in conn.execute("SELECT * FROM users ORDER BY role, name")]
            payload["reports"] = calculate_reports(jobs, payload.get("logs", []), payload.get("deliveryPartners", []))
            payload["settings"] = {item["key"]: item["value"] for item in conn.execute("SELECT * FROM app_settings")}
        return payload


def calculate_metrics(jobs: list[dict]) -> dict:
    today = datetime.now().date().isoformat()
    return {
        "totalJobs": len(jobs),
        "readyJobs": sum(job["currentStatus"] == "ready" for job in jobs),
        "activeDispatchJobs": sum(job["currentStatus"] in {"assigned", "packing", "product-photo-uploaded"} for job in jobs),
        "submittedForReview": sum(job["currentStatus"] == "submitted-for-review" for job in jobs),
        "needsCorrection": sum(job["currentStatus"] == "needs-correction" for job in jobs),
        "approved": sum(job["currentStatus"] in {"approved-by-reviewer", "dispatch-pending"} for job in jobs),
        "dispatchedToday": sum(job["currentStatus"] == "dispatched" and (job["timestamps"].get("dispatchedAt") or "").startswith(today) for job in jobs),
        "deliveredToday": sum(job["currentStatus"] in {"delivered", "completed"} and (job["timestamps"].get("deliveredAt") or job["timestamps"].get("completedAt") or "").startswith(today) for job in jobs),
        "completedToday": sum(job["currentStatus"] == "completed" and (job["timestamps"].get("completedAt") or "").startswith(today) for job in jobs),
        "delayedJobs": sum(job["currentStatus"] not in {"completed", "cancelled"} and job.get("dispatchDate", today) < today for job in jobs),
    }


def hours_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 3600, 2)
    except ValueError:
        return None


def calculate_reports(jobs: list[dict], logs: list[dict], partners: list[dict] | None = None) -> dict:
    partners = partners or []
    by_dispatcher = {}
    by_reviewer = {}
    by_transport = {}
    by_route = {}
    by_partner = {}
    shortage = []
    difference = []
    hisaab_rows = []
    for job in jobs:
        dispatcher = job.get("dispatcherId") or "Unassigned"
        reviewer = job.get("reviewerId") or "Unreviewed"
        by_dispatcher.setdefault(dispatcher, {"jobs": 0, "completed": 0, "corrections": 0, "hours": []})
        by_dispatcher[dispatcher]["jobs"] += 1
        by_dispatcher[dispatcher]["completed"] += int(job["currentStatus"] == "completed")
        if job["currentStatus"] == "needs-correction" or job.get("shortageItems"):
            by_dispatcher[dispatcher]["corrections"] += 1
        work_hours = hours_between(job["timestamps"].get("jobClaimedAt"), job["timestamps"].get("submittedForReviewAt"))
        if work_hours is not None:
            by_dispatcher[dispatcher]["hours"].append(work_hours)

        by_reviewer.setdefault(reviewer, {"jobs": 0, "approved": 0, "hours": []})
        by_reviewer[reviewer]["jobs"] += 1
        by_reviewer[reviewer]["approved"] += int(job["currentStatus"] in {"approved-by-reviewer", "dispatch-pending", "dispatched", "delivered", "completed"})
        review_hours = hours_between(job["timestamps"].get("submittedForReviewAt"), job["timestamps"].get("reviewerApprovedAt"))
        if review_hours is not None:
            by_reviewer[reviewer]["hours"].append(review_hours)

        transport = job.get("transportName") or "Not set"
        route = job.get("deliveryRoute") or "Not set"
        partner = job.get("deliveryPartnerName") or "Not set"
        by_transport[transport] = by_transport.get(transport, 0) + 1
        by_route[route] = by_route.get(route, 0) + 1
        by_partner[partner] = by_partner.get(partner, 0) + 1
        if job.get("shortageItems") or job.get("shortageReason"):
            shortage.append(job)
        if job.get("packageDifferenceReason"):
            difference.append(job)
        if job.get("currentStatus") in {"dispatched", "delivered", "completed"}:
            hisaab_rows.append(calculate_hisaab(job, partners))

    def average(values):
        return round(sum(values) / len(values), 2) if values else 0

    return {
        "dispatcherProductivity": [
            {"name": key, **{k: v for k, v in value.items() if k != "hours"}, "avgHours": average(value["hours"])} for key, value in by_dispatcher.items()
        ],
        "reviewerProductivity": [
            {"name": key, **{k: v for k, v in value.items() if k != "hours"}, "avgHours": average(value["hours"])} for key, value in by_reviewer.items()
        ],
        "transportReport": by_transport,
        "routeReport": by_route,
        "deliveryPartnerReport": by_partner,
        "shortageReport": shortage,
        "packageDifferenceReport": difference,
        "hisaabReport": hisaab_rows,
        "dailySummary": calculate_metrics(jobs),
    }


def status_label(status: str) -> str:
    labels = {
        "ready": "Ready",
        "assigned": "Assigned",
        "goods-photo-uploaded": "Goods Photo Uploaded",
        "goods-submitted-for-review": "Goods Submitted for Review",
        "goods-needs-correction": "Goods Needs Correction",
        "goods-approved": "Goods Approved",
        "packing": "Packing",
        "product-photo-uploaded": "Product Photo Uploaded",
        "submitted-for-review": "Submitted for Review",
        "needs-correction": "Needs Correction",
        "approved-by-reviewer": "Approved",
        "dispatch-pending": "Dispatch Pending",
        "dispatched": "Dispatched",
        "delivered": "Delivered",
        "completed": "Completed",
        "cancelled": "Cancelled",
    }
    return labels.get(status, status.title())


def log_activity(conn: sqlite3.Connection, user: sqlite3.Row | None, job_id: str | None, action_type: str, old_status: str | None = None, new_status: str | None = None, remarks: str = "", metadata: dict | None = None) -> None:
    conn.execute(
        """
        INSERT INTO activity_logs (id, dispatch_job_id, user_id, user_role, action_type, old_status, new_status, remarks, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            job_id,
            user["id"] if user else None,
            user["role"] if user else None,
            action_type,
            old_status,
            new_status,
            remarks,
            json.dumps(metadata or {}, ensure_ascii=False),
            now_iso(),
        ),
    )


def save_upload(file_item, target_dir: Path) -> str:
    file_name = Path(file_item.filename or "upload.bin").name
    extension = Path(file_name).suffix.lower() or ".bin"
    safe_name = f"{uuid.uuid4()}{extension}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / safe_name
    data = file_item.file.read()
    if len(data) > MAX_FILE_SIZE:
        raise ValueError("File too large. Upload a smaller file.")
    target_path.write_bytes(data)
    return f"/uploads/{target_dir.name}/{safe_name}"


def read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if not length:
        return {}
    data = handler.rfile.read(length)
    try:
        return json.loads(data.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def parse_multipart(handler: BaseHTTPRequestHandler):
    content_type = handler.headers.get("Content-Type", "")
    if not content_type.startswith("multipart/form-data"):
        return None
    environ = {
        "REQUEST_METHOD": "POST",
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": handler.headers.get("Content-Length", "0"),
    }
    return cgi.FieldStorage(fp=handler.rfile, headers=handler.headers, environ=environ)


def field_value(form, key: str, default=""):
    item = form[key] if form and key in form else None
    if item is None:
        return default
    if isinstance(item, list):
        item = item[0]
    if getattr(item, "filename", None):
        return default
    value = item.value
    return value if value is not None else default


class DispatchHandler(BaseHTTPRequestHandler):
    server_version = "DispatchDesk/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.handle_health()
            return
        if parsed.path.startswith("/api/"):
            self.handle_api_get(parsed)
            return
        if parsed.path.startswith("/uploads/"):
            self.serve_file(upload_url_to_path(parsed.path))
            return
        if parsed.path == "/":
            self.serve_file(ROOT / "index.html")
            return
        if parsed.path in {"/index.html", "/styles.css", "/app.js", "/manifest.webmanifest", "/dispatch-icon.svg", "/sw.js"}:
            self.serve_file(ROOT / parsed.path.lstrip("/"))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/login":
            self.handle_login()
            return
        if parsed.path == "/api/logout":
            self.handle_logout()
            return
        user = self.current_user()
        if not user:
            self.send_json({"error": "Login required"}, HTTPStatus.UNAUTHORIZED)
            return
        if parsed.path == "/api/dispatches":
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_create_dispatch(user)
            return
        if parsed.path == "/api/dispatches/bulk-import":
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_bulk_import(user)
            return
        if parsed.path == "/api/route-batches":
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_create_route_batch(user)
            return
        if parsed.path == "/api/directory":
            self.require_roles(user, {"admin"}) and self.handle_create_directory_item()
            return
        if parsed.path == "/api/users":
            self.require_roles(user, {"admin"}) and self.handle_create_user()
            return
        if parsed.path == "/api/admin/backup/import":
            self.require_roles(user, {"admin"}) and self.handle_backup_import(user)
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/claim", parsed.path):
            self.require_roles(user, {"dispatcher"}) and self.handle_claim(match.group(1), user)
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/unassign", parsed.path):
            self.require_roles(user, {"dispatcher", "admin"}) and self.handle_unassign(match.group(1), user)
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/product-photo", parsed.path):
            self.require_roles(user, {"dispatcher"}) and self.handle_product_photo(match.group(1), user)
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/submit-goods-review", parsed.path):
            self.require_roles(user, {"dispatcher"}) and self.handle_submit_goods_review(match.group(1), user)
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/goods-review-decision", parsed.path):
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_goods_review_decision(match.group(1), user)
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/closeup-photo", parsed.path):
            self.require_roles(user, {"dispatcher"}) and self.handle_product_photo(match.group(1), user, photo_type="close-up-marking")
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/submit-review", parsed.path):
            self.require_roles(user, {"dispatcher"}) and self.handle_submit_review(match.group(1), user)
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/review-decision", parsed.path):
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_review_decision(match.group(1), user)
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/bilty-photo", parsed.path):
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_bilty_photo(match.group(1), user)
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/mark-dispatched", parsed.path):
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_mark_dispatched(match.group(1), user)
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/mark-delivered", parsed.path):
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_mark_delivered(match.group(1), user)
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/mark-completed", parsed.path):
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_mark_completed(match.group(1), user)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        user = self.current_user()
        if not user:
            self.send_json({"error": "Login required"}, HTTPStatus.UNAUTHORIZED)
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/packing", parsed.path):
            self.require_roles(user, {"dispatcher", "admin"}) and self.handle_update_packing(match.group(1), user)
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/bilty", parsed.path):
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_update_bilty(match.group(1), user)
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/reviewer-dispatch", parsed.path):
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_reviewer_dispatch_update(match.group(1), user)
            return
        if match := re.fullmatch(r"/api/routes/([^/]+)", parsed.path):
            self.require_roles(user, {"admin"}) and self.handle_update_route(match.group(1))
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/admin", parsed.path):
            self.require_roles(user, {"admin"}) and self.handle_admin_update(match.group(1), user)
            return
        if match := re.fullmatch(r"/api/users/([^/]+)", parsed.path):
            self.require_roles(user, {"admin"}) and self.handle_update_user(match.group(1))
            return
        if match := re.fullmatch(r"/api/directory/([^/]+)", parsed.path):
            self.require_roles(user, {"admin"}) and self.handle_update_directory_item(match.group(1))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        user = self.current_user()
        if not user:
            self.send_json({"error": "Login required"}, HTTPStatus.UNAUTHORIZED)
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/cancel", parsed.path):
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_cancel_dispatch(match.group(1), user)
            return
        if match := re.fullmatch(r"/api/directory/([^/]+)", parsed.path):
            self.require_roles(user, {"admin"}) and self.handle_delete_directory_item(match.group(1))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def handle_api_get(self, parsed) -> None:
        user = self.current_user()
        if not user:
            self.send_json({"error": "Login required"}, HTTPStatus.UNAUTHORIZED)
            return
        if parsed.path == "/api/me":
            self.send_json({"user": serialize_user(user)})
            return
        if parsed.path == "/api/bootstrap":
            self.send_json(bootstrap_payload(user))
            return
        if parsed.path == "/api/bills/export":
            if not self.require_roles(user, {"admin"}):
                return
            self.handle_bill_export(parsed)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def handle_health(self) -> None:
        try:
            with db_connect() as conn:
                tables = [row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
                users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] if "users" in tables else 0
                jobs = conn.execute("SELECT COUNT(*) FROM dispatch_jobs").fetchone()[0] if "dispatch_jobs" in tables else 0
            sample_bill = next(BILLS_DIR.glob("*"), None) if BILLS_DIR.exists() else None
            self.send_json({
                "ok": True,
                "dataDir": str(DATA_DIR),
                "uploadDir": str(UPLOAD_DIR),
                "dbPath": str(DB_PATH),
                "dbExists": DB_PATH.exists(),
                "uploadDirExists": UPLOAD_DIR.exists(),
                "tables": tables,
                "userColumns": sorted(table_columns(sqlite3.connect(DB_PATH), "users")) if DB_PATH.exists() else [],
                "users": users,
                "jobs": jobs,
                "uploadFiles": sum(1 for _ in UPLOAD_DIR.rglob("*")) if UPLOAD_DIR.exists() else 0,
                "sampleBillUrl": f"/uploads/bills/{sample_bill.name}" if sample_bill else None,
                "sampleBillPath": str(sample_bill) if sample_bill else None,
                "sampleBillExists": sample_bill.exists() if sample_bill else False,
            })
        except Exception as exc:  # pragma: no cover - diagnostic endpoint
            self.send_json({"ok": False, "error": str(exc), "dataDir": str(DATA_DIR), "dbPath": str(DB_PATH)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def require_roles(self, user: sqlite3.Row, roles: set[str]) -> bool:
        if user["role"] not in roles:
            self.send_json({"error": "Access denied"}, HTTPStatus.FORBIDDEN)
            return False
        return True

    def current_user(self):
        cookie = SimpleCookie(self.headers.get("Cookie"))
        token = cookie.get(SESSION_COOKIE)
        if not token:
            return None
        with db_connect() as conn:
            row = conn.execute(
                """
                SELECT users.* FROM auth_sessions
                JOIN users ON users.id = auth_sessions.user_id
                WHERE auth_sessions.token = ? AND auth_sessions.expires_at > ? AND users.active_status = 1
                """,
                (token.value, now_iso()),
            ).fetchone()
        return row

    def handle_login(self) -> None:
        payload = read_json_body(self)
        login = payload.get("login", "").strip()
        password = payload.get("password", "")
        with db_connect() as conn:
            user = conn.execute("SELECT * FROM users WHERE email_or_mobile = ? AND active_status = 1", (login,)).fetchone()
            if not user or not verify_password(password, user["password_hash"]):
                self.send_json({"error": "Invalid login or password"}, HTTPStatus.UNAUTHORIZED)
                return
            token = secrets.token_urlsafe(32)
            timestamp = now_iso()
            expires = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + SESSION_TTL_SECONDS, timezone.utc).isoformat()
            conn.execute("INSERT INTO auth_sessions (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)", (token, user["id"], expires, timestamp))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL_SECONDS}")
        self.end_headers()
        self.wfile.write(json.dumps({"user": serialize_user(user)}).encode("utf-8"))

    def handle_logout(self) -> None:
        cookie = SimpleCookie(self.headers.get("Cookie"))
        token = cookie.get(SESSION_COOKIE)
        if token:
            with db_connect() as conn:
                conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token.value,))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
        self.end_headers()
        self.wfile.write(b"{}")

    def handle_create_dispatch(self, user: sqlite3.Row) -> None:
        form = parse_multipart(self)
        if form:
            payload = {key: field_value(form, key) for key in form.keys()}
            bill_file = form["billFile"] if "billFile" in form and getattr(form["billFile"], "filename", None) else None
        else:
            payload = read_json_body(self)
            bill_file = None
        required = ["partyName", "place", "orderCaseCount", "deliveryRoute"]
        if any(not str(payload.get(item, "")).strip() for item in required):
            self.send_json({"error": "Party, place, route, and total cases are required."}, HTTPStatus.BAD_REQUEST)
            return
        timestamp = now_iso()
        job_id = str(uuid.uuid4())
        invoice_number = ""
        bill_items = []
        extracted = {}
        bill_url = ""
        if bill_file:
            bill_url = save_upload(bill_file, BILLS_DIR)
            extracted = extract_invoice_from_pdf(upload_url_to_path(bill_url))
            invoice_number = extracted.get("invoiceNumber") or ""
            bill_items = extracted.get("billItems") or []
        manual_items = json_loads(payload.get("billItemsJson"), [])
        if manual_items:
            bill_items = normalize_bill_items(manual_items)
        invoice_number = invoice_number or str(payload.get("invoiceNumber", "")).strip()
        if invoice_number:
            duplicate = conn_duplicate_invoice(invoice_number)
            if duplicate:
                self.send_json({"error": "Check duplicate invoice", "duplicateJobId": duplicate}, HTTPStatus.CONFLICT)
                return
        daily_entry = next_daily_entry(payload.get("dispatchDate") or timestamp[:10])
        order_cases = int(float(payload.get("orderCaseCount") or extracted.get("orderCaseCount") or 0))
        total_amount = payload.get("invoiceAmount") or payload.get("totalAmount") or extracted.get("invoiceAmount")
        freight_amount = payload.get("freightAmount") or extracted.get("freightAmount")
        with db_connect() as conn:
            conn.execute(
                """
                INSERT INTO dispatch_jobs (
                    id, daily_entry_no, dispatch_date, invoice_number, party_name, party_city, party_mobile_number,
                    place, bill_date, bill_file_url, extracted_bill_data_json, total_cases, total_amount, bill_items_json,
                    delivery_route, transport_name, current_status, priority, uploaded_by, bill_uploaded_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    daily_entry,
                    payload.get("dispatchDate") or timestamp[:10],
                    invoice_number,
                    payload.get("partyName") or extracted.get("partyName") or "Unknown Party",
                    payload.get("partyCity") or extracted.get("partyCity") or payload.get("place"),
                    payload.get("partyMobileNumber") or "",
                    payload.get("place") or extracted.get("partyCity") or payload.get("partyCity") or "",
                    payload.get("invoiceDate") or extracted.get("invoiceDate") or timestamp[:10],
                    bill_url,
                    json.dumps(extracted, ensure_ascii=False),
                    order_cases,
                    float(total_amount) if total_amount not in (None, "") else None,
                    json.dumps(bill_items, ensure_ascii=False),
                    payload.get("deliveryRoute", "").strip(),
                    payload.get("transportName", "").strip(),
                    payload.get("priority", "normal"),
                    user["id"],
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            log_activity(conn, user, job_id, "bill_uploaded", None, "ready", "Bill uploaded", {"dailyEntryNo": daily_entry})
        self.send_json({"job": serialize_job_by_id(job_id)}, HTTPStatus.CREATED)

    def handle_bulk_import(self, user: sqlite3.Row) -> None:
        form = parse_multipart(self)
        if not form or "billFiles" not in form:
            self.send_json({"error": "Upload bill PDFs"}, HTTPStatus.BAD_REQUEST)
            return
        files = form["billFiles"] if isinstance(form["billFiles"], list) else [form["billFiles"]]
        created = []
        errors = []
        for file_item in files:
            if not getattr(file_item, "filename", None):
                continue
            try:
                bill_url = save_upload(file_item, BILLS_DIR)
                extracted = extract_invoice_from_pdf(upload_url_to_path(bill_url))
                party = extracted.get("partyName") or Path(file_item.filename).stem.replace("-", " ")[:80]
                city = extracted.get("partyCity") or "Manual city"
                order_cases = int(extracted.get("orderCaseCount") or 0)
                invoice_number = extracted.get("invoiceNumber") or ""
                if invoice_number and conn_duplicate_invoice(invoice_number):
                    errors.append({"file": file_item.filename, "error": "Check duplicate invoice"})
                    continue
                timestamp = now_iso()
                dispatch_date = field_value(form, "dispatchDate", timestamp[:10])
                job_id = str(uuid.uuid4())
                daily_entry = next_daily_entry(dispatch_date)
                with db_connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO dispatch_jobs (
                            id, daily_entry_no, dispatch_date, invoice_number, party_name, party_city, place, bill_date,
                            bill_file_url, extracted_bill_data_json, total_cases, total_amount, bill_items_json,
                            delivery_route, transport_name, current_status, priority, uploaded_by, bill_uploaded_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', 'normal', ?, ?, ?, ?)
                        """,
                        (
                            job_id,
                            daily_entry,
                            dispatch_date,
                            invoice_number,
                            party,
                            city,
                            city,
                            extracted.get("invoiceDate") or dispatch_date,
                            bill_url,
                            json.dumps(extracted, ensure_ascii=False),
                            order_cases,
                            extracted.get("invoiceAmount"),
                            json.dumps(extracted.get("billItems") or [], ensure_ascii=False),
                            field_value(form, "deliveryRoute", "Route 1"),
                            field_value(form, "transportName", ""),
                            user["id"],
                            timestamp,
                            timestamp,
                            timestamp,
                        ),
                    )
                    log_activity(conn, user, job_id, "bill_uploaded", None, "ready", "Bulk bill uploaded", {"file": file_item.filename})
                created.append(serialize_job_by_id(job_id))
            except Exception as exc:  # pragma: no cover - per-file safety
                errors.append({"file": file_item.filename, "error": str(exc)})
        self.send_json({"created": created, "errors": errors}, HTTPStatus.CREATED)

    def handle_claim(self, job_id: str, user: sqlite3.Row) -> None:
        with db_connect() as conn:
            active = conn.execute(
                "SELECT COUNT(*) FROM dispatch_jobs WHERE dispatcher_id = ? AND current_status IN ({})".format(
                    ",".join("?" for _ in ACTIVE_DISPATCHER_STATUSES)
                ),
                (user["id"], *ACTIVE_DISPATCHER_STATUSES),
            ).fetchone()[0]
            if active >= 2:
                self.send_json({"error": "You already have 2 active jobs. Complete one job before taking another."}, HTTPStatus.BAD_REQUEST)
                return
            job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job or job["current_status"] != "ready":
                self.send_json({"error": "Job is not available."}, HTTPStatus.BAD_REQUEST)
                return
            timestamp = now_iso()
            conn.execute(
                """
                UPDATE dispatch_jobs
                SET dispatcher_id = ?, current_status = 'assigned', job_claimed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (user["id"], timestamp, timestamp, job_id),
            )
            log_activity(conn, user, job_id, "job_claimed", job["current_status"], "assigned", "Job claimed")
        self.send_json({"job": serialize_job_by_id(job_id)})

    def handle_unassign(self, job_id: str, user: sqlite3.Row) -> None:
        with db_connect() as conn:
            job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                self.send_json({"error": "Job not found"}, HTTPStatus.NOT_FOUND)
                return
            if user["role"] == "dispatcher" and job["dispatcher_id"] != user["id"]:
                self.send_json({"error": "You can only unassign your own job."}, HTTPStatus.FORBIDDEN)
                return
            untouched = job["current_status"] == "assigned" and not conn.execute("SELECT COUNT(*) FROM packing_breakup WHERE dispatch_job_id = ?", (job_id,)).fetchone()[0] and not conn.execute("SELECT COUNT(*) FROM photos WHERE dispatch_job_id = ?", (job_id,)).fetchone()[0]
            if user["role"] == "dispatcher" and not untouched:
                self.send_json({"error": "Only untouched assigned jobs can be unassigned."}, HTTPStatus.BAD_REQUEST)
                return
            timestamp = now_iso()
            conn.execute("UPDATE dispatch_jobs SET dispatcher_id = NULL, current_status = 'ready', job_claimed_at = NULL, updated_at = ? WHERE id = ?", (timestamp, job_id))
            log_activity(conn, user, job_id, "job_unassigned", job["current_status"], "ready", "Job returned to available work")
        self.send_json({"job": serialize_job_by_id(job_id)})

    def handle_product_photo(self, job_id: str, user: sqlite3.Row, photo_type: str = "packing") -> None:
        form = parse_multipart(self)
        if not form or "photo" not in form:
            self.send_json({"error": "Upload packing photo"}, HTTPStatus.BAD_REQUEST)
            return
        photo_items = form["photo"] if isinstance(form["photo"], list) else [form["photo"]]
        normalized_type = normalize_photo_type(field_value(form, "photoType", photo_type))
        with db_connect() as conn:
            job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job or job["dispatcher_id"] != user["id"]:
                self.send_json({"error": "Job not assigned to you"}, HTTPStatus.FORBIDDEN)
                return
            if job["current_status"] in {"submitted-for-review", "approved-by-reviewer", "dispatch-pending", "dispatched", "delivered", "completed"}:
                self.send_json({"error": "Packing cannot be edited for this job."}, HTTPStatus.BAD_REQUEST)
                return
            timestamp = now_iso()
            urls = []
            for photo_item in photo_items:
                if not getattr(photo_item, "filename", None):
                    continue
                url = save_upload(photo_item, PRODUCT_PHOTOS_DIR)
                urls.append(url)
                conn.execute(
                    "INSERT INTO photos (id, dispatch_job_id, photo_type, file_url, uploaded_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), job_id, normalized_type, url, user["id"], timestamp),
                )
            if not urls:
                self.send_json({"error": "Upload packing photo"}, HTTPStatus.BAD_REQUEST)
                return
            new_status = job["current_status"]
            if normalized_type == "goods-check":
                new_status = "goods-photo-uploaded"
            elif job["current_status"] in {"assigned", "goods-photo-uploaded", "goods-approved"}:
                new_status = "product-photo-uploaded"
            conn.execute(
                """
                UPDATE dispatch_jobs
                SET current_status = ?, product_photo_uploaded_at = ?, packing_started_at = COALESCE(packing_started_at, ?), updated_at = ?
                WHERE id = ?
                """,
                (new_status, timestamp, timestamp, timestamp, job_id),
            )
            log_activity(conn, user, job_id, "photo_uploaded", job["current_status"], new_status, "Packing photo uploaded", {"photoType": normalized_type, "photos": urls})
        self.send_json({"job": serialize_job_by_id(job_id), "urls": urls})

    def handle_submit_goods_review(self, job_id: str, user: sqlite3.Row) -> None:
        with db_connect() as conn:
            job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job or job["dispatcher_id"] != user["id"]:
                self.send_json({"error": "Job not assigned to you"}, HTTPStatus.FORBIDDEN)
                return
            goods_count = conn.execute("SELECT COUNT(*) FROM photos WHERE dispatch_job_id = ? AND photo_type = 'goods-check'", (job_id,)).fetchone()[0]
            if not goods_count:
                self.send_json({"error": "Upload goods photo"}, HTTPStatus.BAD_REQUEST)
                return
            timestamp = now_iso()
            conn.execute("UPDATE dispatch_jobs SET current_status = 'goods-submitted-for-review', updated_at = ? WHERE id = ?", (timestamp, job_id))
            log_activity(conn, user, job_id, "goods_submitted", job["current_status"], "goods-submitted-for-review", "Goods submitted for review")
        self.send_json({"job": serialize_job_by_id(job_id)})

    def handle_goods_review_decision(self, job_id: str, user: sqlite3.Row) -> None:
        payload = read_json_body(self)
        decision = payload.get("decision")
        note = payload.get("note", "").strip()
        if decision == "send-back" and not note:
            self.send_json({"error": "Please enter correction reason."}, HTTPStatus.BAD_REQUEST)
            return
        with db_connect() as conn:
            job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                self.send_json({"error": "Job not found"}, HTTPStatus.NOT_FOUND)
                return
            if decision == "approve":
                new_status = "goods-approved"
                action = "goods_approved"
                remarks = note or "Goods photo approved"
            elif decision == "send-back":
                new_status = "goods-needs-correction"
                action = "goods_correction_sent"
                remarks = note
            else:
                self.send_json({"error": "Invalid decision"}, HTTPStatus.BAD_REQUEST)
                return
            timestamp = now_iso()
            conn.execute(
                "UPDATE dispatch_jobs SET current_status = ?, reviewer_id = ?, reviewer_note = ?, reviewed_at = ?, updated_at = ? WHERE id = ?",
                (new_status, user["id"], note, timestamp, timestamp, job_id),
            )
            log_activity(conn, user, job_id, action, job["current_status"], new_status, remarks)
        self.send_json({"job": serialize_job_by_id(job_id)})

    def handle_update_packing(self, job_id: str, user: sqlite3.Row) -> None:
        payload = read_json_body(self)
        raw_lines = payload.get("packingBreakup", [])
        lines = normalize_packing_lines(raw_lines)
        total_packages = sum(item["packageCount"] for item in lines)
        total_cases = sum(item["totalCases"] for item in lines)
        shortage_items = normalize_exception_items(payload.get("shortageItems", []))
        with db_connect() as conn:
            job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                self.send_json({"error": "Job not found"}, HTTPStatus.NOT_FOUND)
                return
            if user["role"] == "dispatcher" and job["dispatcher_id"] != user["id"]:
                self.send_json({"error": "Job not assigned to you"}, HTTPStatus.FORBIDDEN)
                return
            if user["role"] == "dispatcher" and job["current_status"] in {"submitted-for-review", "approved-by-reviewer", "dispatch-pending", "dispatched", "delivered", "completed"}:
                self.send_json({"error": "Packing cannot be edited for this job."}, HTTPStatus.BAD_REQUEST)
                return
            if not lines:
                self.send_json({"error": "Enter packing breakup"}, HTTPStatus.BAD_REQUEST)
                return
            order_cases = int(job["total_cases"] or 0)
            expected_delta = total_cases - order_cases
            if expected_delta != 0 and not exception_items_match_delta(shortage_items, expected_delta):
                self.send_json({"error": "Packed cases do not match bill cases. Please correct the breakup or enter valid item difference."}, HTTPStatus.BAD_REQUEST)
                return
            timestamp = now_iso()
            conn.execute("DELETE FROM packing_breakup WHERE dispatch_job_id = ?", (job_id,))
            for line in lines:
                conn.execute(
                    """
                    INSERT INTO packing_breakup (id, dispatch_job_id, packing_type, no_of_packages, cases_per_package, total_cases, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), job_id, line["packageType"], line["packageCount"], line["casesPerPackage"], line["totalCases"], timestamp),
                )
            status = job["current_status"]
            if status in {"assigned", "goods-approved", "goods-photo-uploaded", "goods-needs-correction"}:
                status = "packing"
            conn.execute(
                """
                UPDATE dispatch_jobs
                SET total_packages = ?, total_packed_cases = ?, shortage_note = ?, shortage_items_json = ?, current_status = ?,
                    dispatcher_note = ?, packing_started_at = COALESCE(packing_started_at, ?), updated_at = ?
                WHERE id = ?
                """,
                (
                    total_packages,
                    total_cases,
                    payload.get("shortageNote", "").strip(),
                    json.dumps(shortage_items, ensure_ascii=False),
                    status,
                    payload.get("dispatcherNote", "").strip(),
                    timestamp,
                    timestamp,
                    job_id,
                ),
            )
            log_activity(conn, user, job_id, "packing_saved", job["current_status"], status, "Packing details saved", {"packing": packing_summary(lines)})
        self.send_json({"job": serialize_job_by_id(job_id)})

    def handle_submit_review(self, job_id: str, user: sqlite3.Row) -> None:
        payload = read_json_body(self)
        with db_connect() as conn:
            job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job or job["dispatcher_id"] != user["id"]:
                self.send_json({"error": "Job not assigned to you"}, HTTPStatus.FORBIDDEN)
                return
            packing_count = conn.execute("SELECT COUNT(*) FROM packing_breakup WHERE dispatch_job_id = ?", (job_id,)).fetchone()[0]
            photo_count = conn.execute("SELECT COUNT(*) FROM photos WHERE dispatch_job_id = ? AND photo_type IN ('packing','final-packing','product-photo')", (job_id,)).fetchone()[0]
            goods_count = conn.execute("SELECT COUNT(*) FROM photos WHERE dispatch_job_id = ? AND photo_type = 'goods-check'", (job_id,)).fetchone()[0]
            if not goods_count:
                self.send_json({"error": "Upload goods photo"}, HTTPStatus.BAD_REQUEST)
                return
            if not packing_count:
                self.send_json({"error": "Enter packing breakup"}, HTTPStatus.BAD_REQUEST)
                return
            if not photo_count:
                self.send_json({"error": "Upload packing photo"}, HTTPStatus.BAD_REQUEST)
                return
            order_cases = int(job["total_cases"] or 0)
            total_packed = int(job["total_packed_cases"] or 0)
            shortage_items = json_loads(job["shortage_items_json"], [])
            if total_packed != order_cases and not exception_items_match_delta(shortage_items, total_packed - order_cases):
                self.send_json({"error": "Packed cases do not match bill cases. Please correct the breakup or enter valid item difference."}, HTTPStatus.BAD_REQUEST)
                return
            timestamp = now_iso()
            old_status = job["current_status"]
            new_status = "submitted-for-review"
            conn.execute(
                """
                UPDATE dispatch_jobs
                SET current_status = ?, submitted_for_review_at = ?, correction_resubmitted_at = CASE WHEN current_status = 'needs-correction' THEN ? ELSE correction_resubmitted_at END,
                    dispatcher_note = COALESCE(NULLIF(?, ''), dispatcher_note), updated_at = ?
                WHERE id = ?
                """,
                (new_status, timestamp, timestamp, payload.get("dispatcherNote", "").strip(), timestamp, job_id),
            )
            log_activity(conn, user, job_id, "submitted_for_review", old_status, new_status, "Submitted for reviewer checking")
        self.send_json({"job": serialize_job_by_id(job_id)})

    def handle_review_decision(self, job_id: str, user: sqlite3.Row) -> None:
        payload = read_json_body(self)
        decision = payload.get("decision")
        note = payload.get("note", "").strip()
        if decision in {"send-back", "reject"} and not note:
            self.send_json({"error": "Please enter rejection reason."}, HTTPStatus.BAD_REQUEST)
            return
        with db_connect() as conn:
            job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                self.send_json({"error": "Job not found"}, HTTPStatus.NOT_FOUND)
                return
            final_photo = conn.execute("SELECT COUNT(*) FROM photos WHERE dispatch_job_id = ? AND photo_type IN ('packing','final-packing','product-photo')", (job_id,)).fetchone()[0]
            if decision == "approve" and not final_photo:
                self.send_json({"error": "Cannot approve. Required photos are missing."}, HTTPStatus.BAD_REQUEST)
                return
            if decision == "approve":
                new_status = "dispatch-pending"
                action = "reviewer_approved"
                remarks = note or "Packing approved for dispatch"
                reviewed_at = now_iso()
                conn.execute(
                    """
                    UPDATE dispatch_jobs
                    SET current_status = ?, reviewer_id = ?, reviewer_note = ?, reviewed_at = ?, reviewer_approved_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (new_status, user["id"], note, reviewed_at, reviewed_at, reviewed_at, job_id),
                )
            elif decision == "send-back":
                new_status = "needs-correction"
                action = "correction_sent"
                remarks = note
                timestamp = now_iso()
                conn.execute(
                    "UPDATE dispatch_jobs SET current_status = ?, reviewer_id = ?, reviewer_note = ?, correction_sent_at = ?, updated_at = ? WHERE id = ?",
                    (new_status, user["id"], note, timestamp, timestamp, job_id),
                )
            elif decision == "reject":
                new_status = "cancelled"
                action = "cancelled"
                remarks = note
                timestamp = now_iso()
                conn.execute(
                    "UPDATE dispatch_jobs SET current_status = ?, reviewer_id = ?, reviewer_note = ?, reviewed_at = ?, updated_at = ? WHERE id = ?",
                    (new_status, user["id"], note, timestamp, timestamp, job_id),
                )
            else:
                self.send_json({"error": "Invalid reviewer decision"}, HTTPStatus.BAD_REQUEST)
                return
            log_activity(conn, user, job_id, action, job["current_status"], new_status, remarks)
        self.send_json({"job": serialize_job_by_id(job_id)})

    def handle_reviewer_dispatch_update(self, job_id: str, user: sqlite3.Row) -> None:
        payload = read_json_body(self)
        delivery_partner = payload.get("deliveryPartnerName", "").strip()
        transport_mode = payload.get("transportMode", "").strip()
        transport_name = payload.get("transportName", "").strip()
        if transport_mode.lower() != "self" and not delivery_partner:
            self.send_json({"error": "Enter delivery partner name"}, HTTPStatus.BAD_REQUEST)
            return
        if not transport_mode:
            self.send_json({"error": "Select transport mode"}, HTTPStatus.BAD_REQUEST)
            return
        if transport_mode == "Transport" and not transport_name:
            self.send_json({"error": "Select transport name"}, HTTPStatus.BAD_REQUEST)
            return
        bilty_count = payload.get("biltyPackageCount")
        try:
            bilty_count_int = int(bilty_count) if bilty_count not in (None, "") else None
        except (TypeError, ValueError):
            self.send_json({"error": "Enter bilty package count"}, HTTPStatus.BAD_REQUEST)
            return
        with db_connect() as conn:
            job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                self.send_json({"error": "Job not found"}, HTTPStatus.NOT_FOUND)
                return
            total_packages = int(job["total_packages"] or 0)
            diff = (bilty_count_int - total_packages) if bilty_count_int is not None else None
            if bilty_count_int is not None and diff and not payload.get("packageDifferenceReason"):
                self.send_json({"error": "Select difference reason"}, HTTPStatus.BAD_REQUEST)
                return
            timestamp = now_iso()
            conn.execute(
                """
                UPDATE dispatch_jobs
                SET delivery_partner_name = ?, transport_mode = ?, transport_name = ?, delivery_route = ?,
                    route_sequence = ?, package_count_difference = ?, package_difference_reason = ?,
                    package_difference_note = ?, bilty_package_count = ?, optional_reference_number = ?, freight_amount = ?, reviewer_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    delivery_partner,
                    transport_mode,
                    transport_name,
                    payload.get("deliveryRoute", "").strip(),
                    payload.get("routeSequence") or None,
                    diff,
                    payload.get("packageDifferenceReason", "").strip(),
                    payload.get("packageDifferenceNote", "").strip(),
                    bilty_count_int,
                    payload.get("optionalReferenceNumber", "").strip(),
                    float(payload.get("freightAmount") or 0) if payload.get("freightAmount") not in (None, "") else None,
                    user["id"],
                    timestamp,
                    job_id,
                ),
            )
            log_activity(conn, user, job_id, "reviewer_dispatch_details_saved", job["current_status"], job["current_status"], "Dispatch details saved")
        self.send_json({"job": serialize_job_by_id(job_id)})

    def handle_bilty_photo(self, job_id: str, user: sqlite3.Row) -> None:
        form = parse_multipart(self)
        if not form or "photo" not in form:
            self.send_json({"error": "Upload bilty photo"}, HTTPStatus.BAD_REQUEST)
            return
        photo_item = form["photo"] if not isinstance(form["photo"], list) else form["photo"][0]
        with db_connect() as conn:
            job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                self.send_json({"error": "Job not found"}, HTTPStatus.NOT_FOUND)
                return
            url = save_upload(photo_item, BILTY_PHOTOS_DIR)
            timestamp = now_iso()
            conn.execute("UPDATE dispatch_jobs SET bilty_photo_url = ?, updated_at = ? WHERE id = ?", (url, timestamp, job_id))
            conn.execute(
                """
                INSERT INTO photos (id, dispatch_job_id, photo_type, file_url, uploaded_by, created_at)
                VALUES (?, ?, 'bilty', ?, ?, ?)
                """,
                (str(uuid.uuid4()), job_id, url, user["id"], timestamp),
            )
            log_activity(conn, user, job_id, "bilty_photo_uploaded", job["current_status"], job["current_status"], "Bilty photo uploaded", {"photo": url})
        self.send_json({"job": serialize_job_by_id(job_id), "url": url})

    def handle_update_bilty(self, job_id: str, user: sqlite3.Row) -> None:
        payload = read_json_body(self)
        with db_connect() as conn:
            job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                self.send_json({"error": "Job not found"}, HTTPStatus.NOT_FOUND)
                return
            timestamp = now_iso()
            conn.execute(
                """
                UPDATE dispatch_jobs
                SET optional_reference_number = ?, bilty_date = ?, bilty_package_count = ?, bilty_value = ?, freight_amount = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload.get("optionalReferenceNumber", "").strip(),
                    payload.get("biltyDate", "").strip(),
                    int(payload.get("biltyPackageCount")) if payload.get("biltyPackageCount") not in (None, "") else None,
                    float(payload.get("biltyValue")) if payload.get("biltyValue") not in (None, "") else None,
                    float(payload.get("freightAmount")) if payload.get("freightAmount") not in (None, "") else None,
                    timestamp,
                    job_id,
                ),
            )
            log_activity(conn, user, job_id, "bilty_saved", job["current_status"], job["current_status"], "Bilty details saved")
        self.send_json({"job": serialize_job_by_id(job_id)})

    def handle_mark_dispatched(self, job_id: str, user: sqlite3.Row) -> None:
        with db_connect() as conn:
            job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                self.send_json({"error": "Job not found"}, HTTPStatus.NOT_FOUND)
                return
            if not job["transport_mode"]:
                self.send_json({"error": "Select transport mode"}, HTTPStatus.BAD_REQUEST)
                return
            if str(job["transport_mode"]).lower() != "self" and not job["delivery_partner_name"]:
                self.send_json({"error": "Enter delivery partner name"}, HTTPStatus.BAD_REQUEST)
                return
            if job["transport_mode"] == "Transport" and not job["transport_name"]:
                self.send_json({"error": "Select transport name"}, HTTPStatus.BAD_REQUEST)
                return
            if job["transport_mode"] == "Transport" and (job["freight_amount"] in (None, "")):
                self.send_json({"error": "Enter freight amount"}, HTTPStatus.BAD_REQUEST)
                return
            timestamp = now_iso()
            conn.execute("UPDATE dispatch_jobs SET current_status = 'dispatched', dispatched_at = ?, updated_at = ? WHERE id = ?", (timestamp, timestamp, job_id))
            log_activity(conn, user, job_id, "marked_dispatched", job["current_status"], "dispatched", "Sent to dispatch")
        self.send_json({"job": serialize_job_by_id(job_id)})

    def handle_mark_delivered(self, job_id: str, user: sqlite3.Row) -> None:
        with db_connect() as conn:
            job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                self.send_json({"error": "Job not found"}, HTTPStatus.NOT_FOUND)
                return
            timestamp = now_iso()
            conn.execute("UPDATE dispatch_jobs SET current_status = 'delivered', delivered_at = ?, updated_at = ? WHERE id = ?", (timestamp, timestamp, job_id))
            log_activity(conn, user, job_id, "marked_delivered", job["current_status"], "delivered", "Delivery partner took goods")
        self.send_json({"job": serialize_job_by_id(job_id)})

    def handle_mark_completed(self, job_id: str, user: sqlite3.Row) -> None:
        with db_connect() as conn:
            job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                self.send_json({"error": "Job not found"}, HTTPStatus.NOT_FOUND)
                return
            if job["transport_mode"] == "Transport" and not job["bilty_photo_url"]:
                self.send_json({"error": "Upload bilty photo"}, HTTPStatus.BAD_REQUEST)
                return
            if job["transport_mode"] == "Transport" and job["bilty_package_count"] is None:
                self.send_json({"error": "Enter bilty package count"}, HTTPStatus.BAD_REQUEST)
                return
            if job["bilty_package_count"] is not None and job["bilty_package_count"] != job["total_packages"] and not job["package_difference_reason"]:
                self.send_json({"error": "Select difference reason"}, HTTPStatus.BAD_REQUEST)
                return
            timestamp = now_iso()
            conn.execute("UPDATE dispatch_jobs SET current_status = 'completed', completed_at = ?, updated_at = ? WHERE id = ?", (timestamp, timestamp, job_id))
            log_activity(conn, user, job_id, "marked_completed", job["current_status"], "completed", "Dispatch completed")
        self.send_json({"job": serialize_job_by_id(job_id)})

    def handle_cancel_dispatch(self, job_id: str, user: sqlite3.Row) -> None:
        payload = read_json_body(self)
        reason = payload.get("reason", "").strip() or "Cancelled by reviewer/admin"
        with db_connect() as conn:
            job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                self.send_json({"error": "Job not found"}, HTTPStatus.NOT_FOUND)
                return
            timestamp = now_iso()
            conn.execute("UPDATE dispatch_jobs SET current_status = 'cancelled', reviewer_note = ?, updated_at = ? WHERE id = ?", (reason, timestamp, job_id))
            log_activity(conn, user, job_id, "cancelled", job["current_status"], "cancelled", reason)
        self.send_json({"job": serialize_job_by_id(job_id)})

    def handle_admin_update(self, job_id: str, user: sqlite3.Row) -> None:
        payload = read_json_body(self)
        allowed = {
            "partyName": "party_name",
            "partyCity": "party_city",
            "partyMobileNumber": "party_mobile_number",
            "place": "place",
            "orderCaseCount": "total_cases",
            "invoiceAmount": "total_amount",
            "currentStatus": "current_status",
            "deliveryPartnerName": "delivery_partner_name",
            "transportMode": "transport_mode",
            "transportName": "transport_name",
            "deliveryRoute": "delivery_route",
            "dispatcherId": "dispatcher_id",
            "reviewerId": "reviewer_id",
            "adminNote": "admin_note",
        }
        updates = []
        values = []
        for key, column in allowed.items():
            if key in payload:
                updates.append(f"{column} = ?")
                values.append(payload[key])
        if not updates:
            self.send_json({"error": "No editable fields provided"}, HTTPStatus.BAD_REQUEST)
            return
        with db_connect() as conn:
            job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
            if not job:
                self.send_json({"error": "Job not found"}, HTTPStatus.NOT_FOUND)
                return
            values.extend([user["id"], now_iso(), job_id])
            conn.execute(f"UPDATE dispatch_jobs SET {', '.join(updates)}, admin_override_by = ?, updated_at = ? WHERE id = ?", values)
            log_activity(conn, user, job_id, "admin_override", job["current_status"], payload.get("currentStatus", job["current_status"]), payload.get("adminNote", "Manual admin edit"), payload)
        self.send_json({"job": serialize_job_by_id(job_id)})

    def handle_create_user(self) -> None:
        payload = read_json_body(self)
        name = payload.get("name", "").strip()
        login = payload.get("emailOrMobile", "").strip()
        password = payload.get("password", "").strip() or "dispatch123"
        role = payload.get("role", "").strip()
        if not name or not login or role not in {"admin", "reviewer", "dispatcher"}:
            self.send_json({"error": "Name, login, and valid role required"}, HTTPStatus.BAD_REQUEST)
            return
        timestamp = now_iso()
        with db_connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO users (id, name, email_or_mobile, password_hash, role, active_status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                    (str(uuid.uuid4()), name, login, hash_password(password), role, timestamp, timestamp),
                )
            except sqlite3.IntegrityError:
                self.send_json({"error": "Login already exists"}, HTTPStatus.CONFLICT)
                return
        self.send_json({"ok": True}, HTTPStatus.CREATED)

    def handle_update_user(self, user_id: str) -> None:
        payload = read_json_body(self)
        fields = []
        values = []
        if "name" in payload:
            fields.append("name = ?")
            values.append(payload["name"].strip())
        if "emailOrMobile" in payload:
            fields.append("email_or_mobile = ?")
            values.append(payload["emailOrMobile"].strip())
        if "role" in payload and payload["role"] in {"admin", "reviewer", "dispatcher"}:
            fields.append("role = ?")
            values.append(payload["role"])
        if "activeStatus" in payload:
            fields.append("active_status = ?")
            values.append(1 if payload["activeStatus"] else 0)
        if payload.get("password"):
            fields.append("password_hash = ?")
            values.append(hash_password(payload["password"]))
        if not fields:
            self.send_json({"error": "No user fields provided"}, HTTPStatus.BAD_REQUEST)
            return
        values.extend([now_iso(), user_id])
        with db_connect() as conn:
            conn.execute(f"UPDATE users SET {', '.join(fields)}, updated_at = ? WHERE id = ?", values)
        self.send_json({"ok": True})

    def handle_create_directory_item(self) -> None:
        payload = read_json_body(self)
        kind = payload.get("kind")
        name = payload.get("name", "").strip()
        if not name or kind not in {"deliveryPartner", "transport"}:
            self.send_json({"error": "Name and directory type required"}, HTTPStatus.BAD_REQUEST)
            return
        timestamp = now_iso()
        with db_connect() as conn:
            try:
                if kind == "deliveryPartner":
                    conn.execute(
                        "INSERT INTO delivery_partners (name, active_status, cost_per_package, cost_per_bora, munshiyana_per_transport, created_at, updated_at) VALUES (?, 1, ?, ?, ?, ?, ?)",
                        (name, float(payload.get("costPerPackage") or 10), float(payload.get("costPerBora") or 40), float(payload.get("munshiyanaPerTransport") or 20), timestamp, timestamp),
                    )
                else:
                    conn.execute(
                        "INSERT INTO transports (name, active_status, default_route, default_delivery_partner, created_at, updated_at) VALUES (?, 1, ?, ?, ?, ?)",
                        (name, payload.get("defaultRoute", ""), payload.get("defaultDeliveryPartner", ""), timestamp, timestamp),
                    )
            except sqlite3.IntegrityError:
                self.send_json({"error": "Name already exists"}, HTTPStatus.CONFLICT)
                return
        self.send_json({"ok": True}, HTTPStatus.CREATED)

    def handle_update_directory_item(self, item_id: str) -> None:
        payload = read_json_body(self)
        kind = payload.get("kind")
        name = payload.get("name", "").strip()
        timestamp = now_iso()
        with db_connect() as conn:
            if kind == "deliveryPartner":
                old = conn.execute("SELECT * FROM delivery_partners WHERE id = ?", (item_id,)).fetchone()
                if not old:
                    self.send_json({"error": "Delivery partner not found"}, HTTPStatus.NOT_FOUND)
                    return
                old_name = old["name"]
                cost_per_package = float(payload.get("costPerPackage") or old["cost_per_package"] or 10)
                cost_per_bora = float(payload.get("costPerBora") or old["cost_per_bora"] or 40)
                munshiyana = float(payload.get("munshiyanaPerTransport") or old["munshiyana_per_transport"] or 20)
                conn.execute(
                    "UPDATE delivery_partners SET name = ?, active_status = ?, cost_per_package = ?, cost_per_bora = ?, munshiyana_per_transport = ?, updated_at = ? WHERE id = ?",
                    (name or old_name, 1 if payload.get("activeStatus", True) else 0, cost_per_package, cost_per_bora, munshiyana, timestamp, item_id),
                )
                if name and name != old_name:
                    conn.execute("UPDATE dispatch_jobs SET delivery_partner_name = ?, updated_at = ? WHERE delivery_partner_name = ?", (name, timestamp, old_name))
                    conn.execute("UPDATE route_batches SET delivery_partner_name = ?, updated_at = ? WHERE delivery_partner_name = ?", (name, timestamp, old_name))
            elif kind == "transport":
                old = conn.execute("SELECT * FROM transports WHERE id = ?", (item_id,)).fetchone()
                if not old:
                    self.send_json({"error": "Transport not found"}, HTTPStatus.NOT_FOUND)
                    return
                old_name = old["name"]
                conn.execute(
                    "UPDATE transports SET name = ?, active_status = ?, default_route = ?, default_delivery_partner = ?, updated_at = ? WHERE id = ?",
                    (name or old_name, 1 if payload.get("activeStatus", True) else 0, payload.get("defaultRoute", old["default_route"] or ""), payload.get("defaultDeliveryPartner", old["default_delivery_partner"] or ""), timestamp, item_id),
                )
                if name and name != old_name:
                    conn.execute("UPDATE dispatch_jobs SET transport_name = ?, updated_at = ? WHERE transport_name = ?", (name, timestamp, old_name))
            else:
                self.send_json({"error": "Invalid directory type"}, HTTPStatus.BAD_REQUEST)
                return
        self.send_json({"ok": True})

    def handle_delete_directory_item(self, item_id: str) -> None:
        payload = read_json_body(self)
        kind = payload.get("kind")
        with db_connect() as conn:
            if kind == "deliveryPartner":
                conn.execute("DELETE FROM delivery_partners WHERE id = ?", (item_id,))
            elif kind == "transport":
                conn.execute("DELETE FROM transports WHERE id = ?", (item_id,))
            else:
                self.send_json({"error": "Invalid directory type"}, HTTPStatus.BAD_REQUEST)
                return
        self.send_json({"ok": True})

    def handle_update_route(self, route_id: str) -> None:
        payload = read_json_body(self)
        name = payload.get("name", "").strip()
        if not name:
            self.send_json({"error": "Route name required"}, HTTPStatus.BAD_REQUEST)
            return
        with db_connect() as conn:
            conn.execute("UPDATE route_names SET name = ? WHERE id = ?", (name, route_id))
        self.send_json({"ok": True})

    def handle_backup_import(self, user: sqlite3.Row) -> None:
        form = parse_multipart(self)
        if not form or "backupFile" not in form:
            self.send_json({"error": "Backup ZIP file is required."}, HTTPStatus.BAD_REQUEST)
            return
        file_item = form["backupFile"] if not isinstance(form["backupFile"], list) else form["backupFile"][0]
        if not getattr(file_item, "filename", None):
            self.send_json({"error": "Backup ZIP file is required."}, HTTPStatus.BAD_REQUEST)
            return
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = DATA_DIR / f"pre-import-backup-{timestamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        if DB_PATH.exists():
            shutil.copy2(DB_PATH, backup_dir / "dispatches.db")
        if UPLOAD_DIR.exists():
            shutil.copytree(UPLOAD_DIR, backup_dir / "uploads", dirs_exist_ok=True)
        archive_bytes = file_item.file.read()
        if len(archive_bytes) > 200 * 1024 * 1024:
            self.send_json({"error": "Backup file is too large."}, HTTPStatus.BAD_REQUEST)
            return
        extract_dir = DATA_DIR / f"import-{timestamp}"
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                for member in archive.infolist():
                    member_path = (extract_dir / member.filename).resolve()
                    if not str(member_path).startswith(str(extract_dir.resolve())):
                        raise ValueError("Invalid backup path")
                archive.extractall(extract_dir)
        except (zipfile.BadZipFile, ValueError):
            self.send_json({"error": "Invalid backup ZIP."}, HTTPStatus.BAD_REQUEST)
            return
        source_db = extract_dir / "dispatches.db"
        if not source_db.exists():
            matches = list(extract_dir.rglob("dispatches.db"))
            source_db = matches[0] if matches else source_db
        if not source_db.exists():
            self.send_json({"error": "Backup must contain dispatches.db."}, HTTPStatus.BAD_REQUEST)
            return
        try:
            with sqlite3.connect(source_db) as test_conn:
                table_names = {row[0] for row in test_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "dispatch_jobs" not in table_names or "users" not in table_names:
                self.send_json({"error": "Backup database is not a Dispatch Desk database."}, HTTPStatus.BAD_REQUEST)
                return
        except sqlite3.DatabaseError:
            self.send_json({"error": "Backup database is invalid."}, HTTPStatus.BAD_REQUEST)
            return
        shutil.copy2(source_db, DB_PATH)
        source_uploads = extract_dir / "uploads"
        if not source_uploads.exists():
            matches = [path for path in extract_dir.rglob("uploads") if path.is_dir()]
            source_uploads = matches[0] if matches else source_uploads
        if source_uploads.exists():
            for item in source_uploads.rglob("*"):
                if not item.is_file():
                    continue
                rel = upload_member_relative_path(str(item.relative_to(source_uploads.parent))) or item.relative_to(source_uploads)
                target = UPLOAD_DIR / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
        ensure_storage()
        with db_connect() as conn:
            log_activity(conn, user, None, "backup_imported", None, None, "Backup imported", {"preImportBackup": str(backup_dir)})
        self.send_json({"ok": True, "message": "Backup imported", "preImportBackup": str(backup_dir)})

    def handle_bill_export(self, parsed) -> None:
        params = parse_qs(parsed.query)
        date_filter = params.get("date", [""])[0]
        with db_connect() as conn:
            if date_filter:
                rows = conn.execute("SELECT * FROM dispatch_jobs WHERE dispatch_date = ? ORDER BY daily_entry_no", (date_filter,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM dispatch_jobs ORDER BY dispatch_date DESC, daily_entry_no DESC").fetchall()
            jobs = [serialize_job(row, conn) for row in rows]
            log_rows = [dict(item) for item in conn.execute("SELECT * FROM activity_logs ORDER BY created_at DESC")]
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("dispatch_jobs.json", json.dumps(jobs, ensure_ascii=False, indent=2))
            archive.writestr("activity_logs.json", json.dumps(log_rows, ensure_ascii=False, indent=2))
            csv_lines = [
                "dispatch_date,daily_entry_no,party_name,city,status,total_cases,total_packages,total_packed_cases,delivery_partner,transport,route",
            ]
            for job in jobs:
                csv_lines.append(
                    ",".join(
                        str(value).replace(",", " ")
                        for value in [
                            job.get("dispatchDate"),
                            job.get("dailyEntryNo"),
                            job.get("partyName"),
                            job.get("partyCity"),
                            job.get("currentStatus"),
                            job.get("orderCaseCount"),
                            job.get("totalPackages"),
                            job.get("totalPackedCases"),
                            job.get("deliveryPartnerName"),
                            job.get("transportName"),
                            job.get("deliveryRoute"),
                        ]
                    )
                )
            archive.writestr("dispatch_jobs.csv", "\n".join(csv_lines))
            if DB_PATH.exists():
                archive.write(DB_PATH, "dispatches.db")
            if UPLOAD_DIR.exists():
                for path in UPLOAD_DIR.rglob("*"):
                    if path.is_file():
                        archive.write(path, f"uploads/{path.relative_to(UPLOAD_DIR)}")
        data = buffer.getvalue()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", "attachment; filename=daily-dispatch-backup.zip")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_create_route_batch(self, user: sqlite3.Row) -> None:
        payload = read_json_body(self)
        route_name = payload.get("routeName", "").strip()
        job_ids = payload.get("jobIds", [])
        if not route_name or not job_ids:
            self.send_json({"error": "Route name and jobs are required."}, HTTPStatus.BAD_REQUEST)
            return
        batch_id = str(uuid.uuid4())
        timestamp = now_iso()
        with db_connect() as conn:
            conn.execute(
                """
                INSERT INTO route_batches (id, route_name, delivery_partner_name, status, created_by, created_at, updated_at)
                VALUES (?, ?, ?, 'open', ?, ?, ?)
                """,
                (batch_id, route_name, payload.get("deliveryPartnerName", "").strip(), user["id"], timestamp, timestamp),
            )
            for sequence, job_id in enumerate(job_ids, start=1):
                conn.execute(
                    """
                    UPDATE dispatch_jobs
                    SET route_batch_id = ?, delivery_route = ?, route_sequence = ?, delivery_partner_name = COALESCE(NULLIF(delivery_partner_name, ''), ?), updated_at = ?
                    WHERE id = ?
                    """,
                    (batch_id, route_name, sequence, payload.get("deliveryPartnerName", "").strip(), timestamp, job_id),
                )
            log_activity(conn, user, None, "route_batch_created", None, None, f"Route batch created for {route_name}", {"jobIds": job_ids})
        self.send_json({"id": batch_id, "routeName": route_name}, HTTPStatus.CREATED)

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def conn_duplicate_invoice(invoice_number: str) -> str | None:
    with db_connect() as conn:
        row = conn.execute("SELECT id FROM dispatch_jobs WHERE invoice_number = ?", (invoice_number,)).fetchone()
    return row["id"] if row else None


def next_daily_entry(dispatch_date: str) -> int:
    with db_connect() as conn:
        row = conn.execute("SELECT MAX(daily_entry_no) as max_no FROM dispatch_jobs WHERE dispatch_date = ?", (dispatch_date,)).fetchone()
    return int(row["max_no"] or 0) + 1


def serialize_job_by_id(job_id: str) -> dict:
    with db_connect() as conn:
        row = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
        return serialize_job(row, conn)


def normalize_packing_lines(raw_lines) -> list[dict]:
    lines = []
    if not isinstance(raw_lines, list):
        return lines
    for line in raw_lines:
        if not isinstance(line, dict):
            continue
        package_type = str(line.get("packageType") or line.get("packingType") or "Other").strip() or "Other"
        try:
            package_count = int(float(line.get("packageCount", line.get("noOfPackages", 0)) or 0))
            cases_per_package = int(float(line.get("casesPerPackage", 0) or 0))
        except (TypeError, ValueError):
            continue
        total_cases = package_count * cases_per_package
        if package_count <= 0 or cases_per_package <= 0:
            continue
        lines.append({
            "packageType": package_type,
            "packageCount": package_count,
            "casesPerPackage": cases_per_package,
            "totalCases": total_cases,
        })
    return lines


def main() -> None:
    ensure_storage()
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), DispatchHandler)
    print(f"Daily Dispatch Desk running on http://0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
