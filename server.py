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
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pypdf import PdfReader


ROOT = Path(__file__).parent


def default_data_dir() -> Path:
    configured = os.environ.get("DISPATCH_DATA_DIR")
    if configured:
        return Path(configured)
    render_disk = Path("/var/data")
    if os.environ.get("RENDER") and render_disk.exists():
        return render_disk
    return ROOT / "data"


DATA_DIR = default_data_dir()
UPLOAD_DIR = Path(os.environ.get("DISPATCH_UPLOAD_DIR", DATA_DIR / "uploads" if DATA_DIR.name == "data" and str(DATA_DIR).startswith("/var/") else ROOT / "uploads"))
BILLS_DIR = UPLOAD_DIR / "bills"
PRODUCT_PHOTOS_DIR = UPLOAD_DIR / "product-photos"
BILTY_PHOTOS_DIR = UPLOAD_DIR / "bilty-photos"
LEGACY_JSON_PATH = DATA_DIR / "dispatches.json"
DB_PATH = Path(os.environ.get("DISPATCH_DB_PATH", DATA_DIR / "dispatches.db"))
PORT = int(os.environ.get("DISPATCH_PORT", os.environ.get("PORT", "8000")))
SESSION_DAYS = 7

STATUSES = {
    "ready",
    "assigned",
    "goods-photo-uploaded",
    "goods-submitted-for-review",
    "goods-needs-correction",
    "goods-approved",
    "packing",
    "submitted-for-review",
    "needs-correction",
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


def ensure_storage() -> None:
    DATA_DIR.mkdir(exist_ok=True)
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
                dispatcher_note TEXT,
                reviewer_note TEXT,
                admin_note TEXT,
                whatsapp_template_name TEXT,
                whatsapp_sent_status TEXT,
                whatsapp_sent_at TEXT,
                whatsapp_message_id TEXT,
                whatsapp_failed_reason TEXT,
                bill_uploaded_at TEXT,
                job_claimed_at TEXT,
                goods_photo_uploaded_at TEXT,
                goods_submitted_for_review_at TEXT,
                goods_reviewed_at TEXT,
                goods_approved_at TEXT,
                goods_reviewer_note TEXT,
                packing_started_at TEXT,
                product_photo_uploaded_at TEXT,
                submitted_for_review_at TEXT,
                reviewed_at TEXT,
                correction_sent_at TEXT,
                correction_resubmitted_at TEXT,
                reviewer_approved_at TEXT,
                bilty_uploaded_at TEXT,
                dispatched_at TEXT,
                delivered_at TEXT,
                completed_at TEXT,
                correction_count INTEGER NOT NULL DEFAULT 0,
                admin_override_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(uploaded_by) REFERENCES users(id),
                FOREIGN KEY(dispatcher_id) REFERENCES users(id),
                FOREIGN KEY(reviewer_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS packing_details (
                id TEXT PRIMARY KEY,
                dispatch_job_id TEXT NOT NULL UNIQUE,
                packing_breakup_json TEXT NOT NULL,
                packing_type TEXT,
                shop_package_count INTEGER NOT NULL DEFAULT 0,
                packing_photo_urls_json TEXT,
                closeup_marking_photo_url TEXT,
                number_of_boxes INTEGER NOT NULL DEFAULT 0,
                number_of_cases INTEGER NOT NULL DEFAULT 0,
                dispatcher_note TEXT,
                product_photo_url TEXT,
                created_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(dispatch_job_id) REFERENCES dispatch_jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS packing_breakup (
                id TEXT PRIMARY KEY,
                dispatch_job_id TEXT NOT NULL,
                packing_type TEXT NOT NULL,
                no_of_packages INTEGER NOT NULL DEFAULT 0,
                cases_per_package INTEGER NOT NULL DEFAULT 0,
                total_cases INTEGER NOT NULL DEFAULT 0,
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
                FOREIGN KEY(dispatch_job_id) REFERENCES dispatch_jobs(id) ON DELETE CASCADE,
                FOREIGN KEY(uploaded_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS review_details (
                id TEXT PRIMARY KEY,
                dispatch_job_id TEXT NOT NULL UNIQUE,
                reviewer_id TEXT,
                review_decision TEXT,
                reviewer_note TEXT,
                transporter_delivery_partner_name TEXT,
                reviewed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(dispatch_job_id) REFERENCES dispatch_jobs(id) ON DELETE CASCADE,
                FOREIGN KEY(reviewer_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS bilty_details (
                id TEXT PRIMARY KEY,
                dispatch_job_id TEXT NOT NULL UNIQUE,
                bilty_number TEXT,
                optional_reference_number TEXT,
                bilty_photo_url TEXT,
                delivery_partner_name TEXT,
                bilty_date TEXT,
                bilty_package_count INTEGER,
                bilty_value REAL,
                freight_amount REAL,
                bilty_uploaded_by TEXT,
                bilty_uploaded_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(dispatch_job_id) REFERENCES dispatch_jobs(id) ON DELETE CASCADE,
                FOREIGN KEY(bilty_uploaded_by) REFERENCES users(id)
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
                FOREIGN KEY(dispatch_job_id) REFERENCES dispatch_jobs(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS ai_photo_checks (
                id TEXT PRIMARY KEY,
                dispatch_job_id TEXT NOT NULL UNIQUE,
                ai_check_status TEXT,
                ai_match_score REAL,
                ai_risk_level TEXT,
                ai_detected_box_count INTEGER,
                ai_detected_party_marking TEXT,
                ai_detected_package_count INTEGER,
                ai_detected_bilty_number TEXT,
                ai_detected_bilty_transport_name TEXT,
                ai_detected_bilty_package_count INTEGER,
                ai_detected_bilty_date TEXT,
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
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS route_names (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
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

            CREATE TABLE IF NOT EXISTS delivery_partners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                preferred_transport_name TEXT,
                active_status INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                active_status INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        migrate_schema(conn)
        seed_routes(conn)
        seed_users(conn)
        seed_settings(conn)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"{base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        salt_b64, digest_b64 = encoded.split("$", 1)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
        return secrets.compare_digest(digest, expected)
    except Exception:
        return False


def valid_password_hash(encoded: str | None) -> bool:
    if not encoded or "$" not in encoded:
        return False
    try:
        salt_b64, digest_b64 = encoded.split("$", 1)
        base64.b64decode(salt_b64)
        base64.b64decode(digest_b64)
        return True
    except Exception:
        return False


def seed_users(conn: sqlite3.Connection) -> None:
    timestamp = now_iso()
    for user_id, name, login, password, role in DEFAULT_USERS:
        current = conn.execute(
            "SELECT * FROM users WHERE email_or_mobile = ? OR id = ?",
            (login, user_id),
        ).fetchone()
        if current:
            updates = {
                "name": current["name"] or name,
                "email_or_mobile": current["email_or_mobile"] or login,
                "role": current["role"] if current["role"] in {"reviewer", "dispatcher", "admin"} else role,
                "active_status": 1,
                "updated_at": timestamp,
            }
            if not valid_password_hash(current["password_hash"]):
                updates["password_hash"] = hash_password(password)
            set_sql = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE users SET {set_sql} WHERE id = ?",
                [*updates.values(), current["id"]],
            )
            continue
        conn.execute(
            """
            INSERT INTO users (id, name, email_or_mobile, password_hash, role, active_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (user_id, name, login, hash_password(password), role, timestamp, timestamp),
        )


def seed_settings(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('dispatcher_label', 'Dispatcher')")
    conn.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('reviewer_label', 'Reviewer')")


def ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def migrate_schema(conn: sqlite3.Connection) -> None:
    for column, ddl in {
        "name": "TEXT",
        "email_or_mobile": "TEXT",
        "password_hash": "TEXT",
        "role": "TEXT",
        "active_status": "INTEGER NOT NULL DEFAULT 1",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    }.items():
        ensure_column(conn, "users", column, ddl)
    timestamp = now_iso()
    conn.execute("UPDATE users SET active_status = 1 WHERE active_status IS NULL")
    conn.execute("UPDATE users SET created_at = ? WHERE created_at IS NULL OR created_at = ''", (timestamp,))
    conn.execute("UPDATE users SET updated_at = ? WHERE updated_at IS NULL OR updated_at = ''", (timestamp,))

    for column, ddl in {
        "preferred_transport_name": "TEXT",
        "active_status": "INTEGER NOT NULL DEFAULT 1",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    }.items():
        ensure_column(conn, "delivery_partners", column, ddl)
    conn.execute("UPDATE delivery_partners SET active_status = 1 WHERE active_status IS NULL")
    conn.execute("UPDATE delivery_partners SET created_at = ? WHERE created_at IS NULL OR created_at = ''", (timestamp,))
    conn.execute("UPDATE delivery_partners SET updated_at = ? WHERE updated_at IS NULL OR updated_at = ''", (timestamp,))

    for column, ddl in {
        "daily_entry_no": "INTEGER",
        "dispatch_date": "TEXT",
        "party_city": "TEXT",
        "party_mobile_number": "TEXT",
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
        "dispatcher_note": "TEXT",
        "reviewer_note": "TEXT",
        "admin_note": "TEXT",
        "whatsapp_template_name": "TEXT",
        "whatsapp_sent_status": "TEXT",
        "whatsapp_sent_at": "TEXT",
        "whatsapp_message_id": "TEXT",
        "whatsapp_failed_reason": "TEXT",
        "completed_at": "TEXT",
        "goods_photo_uploaded_at": "TEXT",
        "goods_submitted_for_review_at": "TEXT",
        "goods_reviewed_at": "TEXT",
        "goods_approved_at": "TEXT",
        "goods_reviewer_note": "TEXT",
    }.items():
        ensure_column(conn, "dispatch_jobs", column, ddl)
    for column, ddl in {
        "packing_type": "TEXT",
        "shop_package_count": "INTEGER NOT NULL DEFAULT 0",
        "packing_photo_urls_json": "TEXT",
        "closeup_marking_photo_url": "TEXT",
    }.items():
        ensure_column(conn, "packing_details", column, ddl)
    for column, ddl in {
        "optional_reference_number": "TEXT",
        "bilty_date": "TEXT",
        "bilty_package_count": "INTEGER",
        "bilty_value": "REAL",
        "freight_amount": "REAL",
    }.items():
        ensure_column(conn, "bilty_details", column, ddl)
    for column, ddl in {
        "ai_detected_box_count": "INTEGER",
        "ai_detected_party_marking": "TEXT",
        "ai_detected_package_count": "INTEGER",
        "ai_detected_bilty_number": "TEXT",
        "ai_detected_bilty_transport_name": "TEXT",
        "ai_detected_bilty_package_count": "INTEGER",
        "ai_detected_bilty_date": "TEXT",
    }.items():
        ensure_column(conn, "ai_photo_checks", column, ddl)
    conn.execute(
        """
        UPDATE dispatch_jobs
        SET delivery_partner_name = COALESCE(delivery_partner_name, transporter_delivery_partner_name),
            party_city = COALESCE(party_city, place),
            dispatch_date = COALESCE(dispatch_date, substr(created_at, 1, 10)),
            transport_mode = COALESCE(transport_mode, CASE WHEN transporter_delivery_partner_name = '' THEN 'Self' ELSE 'Transport' END)
        """
    )
    conn.execute(
        """
        UPDATE packing_details
        SET shop_package_count = CASE WHEN shop_package_count = 0 THEN number_of_boxes ELSE shop_package_count END,
            packing_photo_urls_json = COALESCE(packing_photo_urls_json, '[]'),
            packing_type = COALESCE(packing_type, 'Mixed')
        """
    )
    jobs = conn.execute("SELECT id, extracted_bill_data_json FROM dispatch_jobs").fetchall()
    for job in jobs:
        if job["extracted_bill_data_json"]:
            extracted = load_json(job["extracted_bill_data_json"], {})
            items = extracted.get("items") or extracted.get("billItems") or []
            conn.execute(
                "UPDATE dispatch_jobs SET bill_items_json = COALESCE(bill_items_json, ?) WHERE id = ?",
                (json.dumps(items), job["id"]),
            )
    packing_jobs = conn.execute("SELECT id FROM dispatch_jobs").fetchall()
    for job in packing_jobs:
        lines = conn.execute(
            """
            SELECT packing_type, no_of_packages, cases_per_package, total_cases
            FROM packing_breakup
            WHERE dispatch_job_id = ?
            """,
            (job["id"],),
        ).fetchall()
        if not lines:
            legacy = conn.execute(
                "SELECT packing_breakup_json FROM packing_details WHERE dispatch_job_id = ?",
                (job["id"],),
            ).fetchone()
            legacy_lines = normalize_packing_lines(load_json(legacy["packing_breakup_json"] if legacy else None, []))
            for line in legacy_lines:
                conn.execute(
                    """
                    INSERT INTO packing_breakup
                    (id, dispatch_job_id, packing_type, no_of_packages, cases_per_package, total_cases, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        job["id"],
                        line["packageType"],
                        line["packageCount"],
                        line["casesPerPackage"],
                        line["totalCases"],
                        now_iso(),
                        now_iso(),
                    ),
                )
            lines = conn.execute(
                """
                SELECT packing_type, no_of_packages, cases_per_package, total_cases
                FROM packing_breakup
                WHERE dispatch_job_id = ?
                """,
                (job["id"],),
            ).fetchall()
        if lines:
            total_packages = sum(line["no_of_packages"] for line in lines)
            total_packed_cases = sum(line["total_cases"] for line in lines)
            conn.execute(
                "UPDATE dispatch_jobs SET total_packages = ?, total_packed_cases = ? WHERE id = ?",
                (total_packages, total_packed_cases, job["id"]),
            )
    rows = conn.execute(
        """
        SELECT dispatch_job_id, product_photo_url, packing_photo_urls_json
        FROM packing_details
        WHERE product_photo_url IS NOT NULL AND product_photo_url != ''
        """
    ).fetchall()
    for row in rows:
        current = load_json(row["packing_photo_urls_json"], [])
        if row["product_photo_url"] not in current:
            current.append(row["product_photo_url"])
            conn.execute(
                "UPDATE packing_details SET packing_photo_urls_json = ? WHERE dispatch_job_id = ?",
                (json.dumps(current), row["dispatch_job_id"]),
            )


def seed_routes(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) FROM route_names").fetchone()[0]:
        return
    conn.executemany("INSERT INTO route_names (id, name) VALUES (?, ?)", [(1, "Route 1"), (2, "Route 2"), (3, "Route 3")])


def normalize_packing_lines(value) -> list[dict]:
    if isinstance(value, list):
        lines = []
        for item in value:
            package_type = str(item.get("packageType", item.get("type", ""))).strip() or "Other"
            package_count = int(item.get("packageCount", item.get("count", 0)) or 0)
            cases_per_package = int(item.get("casesPerPackage", 1) or 1)
            total_cases = package_count * cases_per_package
            if package_count or total_cases:
                lines.append(
                    {
                        "packageType": package_type,
                        "packageCount": package_count,
                        "casesPerPackage": cases_per_package,
                        "totalCases": total_cases,
                    }
                )
        return lines
    if isinstance(value, dict):
        lines = []
        for key in ["1", "2", "3", "4", "5"]:
            if int(value.get(key, 0) or 0):
                lines.append(
                    {
                        "packageType": "Carton",
                        "packageCount": int(value[key]),
                        "casesPerPackage": int(key),
                        "totalCases": int(value[key]) * int(key),
                    }
                )
        if int(value.get("bora", 0) or 0):
            lines.append(
                {
                    "packageType": "Bora",
                    "packageCount": int(value["bora"]),
                    "casesPerPackage": 1,
                    "totalCases": int(value["bora"]),
                }
            )
        return lines
    return []


def packing_totals(packing) -> dict:
    lines = normalize_packing_lines(packing)
    return {
        "totalPackages": sum(line["packageCount"] for line in lines),
        "totalPackedCases": sum(line["totalCases"] for line in lines),
    }


def packing_summary(packing) -> str:
    lines = normalize_packing_lines(packing)
    parts = [
        f"{line['packageType']} | {line['packageCount']} × {line['casesPerPackage']} = {line['totalCases']} cases"
        for line in lines
    ]
    return ", ".join(parts) if parts else "No packing breakup added yet."


def empty_packing() -> list[dict]:
    return []


def extract_pdf_text(file_path: Path) -> str:
    reader = PdfReader(str(file_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_bill_text(text: str) -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    first_line = lines[0] if lines else ""
    cleaned_first = re.sub(r"\([^)]*\)", "", first_line).strip()
    cleaned_first = re.sub(r"\s+", " ", cleaned_first)
    title_parts = cleaned_first.split()
    party = " ".join(title_parts[:-1]).strip() if len(title_parts) > 1 else cleaned_first
    place = title_parts[-1].strip() if len(title_parts) > 1 else ""
    invoice_match = re.search(r"Invoice No\.\s*:\s*([A-Z0-9-]+)", text, flags=re.I)
    date_match = re.search(r"Date\s*:\s*(\d{2}/\d{2}/\d{4})", text, flags=re.I)
    address_match = re.search(r"Address\.\s*:\s*([^\n]+)", text, flags=re.I)
    cases_match = re.search(r"\}\s*(\d+)\s+CSTOTAL", text, flags=re.I)
    amount_match = re.search(r"\}\s*\d+\s+CSTOTAL\s+([0-9,]+\.\d{2})", text, flags=re.I)
    freight_match = re.search(r"FREIGHT\s*:\s*([0-9,]+\.\d{2})", text, flags=re.I)
    raw_address = address_match.group(1).strip() if address_match else ""
    mode = "self" if raw_address.upper() == "SELF" else "transport"
    transporter = "" if mode == "self" else raw_address
    bill_date = datetime.strptime(date_match.group(1), "%d/%m/%Y").date().isoformat() if date_match else ""
    total_amount = float(amount_match.group(1).replace(",", "")) if amount_match else None
    items = []
    for line in lines:
        item_match = re.match(r"^\d+\s+(.+?)\s+(\d+):0\s+CASE\b", line, flags=re.I)
        if item_match:
            items.append(
                {
                    "name": item_match.group(1).strip(),
                    "quantity": int(item_match.group(2)),
                }
            )
    return {
        "party": party,
        "place": place,
        "invoice": invoice_match.group(1) if invoice_match else "",
        "billDate": bill_date,
        "cases": int(cases_match.group(1)) if cases_match else 0,
        "mode": mode,
        "transporter": transporter,
        "totalAmount": total_amount,
        "freightAmount": float(freight_match.group(1).replace(",", "")) if freight_match else None,
        "items": items,
        "rawTextPreview": text[:1200],
    }


def log_action(
    conn: sqlite3.Connection,
    job_id: str | None,
    user: sqlite3.Row | dict | None,
    action_type: str,
    old_status: str | None = None,
    new_status: str | None = None,
    remarks: str = "",
    metadata: dict | None = None,
    created_at: str | None = None,
) -> None:
    user_id = user["id"] if user else None
    user_role = user["role"] if user else None
    conn.execute(
        """
        INSERT INTO activity_logs
        (id, dispatch_job_id, user_id, user_role, action_type, old_status, new_status, remarks, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            job_id,
            user_id,
            user_role,
            action_type,
            old_status,
            new_status,
            remarks,
            json.dumps(metadata or {}),
            created_at or now_iso(),
        ),
    )


def legacy_status(status: str) -> str:
    return {
        "approved": "approved-by-reviewer",
        "packing-done": "packing",
        "bilty-pending": "dispatch-pending",
    }.get(status, status if status in STATUSES else "ready")


def migrate_legacy_json_if_needed() -> None:
    if not LEGACY_JSON_PATH.exists():
        return
    with db_connect() as conn:
        existing_jobs = conn.execute("SELECT COUNT(*) FROM dispatch_jobs").fetchone()[0]
        if existing_jobs:
            return
        legacy = json.loads(LEGACY_JSON_PATH.read_text(encoding="utf-8"))
        users = legacy.get("users", [])
        now = now_iso()
        for user in users:
            exists = conn.execute("SELECT 1 FROM users WHERE id = ?", (user["id"],)).fetchone()
            if not exists:
                conn.execute(
                    """
                    INSERT INTO users (id, name, email_or_mobile, password_hash, role, active_status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        user["id"],
                        user["name"],
                        user["id"],
                        hash_password("changeme123"),
                        user["role"],
                        now,
                        now,
                    ),
                )

        for job in legacy.get("dispatches", []):
            created_at = job.get("createdAt") or now
            updated_at = job.get("updatedAt") or created_at
            status = legacy_status(job.get("status", "ready"))
            reviewer_id = next(
                (
                    entry.get("actorId")
                    for entry in job.get("auditLog", [])
                    if str(entry.get("actorId", "")).startswith("reviewer")
                ),
                None,
            )
            conn.execute(
                """
                INSERT INTO dispatch_jobs (
                    id, invoice_number, party_name, place, bill_date, bill_file_url, extracted_bill_data_json,
                    total_cases, total_amount, current_status, priority, uploaded_by, dispatcher_id, reviewer_id,
                    transporter_delivery_partner_name, bill_uploaded_at, job_claimed_at, packing_started_at,
                    product_photo_uploaded_at, submitted_for_review_at, reviewed_at, correction_sent_at,
                    correction_resubmitted_at, reviewer_approved_at, bilty_uploaded_at, dispatched_at, delivered_at,
                    correction_count, admin_override_by, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'normal', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job["id"],
                    job.get("invoice", ""),
                    job.get("party", ""),
                    job.get("place", ""),
                    job.get("billDate", ""),
                    job.get("billFileUrl", ""),
                    json.dumps({}),
                    int(job.get("cases", 0)),
                    None,
                    status,
                    reviewer_id or "reviewer-1",
                    job.get("assignee") or None,
                    reviewer_id,
                    job.get("transporter", ""),
                    created_at,
                    created_at if job.get("assignee") else None,
                    created_at if job.get("packing") else None,
                    created_at if job.get("productPhotoUrl") else None,
                    created_at if status in {"submitted-for-review", "approved-by-reviewer", "delivered"} else None,
                    created_at if reviewer_id else None,
                    None,
                    None,
                    updated_at if status in {"approved-by-reviewer", "delivered"} else None,
                    updated_at if job.get("biltyPhotoUrl") else None,
                    updated_at if status in {"dispatched", "delivered"} else None,
                    updated_at if status == "delivered" else None,
                    0,
                    None,
                    created_at,
                    updated_at,
                ),
            )
            packing = job.get("packing") or empty_packing()
            conn.execute(
                """
                INSERT INTO packing_details
                (id, dispatch_job_id, packing_breakup_json, number_of_boxes, number_of_cases, dispatcher_note,
                 product_photo_url, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    job["id"],
                    json.dumps(packing),
                    sum(int(value or 0) for value in packing.values()),
                    int(job.get("cases", 0)),
                    job.get("dispatcherNote", ""),
                    job.get("productPhotoUrl", ""),
                    job.get("assignee") or None,
                    created_at,
                    updated_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO review_details
                (id, dispatch_job_id, reviewer_id, review_decision, reviewer_note,
                 transporter_delivery_partner_name, reviewed_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    job["id"],
                    reviewer_id,
                    "approved" if status in {"approved-by-reviewer", "delivered"} else None,
                    job.get("reviewerNote", ""),
                    job.get("transporter", ""),
                    updated_at if reviewer_id else None,
                    created_at,
                    updated_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO bilty_details
                (id, dispatch_job_id, bilty_number, bilty_photo_url, delivery_partner_name,
                 bilty_uploaded_by, bilty_uploaded_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    job["id"],
                    job.get("biltyNumber", ""),
                    job.get("biltyPhotoUrl", ""),
                    job.get("transporter", ""),
                    job.get("assignee") or None,
                    updated_at if job.get("biltyPhotoUrl") else None,
                    created_at,
                    updated_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO ai_photo_checks
                (id, dispatch_job_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), job["id"], created_at, updated_at),
            )
            for entry in reversed(job.get("auditLog", [])):
                changes = entry.get("changes", {})
                status_change = changes.get("status", {})
                actor_id = entry.get("actorId")
                actor = conn.execute("SELECT * FROM users WHERE id = ?", (actor_id,)).fetchone()
                log_action(
                    conn,
                    job["id"],
                    actor,
                    entry.get("action", "legacy_update"),
                    legacy_status(status_change.get("from")) if status_change.get("from") else None,
                    legacy_status(status_change.get("to")) if status_change.get("to") else None,
                    "",
                    {"legacy_changes": changes},
                    entry.get("timestamp") or created_at,
                )


def get_user(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def session_user(handler: BaseHTTPRequestHandler) -> sqlite3.Row | None:
    cookie = SimpleCookie(handler.headers.get("Cookie", ""))
    token = cookie.get("dispatch_session")
    if not token:
        return None
    with db_connect() as conn:
        row = conn.execute(
            """
            SELECT u.* FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ? AND s.expires_at > ?
            """,
            (token.value, now_iso()),
        ).fetchone()
        return row


def serialize_user(user: sqlite3.Row) -> dict:
    return {
        "id": user["id"],
        "name": user["name"],
        "emailOrMobile": user["email_or_mobile"],
        "role": user["role"],
        "activeStatus": bool(user["active_status"]),
    }


def load_json(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def serialize_job(conn: sqlite3.Connection, job_id: str) -> dict:
    job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
    packing = conn.execute("SELECT * FROM packing_details WHERE dispatch_job_id = ?", (job_id,)).fetchone()
    review = conn.execute("SELECT * FROM review_details WHERE dispatch_job_id = ?", (job_id,)).fetchone()
    bilty = conn.execute("SELECT * FROM bilty_details WHERE dispatch_job_id = ?", (job_id,)).fetchone()
    ai = conn.execute("SELECT * FROM ai_photo_checks WHERE dispatch_job_id = ?", (job_id,)).fetchone()
    logs = conn.execute(
        """
        SELECT l.*, u.name AS user_name
        FROM activity_logs l
        LEFT JOIN users u ON u.id = l.user_id
        WHERE l.dispatch_job_id = ?
        ORDER BY l.created_at DESC
        """,
        (job_id,),
    ).fetchall()
    packing_rows = conn.execute(
        """
        SELECT packing_type, no_of_packages, cases_per_package, total_cases
        FROM packing_breakup
        WHERE dispatch_job_id = ?
        ORDER BY created_at, id
        """,
        (job_id,),
    ).fetchall()
    packing_json = [
        {
            "packageType": row["packing_type"],
            "packageCount": row["no_of_packages"],
            "casesPerPackage": row["cases_per_package"],
            "totalCases": row["total_cases"],
        }
        for row in packing_rows
    ] or normalize_packing_lines(load_json(packing["packing_breakup_json"] if packing else None, empty_packing()))
    packing_photos = [
        {"photoType": row["photo_type"], "fileUrl": row["file_url"], "createdAt": row["created_at"]}
        for row in conn.execute(
            """
            SELECT photo_type, file_url, created_at
            FROM photos
            WHERE dispatch_job_id = ? AND photo_type IN ('pre-dispatch', 'final-packing')
            ORDER BY created_at
            """,
            (job_id,),
        ).fetchall()
    ]
    if not packing_photos:
        packing_photos = [
            {"photoType": "final-packing", "fileUrl": url, "createdAt": None}
            for url in load_json(packing["packing_photo_urls_json"] if packing else None, [])
        ]
    goods_check_photos = [
        {"photoType": row["photo_type"], "fileUrl": row["file_url"], "createdAt": row["created_at"]}
        for row in conn.execute(
            """
            SELECT photo_type, file_url, created_at
            FROM photos
            WHERE dispatch_job_id = ? AND photo_type = 'goods-check'
            ORDER BY created_at
            """,
            (job_id,),
        ).fetchall()
    ]
    totals = packing_totals(packing_json)
    return {
        "id": job["id"],
        "dailyEntryNo": job["daily_entry_no"],
        "dispatchDate": job["dispatch_date"] or date_part(job["created_at"]),
        "invoiceNumber": job["invoice_number"] or "",
        "partyName": job["party_name"],
        "partyCity": job["party_city"] or job["place"],
        "partyMobileNumber": job["party_mobile_number"] or "",
        "place": job["place"],
        "billDate": job["bill_date"] or "",
        "invoiceDate": job["bill_date"] or "",
        "billFileUrl": job["bill_file_url"] or "",
        "extractedBillData": load_json(job["extracted_bill_data_json"], {}),
        "billItems": load_json(job["bill_items_json"], []),
        "totalCases": job["total_cases"],
        "orderCaseCount": job["total_cases"],
        "totalPackages": job["total_packages"] or totals["totalPackages"],
        "totalPackedCases": job["total_packed_cases"] or totals["totalPackedCases"],
        "totalAmount": job["total_amount"],
        "invoiceAmount": job["total_amount"],
        "currentStatus": job["current_status"],
        "priority": job["priority"],
        "uploadedBy": job["uploaded_by"],
        "dispatcherId": job["dispatcher_id"],
        "reviewerId": job["reviewer_id"],
        "transporterDeliveryPartnerName": job["transporter_delivery_partner_name"] or "",
        "deliveryPartnerName": job["delivery_partner_name"] or "",
        "transportMode": job["transport_mode"] or "",
        "transportName": job["transport_name"] or "",
        "deliveryRoute": job["delivery_route"] or "",
        "routeSequence": job["route_sequence"],
        "routeBatchId": job["route_batch_id"],
        "packageCountDifference": job["package_count_difference"],
        "packageDifferenceReason": job["package_difference_reason"] or "",
        "packageDifferenceNote": job["package_difference_note"] or "",
        "shortageReason": job["shortage_reason"] or "",
        "shortageNote": job["shortage_note"] or "",
        "shortageItems": load_json(job["shortage_items_json"], []),
        "dispatcherNote": job["dispatcher_note"] or "",
        "reviewerNote": job["reviewer_note"] or "",
        "adminNote": job["admin_note"] or "",
        "whatsapp": {
            "templateName": job["whatsapp_template_name"],
            "sentStatus": job["whatsapp_sent_status"],
            "sentAt": job["whatsapp_sent_at"],
            "messageId": job["whatsapp_message_id"],
            "failedReason": job["whatsapp_failed_reason"],
        },
        "timestamps": {
            "billUploadedAt": job["bill_uploaded_at"],
            "jobClaimedAt": job["job_claimed_at"],
            "goodsPhotoUploadedAt": job["goods_photo_uploaded_at"],
            "goodsSubmittedForReviewAt": job["goods_submitted_for_review_at"],
            "goodsReviewedAt": job["goods_reviewed_at"],
            "goodsApprovedAt": job["goods_approved_at"],
            "packingStartedAt": job["packing_started_at"],
            "productPhotoUploadedAt": job["product_photo_uploaded_at"],
            "submittedForReviewAt": job["submitted_for_review_at"],
            "reviewedAt": job["reviewed_at"],
            "correctionSentAt": job["correction_sent_at"],
            "correctionResubmittedAt": job["correction_resubmitted_at"],
            "reviewerApprovedAt": job["reviewer_approved_at"],
            "biltyUploadedAt": job["bilty_uploaded_at"],
            "dispatchedAt": job["dispatched_at"],
            "deliveredAt": job["delivered_at"],
            "completedAt": job["completed_at"],
        },
        "correctionCount": job["correction_count"],
        "packingDetails": {
            "packingBreakup": packing_json,
            "packingSummary": packing_summary(packing_json),
            "packingType": packing["packing_type"] if packing else "",
            "totalPackages": job["total_packages"] or totals["totalPackages"],
            "totalPackedCases": job["total_packed_cases"] or totals["totalPackedCases"],
            "packingPhotos": packing_photos,
            "packingPhotoUrls": [photo["fileUrl"] for photo in packing_photos],
            "packingPhotoUrl": packing_photos[-1]["fileUrl"] if packing_photos else packing["product_photo_url"] if packing else "",
            "numberOfBoxes": packing["number_of_boxes"] if packing else 0,
            "numberOfCases": packing["number_of_cases"] if packing else job["total_cases"],
            "dispatcherNote": packing["dispatcher_note"] if packing else "",
            "productPhotoUrl": packing["product_photo_url"] if packing else "",
        },
        "goodsCheck": {
            "photos": goods_check_photos,
            "photoUrls": [photo["fileUrl"] for photo in goods_check_photos],
            "reviewerNote": job["goods_reviewer_note"] or "",
        },
        "reviewDetails": {
            "reviewDecision": review["review_decision"] if review else None,
            "reviewerNote": review["reviewer_note"] if review else "",
            "reviewerId": review["reviewer_id"] if review else None,
            "reviewedAt": review["reviewed_at"] if review else None,
        },
        "biltyDetails": {
            "biltyNumber": bilty["bilty_number"] if bilty else "",
            "optionalReferenceNumber": bilty["optional_reference_number"] if bilty else "",
            "biltyPhotoUrl": bilty["bilty_photo_url"] if bilty else "",
            "deliveryPartnerName": bilty["delivery_partner_name"] if bilty else "",
            "biltyDate": bilty["bilty_date"] if bilty else "",
            "biltyPackageCount": bilty["bilty_package_count"] if bilty else None,
            "biltyValue": bilty["bilty_value"] if bilty else None,
            "freightAmount": bilty["freight_amount"] if bilty else None,
            "biltyUploadedAt": bilty["bilty_uploaded_at"] if bilty else None,
        },
        "aiPhotoCheck": {
            "aiCheckStatus": ai["ai_check_status"] if ai else None,
            "aiMatchScore": ai["ai_match_score"] if ai else None,
            "aiRiskLevel": ai["ai_risk_level"] if ai else None,
            "aiDetectedBoxCount": ai["ai_detected_box_count"] if ai else None,
            "aiDetectedPartyMarking": ai["ai_detected_party_marking"] if ai else None,
            "aiDetectedPackageCount": ai["ai_detected_package_count"] if ai else None,
            "aiDetectedBiltyNumber": ai["ai_detected_bilty_number"] if ai else None,
            "aiDetectedBiltyTransportName": ai["ai_detected_bilty_transport_name"] if ai else None,
            "aiDetectedBiltyPackageCount": ai["ai_detected_bilty_package_count"] if ai else None,
            "aiDetectedBiltyDate": ai["ai_detected_bilty_date"] if ai else None,
            "aiDetectedItems": load_json(ai["ai_detected_items_json"] if ai else None, None),
            "aiMissingItems": load_json(ai["ai_missing_items_json"] if ai else None, None),
            "aiExtraItems": load_json(ai["ai_extra_items_json"] if ai else None, None),
            "aiQuantityMismatch": load_json(ai["ai_quantity_mismatch_json"] if ai else None, None),
            "aiPhotoQualityScore": ai["ai_photo_quality_score"] if ai else None,
            "aiSummary": ai["ai_summary"] if ai else None,
            "aiCheckedAt": ai["ai_checked_at"] if ai else None,
            "aiModelVersion": ai["ai_model_version"] if ai else None,
        },
        "createdAt": job["created_at"],
        "updatedAt": job["updated_at"],
        "activityLogs": [
            {
                "id": item["id"],
                "userId": item["user_id"],
                "userRole": item["user_role"],
                "userName": item["user_name"] or "System",
                "actionType": item["action_type"],
                "oldStatus": item["old_status"],
                "newStatus": item["new_status"],
                "remarks": item["remarks"] or "",
                "metadata": load_json(item["metadata_json"], {}),
                "createdAt": item["created_at"],
            }
            for item in logs
        ],
    }


def serialize_job_for_user(conn: sqlite3.Connection, job_id: str, user: sqlite3.Row) -> dict:
    payload = serialize_job(conn, job_id)
    if user["role"] == "dispatcher":
        payload["activityLogs"] = []
    return payload


def accessible_job_ids(conn: sqlite3.Connection, user: sqlite3.Row) -> list[str]:
    if user["role"] == "admin":
        rows = conn.execute("SELECT id FROM dispatch_jobs ORDER BY created_at DESC").fetchall()
    elif user["role"] == "reviewer":
        rows = conn.execute("SELECT id FROM dispatch_jobs ORDER BY created_at DESC").fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id FROM dispatch_jobs
            WHERE current_status = 'ready' OR dispatcher_id = ?
            ORDER BY created_at DESC
            """,
            (user["id"],),
        ).fetchall()
    return [row["id"] for row in rows]


def date_part(value: str | None) -> str:
    return value[:10] if value else ""


def minutes_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 60, 1)


def reviewer_metrics(conn: sqlite3.Connection) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    jobs = conn.execute("SELECT * FROM dispatch_jobs").fetchall()
    review_times = [
        minutes_between(job["submitted_for_review_at"], job["reviewer_approved_at"])
        for job in jobs
        if job["reviewer_approved_at"]
    ]
    review_times = [item for item in review_times if item is not None]
    return {
        "pendingChecking": sum(job["current_status"] == "submitted-for-review" for job in jobs),
        "approvedToday": sum(date_part(job["reviewer_approved_at"]) == today for job in jobs),
        "sentBackToday": sum(date_part(job["correction_sent_at"]) == today for job in jobs),
        "rejectedCancelled": sum(job["current_status"] == "cancelled" for job in jobs),
        "averageCheckingMinutes": round(sum(review_times) / len(review_times), 1) if review_times else 0,
        "oldPendingCases": sum(
            job["current_status"] == "submitted-for-review"
            and minutes_between(job["submitted_for_review_at"], now_iso()) not in (None,)
            and minutes_between(job["submitted_for_review_at"], now_iso()) > 120
            for job in jobs
        ),
    }


def dispatcher_metrics(conn: sqlite3.Connection, dispatcher_id: str) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    jobs = conn.execute("SELECT * FROM dispatch_jobs").fetchall()
    return {
        "openJobs": sum(job["current_status"] == "ready" for job in jobs),
        "myActiveJobs": sum(
            job["dispatcher_id"] == dispatcher_id
            and job["current_status"]
            in {"assigned", "packing", "needs-correction"}
            for job in jobs
        ),
        "submittedForReview": sum(
            job["dispatcher_id"] == dispatcher_id and job["current_status"] == "submitted-for-review" for job in jobs
        ),
        "needsCorrection": sum(
            job["dispatcher_id"] == dispatcher_id and job["current_status"] == "needs-correction" for job in jobs
        ),
        "approvedForDispatch": sum(
            job["dispatcher_id"] == dispatcher_id
            and job["current_status"] in {"approved-by-reviewer", "dispatch-pending"}
            for job in jobs
        ),
        "deliveredToday": sum(
            job["dispatcher_id"] == dispatcher_id and date_part(job["delivered_at"]) == today for job in jobs
        ),
    }


def admin_metrics(conn: sqlite3.Connection) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    jobs = conn.execute("SELECT * FROM dispatch_jobs").fetchall()
    return {
        "totalJobs": len(jobs),
        "readyJobs": sum(job["current_status"] == "ready" for job in jobs),
        "activeDispatchJobs": sum(
            job["current_status"] in {"assigned", "packing"} for job in jobs
        ),
        "pendingReviewerCheck": sum(job["current_status"] == "submitted-for-review" for job in jobs),
        "needsCorrection": sum(job["current_status"] == "needs-correction" for job in jobs),
        "biltyPending": sum(job["current_status"] in {"approved-by-reviewer", "dispatch-pending"} for job in jobs),
        "dispatchedToday": sum(date_part(job["dispatched_at"]) == today for job in jobs),
        "deliveredToday": sum(date_part(job["delivered_at"]) == today for job in jobs),
        "delayedJobs": sum(
            job["current_status"] not in {"delivered", "cancelled"}
            and minutes_between(job["created_at"], now_iso()) not in (None,)
            and minutes_between(job["created_at"], now_iso()) > 240
            for job in jobs
        ),
    }


def productivity_reports(conn: sqlite3.Connection) -> dict:
    dispatchers = conn.execute("SELECT * FROM users WHERE role = 'dispatcher'").fetchall()
    reviewers = conn.execute("SELECT * FROM users WHERE role = 'reviewer'").fetchall()
    jobs = conn.execute("SELECT * FROM dispatch_jobs").fetchall()
    dispatcher_rows = []
    for user in dispatchers:
        own = [job for job in jobs if job["dispatcher_id"] == user["id"]]
        avg_work = [
            minutes_between(job["job_claimed_at"], job["product_photo_uploaded_at"])
            for job in own
            if job["product_photo_uploaded_at"]
        ]
        avg_work = [item for item in avg_work if item is not None]
        dispatcher_rows.append(
            {
                "userId": user["id"],
                "name": user["name"],
                "completedJobs": sum(job["current_status"] == "delivered" for job in own),
                "corrections": sum(job["correction_count"] for job in own),
                "averageWorkingMinutes": round(sum(avg_work) / len(avg_work), 1) if avg_work else 0,
            }
        )
    reviewer_rows = []
    for user in reviewers:
        own = [job for job in jobs if job["reviewer_id"] == user["id"]]
        avg_review = [
            minutes_between(job["submitted_for_review_at"], job["reviewer_approved_at"])
            for job in own
            if job["reviewer_approved_at"]
        ]
        avg_review = [item for item in avg_review if item is not None]
        reviewer_rows.append(
            {
                "userId": user["id"],
                "name": user["name"],
                "approvals": sum(job["reviewer_approved_at"] is not None for job in own),
                "averageReviewMinutes": round(sum(avg_review) / len(avg_review), 1) if avg_review else 0,
            }
        )
    transporter = conn.execute(
        """
        SELECT transport_name AS name, COUNT(*) AS total
        FROM dispatch_jobs
        WHERE transport_name IS NOT NULL AND transport_name != ''
        GROUP BY transport_name
        ORDER BY total DESC
        """
    ).fetchall()
    delivery_partners = conn.execute(
        """
        SELECT delivery_partner_name AS name, COUNT(*) AS total
        FROM dispatch_jobs
        WHERE delivery_partner_name IS NOT NULL AND delivery_partner_name != ''
        GROUP BY delivery_partner_name
        ORDER BY total DESC
        """
    ).fetchall()
    job_timings = []
    for job in jobs:
        dispatcher_minutes = minutes_between(job["job_claimed_at"], job["submitted_for_review_at"])
        reviewer_minutes = minutes_between(job["submitted_for_review_at"], job["reviewer_approved_at"])
        total_minutes = minutes_between(job["bill_uploaded_at"], job["completed_at"] or job["delivered_at"] or job["dispatched_at"])
        job_timings.append(
            {
                "jobId": job["id"],
                "dispatchDate": job["dispatch_date"],
                "partyName": job["party_name"],
                "partyCity": job["party_city"] or job["place"],
                "dispatcherMinutes": dispatcher_minutes or 0,
                "reviewerMinutes": reviewer_minutes or 0,
                "totalMinutes": total_minutes or 0,
                "invoiceAmount": job["total_amount"] or 0,
                "freightAmount": conn.execute(
                    "SELECT COALESCE(freight_amount, 0) FROM bilty_details WHERE dispatch_job_id = ?",
                    (job["id"],),
                ).fetchone()[0],
                "status": job["current_status"],
            }
        )
    daily_summary = []
    for row in conn.execute(
        """
        SELECT dispatch_date,
               COUNT(*) AS jobs,
               COALESCE(SUM(total_packages), 0) AS packages,
               COALESCE(SUM(total_packed_cases), 0) AS packed_cases,
               COALESCE(SUM(total_amount), 0) AS invoice_amount
        FROM dispatch_jobs
        GROUP BY dispatch_date
        ORDER BY dispatch_date DESC
        """
    ):
        day_jobs = [item for item in job_timings if item["dispatchDate"] == row["dispatch_date"]]
        daily_summary.append(
            {
                "date": row["dispatch_date"],
                "jobs": row["jobs"],
                "packages": row["packages"],
                "packedCases": row["packed_cases"],
                "invoiceAmount": row["invoice_amount"],
                "freightAmount": round(sum(item["freightAmount"] or 0 for item in day_jobs), 2),
                "dispatcherMinutes": round(sum(item["dispatcherMinutes"] or 0 for item in day_jobs), 1),
                "reviewerMinutes": round(sum(item["reviewerMinutes"] or 0 for item in day_jobs), 1),
                "totalMinutes": round(sum(item["totalMinutes"] or 0 for item in day_jobs), 1),
            }
        )
    return {
        "dispatcherWise": dispatcher_rows,
        "reviewerWise": reviewer_rows,
        "transporterWise": [{"name": row["name"], "total": row["total"]} for row in transporter],
        "deliveryPartnerWise": [{"name": row["name"], "total": row["total"]} for row in delivery_partners],
        "jobTimings": job_timings,
        "dailySummary": daily_summary,
    }


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
        user = self.require_user()
        if not user:
            return
        if parsed.path == "/api/bills/extract":
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_bill_extract(user)
            return
        if parsed.path == "/api/dispatches":
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_create_dispatch(user)
            return
        if parsed.path == "/api/route-batches":
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_create_route_batch(user)
            return
        if parsed.path == "/api/delivery-partners":
            self.require_roles(user, {"admin"}) and self.handle_create_delivery_partner()
            return
        if parsed.path == "/api/users":
            self.require_roles(user, {"admin"}) and self.handle_create_user()
            return
        if parsed.path == "/api/admin/backup/import":
            self.require_roles(user, {"admin"}) and self.handle_backup_import(user)
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/claim", parsed.path):
            self.require_roles(user, {"dispatcher"}) and self.handle_claim_dispatch(user, match.group(1))
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/unassign", parsed.path):
            self.require_roles(user, {"dispatcher"}) and self.handle_unassign_dispatch(user, match.group(1))
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/product-photo", parsed.path):
            self.require_roles(user, {"dispatcher"}) and self.handle_product_photo(user, match.group(1))
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/submit-goods-review", parsed.path):
            self.require_roles(user, {"dispatcher"}) and self.handle_submit_goods_review(user, match.group(1))
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/goods-review-decision", parsed.path):
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_goods_review_decision(user, match.group(1))
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/closeup-photo", parsed.path):
            self.require_roles(user, {"dispatcher"}) and self.handle_closeup_photo(user, match.group(1))
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/submit-review", parsed.path):
            self.require_roles(user, {"dispatcher"}) and self.handle_submit_review(user, match.group(1))
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/review-decision", parsed.path):
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_review_decision(user, match.group(1))
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/bilty-photo", parsed.path):
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_bilty_photo(user, match.group(1))
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/mark-dispatched", parsed.path):
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_mark_dispatched(user, match.group(1))
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/mark-delivered", parsed.path):
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_mark_delivered(user, match.group(1))
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/mark-completed", parsed.path):
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_mark_completed(user, match.group(1))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        user = self.require_user()
        if not user:
            return
        if match := re.fullmatch(r"/api/users/([^/]+)", parsed.path):
            self.require_roles(user, {"admin"}) and self.handle_update_user(match.group(1))
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/packing", parsed.path):
            self.require_roles(user, {"dispatcher"}) and self.handle_save_packing(user, match.group(1))
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/bilty", parsed.path):
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_save_bilty(user, match.group(1))
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/reviewer-dispatch", parsed.path):
            self.require_roles(user, {"reviewer", "admin"}) and self.handle_save_reviewer_dispatch(user, match.group(1))
            return
        if match := re.fullmatch(r"/api/routes/([^/]+)", parsed.path):
            self.require_roles(user, {"admin"}) and self.handle_update_route(match.group(1))
            return
        if match := re.fullmatch(r"/api/dispatches/([^/]+)/admin", parsed.path):
            self.require_roles(user, {"admin"}) and self.handle_admin_override(user, match.group(1))
            return
        if parsed.path == "/api/settings":
            self.require_roles(user, {"admin"}) and self.handle_update_settings()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def handle_api_get(self, parsed) -> None:
        user = self.require_user()
        if not user:
            return
        if parsed.path == "/api/me":
            self.send_json({"user": serialize_user(user)})
            return
        if parsed.path == "/api/bootstrap":
            with db_connect() as conn:
                jobs = [serialize_job_for_user(conn, job_id, user) for job_id in accessible_job_ids(conn, user)]
                directory = [
                    {"id": item["id"], "name": item["name"], "role": item["role"]}
                    for item in conn.execute("SELECT * FROM users WHERE active_status = 1 ORDER BY role, name")
                ]
                payload = {
                    "me": serialize_user(user),
                    "jobs": jobs,
                    "directory": directory,
                    "settings": {item["key"]: item["value"] for item in conn.execute("SELECT key, value FROM app_settings")},
                }
                if user["role"] == "dispatcher":
                    payload["metrics"] = dispatcher_metrics(conn, user["id"])
                elif user["role"] == "reviewer":
                    payload["metrics"] = reviewer_metrics(conn)
                else:
                    payload["metrics"] = admin_metrics(conn)
                    payload["users"] = [serialize_user(item) for item in conn.execute("SELECT * FROM users ORDER BY role, name")]
                    payload["reports"] = productivity_reports(conn)
                if user["role"] in {"reviewer", "admin"}:
                    payload["routes"] = [dict(item) for item in conn.execute("SELECT * FROM route_names ORDER BY id")]
                    payload["routeBatches"] = [dict(item) for item in conn.execute("SELECT * FROM route_batches ORDER BY created_at DESC")]
                    payload["deliveryPartners"] = [
                        dict(item)
                        for item in conn.execute(
                            "SELECT id, name, preferred_transport_name, active_status FROM delivery_partners WHERE active_status = 1 ORDER BY name"
                        )
                    ]
                self.send_json(payload)
            return
        if parsed.path == "/api/admin/reports":
            if not self.require_roles(user, {"admin"}):
                return
            with db_connect() as conn:
                self.send_json(productivity_reports(conn))
            return
        if parsed.path == "/api/bills/export":
            if not self.require_roles(user, {"admin"}):
                return
            self.handle_bill_export(parsed)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def handle_login(self) -> None:
        try:
            payload = self.read_json()
            login = payload.get("login", "").strip()
            password = payload.get("password", "")
            ensure_storage()
            with db_connect() as conn:
                user = conn.execute(
                    "SELECT * FROM users WHERE email_or_mobile = ? AND active_status = 1",
                    (login,),
                ).fetchone()
                if not user or not verify_password(password, user["password_hash"]):
                    self.send_json({"error": "Invalid login or password."}, HTTPStatus.UNAUTHORIZED)
                    return
                token = secrets.token_urlsafe(32)
                expires_at = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat()
                conn.execute(
                    "INSERT INTO auth_sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                    (token, user["id"], now_iso(), expires_at),
                )
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header(
                    "Set-Cookie",
                    f"dispatch_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_DAYS * 86400}",
                )
                data = json.dumps({"user": serialize_user(user)}).encode("utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except Exception as exc:
            print(f"LOGIN_ERROR {type(exc).__name__}: {exc}", flush=True)
            self.send_json(
                {
                    "error": "Login server error.",
                    "errorType": type(exc).__name__,
                    "detail": str(exc),
                },
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def handle_health(self) -> None:
        payload = {
            "ok": True,
            "dataDir": str(DATA_DIR),
            "uploadDir": str(UPLOAD_DIR),
            "dbPath": str(DB_PATH),
            "dbExists": DB_PATH.exists(),
            "uploadDirExists": UPLOAD_DIR.exists(),
        }
        try:
            ensure_storage()
            with db_connect() as conn:
                tables = {
                    row[0]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                payload["tables"] = sorted(tables)
                payload["userColumns"] = [
                    row["name"] for row in conn.execute("PRAGMA table_info(users)")
                ] if "users" in tables else []
                payload["users"] = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] if "users" in tables else 0
                payload["jobs"] = conn.execute("SELECT COUNT(*) FROM dispatch_jobs").fetchone()[0] if "dispatch_jobs" in tables else 0
                payload["uploadFiles"] = sum(1 for item in UPLOAD_DIR.rglob("*") if item.is_file()) if UPLOAD_DIR.exists() else 0
                sample_bill = conn.execute(
                    "SELECT bill_file_url FROM dispatch_jobs WHERE bill_file_url IS NOT NULL AND bill_file_url != '' LIMIT 1"
                ).fetchone() if "dispatch_jobs" in tables else None
                if sample_bill:
                    sample_path = upload_url_to_path(sample_bill["bill_file_url"])
                    payload["sampleBillUrl"] = sample_bill["bill_file_url"]
                    payload["sampleBillPath"] = str(sample_path)
                    payload["sampleBillExists"] = sample_path.exists()
        except Exception as exc:
            payload.update({"ok": False, "errorType": type(exc).__name__, "detail": str(exc)})
        self.send_json(payload, HTTPStatus.OK if payload.get("ok") else HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_logout(self) -> None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie.get("dispatch_session")
        if token:
            with db_connect() as conn:
                conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token.value,))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", "dispatch_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
        data = b'{"ok": true}'
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_bill_extract(self, user: sqlite3.Row) -> None:
        form = self.parse_multipart()
        upload = form["file"] if "file" in form else None
        if upload is None or not getattr(upload, "filename", ""):
            self.send_json({"error": "Bill file is required."}, HTTPStatus.BAD_REQUEST)
            return
        suffix = Path(upload.filename).suffix.lower()
        if suffix != ".pdf":
            self.send_json(
                {"error": "Real extraction is currently available for PDF bills. Photo OCR comes next."},
                HTTPStatus.BAD_REQUEST,
            )
            return
        saved_name = f"{uuid.uuid4()}{suffix}"
        saved_path = BILLS_DIR / saved_name
        with saved_path.open("wb") as target:
            shutil.copyfileobj(upload.file, target)
        try:
            text = extract_pdf_text(saved_path)
            extracted = parse_bill_text(text)
        except Exception as exc:
            self.send_json({"error": f"Could not read PDF: {exc}"}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json({"fileUrl": f"/uploads/bills/{saved_name}", "fileName": upload.filename, "extracted": extracted})

    def handle_create_dispatch(self, user: sqlite3.Row) -> None:
        payload = self.read_json()
        required = ["partyName", "place", "orderCaseCount", "deliveryRoute"]
        if any(not payload.get(field) for field in required):
            self.send_json({"error": "Party, place, route, and total cases are required."}, HTTPStatus.BAD_REQUEST)
            return
        invoice = payload.get("invoiceNumber", "").strip()
        with db_connect() as conn:
            timestamp = now_iso()
            job_id = str(uuid.uuid4())
            next_entry = conn.execute(
                "SELECT COALESCE(MAX(daily_entry_no), 0) + 1 FROM dispatch_jobs WHERE dispatch_date = ?",
                (payload.get("dispatchDate") or timestamp[:10],),
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO dispatch_jobs (
                    id, daily_entry_no, dispatch_date, invoice_number, party_name, party_city, party_mobile_number,
                    place, bill_date, bill_file_url, extracted_bill_data_json,
                    bill_items_json, total_cases, total_packages, total_packed_cases, total_amount,
                    delivery_route, transport_name, current_status, priority, uploaded_by, bill_uploaded_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, 'ready', ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    next_entry,
                    payload.get("dispatchDate") or timestamp[:10],
                    invoice,
                    payload["partyName"].strip(),
                    payload.get("partyCity", payload["place"]).strip(),
                    payload.get("partyMobileNumber", "").strip(),
                    payload["place"].strip(),
                    payload.get("invoiceDate", payload.get("billDate", "")),
                    payload.get("billFileUrl", ""),
                    json.dumps(payload.get("extractedBillData", {})),
                    json.dumps(payload.get("billItems", payload.get("extractedBillData", {}).get("items", []))),
                    int(payload["orderCaseCount"]),
                    payload.get("invoiceAmount", payload.get("totalAmount")),
                    payload.get("deliveryRoute", "").strip(),
                    payload.get("extractedBillData", {}).get("transporter", "").strip(),
                    payload.get("priority", "normal"),
                    user["id"],
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            conn.execute(
                """
                INSERT INTO packing_details
                (id, dispatch_job_id, packing_breakup_json, packing_type, shop_package_count, packing_photo_urls_json,
                 number_of_boxes, number_of_cases, dispatcher_note, product_photo_url, created_by, created_at, updated_at)
                VALUES (?, ?, ?, '', 0, '[]', 0, ?, '', '', NULL, ?, ?)
                """,
                (str(uuid.uuid4()), job_id, json.dumps(empty_packing()), int(payload["orderCaseCount"]), timestamp, timestamp),
            )
            conn.execute(
                """
                INSERT INTO review_details
                (id, dispatch_job_id, reviewer_id, review_decision, reviewer_note,
                 transporter_delivery_partner_name, reviewed_at, created_at, updated_at)
                VALUES (?, ?, NULL, NULL, '', '', NULL, ?, ?)
                """,
                (str(uuid.uuid4()), job_id, timestamp, timestamp),
            )
            conn.execute(
                """
                INSERT INTO bilty_details
                (id, dispatch_job_id, bilty_number, bilty_photo_url, delivery_partner_name,
                 freight_amount, bilty_uploaded_by, bilty_uploaded_at, created_at, updated_at)
                VALUES (?, ?, '', '', '', ?, NULL, NULL, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    job_id,
                    payload.get("extractedBillData", {}).get("freightAmount"),
                    timestamp,
                    timestamp,
                ),
            )
            conn.execute(
                """
                INSERT INTO ai_photo_checks
                (id, dispatch_job_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), job_id, timestamp, timestamp),
            )
            log_action(conn, job_id, user, "bill_uploaded", None, "ready", metadata={"bill_file_url": payload.get("billFileUrl", "")})
            self.send_json(serialize_job_for_user(conn, job_id, user), HTTPStatus.CREATED)

    def handle_claim_dispatch(self, user: sqlite3.Row, job_id: str) -> None:
        with db_connect() as conn:
            job = self.require_job(conn, job_id)
            if not job:
                return
            if job["current_status"] != "ready" or job["dispatcher_id"]:
                self.send_json({"error": "This job is no longer available to claim."}, HTTPStatus.CONFLICT)
                return
            active_count = conn.execute(
                """
                SELECT COUNT(*) FROM dispatch_jobs
                WHERE dispatcher_id = ?
                AND current_status IN ('assigned', 'goods-photo-uploaded', 'goods-needs-correction', 'goods-approved', 'packing', 'needs-correction')
                """,
                (user["id"],),
            ).fetchone()[0]
            if active_count >= 2:
                self.send_json({"error": "You already have 2 active jobs. Complete one job before taking another."}, HTTPStatus.CONFLICT)
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
            log_action(conn, job_id, user, "job_claimed", "ready", "assigned")
            self.send_json(serialize_job_for_user(conn, job_id, user))

    def handle_unassign_dispatch(self, user: sqlite3.Row, job_id: str) -> None:
        with db_connect() as conn:
            job = self.require_owned_dispatcher_job(conn, user, job_id)
            if not job:
                return
            packing = conn.execute("SELECT * FROM packing_details WHERE dispatch_job_id = ?", (job_id,)).fetchone()
            photo_count = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE dispatch_job_id = ? AND photo_type IN ('pre-dispatch', 'final-packing')",
                (job_id,),
            ).fetchone()[0]
            breakup = normalize_packing_lines(load_json(packing["packing_breakup_json"], empty_packing()))
            if job["current_status"] != "assigned" or breakup or photo_count:
                self.send_json({"error": "Only untouched claimed jobs can be unassigned."}, HTTPStatus.CONFLICT)
                return
            timestamp = now_iso()
            conn.execute(
                """
                UPDATE dispatch_jobs
                SET dispatcher_id = NULL, current_status = 'ready', job_claimed_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (timestamp, job_id),
            )
            log_action(conn, job_id, user, "job_unassigned", "assigned", "ready")
            self.send_json(serialize_job_for_user(conn, job_id, user))

    def handle_save_packing(self, user: sqlite3.Row, job_id: str) -> None:
        payload = self.read_json()
        with db_connect() as conn:
            job = self.require_owned_dispatcher_job(conn, user, job_id)
            if not job:
                return
            if job["current_status"] not in {
                "assigned",
                "goods-photo-uploaded",
                "goods-needs-correction",
                "goods-approved",
                "packing",
                "needs-correction",
            }:
                self.send_json({"error": "Packing can no longer be edited for this job."}, HTTPStatus.CONFLICT)
                return
            packing = normalize_packing_lines(payload.get("packingBreakup", empty_packing()))
            totals = packing_totals(packing)
            packing_type = payload.get("packingType", "").strip()
            number_of_boxes = totals["totalPackages"]
            number_of_cases = totals["totalPackedCases"]
            note = payload.get("dispatcherNote", "").strip()
            shortage_reason = payload.get("shortageReason", "").strip()
            shortage_note = payload.get("shortageNote", "").strip()
            shortage_items = payload.get("shortageItems", [])
            timestamp = now_iso()
            old_status = job["current_status"]
            new_status = "packing" if old_status in {"assigned", "goods-photo-uploaded", "goods-needs-correction", "goods-approved"} else old_status
            conn.execute(
                """
                UPDATE packing_details
                SET packing_breakup_json = ?, packing_type = ?, shop_package_count = ?, number_of_boxes = ?,
                    number_of_cases = ?, dispatcher_note = ?, updated_at = ?
                WHERE dispatch_job_id = ?
                """,
                (json.dumps(packing), packing_type, totals["totalPackages"], number_of_boxes, number_of_cases, note, timestamp, job_id),
            )
            conn.execute("DELETE FROM packing_breakup WHERE dispatch_job_id = ?", (job_id,))
            for line in packing:
                conn.execute(
                    """
                    INSERT INTO packing_breakup
                    (id, dispatch_job_id, packing_type, no_of_packages, cases_per_package, total_cases, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        job_id,
                        line["packageType"],
                        line["packageCount"],
                        line["casesPerPackage"],
                        line["totalCases"],
                        timestamp,
                        timestamp,
                    ),
                )
            conn.execute(
                """
                UPDATE dispatch_jobs
                SET current_status = ?, packing_started_at = COALESCE(packing_started_at, ?),
                    dispatcher_note = ?, total_packages = ?, total_packed_cases = ?,
                    shortage_reason = ?, shortage_note = ?, shortage_items_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    new_status,
                    timestamp,
                    note,
                    totals["totalPackages"],
                    totals["totalPackedCases"],
                    shortage_reason,
                    shortage_note,
                    json.dumps(shortage_items),
                    timestamp,
                    job_id,
                ),
            )
            log_action(
                conn,
                job_id,
                user,
                "packing_saved",
                old_status,
                new_status,
                metadata={
                    "packing_breakup": packing,
                    "total_packages": totals["totalPackages"],
                    "total_packed_cases": totals["totalPackedCases"],
                    "order_case_count": job["total_cases"],
                    "shortage_reason": shortage_reason,
                },
            )
            self.send_json(serialize_job_for_user(conn, job_id, user))

    def handle_product_photo(self, user: sqlite3.Row, job_id: str) -> None:
        form = self.parse_multipart()
        upload = form["file"] if "file" in form else None
        photo_type = str(form["photoType"].value).strip() if "photoType" in form else "final-packing"
        if photo_type not in {"goods-check", "pre-dispatch", "final-packing"}:
            photo_type = "final-packing"
        if upload is None or not getattr(upload, "filename", ""):
            self.send_json({"error": "Product photo is required."}, HTTPStatus.BAD_REQUEST)
            return
        with db_connect() as conn:
            job = self.require_owned_dispatcher_job(conn, user, job_id)
            if not job:
                return
            if photo_type == "goods-check":
                allowed_statuses = {"assigned", "goods-photo-uploaded", "goods-needs-correction", "packing", "needs-correction"}
            else:
                allowed_statuses = {"goods-approved", "packing", "needs-correction"}
            if job["current_status"] not in allowed_statuses:
                self.send_json({"error": "Product photo cannot be changed at this stage."}, HTTPStatus.CONFLICT)
                return
            suffix = Path(upload.filename).suffix.lower() or ".jpg"
            saved_name = f"{uuid.uuid4()}{suffix}"
            saved_path = PRODUCT_PHOTOS_DIR / saved_name
            with saved_path.open("wb") as target:
                shutil.copyfileobj(upload.file, target)
            timestamp = now_iso()
            old_status = job["current_status"]
            photo_url = f"/uploads/product-photos/{saved_name}"
            if photo_type == "goods-check":
                conn.execute(
                    """
                    UPDATE dispatch_jobs
                    SET current_status = CASE
                            WHEN current_status IN ('assigned', 'goods-photo-uploaded', 'goods-needs-correction') THEN 'packing'
                            ELSE current_status
                        END,
                        goods_photo_uploaded_at = ?,
                        packing_started_at = COALESCE(packing_started_at, ?),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (timestamp, timestamp, timestamp, job_id),
                )
                new_status = "packing" if old_status in {"assigned", "goods-photo-uploaded", "goods-needs-correction"} else old_status
            else:
                packing_row = conn.execute("SELECT packing_photo_urls_json FROM packing_details WHERE dispatch_job_id = ?", (job_id,)).fetchone()
                photos = load_json(packing_row["packing_photo_urls_json"], [])
                photos.append(photo_url)
                conn.execute(
                    """
                    UPDATE packing_details
                    SET product_photo_url = ?, packing_photo_urls_json = ?, updated_at = ?
                    WHERE dispatch_job_id = ?
                    """,
                    (photo_url, json.dumps(photos), timestamp, job_id),
                )
                conn.execute(
                    """
                    UPDATE dispatch_jobs
                    SET current_status = CASE WHEN current_status = 'goods-approved' THEN 'packing' ELSE current_status END,
                        packing_started_at = COALESCE(packing_started_at, ?),
                        product_photo_uploaded_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (timestamp, timestamp, timestamp, job_id),
                )
                new_status = "packing" if old_status == "goods-approved" else old_status
            log_action(
                conn,
                job_id,
                user,
                "product_photo_uploaded",
                old_status,
                new_status,
                metadata={"file_url": photo_url, "photo_type": photo_type},
            )
            conn.execute(
                """
                INSERT INTO photos (id, dispatch_job_id, photo_type, file_url, uploaded_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), job_id, photo_type, photo_url, user["id"], timestamp),
            )
            self.send_json(serialize_job_for_user(conn, job_id, user))

    def handle_submit_goods_review(self, user: sqlite3.Row, job_id: str) -> None:
        with db_connect() as conn:
            job = self.require_owned_dispatcher_job(conn, user, job_id)
            if not job:
                return
            goods_photo_count = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE dispatch_job_id = ? AND photo_type = 'goods-check'",
                (job_id,),
            ).fetchone()[0]
            if not goods_photo_count:
                self.send_json({"error": "Upload goods photo"}, HTTPStatus.BAD_REQUEST)
                return
            if job["current_status"] not in {"goods-photo-uploaded", "goods-needs-correction"}:
                self.send_json({"error": "Goods check is not ready for review."}, HTTPStatus.CONFLICT)
                return
            timestamp = now_iso()
            old_status = job["current_status"]
            conn.execute(
                """
                UPDATE dispatch_jobs
                SET current_status = 'goods-submitted-for-review',
                    goods_submitted_for_review_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (timestamp, timestamp, job_id),
            )
            log_action(conn, job_id, user, "goods_submitted_for_review", old_status, "goods-submitted-for-review")
            self.send_json(serialize_job_for_user(conn, job_id, user))

    def handle_goods_review_decision(self, user: sqlite3.Row, job_id: str) -> None:
        payload = self.read_json()
        decision = payload.get("decision")
        note = payload.get("reviewerNote", "").strip()
        if decision not in {"approve", "correction", "cancel"}:
            self.send_json({"error": "Invalid goods review decision."}, HTTPStatus.BAD_REQUEST)
            return
        with db_connect() as conn:
            job = self.require_job(conn, job_id)
            if not job:
                return
            if job["current_status"] != "goods-submitted-for-review":
                self.send_json({"error": "Only submitted goods checks can be reviewed."}, HTTPStatus.CONFLICT)
                return
            timestamp = now_iso()
            status_map = {
                "approve": "goods-approved",
                "correction": "goods-needs-correction",
                "cancel": "cancelled",
            }
            new_status = status_map[decision]
            conn.execute(
                """
                UPDATE dispatch_jobs
                SET current_status = ?,
                    reviewer_id = ?,
                    goods_reviewer_note = ?,
                    goods_reviewed_at = ?,
                    goods_approved_at = CASE WHEN ? = 'approve' THEN ? ELSE goods_approved_at END,
                    updated_at = ?
                WHERE id = ?
                """,
                (new_status, user["id"], note, timestamp, decision, timestamp, timestamp, job_id),
            )
            conn.execute(
                """
                UPDATE ai_photo_checks
                SET ai_check_status = ?,
                    ai_summary = ?,
                    ai_checked_at = ?,
                    ai_model_version = COALESCE(ai_model_version, 'human-label-v1'),
                    updated_at = ?
                WHERE dispatch_job_id = ?
                """,
                (
                    f"human-{decision}",
                    note or f"Human reviewer marked goods as {decision}.",
                    timestamp,
                    timestamp,
                    job_id,
                ),
            )
            log_action(conn, job_id, user, f"goods_review_{decision}", "goods-submitted-for-review", new_status, remarks=note)
            self.send_json(serialize_job_for_user(conn, job_id, user))

    def handle_closeup_photo(self, user: sqlite3.Row, job_id: str) -> None:
        form = self.parse_multipart()
        upload = form["file"] if "file" in form else None
        if upload is None or not getattr(upload, "filename", ""):
            self.send_json({"error": "Close-up photo is required."}, HTTPStatus.BAD_REQUEST)
            return
        with db_connect() as conn:
            job = self.require_owned_dispatcher_job(conn, user, job_id)
            if not job:
                return
            if job["current_status"] not in {"assigned", "packing", "needs-correction"}:
                self.send_json({"error": "Close-up photo cannot be changed at this stage."}, HTTPStatus.CONFLICT)
                return
            suffix = Path(upload.filename).suffix.lower() or ".jpg"
            saved_name = f"{uuid.uuid4()}{suffix}"
            saved_path = PRODUCT_PHOTOS_DIR / saved_name
            with saved_path.open("wb") as target:
                shutil.copyfileobj(upload.file, target)
            photo_url = f"/uploads/product-photos/{saved_name}"
            timestamp = now_iso()
            conn.execute(
                "UPDATE packing_details SET closeup_marking_photo_url = ?, updated_at = ? WHERE dispatch_job_id = ?",
                (photo_url, timestamp, job_id),
            )
            log_action(conn, job_id, user, "closeup_photo_uploaded", job["current_status"], job["current_status"], metadata={"file_url": photo_url, "photo_type": "closeup"})
            self.send_json(serialize_job_for_user(conn, job_id, user))

    def handle_submit_review(self, user: sqlite3.Row, job_id: str) -> None:
        with db_connect() as conn:
            job = self.require_owned_dispatcher_job(conn, user, job_id)
            if not job:
                return
            goods_photo_count = conn.execute(
                """
                SELECT COUNT(*) FROM photos
                WHERE dispatch_job_id = ? AND photo_type = 'goods-check'
                """,
                (job_id,),
            ).fetchone()[0]
            if not goods_photo_count:
                self.send_json({"error": "Upload goods photo"}, HTTPStatus.BAD_REQUEST)
                return
            packing = conn.execute("SELECT * FROM packing_details WHERE dispatch_job_id = ?", (job_id,)).fetchone()
            breakup = normalize_packing_lines(load_json(packing["packing_breakup_json"], empty_packing()))
            packing_photo_count = conn.execute(
                """
                SELECT COUNT(*) FROM photos
                WHERE dispatch_job_id = ? AND photo_type IN ('pre-dispatch', 'final-packing')
                """,
                (job_id,),
            ).fetchone()[0]
            if not packing_photo_count and not packing["product_photo_url"]:
                self.send_json({"error": "Upload packing photo"}, HTTPStatus.BAD_REQUEST)
                return
            if not breakup:
                self.send_json({"error": "Enter packing breakup"}, HTTPStatus.BAD_REQUEST)
                return
            totals = packing_totals(breakup)
            if totals["totalPackedCases"] != job["total_cases"] and not job["shortage_reason"]:
                self.send_json({"error": "Packed cases do not match bill cases. Please correct the breakup or enter a valid reason."}, HTTPStatus.BAD_REQUEST)
                return
            if job["current_status"] not in {"packing", "needs-correction"}:
                self.send_json({"error": "This job is not ready to submit for review."}, HTTPStatus.CONFLICT)
                return
            timestamp = now_iso()
            old_status = job["current_status"]
            conn.execute(
                """
                UPDATE dispatch_jobs
                SET current_status = 'submitted-for-review',
                    submitted_for_review_at = ?,
                    correction_resubmitted_at = CASE WHEN correction_count > 0 AND correction_sent_at IS NOT NULL THEN ? ELSE correction_resubmitted_at END,
                    updated_at = ?
                WHERE id = ?
                """,
                (timestamp, timestamp, timestamp, job_id),
            )
            log_action(conn, job_id, user, "submitted_for_review", old_status, "submitted-for-review")
            self.send_json(serialize_job_for_user(conn, job_id, user))

    def handle_review_decision(self, user: sqlite3.Row, job_id: str) -> None:
        payload = self.read_json()
        decision = payload.get("decision")
        note = payload.get("reviewerNote", "").strip()
        if decision not in {"approve", "correction", "cancel"}:
            self.send_json({"error": "Invalid review decision."}, HTTPStatus.BAD_REQUEST)
            return
        with db_connect() as conn:
            job = self.require_job(conn, job_id)
            if not job:
                return
            if job["current_status"] != "submitted-for-review":
                self.send_json({"error": "Only jobs submitted for review can be reviewed."}, HTTPStatus.CONFLICT)
                return
            packing = conn.execute("SELECT * FROM packing_details WHERE dispatch_job_id = ?", (job_id,)).fetchone()
            breakup = normalize_packing_lines(load_json(packing["packing_breakup_json"], empty_packing())) if packing else []
            packing_photo_count = conn.execute(
                """
                SELECT COUNT(*) FROM photos
                WHERE dispatch_job_id = ? AND photo_type IN ('pre-dispatch', 'final-packing')
                """,
                (job_id,),
            ).fetchone()[0]
            goods_photo_count = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE dispatch_job_id = ? AND photo_type = 'goods-check'",
                (job_id,),
            ).fetchone()[0]
            totals = packing_totals(breakup)
            if decision == "approve":
                if not goods_photo_count or (not packing_photo_count and not (packing["product_photo_url"] if packing else "")):
                    self.send_json({"error": "Cannot approve. Required photos are missing."}, HTTPStatus.BAD_REQUEST)
                    return
                if not breakup:
                    self.send_json({"error": "Cannot approve. Please enter package breakup."}, HTTPStatus.BAD_REQUEST)
                    return
                if totals["totalPackedCases"] != int(job["total_cases"] or 0) and not job["shortage_reason"]:
                    self.send_json({"error": "Cannot approve. Packed cases do not match bill cases."}, HTTPStatus.BAD_REQUEST)
                    return
            if decision == "approve" and job["correction_count"] > 0 and not note:
                self.send_json({"error": "Reviewer note is required after a correction was raised."}, HTTPStatus.BAD_REQUEST)
                return
            timestamp = now_iso()
            status_map = {"approve": "approved-by-reviewer", "correction": "needs-correction", "cancel": "cancelled"}
            new_status = status_map[decision]
            conn.execute(
                """
                UPDATE review_details
                SET reviewer_id = ?, review_decision = ?, reviewer_note = ?,
                    transporter_delivery_partner_name = ?, reviewed_at = ?, updated_at = ?
                WHERE dispatch_job_id = ?
                """,
                (user["id"], decision, note, job["delivery_partner_name"] or "", timestamp, timestamp, job_id),
            )
            conn.execute(
                """
                UPDATE dispatch_jobs
                SET current_status = ?, reviewer_id = ?, reviewer_note = ?,
                    reviewed_at = ?, correction_sent_at = CASE WHEN ? = 'correction' THEN ? ELSE correction_sent_at END,
                    reviewer_approved_at = CASE WHEN ? = 'approve' THEN ? ELSE reviewer_approved_at END,
                    correction_count = correction_count + CASE WHEN ? = 'correction' THEN 1 ELSE 0 END,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    new_status,
                    user["id"],
                    note,
                    timestamp,
                    decision,
                    timestamp,
                    decision,
                    timestamp,
                    decision,
                    timestamp,
                    job_id,
                ),
            )
            log_action(conn, job_id, user, f"review_{decision}", "submitted-for-review", new_status, remarks=note)
            self.send_json(serialize_job_for_user(conn, job_id, user))

    def handle_save_bilty(self, user: sqlite3.Row, job_id: str) -> None:
        payload = self.read_json()
        optional_reference_number = payload.get("optionalReferenceNumber", payload.get("biltyNumber", "")).strip()
        with db_connect() as conn:
            job = self.require_bilty_actor_job(conn, user, job_id)
            if not job:
                return
            if job["current_status"] not in {"approved-by-reviewer", "dispatch-pending", "dispatched"}:
                self.send_json({"error": "Bilty can only be added after reviewer approval."}, HTTPStatus.CONFLICT)
                return
            timestamp = now_iso()
            old_status = job["current_status"]
            conn.execute(
                """
                UPDATE bilty_details
                SET optional_reference_number = ?, updated_at = ?
                WHERE dispatch_job_id = ?
                """,
                (optional_reference_number, timestamp, job_id),
            )
            conn.execute(
                """
                UPDATE dispatch_jobs
                SET current_status = 'dispatch-pending', updated_at = ?
                WHERE id = ?
                """,
                (timestamp, job_id),
            )
            log_action(conn, job_id, user, "bilty_reference_saved", old_status, "dispatch-pending")
            self.send_json(serialize_job_for_user(conn, job_id, user))

    def handle_save_reviewer_dispatch(self, user: sqlite3.Row, job_id: str) -> None:
        payload = self.read_json()
        with db_connect() as conn:
            job = self.require_job(conn, job_id)
            if not job:
                return
            if job["current_status"] not in {"approved-by-reviewer", "dispatch-pending", "dispatched", "delivered"}:
                self.send_json({"error": "Approve packing first"}, HTTPStatus.CONFLICT)
                return
            delivery_partner_name = payload.get("deliveryPartnerName", "").strip()
            transport_mode = payload.get("transportMode", "").strip()
            transport_name = payload.get("transportName", "").strip()
            bilty_package_count = payload.get("biltyPackageCount")
            bilty_package_count = None if bilty_package_count in ("", None) else int(bilty_package_count)
            optional_reference_number = payload.get("optionalReferenceNumber", "").strip()
            package_difference_reason = payload.get("packageDifferenceReason", "").strip()
            package_difference_note = payload.get("packageDifferenceNote", "").strip()
            bilty_date = payload.get("biltyDate", "")
            bilty_value = payload.get("biltyValue")
            freight_amount = payload.get("freightAmount")
            delivery_route = payload.get("deliveryRoute", "").strip()
            route_sequence = payload.get("routeSequence")
            difference = None if bilty_package_count is None else bilty_package_count - int(job["total_packages"] or 0)
            timestamp = now_iso()
            conn.execute(
                """
                UPDATE dispatch_jobs
                SET delivery_partner_name = ?, transport_mode = ?, transport_name = ?, delivery_route = ?,
                    route_sequence = ?, package_count_difference = ?, package_difference_reason = ?,
                    package_difference_note = ?, current_status = CASE WHEN current_status = 'approved-by-reviewer' THEN 'dispatch-pending' ELSE current_status END,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    delivery_partner_name,
                    transport_mode,
                    transport_name,
                    delivery_route,
                    route_sequence,
                    difference,
                    package_difference_reason,
                    package_difference_note,
                    timestamp,
                    job_id,
                ),
            )
            conn.execute(
                """
                UPDATE bilty_details
                SET optional_reference_number = ?, delivery_partner_name = ?, bilty_date = ?,
                    bilty_package_count = ?, bilty_value = ?, freight_amount = ?, updated_at = ?
                WHERE dispatch_job_id = ?
                """,
                (
                    optional_reference_number,
                    delivery_partner_name,
                    bilty_date,
                    bilty_package_count,
                    bilty_value,
                    freight_amount,
                    timestamp,
                    job_id,
                ),
            )
            if delivery_partner_name:
                conn.execute(
                    """
                    INSERT INTO delivery_partners (name, preferred_transport_name, active_status, created_at, updated_at)
                    VALUES (?, ?, 1, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                      preferred_transport_name = CASE WHEN excluded.preferred_transport_name != '' THEN excluded.preferred_transport_name ELSE delivery_partners.preferred_transport_name END,
                      active_status = 1,
                      updated_at = excluded.updated_at
                    """,
                    (delivery_partner_name, transport_name, timestamp, timestamp),
                )
            log_action(conn, job_id, user, "dispatch_details_saved", job["current_status"], "dispatch-pending" if job["current_status"] == "approved-by-reviewer" else job["current_status"], metadata=payload)
            self.send_json(serialize_job_for_user(conn, job_id, user))

    def handle_bilty_photo(self, user: sqlite3.Row, job_id: str) -> None:
        form = self.parse_multipart()
        upload = form["file"] if "file" in form else None
        if upload is None or not getattr(upload, "filename", ""):
            self.send_json({"error": "Bilty photo is required."}, HTTPStatus.BAD_REQUEST)
            return
        with db_connect() as conn:
            job = self.require_bilty_actor_job(conn, user, job_id)
            if not job:
                return
            if job["current_status"] not in {"approved-by-reviewer", "dispatch-pending", "dispatched"}:
                self.send_json({"error": "Bilty can only be added after reviewer approval."}, HTTPStatus.CONFLICT)
                return
            suffix = Path(upload.filename).suffix.lower() or ".jpg"
            saved_name = f"{uuid.uuid4()}{suffix}"
            saved_path = BILTY_PHOTOS_DIR / saved_name
            with saved_path.open("wb") as target:
                shutil.copyfileobj(upload.file, target)
            timestamp = now_iso()
            old_status = job["current_status"]
            conn.execute(
                """
                UPDATE bilty_details
                SET bilty_photo_url = ?, delivery_partner_name = ?, bilty_uploaded_by = ?,
                    bilty_uploaded_at = ?, updated_at = ?
                WHERE dispatch_job_id = ?
                """,
                (
                    f"/uploads/bilty-photos/{saved_name}",
                    job["delivery_partner_name"] or "",
                    user["id"],
                    timestamp,
                    timestamp,
                    job_id,
                ),
            )
            conn.execute(
                """
                UPDATE dispatch_jobs
                SET bilty_uploaded_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (timestamp, timestamp, job_id),
            )
            log_action(
                conn,
                job_id,
                user,
                "bilty_photo_uploaded",
                old_status,
                job["current_status"],
                metadata={"file_url": f"/uploads/bilty-photos/{saved_name}"},
            )
            self.send_json(serialize_job_for_user(conn, job_id, user))

    def handle_mark_dispatched(self, user: sqlite3.Row, job_id: str) -> None:
        with db_connect() as conn:
            job = self.require_bilty_actor_job(conn, user, job_id)
            if not job:
                return
            if job["current_status"] not in {"approved-by-reviewer", "dispatch-pending"}:
                self.send_json({"error": "Only approved jobs can be dispatched."}, HTTPStatus.CONFLICT)
                return
            mode = job["transport_mode"] or ""
            if not job["delivery_partner_name"]:
                self.send_json({"error": "Enter delivery partner name"}, HTTPStatus.BAD_REQUEST)
                return
            if not mode:
                self.send_json({"error": "Select transport mode"}, HTTPStatus.BAD_REQUEST)
                return
            if mode == "Transport" and not job["transport_name"]:
                self.send_json({"error": "Select transport name"}, HTTPStatus.BAD_REQUEST)
                return
            bilty = conn.execute("SELECT freight_amount FROM bilty_details WHERE dispatch_job_id = ?", (job_id,)).fetchone()
            freight_amount = bilty["freight_amount"] if bilty else None
            if mode != "Self" and (freight_amount is None or float(freight_amount) <= 0):
                self.send_json({"error": "Enter freight amount"}, HTTPStatus.BAD_REQUEST)
                return
            timestamp = now_iso()
            if mode == "Self":
                conn.execute(
                    """
                    UPDATE dispatch_jobs
                    SET current_status = 'completed', dispatched_at = ?, delivered_at = ?, completed_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (timestamp, timestamp, timestamp, timestamp, job_id),
                )
                log_action(conn, job_id, user, "marked_self_completed", job["current_status"], "completed")
                self.send_json(serialize_job_for_user(conn, job_id, user))
                return
            conn.execute(
                "UPDATE dispatch_jobs SET current_status = 'dispatched', dispatched_at = ?, updated_at = ? WHERE id = ?",
                (timestamp, timestamp, job_id),
            )
            log_action(conn, job_id, user, "marked_dispatched", job["current_status"], "dispatched")
            self.send_json(serialize_job_for_user(conn, job_id, user))

    def handle_mark_delivered(self, user: sqlite3.Row, job_id: str) -> None:
        with db_connect() as conn:
            job = self.require_bilty_actor_job(conn, user, job_id)
            if not job:
                return
            if job["current_status"] != "dispatched":
                self.send_json({"error": "A job must be dispatched before it can be delivered."}, HTTPStatus.CONFLICT)
                return
            timestamp = now_iso()
            conn.execute(
                "UPDATE dispatch_jobs SET current_status = 'delivered', delivered_at = ?, updated_at = ? WHERE id = ?",
                (timestamp, timestamp, job_id),
            )
            log_action(conn, job_id, user, "marked_delivered", "dispatched", "delivered")
            self.send_json(serialize_job_for_user(conn, job_id, user))

    def handle_mark_completed(self, user: sqlite3.Row, job_id: str) -> None:
        with db_connect() as conn:
            job = self.require_job(conn, job_id)
            if not job:
                return
            if job["current_status"] not in {"dispatched", "delivered"}:
                self.send_json({"error": "Mark sent to transport first"}, HTTPStatus.CONFLICT)
                return
            bilty = conn.execute("SELECT * FROM bilty_details WHERE dispatch_job_id = ?", (job_id,)).fetchone()
            mode = job["transport_mode"] or ""
            if mode == "Transport":
                if not bilty["bilty_photo_url"]:
                    self.send_json({"error": "Upload bilty photo"}, HTTPStatus.BAD_REQUEST)
                    return
                if bilty["bilty_package_count"] is None:
                    self.send_json({"error": "Enter bilty package count"}, HTTPStatus.BAD_REQUEST)
                    return
                if int(bilty["bilty_package_count"]) != int(job["total_packages"] or 0) and not job["package_difference_reason"]:
                    self.send_json({"error": "Select difference reason"}, HTTPStatus.BAD_REQUEST)
                    return
            if mode != "Self" and (bilty["freight_amount"] is None or float(bilty["freight_amount"]) <= 0):
                self.send_json({"error": "Enter freight amount"}, HTTPStatus.BAD_REQUEST)
                return
            timestamp = now_iso()
            old_status = job["current_status"]
            conn.execute(
                "UPDATE dispatch_jobs SET current_status = 'completed', completed_at = ?, updated_at = ? WHERE id = ?",
                (timestamp, timestamp, job_id),
            )
            log_action(conn, job_id, user, "marked_completed", old_status, "completed")
            self.send_json(serialize_job_for_user(conn, job_id, user))

    def handle_admin_override(self, user: sqlite3.Row, job_id: str) -> None:
        payload = self.read_json()
        with db_connect() as conn:
            job = self.require_job(conn, job_id)
            if not job:
                return
            updates = []
            params = []
            if "dispatcherId" in payload:
                updates.append("dispatcher_id = ?")
                params.append(payload["dispatcherId"] or None)
            if "currentStatus" in payload:
                if payload["currentStatus"] not in STATUSES:
                    self.send_json({"error": "Invalid status."}, HTTPStatus.BAD_REQUEST)
                    return
                updates.append("current_status = ?")
                params.append(payload["currentStatus"])
            if "partyName" in payload:
                updates.append("party_name = ?")
                params.append(payload["partyName"].strip())
            if "place" in payload:
                updates.append("place = ?")
                params.append(payload["place"].strip())
                updates.append("party_city = ?")
                params.append(payload["place"].strip())
            if "invoiceNumber" in payload:
                updates.append("invoice_number = ?")
                params.append(payload["invoiceNumber"].strip())
            if "totalCases" in payload:
                updates.append("total_cases = ?")
                params.append(int(payload["totalCases"]))
            if "transporterDeliveryPartnerName" in payload:
                updates.append("transporter_delivery_partner_name = ?")
                params.append(payload["transporterDeliveryPartnerName"].strip())
            if not updates:
                self.send_json({"error": "No changes provided."}, HTTPStatus.BAD_REQUEST)
                return
            old_status = job["current_status"]
            new_status = payload.get("currentStatus", old_status)
            updates.extend(["admin_override_by = ?", "updated_at = ?"])
            params.extend([user["id"], now_iso(), job_id])
            conn.execute(f"UPDATE dispatch_jobs SET {', '.join(updates)} WHERE id = ?", params)
            log_action(conn, job_id, user, "admin_override", old_status, new_status, metadata=payload)
            self.send_json(serialize_job_for_user(conn, job_id, user))

    def handle_create_route_batch(self, user: sqlite3.Row) -> None:
        payload = self.read_json()
        route_name = payload.get("routeName", "").strip()
        job_ids = payload.get("jobIds", [])
        if not route_name or not job_ids:
            self.send_json({"error": "Route name and jobs are required."}, HTTPStatus.BAD_REQUEST)
            return
        with db_connect() as conn:
            batch_id = str(uuid.uuid4())
            timestamp = now_iso()
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
            self.send_json({"id": batch_id, "routeName": route_name}, HTTPStatus.CREATED)

    def handle_create_delivery_partner(self) -> None:
        payload = self.read_json()
        name = payload.get("name", "").strip()
        if not name:
            self.send_json({"error": "Delivery partner name is required."}, HTTPStatus.BAD_REQUEST)
            return
        timestamp = now_iso()
        with db_connect() as conn:
            conn.execute(
                """
                INSERT INTO delivery_partners (name, preferred_transport_name, active_status, created_at, updated_at)
                VALUES (?, '', 1, ?, ?)
                ON CONFLICT(name) DO UPDATE SET active_status = 1, updated_at = excluded.updated_at
                """,
                (name, timestamp, timestamp),
            )
            self.send_json({"ok": True, "name": name}, HTTPStatus.CREATED)

    def handle_create_user(self) -> None:
        payload = self.read_json()
        name = payload.get("name", "").strip()
        login = payload.get("login", "").strip()
        password = payload.get("password", "")
        role = payload.get("role", "")
        if not name or not login or not password:
            self.send_json({"error": "Name, login, and password are required."}, HTTPStatus.BAD_REQUEST)
            return
        if role not in {"reviewer", "dispatcher", "admin"}:
            self.send_json({"error": "Invalid role."}, HTTPStatus.BAD_REQUEST)
            return
        timestamp = now_iso()
        with db_connect() as conn:
            existing = conn.execute("SELECT id FROM users WHERE email_or_mobile = ?", (login,)).fetchone()
            if existing:
                self.send_json({"error": "Login already exists."}, HTTPStatus.CONFLICT)
                return
            user_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO users (id, name, email_or_mobile, password_hash, role, active_status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (user_id, name, login, hash_password(password), role, timestamp, timestamp),
            )
            user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            self.send_json(serialize_user(user), HTTPStatus.CREATED)

    def handle_backup_import(self, user: sqlite3.Row) -> None:
        form = self.parse_multipart()
        upload = form["file"] if "file" in form else None
        if upload is None or not getattr(upload, "filename", ""):
            self.send_json({"error": "Backup ZIP file is required."}, HTTPStatus.BAD_REQUEST)
            return

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        backup_dir = DATA_DIR / f"pre-import-backup-{timestamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        if DB_PATH.exists():
            shutil.copy2(DB_PATH, backup_dir / "dispatches.db")
        if UPLOAD_DIR.exists():
            shutil.copytree(UPLOAD_DIR, backup_dir / "uploads", dirs_exist_ok=True)

        with tempfile.TemporaryDirectory() as temp_name:
            temp_dir = Path(temp_name)
            zip_path = temp_dir / "import.zip"
            with zip_path.open("wb") as target:
                shutil.copyfileobj(upload.file, target)

            try:
                with zipfile.ZipFile(zip_path) as archive:
                    members = archive.infolist()
                    for member in members:
                        member_path = Path(member.filename)
                        if member_path.is_absolute() or ".." in member_path.parts:
                            self.send_json({"error": "Invalid backup ZIP."}, HTTPStatus.BAD_REQUEST)
                            return
                    archive.extractall(temp_dir / "extracted")
            except zipfile.BadZipFile:
                self.send_json({"error": "Invalid backup ZIP."}, HTTPStatus.BAD_REQUEST)
                return

            extracted = temp_dir / "extracted"
            source_db = extracted / "dispatches.db"
            source_uploads = extracted / "uploads"
            if not source_db.exists():
                self.send_json({"error": "Backup must contain dispatches.db."}, HTTPStatus.BAD_REQUEST)
                return

            with sqlite3.connect(source_db) as check_conn:
                tables = {row[0] for row in check_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "dispatch_jobs" not in tables or "users" not in tables:
                    self.send_json({"error": "Backup database is not a Dispatch Desk database."}, HTTPStatus.BAD_REQUEST)
                    return

            shutil.copy2(source_db, DB_PATH)
            shutil.rmtree(UPLOAD_DIR, ignore_errors=True)
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            copied_files = 0
            if source_uploads.exists():
                shutil.copytree(source_uploads, UPLOAD_DIR, dirs_exist_ok=True)
                copied_files = sum(1 for item in UPLOAD_DIR.rglob("*") if item.is_file())
            if copied_files == 0:
                with zipfile.ZipFile(zip_path) as archive:
                    for member in archive.infolist():
                        if member.is_dir() or not member.filename.startswith("uploads/"):
                            continue
                        relative = Path(member.filename).relative_to("uploads")
                        target = UPLOAD_DIR / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(member) as source, target.open("wb") as destination:
                            shutil.copyfileobj(source, destination)
                        copied_files += 1

        ensure_storage()
        with db_connect() as conn:
            log_action(
                conn,
                None,
                user,
                "backup_imported",
                None,
                None,
                remarks=f"Imported cloud migration backup. Previous data backed up at {backup_dir.name}.",
            )
            job_count = conn.execute("SELECT COUNT(*) FROM dispatch_jobs").fetchone()[0]
            photo_count = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        file_count = sum(1 for item in UPLOAD_DIR.rglob("*") if item.is_file()) if UPLOAD_DIR.exists() else 0
        self.send_json({"ok": True, "jobs": job_count, "photos": photo_count, "files": file_count, "backupFolder": backup_dir.name})

    def handle_update_settings(self) -> None:
        payload = self.read_json()
        updates = {
            "dispatcher_label": payload.get("dispatcherLabel", "").strip() or "Dispatcher",
            "reviewer_label": payload.get("reviewerLabel", "").strip() or "Reviewer",
        }
        with db_connect() as conn:
            for key, value in updates.items():
                conn.execute(
                    "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
        self.send_json({"ok": True, **updates})

    def handle_update_route(self, route_id: str) -> None:
        payload = self.read_json()
        name = payload.get("name", "").strip()
        if not name:
            self.send_json({"error": "Route name is required."}, HTTPStatus.BAD_REQUEST)
            return
        with db_connect() as conn:
            conn.execute("UPDATE route_names SET name = ? WHERE id = ?", (name, route_id))
            self.send_json({"id": int(route_id), "name": name})

    def handle_update_user(self, user_id: str) -> None:
        payload = self.read_json()
        with db_connect() as conn:
            current = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not current:
                self.send_json({"error": "User not found."}, HTTPStatus.NOT_FOUND)
                return
            name = payload.get("name", current["name"]).strip()
            login = payload.get("login", current["email_or_mobile"]).strip()
            password = payload.get("password", "")
            role = payload.get("role", current["role"])
            active_status = 1 if payload.get("activeStatus", bool(current["active_status"])) else 0
            if not name or not login:
                self.send_json({"error": "Name and login are required."}, HTTPStatus.BAD_REQUEST)
                return
            if role not in {"reviewer", "dispatcher", "admin"}:
                self.send_json({"error": "Invalid role."}, HTTPStatus.BAD_REQUEST)
                return
            duplicate = conn.execute(
                "SELECT id FROM users WHERE email_or_mobile = ? AND id != ?",
                (login, user_id),
            ).fetchone()
            if duplicate:
                self.send_json({"error": "Login already exists."}, HTTPStatus.CONFLICT)
                return
            updates = ["name = ?", "email_or_mobile = ?", "role = ?", "active_status = ?", "updated_at = ?"]
            params = [name, login, role, active_status, now_iso()]
            if password:
                updates.insert(4, "password_hash = ?")
                params.insert(4, hash_password(password))
            params.append(user_id)
            conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
            self.send_json(serialize_user(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()))

    def handle_bill_export(self, parsed) -> None:
        query = parse_qs(parsed.query)
        date = query.get("date", [""])[0]
        with db_connect() as conn:
            rows = conn.execute(
                """
                SELECT invoice_number, party_name, place, bill_file_url
                FROM dispatch_jobs
                WHERE bill_file_url IS NOT NULL AND bill_file_url != ''
                AND (? = '' OR substr(created_at, 1, 10) = ?)
                """,
                (date, date),
            ).fetchall()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for row in rows:
                bill_path = upload_url_to_path(row["bill_file_url"])
                if not bill_path.exists():
                    continue
                safe_party = re.sub(r"[^A-Za-z0-9_-]+", "_", row["party_name"]).strip("_")
                safe_place = re.sub(r"[^A-Za-z0-9_-]+", "_", row["place"]).strip("_")
                invoice = re.sub(r"[^A-Za-z0-9_-]+", "_", row["invoice_number"] or "invoice").strip("_")
                archive.write(bill_path, f"{safe_party or 'party'}_{safe_place or 'place'}_{invoice or 'invoice'}{bill_path.suffix}")
        data = buffer.getvalue()
        filename = f"dispatch-bills-{date or 'all'}.zip"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def require_user(self) -> sqlite3.Row | None:
        user = session_user(self)
        if not user:
            self.send_json({"error": "Authentication required."}, HTTPStatus.UNAUTHORIZED)
            return None
        if not user["active_status"]:
            self.send_json({"error": "User is inactive."}, HTTPStatus.FORBIDDEN)
            return None
        return user

    def require_roles(self, user: sqlite3.Row, roles: set[str]) -> bool:
        if user["role"] not in roles:
            self.send_json({"error": "You do not have permission for this action."}, HTTPStatus.FORBIDDEN)
            return False
        return True

    def require_job(self, conn: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
        job = conn.execute("SELECT * FROM dispatch_jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            self.send_json({"error": "Dispatch not found."}, HTTPStatus.NOT_FOUND)
            return None
        return job

    def require_owned_dispatcher_job(self, conn: sqlite3.Connection, user: sqlite3.Row, job_id: str) -> sqlite3.Row | None:
        job = self.require_job(conn, job_id)
        if not job:
            return None
        if job["dispatcher_id"] != user["id"]:
            self.send_json({"error": "You can only work on your own assigned jobs."}, HTTPStatus.FORBIDDEN)
            return None
        return job

    def require_bilty_actor_job(self, conn: sqlite3.Connection, user: sqlite3.Row, job_id: str) -> sqlite3.Row | None:
        job = self.require_job(conn, job_id)
        if not job:
            return None
        if user["role"] == "dispatcher" and job["dispatcher_id"] != user["id"]:
            self.send_json({"error": "You can only update bilty for your own jobs."}, HTTPStatus.FORBIDDEN)
            return None
        return job

    def parse_multipart(self):
        ctype, pdict = cgi.parse_header(self.headers.get("Content-Type", ""))
        if ctype != "multipart/form-data":
            return {}
        pdict["boundary"] = bytes(pdict["boundary"], "utf-8")
        return cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers["Content-Type"]},
        )

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def serve_file(self, file_path: Path) -> None:
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = file_path.read_bytes()
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    ensure_storage()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), DispatchHandler)
    print(f"Dispatch Desk running at http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
