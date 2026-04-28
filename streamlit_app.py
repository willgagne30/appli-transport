from __future__ import annotations

import copy
import hashlib
import hmac
import html
import json
import os
import secrets
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pydeck as pdk
import requests
import streamlit as st

APP_NAME = "LoadSearch"
ENV_PATH = Path(__file__).with_name(".env")
DB_PATH = Path(__file__).with_name("loadsearch.db")
UPLOADS_DIR = Path(__file__).with_name("loadsearch_uploads")
OTHER_CARGO_VALUE = "__other_cargo__"
MAP_BASE_STYLE = pdk.map_styles.CARTO_ROAD
PASSWORD_HASH_NAME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000
RATABLE_REQUEST_STATUSES = {"accepted"}
OWNER_ADMIN_EMAIL = os.getenv("LOADSEARCH_OWNER_EMAIL", "willgagne30@gmail.com").strip().lower()
VERIFICATION_PENDING = "pending"
VERIFICATION_VERIFIED = "verified"

EQUIPMENT_OPTIONS = [
    "Flatbed",
    "Drybox",
    "Fardier",
    "Benne",
    "Porte-autos",
    "Plateforme",
    "Remorque fermee",
    "Step deck",
    "Refrigere",
    "Citerne",
    "B-train",
    "Rideau coulissant",
    "Roll-tite",
]

SUGGESTED_CARGO_OPTIONS = [
    "Bois",
    "Billots",
    "Beton",
    "Autos",
    "Tuyaux",
    "Materiaux mixtes",
]

PROVINCE_OPTIONS = [
    "Alberta",
    "Colombie-Britannique",
    "Ile-du-Prince-Edouard",
    "Manitoba",
    "Nouveau-Brunswick",
    "Nouvelle-Ecosse",
    "Nunavut",
    "Ontario",
    "Quebec",
    "Saskatchewan",
    "Terre-Neuve-et-Labrador",
    "Territoires du Nord-Ouest",
    "Yukon",
]

COMPANY_EXAMPLE_PROMPT = (
    "J'ai 3 voyages de beton a faire de Laval vers Quebec vendredi matin "
    "avec une benne. Le client veut une livraison avant 15h. Prix autour "
    "de 1800 CAD par voyage."
)

CARRIER_EXAMPLE_PROMPT = (
    "Je suis un petit transporteur avec 2 camions flatbed et drybox. Je "
    "cherche surtout des voyages autour de Montreal, Laval, Trois-Rivieres, "
    "Quebec ou Ottawa."
)

CITY_COORDINATES = {
    "montreal": (45.5017, -73.5673),
    "laval": (45.6066, -73.7124),
    "trois-rivieres": (46.3430, -72.5430),
    "trois rivieres": (46.3430, -72.5430),
    "drummondville": (45.8800, -72.4840),
    "sherbrooke": (45.4042, -71.8929),
    "brossard": (45.4620, -73.4659),
    "ottawa": (45.4215, -75.6972),
    "quebec": (46.8139, -71.2080),
    "quebec city": (46.8139, -71.2080),
    "toronto": (43.6532, -79.3832),
    "hamilton": (43.2557, -79.8711),
    "london": (42.9849, -81.2453),
    "winnipeg": (49.8954, -97.1385),
    "halifax": (44.6488, -63.5752),
    "new york": (40.7128, -74.0060),
    "chicago": (41.8781, -87.6298),
    "paris": (48.8566, 2.3522),
    "mexico city": (19.4326, -99.1332),
    "los angeles": (34.0522, -118.2437),
}


def load_env_file(file_path: Path) -> None:
    if not file_path.exists():
        return

    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file(ENV_PATH)
OWNER_ADMIN_EMAIL = os.getenv("LOADSEARCH_OWNER_EMAIL", OWNER_ADMIN_EMAIL).strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def empty_company_profile() -> dict[str, Any]:
    return {
        "legalName": "",
        "businessNumber": "",
        "contactName": "",
        "email": "",
        "phone": "",
        "city": "",
        "province": "",
        "industry": "",
    }


def empty_carrier_profile() -> dict[str, Any]:
    return {
        "transportCompany": "",
        "businessNumber": "",
        "insuranceNumber": "",
        "contactName": "",
        "email": "",
        "phone": "",
        "fleetSize": 1,
        "regions": "",
        "equipmentTypes": [],
    }


def get_db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def ensure_table_columns(
    connection: sqlite3.Connection,
    table_name: str,
    columns: dict[str, str],
) -> None:
    existing_columns = {
        normalize_text(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for column_name, column_definition in columns.items():
        if column_name not in existing_columns:
            connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
            )


def init_database() -> None:
    with get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                role TEXT NOT NULL CHECK(role IN ('company', 'carrier')),
                business_name TEXT NOT NULL,
                legal_name TEXT NOT NULL DEFAULT '',
                transport_company TEXT NOT NULL DEFAULT '',
                business_number TEXT NOT NULL DEFAULT '',
                insurance_number TEXT NOT NULL DEFAULT '',
                contact_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                phone TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                city TEXT NOT NULL DEFAULT '',
                province TEXT NOT NULL DEFAULT '',
                industry TEXT NOT NULL DEFAULT '',
                fleet_size INTEGER NOT NULL DEFAULT 1,
                regions TEXT NOT NULL DEFAULT '',
                equipment_types TEXT NOT NULL DEFAULT '[]',
                verification_status TEXT NOT NULL DEFAULT 'pending',
                verified_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        ensure_table_columns(
            connection,
            "users",
            {
                "verification_status": "TEXT NOT NULL DEFAULT 'pending'",
                "verified_at": "TEXT NOT NULL DEFAULT ''",
            },
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS announcements (
                id TEXT PRIMARY KEY,
                company_account_id TEXT NOT NULL DEFAULT '',
                company_name TEXT NOT NULL,
                title TEXT NOT NULL,
                pickup_address TEXT NOT NULL DEFAULT '',
                pickup_city TEXT NOT NULL DEFAULT '',
                pickup_postal_code TEXT NOT NULL DEFAULT '',
                delivery_address TEXT NOT NULL DEFAULT '',
                delivery_city TEXT NOT NULL DEFAULT '',
                delivery_postal_code TEXT NOT NULL DEFAULT '',
                cargo_type TEXT NOT NULL DEFAULT '',
                equipment TEXT NOT NULL DEFAULT '',
                loading_date TEXT NOT NULL DEFAULT '',
                delivery_date TEXT NOT NULL DEFAULT '',
                trips_total INTEGER NOT NULL DEFAULT 1,
                remaining_trips INTEGER NOT NULL DEFAULT 1,
                budget INTEGER NOT NULL DEFAULT 0,
                notes TEXT NOT NULL DEFAULT '',
                expired_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS service_requests (
                id TEXT PRIMARY KEY,
                announcement_id TEXT NOT NULL,
                announcement_title TEXT NOT NULL,
                company_account_id TEXT NOT NULL DEFAULT '',
                company_name TEXT NOT NULL,
                carrier_account_id TEXT NOT NULL DEFAULT '',
                carrier_name TEXT NOT NULL,
                carrier_business_number TEXT NOT NULL DEFAULT '',
                carrier_insurance_number TEXT NOT NULL DEFAULT '',
                carrier_contact_name TEXT NOT NULL DEFAULT '',
                carrier_phone TEXT NOT NULL DEFAULT '',
                carrier_email TEXT NOT NULL DEFAULT '',
                carrier_fleet_size INTEGER NOT NULL DEFAULT 1,
                carrier_equipment_types TEXT NOT NULL DEFAULT '[]',
                requested_trips INTEGER NOT NULL DEFAULT 1,
                message TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                decision_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                recipient_role TEXT NOT NULL,
                recipient_name TEXT NOT NULL DEFAULT '',
                recipient_account_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                related_announcement_id TEXT NOT NULL DEFAULT '',
                related_request_id TEXT NOT NULL DEFAULT '',
                related_alert_id TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                sender_role TEXT NOT NULL,
                sender_name TEXT NOT NULL DEFAULT '',
                sender_account_id TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                owner_type TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                account_id TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT '',
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                content_type TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS carrier_alerts (
                id TEXT PRIMARY KEY,
                carrier_account_id TEXT NOT NULL,
                carrier_name TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                pickup_city TEXT NOT NULL DEFAULT '',
                delivery_city TEXT NOT NULL DEFAULT '',
                cargo_type TEXT NOT NULL DEFAULT '',
                equipment TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ratings (
                id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                announcement_id TEXT NOT NULL DEFAULT '',
                reviewer_account_id TEXT NOT NULL,
                reviewer_role TEXT NOT NULL CHECK(reviewer_role IN ('company', 'carrier')),
                reviewer_name TEXT NOT NULL DEFAULT '',
                reviewee_account_id TEXT NOT NULL,
                reviewee_role TEXT NOT NULL CHECK(reviewee_role IN ('company', 'carrier')),
                reviewee_name TEXT NOT NULL DEFAULT '',
                score INTEGER NOT NULL CHECK(score >= 1 AND score <= 5),
                comment TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_ratings_request_reviewer_reviewee
            ON ratings (request_id, reviewer_account_id, reviewee_account_id)
            """
        )


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    )
    return f"{PASSWORD_HASH_NAME}${PASSWORD_ITERATIONS}${salt}${derived_key.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected_hex = stored_hash.split("$", 3)
    except ValueError:
        return False

    if algorithm != PASSWORD_HASH_NAME:
        return False

    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations),
    )
    return hmac.compare_digest(derived_key.hex(), expected_hex)


def parse_equipment_types(raw_value: Any) -> list[str]:
    try:
        payload = json.loads(raw_value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [normalize_text(item) for item in payload if normalize_text(item)]


def serialize_account_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None

    equipment_types = parse_equipment_types(row["equipment_types"])
    business_name = normalize_text(row["business_name"])
    legal_name = normalize_text(row["legal_name"]) or business_name
    transport_company = normalize_text(row["transport_company"]) or business_name

    return {
        "id": row["id"],
        "role": row["role"],
        "businessName": business_name,
        "legalName": legal_name,
        "transportCompany": transport_company,
        "businessNumber": normalize_text(row["business_number"]),
        "insuranceNumber": normalize_text(row["insurance_number"]),
        "contactName": normalize_text(row["contact_name"]),
        "email": normalize_text(row["email"]),
        "phone": normalize_text(row["phone"]),
        "city": normalize_text(row["city"]),
        "province": normalize_text(row["province"]),
        "industry": normalize_text(row["industry"]),
        "fleetSize": max(1, int(row["fleet_size"] or 1)),
        "regions": normalize_text(row["regions"]),
        "equipmentTypes": equipment_types,
        "verificationStatus": normalize_text(row["verification_status"]) or VERIFICATION_PENDING,
        "verifiedAt": normalize_text(row["verified_at"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def get_user_row_by_email(email: str) -> sqlite3.Row | None:
    normalized_email = normalize_email(email)
    with get_db_connection() as connection:
        return connection.execute(
            "SELECT * FROM users WHERE email = ?",
            (normalized_email,),
        ).fetchone()


def get_account_by_email(email: str) -> dict[str, Any] | None:
    return serialize_account_row(get_user_row_by_email(email))


def get_account_by_id(account_id: str) -> dict[str, Any] | None:
    with get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE id = ?",
            (normalize_text(account_id),),
        ).fetchone()
    return serialize_account_row(row)


def create_account_record(
    *,
    role: str,
    business_name: str,
    contact_name: str,
    email: str,
    phone: str,
    password: str,
    insurance_number: str = "",
) -> dict[str, Any]:
    account_id = f"account-{datetime.now().timestamp()}"
    now = datetime.now().isoformat(timespec="seconds")
    normalized_business_name = normalize_text(business_name)
    normalized_contact_name = normalize_text(contact_name)
    normalized_email = normalize_email(email)
    normalized_phone = normalize_text(phone)
    normalized_insurance = normalize_text(insurance_number)

    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO users (
                id,
                role,
                business_name,
                legal_name,
                transport_company,
                business_number,
                insurance_number,
                contact_name,
                email,
                phone,
                password_hash,
                city,
                province,
                industry,
                fleet_size,
                regions,
                equipment_types,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                role,
                normalized_business_name,
                normalized_business_name if role == "company" else "",
                normalized_business_name if role == "carrier" else "",
                "",
                normalized_insurance if role == "carrier" else "",
                normalized_contact_name,
                normalized_email,
                normalized_phone,
                hash_password(password),
                "",
                "",
                "",
                1,
                "",
                "[]",
                now,
                now,
            ),
        )

    account = get_account_by_id(account_id)
    if not account:
        raise RuntimeError("Le compte vient d'etre cree mais n'a pas pu etre relu.")
    return account


def update_company_profile_record(account_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE users
            SET
                business_name = ?,
                legal_name = ?,
                business_number = ?,
                contact_name = ?,
                email = ?,
                phone = ?,
                city = ?,
                province = ?,
                industry = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                normalize_text(profile["legalName"]),
                normalize_text(profile["legalName"]),
                normalize_text(profile["businessNumber"]),
                normalize_text(profile["contactName"]),
                normalize_email(profile["email"]),
                normalize_text(profile["phone"]),
                normalize_text(profile["city"]),
                normalize_text(profile["province"]),
                normalize_text(profile["industry"]),
                now,
                normalize_text(account_id),
            ),
        )

    account = get_account_by_id(account_id)
    if not account:
        raise RuntimeError("Le profil entreprise n'a pas pu etre relu.")
    return account


def update_carrier_profile_record(account_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    equipment_payload = json.dumps(profile["equipmentTypes"], ensure_ascii=True)
    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE users
            SET
                business_name = ?,
                transport_company = ?,
                business_number = ?,
                insurance_number = ?,
                contact_name = ?,
                email = ?,
                phone = ?,
                fleet_size = ?,
                regions = ?,
                equipment_types = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                normalize_text(profile["transportCompany"]),
                normalize_text(profile["transportCompany"]),
                normalize_text(profile["businessNumber"]),
                normalize_text(profile["insuranceNumber"]),
                normalize_text(profile["contactName"]),
                normalize_email(profile["email"]),
                normalize_text(profile["phone"]),
                max(1, int(profile["fleetSize"])),
                normalize_text(profile["regions"]),
                equipment_payload,
                now,
                normalize_text(account_id),
            ),
        )

    account = get_account_by_id(account_id)
    if not account:
        raise RuntimeError("Le profil transporteur n'a pas pu etre relu.")
    return account


def list_accounts_by_role(role: str) -> list[dict[str, Any]]:
    with get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM users WHERE role = ? ORDER BY updated_at DESC, created_at DESC",
            (normalize_text(role),),
        ).fetchall()
    return [item for item in (serialize_account_row(row) for row in rows) if item]


def update_account_verification_record(
    account_id: str,
    *,
    verification_status: str,
) -> dict[str, Any]:
    normalized_status = (
        VERIFICATION_VERIFIED
        if normalize_text(verification_status) == VERIFICATION_VERIFIED
        else VERIFICATION_PENDING
    )
    verified_at = (
        datetime.now().isoformat(timespec="seconds")
        if normalized_status == VERIFICATION_VERIFIED
        else ""
    )
    updated_at = datetime.now().isoformat(timespec="seconds")

    with get_db_connection() as connection:
        connection.execute(
            """
            UPDATE users
            SET verification_status = ?, verified_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                normalized_status,
                verified_at,
                updated_at,
                normalize_text(account_id),
            ),
        )

    account = get_account_by_id(account_id)
    if not account:
        raise RuntimeError("Le compte n'a pas pu etre relu apres la mise a jour.")
    return account


def serialize_announcement_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None

    return {
        "id": row["id"],
        "companyAccountId": normalize_text(row["company_account_id"]),
        "companyName": normalize_text(row["company_name"]),
        "title": normalize_text(row["title"]),
        "pickupAddress": normalize_text(row["pickup_address"]),
        "pickupCity": normalize_text(row["pickup_city"]),
        "pickupPostalCode": normalize_text(row["pickup_postal_code"]),
        "deliveryAddress": normalize_text(row["delivery_address"]),
        "deliveryCity": normalize_text(row["delivery_city"]),
        "deliveryPostalCode": normalize_text(row["delivery_postal_code"]),
        "cargoType": normalize_text(row["cargo_type"]),
        "equipment": normalize_text(row["equipment"]),
        "loadingDate": normalize_text(row["loading_date"]),
        "deliveryDate": normalize_text(row["delivery_date"]),
        "tripsTotal": int(row["trips_total"] or 1),
        "remainingTrips": int(row["remaining_trips"] or 0),
        "budget": int(row["budget"] or 0),
        "notes": normalize_text(row["notes"]),
        "expiredAt": normalize_text(row["expired_at"]),
        "createdAt": normalize_text(row["created_at"]),
        "updatedAt": normalize_text(row["updated_at"]),
    }


def serialize_service_request_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None

    return {
        "id": row["id"],
        "announcementId": normalize_text(row["announcement_id"]),
        "announcementTitle": normalize_text(row["announcement_title"]),
        "companyAccountId": normalize_text(row["company_account_id"]),
        "companyName": normalize_text(row["company_name"]),
        "carrierAccountId": normalize_text(row["carrier_account_id"]),
        "carrierName": normalize_text(row["carrier_name"]),
        "carrierBusinessNumber": normalize_text(row["carrier_business_number"]),
        "carrierInsuranceNumber": normalize_text(row["carrier_insurance_number"]),
        "carrierContactName": normalize_text(row["carrier_contact_name"]),
        "carrierPhone": normalize_text(row["carrier_phone"]),
        "carrierEmail": normalize_text(row["carrier_email"]),
        "carrierFleetSize": int(row["carrier_fleet_size"] or 1),
        "carrierEquipmentTypes": parse_equipment_types(row["carrier_equipment_types"]),
        "requestedTrips": int(row["requested_trips"] or 1),
        "message": normalize_text(row["message"]),
        "status": normalize_text(row["status"]),
        "decisionMessage": normalize_text(row["decision_message"]),
        "createdAt": normalize_text(row["created_at"]),
        "updatedAt": normalize_text(row["updated_at"]),
    }


def serialize_notification_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None

    return {
        "id": row["id"],
        "recipientRole": normalize_text(row["recipient_role"]),
        "recipientName": normalize_text(row["recipient_name"]),
        "recipientAccountId": normalize_text(row["recipient_account_id"]),
        "title": normalize_text(row["title"]),
        "message": normalize_text(row["message"]),
        "relatedAnnouncementId": normalize_text(row["related_announcement_id"]),
        "relatedRequestId": normalize_text(row["related_request_id"]),
        "relatedAlertId": normalize_text(row["related_alert_id"]),
        "createdAt": normalize_text(row["created_at"]),
    }


def serialize_message_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None

    return {
        "id": row["id"],
        "requestId": normalize_text(row["request_id"]),
        "senderRole": normalize_text(row["sender_role"]),
        "senderName": normalize_text(row["sender_name"]),
        "senderAccountId": normalize_text(row["sender_account_id"]),
        "body": normalize_text(row["body"]),
        "createdAt": normalize_text(row["created_at"]),
    }


def serialize_document_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None

    return {
        "id": row["id"],
        "ownerType": normalize_text(row["owner_type"]),
        "ownerId": normalize_text(row["owner_id"]),
        "accountId": normalize_text(row["account_id"]),
        "role": normalize_text(row["role"]),
        "fileName": normalize_text(row["file_name"]),
        "filePath": normalize_text(row["file_path"]),
        "contentType": normalize_text(row["content_type"]),
        "description": normalize_text(row["description"]),
        "createdAt": normalize_text(row["created_at"]),
    }


def serialize_alert_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None

    return {
        "id": row["id"],
        "carrierAccountId": normalize_text(row["carrier_account_id"]),
        "carrierName": normalize_text(row["carrier_name"]),
        "title": normalize_text(row["title"]),
        "pickupCity": normalize_text(row["pickup_city"]),
        "deliveryCity": normalize_text(row["delivery_city"]),
        "cargoType": normalize_text(row["cargo_type"]),
        "equipment": normalize_text(row["equipment"]),
        "isActive": bool(int(row["is_active"] or 0)),
        "createdAt": normalize_text(row["created_at"]),
        "updatedAt": normalize_text(row["updated_at"]),
    }


def serialize_rating_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None

    return {
        "id": row["id"],
        "requestId": normalize_text(row["request_id"]),
        "announcementId": normalize_text(row["announcement_id"]),
        "reviewerAccountId": normalize_text(row["reviewer_account_id"]),
        "reviewerRole": normalize_text(row["reviewer_role"]),
        "reviewerName": normalize_text(row["reviewer_name"]),
        "revieweeAccountId": normalize_text(row["reviewee_account_id"]),
        "revieweeRole": normalize_text(row["reviewee_role"]),
        "revieweeName": normalize_text(row["reviewee_name"]),
        "score": max(1, min(5, int(row["score"] or 1))),
        "comment": normalize_text(row["comment"]),
        "createdAt": normalize_text(row["created_at"]),
    }


def list_announcements_from_db() -> list[dict[str, Any]]:
    with get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM announcements ORDER BY created_at ASC"
        ).fetchall()
    return [item for item in (serialize_announcement_row(row) for row in rows) if item]


def list_service_requests_from_db() -> list[dict[str, Any]]:
    with get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM service_requests ORDER BY created_at ASC"
        ).fetchall()
    return [item for item in (serialize_service_request_row(row) for row in rows) if item]


def list_notifications_from_db() -> list[dict[str, Any]]:
    with get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM notifications ORDER BY created_at ASC"
        ).fetchall()
    return [item for item in (serialize_notification_row(row) for row in rows) if item]


def list_messages_for_request(request_id: str) -> list[dict[str, Any]]:
    with get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM messages WHERE request_id = ? ORDER BY created_at ASC",
            (normalize_text(request_id),),
        ).fetchall()
    return [item for item in (serialize_message_row(row) for row in rows) if item]


def list_documents(owner_type: str, owner_id: str) -> list[dict[str, Any]]:
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM documents
            WHERE owner_type = ? AND owner_id = ?
            ORDER BY created_at DESC
            """,
            (normalize_text(owner_type), normalize_text(owner_id)),
        ).fetchall()
    return [item for item in (serialize_document_row(row) for row in rows) if item]


def list_carrier_alerts(carrier_account_id: str, *, only_active: bool = False) -> list[dict[str, Any]]:
    query = "SELECT * FROM carrier_alerts WHERE carrier_account_id = ?"
    params: list[Any] = [normalize_text(carrier_account_id)]
    if only_active:
        query += " AND is_active = 1"
    query += " ORDER BY created_at DESC"
    with get_db_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()
    return [item for item in (serialize_alert_row(row) for row in rows) if item]


def list_ratings_from_db() -> list[dict[str, Any]]:
    with get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM ratings ORDER BY created_at DESC"
        ).fetchall()
    return [item for item in (serialize_rating_row(row) for row in rows) if item]


def load_persisted_data_into_session() -> None:
    st.session_state.announcements = list_announcements_from_db()
    st.session_state.service_requests = list_service_requests_from_db()
    st.session_state.notifications = list_notifications_from_db()
    st.session_state.ratings = list_ratings_from_db()


def safe_file_name(file_name: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "_" for char in file_name)
    return cleaned or "document"


def save_uploaded_documents(
    uploaded_files: list[Any],
    *,
    owner_type: str,
    owner_id: str,
    account_id: str,
    role: str,
    description: str,
) -> int:
    files = [item for item in (uploaded_files or []) if item is not None]
    if not files:
        return 0

    UPLOADS_DIR.mkdir(exist_ok=True)
    created_at = datetime.now().isoformat(timespec="seconds")
    saved_count = 0

    with get_db_connection() as connection:
        for uploaded_file in files:
            file_name = safe_file_name(getattr(uploaded_file, "name", "document"))
            unique_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}-{file_name}"
            file_path = UPLOADS_DIR / unique_name
            file_path.write_bytes(uploaded_file.getbuffer())
            document_id = f"doc-{datetime.now().timestamp()}-{secrets.token_hex(3)}"
            connection.execute(
                """
                INSERT INTO documents (
                    id, owner_type, owner_id, account_id, role, file_name, file_path,
                    content_type, description, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    normalize_text(owner_type),
                    normalize_text(owner_id),
                    normalize_text(account_id),
                    normalize_text(role),
                    file_name,
                    str(file_path),
                    normalize_text(getattr(uploaded_file, "type", "")),
                    normalize_text(description),
                    created_at,
                ),
            )
            saved_count += 1

    return saved_count


def create_announcement_record(announcement: dict[str, Any]) -> dict[str, Any]:
    created_at = normalize_text(announcement.get("createdAt")) or datetime.now().isoformat(timespec="seconds")
    updated_at = normalize_text(announcement.get("updatedAt")) or created_at
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO announcements (
                id, company_account_id, company_name, title, pickup_address, pickup_city,
                pickup_postal_code, delivery_address, delivery_city, delivery_postal_code,
                cargo_type, equipment, loading_date, delivery_date, trips_total,
                remaining_trips, budget, notes, expired_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalize_text(announcement["id"]),
                normalize_text(announcement.get("companyAccountId")),
                normalize_text(announcement["companyName"]),
                normalize_text(announcement["title"]),
                normalize_text(announcement["pickupAddress"]),
                normalize_text(announcement["pickupCity"]),
                normalize_text(announcement["pickupPostalCode"]),
                normalize_text(announcement["deliveryAddress"]),
                normalize_text(announcement["deliveryCity"]),
                normalize_text(announcement["deliveryPostalCode"]),
                normalize_text(announcement["cargoType"]),
                normalize_text(announcement["equipment"]),
                normalize_text(announcement["loadingDate"]),
                normalize_text(announcement["deliveryDate"]),
                int(announcement["tripsTotal"]),
                int(announcement["remainingTrips"]),
                int(announcement["budget"]),
                normalize_text(announcement["notes"]),
                normalize_text(announcement.get("expiredAt")),
                created_at,
                updated_at,
            ),
        )

    with get_db_connection() as connection:
        row = connection.execute(
            "SELECT * FROM announcements WHERE id = ?",
            (normalize_text(announcement["id"]),),
        ).fetchone()
    saved = serialize_announcement_row(row)
    if not saved:
        raise RuntimeError("L'annonce n'a pas pu etre relue.")
    return saved


def update_announcement_record(announcement_id: str, **fields: Any) -> dict[str, Any]:
    if not fields:
        with get_db_connection() as connection:
            row = connection.execute(
                "SELECT * FROM announcements WHERE id = ?",
                (normalize_text(announcement_id),),
            ).fetchone()
        saved = serialize_announcement_row(row)
        if not saved:
            raise RuntimeError("Annonce introuvable.")
        return saved

    columns = {
        "companyAccountId": "company_account_id",
        "companyName": "company_name",
        "title": "title",
        "pickupAddress": "pickup_address",
        "pickupCity": "pickup_city",
        "pickupPostalCode": "pickup_postal_code",
        "deliveryAddress": "delivery_address",
        "deliveryCity": "delivery_city",
        "deliveryPostalCode": "delivery_postal_code",
        "cargoType": "cargo_type",
        "equipment": "equipment",
        "loadingDate": "loading_date",
        "deliveryDate": "delivery_date",
        "tripsTotal": "trips_total",
        "remainingTrips": "remaining_trips",
        "budget": "budget",
        "notes": "notes",
        "expiredAt": "expired_at",
        "updatedAt": "updated_at",
    }
    assignments = []
    params: list[Any] = []
    for key, value in fields.items():
        column = columns.get(key)
        if not column:
            continue
        assignments.append(f"{column} = ?")
        if key in {"tripsTotal", "remainingTrips", "budget"}:
            params.append(int(value))
        else:
            params.append(normalize_text(value))
    assignments.append("updated_at = ?")
    params.append(datetime.now().isoformat(timespec="seconds"))
    params.append(normalize_text(announcement_id))

    with get_db_connection() as connection:
        connection.execute(
            f"UPDATE announcements SET {', '.join(assignments)} WHERE id = ?",
            tuple(params),
        )
        row = connection.execute(
            "SELECT * FROM announcements WHERE id = ?",
            (normalize_text(announcement_id),),
        ).fetchone()
    saved = serialize_announcement_row(row)
    if not saved:
        raise RuntimeError("Annonce introuvable.")
    return saved


def create_service_request_record(service_request: dict[str, Any]) -> dict[str, Any]:
    created_at = normalize_text(service_request.get("createdAt")) or datetime.now().isoformat(timespec="seconds")
    updated_at = normalize_text(service_request.get("updatedAt")) or created_at
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO service_requests (
                id, announcement_id, announcement_title, company_account_id, company_name,
                carrier_account_id, carrier_name, carrier_business_number, carrier_insurance_number,
                carrier_contact_name, carrier_phone, carrier_email, carrier_fleet_size,
                carrier_equipment_types, requested_trips, message, status, decision_message,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalize_text(service_request["id"]),
                normalize_text(service_request["announcementId"]),
                normalize_text(service_request["announcementTitle"]),
                normalize_text(service_request.get("companyAccountId")),
                normalize_text(service_request["companyName"]),
                normalize_text(service_request.get("carrierAccountId")),
                normalize_text(service_request["carrierName"]),
                normalize_text(service_request["carrierBusinessNumber"]),
                normalize_text(service_request["carrierInsuranceNumber"]),
                normalize_text(service_request["carrierContactName"]),
                normalize_text(service_request["carrierPhone"]),
                normalize_text(service_request["carrierEmail"]),
                int(service_request["carrierFleetSize"]),
                json.dumps(service_request["carrierEquipmentTypes"], ensure_ascii=True),
                int(service_request["requestedTrips"]),
                normalize_text(service_request["message"]),
                normalize_text(service_request["status"]),
                normalize_text(service_request["decisionMessage"]),
                created_at,
                updated_at,
            ),
        )
        row = connection.execute(
            "SELECT * FROM service_requests WHERE id = ?",
            (normalize_text(service_request["id"]),),
        ).fetchone()
    saved = serialize_service_request_row(row)
    if not saved:
        raise RuntimeError("La proposition n'a pas pu etre relue.")
    return saved


def update_service_request_record(request_id: str, **fields: Any) -> dict[str, Any]:
    columns = {
        "status": "status",
        "decisionMessage": "decision_message",
        "message": "message",
        "requestedTrips": "requested_trips",
    }
    assignments = []
    params: list[Any] = []
    for key, value in fields.items():
        column = columns.get(key)
        if not column:
            continue
        assignments.append(f"{column} = ?")
        if key == "requestedTrips":
            params.append(int(value))
        else:
            params.append(normalize_text(value))
    assignments.append("updated_at = ?")
    params.append(datetime.now().isoformat(timespec="seconds"))
    params.append(normalize_text(request_id))

    with get_db_connection() as connection:
        connection.execute(
            f"UPDATE service_requests SET {', '.join(assignments)} WHERE id = ?",
            tuple(params),
        )
        row = connection.execute(
            "SELECT * FROM service_requests WHERE id = ?",
            (normalize_text(request_id),),
        ).fetchone()
    saved = serialize_service_request_row(row)
    if not saved:
        raise RuntimeError("Proposition introuvable.")
    return saved


def create_message_record(
    request_id: str,
    *,
    sender_role: str,
    sender_name: str,
    sender_account_id: str,
    body: str,
) -> dict[str, Any]:
    message_id = f"msg-{datetime.now().timestamp()}-{secrets.token_hex(3)}"
    created_at = datetime.now().isoformat(timespec="seconds")
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO messages (
                id, request_id, sender_role, sender_name, sender_account_id, body, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                normalize_text(request_id),
                normalize_text(sender_role),
                normalize_text(sender_name),
                normalize_text(sender_account_id),
                normalize_text(body),
                created_at,
            ),
        )
        row = connection.execute(
            "SELECT * FROM messages WHERE id = ?",
            (message_id,),
        ).fetchone()
    saved = serialize_message_row(row)
    if not saved:
        raise RuntimeError("Message introuvable apres creation.")
    return saved


def create_carrier_alert_record(alert: dict[str, Any]) -> dict[str, Any]:
    alert_id = normalize_text(alert.get("id")) or f"alert-{datetime.now().timestamp()}-{secrets.token_hex(3)}"
    now = datetime.now().isoformat(timespec="seconds")
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO carrier_alerts (
                id, carrier_account_id, carrier_name, title, pickup_city,
                delivery_city, cargo_type, equipment, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                normalize_text(alert["carrierAccountId"]),
                normalize_text(alert["carrierName"]),
                normalize_text(alert["title"]),
                normalize_text(alert["pickupCity"]),
                normalize_text(alert["deliveryCity"]),
                normalize_text(alert["cargoType"]),
                normalize_text(alert["equipment"]),
                1 if alert.get("isActive", True) else 0,
                now,
                now,
            ),
        )
        row = connection.execute(
            "SELECT * FROM carrier_alerts WHERE id = ?",
            (alert_id,),
        ).fetchone()
    saved = serialize_alert_row(row)
    if not saved:
        raise RuntimeError("Alerte introuvable apres creation.")
    return saved


def create_rating_record(rating: dict[str, Any]) -> dict[str, Any]:
    rating_id = normalize_text(rating.get("id")) or f"rating-{datetime.now().timestamp()}-{secrets.token_hex(3)}"
    created_at = normalize_text(rating.get("createdAt")) or datetime.now().isoformat(timespec="seconds")
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO ratings (
                id, request_id, announcement_id, reviewer_account_id, reviewer_role,
                reviewer_name, reviewee_account_id, reviewee_role, reviewee_name,
                score, comment, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rating_id,
                normalize_text(rating["requestId"]),
                normalize_text(rating.get("announcementId")),
                normalize_text(rating["reviewerAccountId"]),
                normalize_text(rating["reviewerRole"]),
                normalize_text(rating["reviewerName"]),
                normalize_text(rating["revieweeAccountId"]),
                normalize_text(rating["revieweeRole"]),
                normalize_text(rating["revieweeName"]),
                max(1, min(5, int(rating["score"]))),
                normalize_text(rating.get("comment")),
                created_at,
            ),
        )
        row = connection.execute(
            "SELECT * FROM ratings WHERE id = ?",
            (rating_id,),
        ).fetchone()
    saved = serialize_rating_row(row)
    if not saved:
        raise RuntimeError("L'evaluation n'a pas pu etre relue.")
    return saved


def delete_carrier_alert_record(alert_id: str) -> None:
    with get_db_connection() as connection:
        connection.execute(
            "DELETE FROM carrier_alerts WHERE id = ?",
            (normalize_text(alert_id),),
        )


def notification_exists(
    *,
    recipient_account_id: str,
    related_announcement_id: str,
    related_alert_id: str,
) -> bool:
    with get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT id FROM notifications
            WHERE recipient_account_id = ? AND related_announcement_id = ? AND related_alert_id = ?
            LIMIT 1
            """,
            (
                normalize_text(recipient_account_id),
                normalize_text(related_announcement_id),
                normalize_text(related_alert_id),
            ),
        ).fetchone()
    return row is not None


def reset_demo_data() -> None:
    with get_db_connection() as connection:
        for table_name in [
            "ratings",
            "messages",
            "documents",
            "notifications",
            "service_requests",
            "carrier_alerts",
            "announcements",
            "users",
        ]:
            connection.execute(f"DELETE FROM {table_name}")

    if UPLOADS_DIR.exists():
        for item in UPLOADS_DIR.iterdir():
            if item.is_file():
                item.unlink()

st.set_page_config(
    page_title=APP_NAME,
    page_icon="LS",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
          background:
            radial-gradient(circle at top left, rgba(30, 58, 138, 0.46), transparent 30%),
            radial-gradient(circle at bottom right, rgba(29, 78, 216, 0.18), transparent 32%),
            linear-gradient(135deg, #020617, #07111f 46%, #0b1629);
          color: #e5f2ff;
        }
        .block-container {
          padding-top: 1.45rem;
          padding-bottom: 2rem;
          max-width: 1280px;
        }
        .top-shell {
          padding: 0.25rem 0;
          border: 0;
          background: transparent;
          box-shadow: none;
          margin-bottom: 0.75rem;
        }
        .brand-title {
          font-size: 2rem;
          font-weight: 800;
          color: #f8fbff;
          margin-bottom: 0.25rem;
        }
        .brand-copy {
          color: #a9bfdf;
          line-height: 1.6;
        }
        .hero-card, .soft-card {
          border: 0;
          background: transparent;
          box-shadow: none;
          padding: 0;
          margin: 0;
        }
        .result-card {
          border-radius: 0;
          border: 0;
          border-bottom: 1px solid rgba(30, 64, 175, 0.28);
          background: transparent;
          box-shadow: none;
          padding: 0.95rem 0;
        }
        .hero-card {
          min-height: 280px;
        }
        .landing-shell {
          max-width: 980px;
          margin: 0 auto;
        }
        .landing-hero {
          text-align: center;
          padding: 2.6rem 2rem;
          border-radius: 32px;
          border: 1px solid rgba(30, 64, 175, 0.4);
          background:
            radial-gradient(circle at top, rgba(30, 64, 175, 0.24), transparent 42%),
            rgba(8, 15, 32, 0.84);
          box-shadow: 0 22px 60px rgba(0, 0, 0, 0.34);
        }
        .landing-title {
          font-size: clamp(2.5rem, 6vw, 5.4rem);
          line-height: 0.95;
          letter-spacing: -0.06em;
          font-weight: 900;
          color: #f8fbff;
          margin: 0.9rem 0 1rem;
        }
        .landing-description {
          max-width: 680px;
          margin: 0 auto;
          color: #b7c6dc;
          font-size: 1.08rem;
          line-height: 1.7;
        }
        .choice-card {
          min-height: 150px;
          border-radius: 24px;
          border: 1px solid rgba(30, 64, 175, 0.34);
          background: rgba(15, 23, 42, 0.82);
          padding: 1.25rem;
          margin-top: 1rem;
        }
        .choice-title {
          font-size: 1.35rem;
          font-weight: 800;
          color: #f8fbff;
          margin-bottom: 0.45rem;
        }
        .contact-bar {
          margin-top: 1.8rem;
          padding: 1.7rem 1.4rem;
          border-radius: 26px;
          border: 1px solid rgba(30, 64, 175, 0.38);
          background: rgba(2, 6, 23, 0.72);
          text-align: left;
          color: #b7c6dc;
          font-size: 1.02rem;
        }
        .contact-bar strong {
          color: #f8fbff;
        }
        .contact-title {
          display: block;
          font-size: 1.25rem;
          margin-bottom: 1rem;
        }
        .contact-detail {
          line-height: 1.7;
        }
        .contact-detail span {
          color: #8ea6c7;
          font-size: 0.9rem;
          text-transform: uppercase;
          letter-spacing: 0.08em;
        }
        .policy-footer {
          margin: 2.4rem auto 0;
          max-width: 980px;
          padding-top: 0.75rem;
          border-top: 1px solid rgba(96, 165, 250, 0.12);
          color: #89a4c7;
          font-size: 0.78rem;
          line-height: 1.65;
        }
        .policy-footer details {
          cursor: pointer;
        }
        .policy-footer summary {
          list-style: none;
          color: #9fb6d9;
          font-size: 0.76rem;
          letter-spacing: 0.04em;
          text-transform: uppercase;
        }
        .policy-footer summary::-webkit-details-marker {
          display: none;
        }
        .policy-copy {
          margin-top: 0.7rem;
          color: #7e97b8;
        }
        .policy-link {
          display: inline-block;
          margin-top: 0.45rem;
          color: #93c5fd;
          text-decoration: none;
          font-size: 0.78rem;
        }
        .policy-link:hover {
          color: #bfdbfe;
          text-decoration: underline;
        }
        .auth-action-bar {
          max-width: 720px;
          margin: 0.75rem auto 0;
          padding: 0;
          border: 0;
          background: transparent;
        }
        .auth-panel {
          max-width: 720px;
          margin: 1rem auto 0;
          padding: 0;
          border: 0;
          background: transparent;
          box-shadow: none;
        }
        .auth-state {
          color: #b7c6dc;
          line-height: 1.6;
          margin-bottom: 0.75rem;
        }
        .st-key-landing_company_choice button {
          background: linear-gradient(135deg, #1e3a8a, #1d4ed8) !important;
          border: 1px solid rgba(59, 130, 246, 0.5) !important;
          color: #f8fbff !important;
          box-shadow: 0 12px 32px rgba(30, 64, 175, 0.28) !important;
        }
        .st-key-landing_company_choice button:hover {
          background: linear-gradient(135deg, #1d4ed8, #2563eb) !important;
          border-color: rgba(59, 130, 246, 0.72) !important;
        }
        .eyebrow {
          display: inline-block;
          padding: 0.4rem 0.75rem;
          border-radius: 999px;
          background: rgba(30, 58, 138, 0.62);
          color: #f8fbff;
          font-size: 0.8rem;
          font-weight: 700;
          letter-spacing: 0.04em;
          text-transform: uppercase;
        }
        .section-title {
          font-size: 1.55rem;
          font-weight: 800;
          color: #f8fbff;
          margin: 0.7rem 0 0.45rem;
        }
        .metric-card {
          border-radius: 0;
          padding: 0.35rem 0;
          background: transparent;
          border: 0;
          min-height: 58px;
        }
        .metric-label {
          color: #9db2d1;
          font-size: 0.92rem;
        }
        .metric-value {
          font-size: 1.55rem;
          font-weight: 800;
          color: #3b82f6;
          margin-top: 0.25rem;
        }
        .map-selection-card {
          margin-top: 1rem;
          border: 0;
          background: transparent;
        }
        .status-pill {
          display: inline-block;
          padding: 0.35rem 0.7rem;
          border-radius: 999px;
          background: rgba(30, 58, 138, 0.62);
          color: #f8fbff;
          font-size: 0.82rem;
          font-weight: 700;
        }
        .status-pill.ai {
          background: rgba(29, 78, 216, 0.36);
          color: #e5f2ff;
        }
        .notice {
          border-radius: 18px;
          padding: 0.95rem 1rem;
          margin-top: 0.75rem;
          border: 1px solid rgba(30, 64, 175, 0.34);
        }
        .notice strong {
          display: block;
          margin-bottom: 0.35rem;
        }
        .notice-info {
          background: rgba(30, 58, 138, 0.42);
          color: #f8fbff;
        }
        .notice-success {
          background: rgba(34, 197, 94, 0.14);
          color: #86efac;
        }
        .notice-warning {
          background: rgba(245, 158, 11, 0.16);
          color: #fcd34d;
        }
        .notice-error {
          background: rgba(239, 68, 68, 0.16);
          color: #fca5a5;
        }
        .route-row {
          display: inline-block;
          padding: 0.55rem 0.9rem;
          border-radius: 999px;
          background: rgba(2, 6, 23, 0.72);
          border: 1px solid rgba(30, 64, 175, 0.34);
          color: #dbeafe;
          font-weight: 700;
          margin: 0.45rem 0 0.8rem;
        }
        .small-copy {
          color: #b7c6dc;
          line-height: 1.6;
          font-size: 0.96rem;
        }
        .score-pill {
          display: inline-block;
          padding: 0.35rem 0.7rem;
          border-radius: 999px;
          font-weight: 700;
          font-size: 0.83rem;
          margin-right: 0.45rem;
          margin-bottom: 0.35rem;
        }
        .score-local {
          background: rgba(30, 58, 138, 0.62);
          color: #f8fbff;
        }
        .score-ai {
          background: rgba(29, 78, 216, 0.36);
          color: #e5f2ff;
        }
        .rating-summary {
          display: flex;
          align-items: center;
          gap: 0.55rem;
          flex-wrap: wrap;
          margin: 0.35rem 0 0.75rem;
          color: #dbeafe;
          font-size: 0.95rem;
        }
        .rating-stars {
          color: #fbbf24;
          font-size: 1rem;
          letter-spacing: 0.05em;
        }
        .rating-stars-off {
          color: rgba(148, 163, 184, 0.55);
        }
        .review-card {
          border-bottom: 1px solid rgba(30, 64, 175, 0.22);
          padding: 0.7rem 0;
        }
        .review-meta {
          color: #8ea6c7;
          font-size: 0.84rem;
          margin-top: 0.15rem;
        }
        .helper-list {
          margin-top: 0.5rem;
          line-height: 1.7;
          color: #b7c6dc;
        }
        .streamlit-expanderHeader {
          font-weight: 700;
        }
        div[data-testid="stTextInput"] input,
        div[data-testid="stTextArea"] textarea,
        div[data-testid="stNumberInput"] input,
        div[data-testid="stDateInput"] input {
          background-color: rgba(2, 6, 23, 0.86);
          color: #e5f2ff;
          border: 1px solid rgba(30, 64, 175, 0.42);
        }
        label, .stMarkdown, .stCaption, .stExpander {
          color: #e5f2ff;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def create_empty_draft() -> dict[str, Any]:
    return {
        "title": "",
        "pickupAddress": "",
        "pickupCity": "",
        "pickupPostalCode": "",
        "deliveryAddress": "",
        "deliveryCity": "",
        "deliveryPostalCode": "",
        "cargoType": "",
        "cargoTypeOther": "",
        "equipment": "",
        "loadingDate": None,
        "deliveryDate": None,
        "tripsTotal": 1,
        "budget": 0,
        "notes": "",
    }


def init_state() -> None:
    defaults = {
        "active_role": None,
        "auth_view": "landing",
        "pending_role": "",
        "current_account": None,
        "registered_accounts": [],
        "auth_message": "",
        "company_profile": empty_company_profile(),
        "carrier_profile": empty_carrier_profile(),
        "announcements": [],
        "filters": {
            "pickupCity": "",
            "deliveryCity": "",
            "cargoType": "",
            "equipment": "",
        },
        "draft_announcement": create_empty_draft(),
        "company_ai": {
            "requestText": "",
            "assistantMessage": "",
            "missingFields": [],
            "error": "",
        },
        "carrier_ai": {
            "requestText": "",
            "assistantMessage": "",
            "matches": [],
            "suggestedFilters": {
                "pickupCity": "",
                "deliveryCity": "",
                "cargoType": "",
                "equipment": "",
            },
            "error": "",
        },
        "service_requests": [],
        "notifications": [],
        "ratings": [],
        "selected_map_announcement_id": "",
        "map_selection_version": 0,
        "ignore_empty_map_selection": False,
        "sync_draft_widgets": False,
        "sync_filter_widgets": False,
        "sync_company_ai_prompt_widget": False,
        "sync_carrier_ai_prompt_widget": False,
        "geocode_cache": {},
        "last_geocode_timestamp": 0.0,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    load_persisted_data_into_session()
    current_account = st.session_state.current_account
    if current_account:
        refreshed_account = get_account_by_id(normalize_text(current_account.get("id")))
        if refreshed_account:
            st.session_state.current_account = refreshed_account
        else:
            st.session_state.current_account = None
            st.session_state.active_role = None
            st.session_state.auth_view = "landing"
            st.session_state.pending_role = ""
            clear_profile_session_state()
    ensure_state_shape()
    sync_widget_keys_from_state()


def ensure_state_shape() -> None:
    carrier_profile = st.session_state.carrier_profile
    if "insuranceNumber" not in carrier_profile:
        carrier_profile["insuranceNumber"] = ""

    for announcement in st.session_state.announcements:
        if "pickupAddress" not in announcement:
            announcement["pickupAddress"] = ""
        if "pickupPostalCode" not in announcement:
            announcement["pickupPostalCode"] = ""
        if "deliveryAddress" not in announcement:
            announcement["deliveryAddress"] = ""
        if "deliveryPostalCode" not in announcement:
            announcement["deliveryPostalCode"] = ""
        if "deliveryDate" not in announcement:
            announcement["deliveryDate"] = announcement.get("loadingDate", "")
        if "budget" not in announcement:
            announcement["budget"] = 0
        if "expiredAt" not in announcement:
            announcement["expiredAt"] = ""

    draft = st.session_state.draft_announcement
    if "pickupAddress" not in draft:
        draft["pickupAddress"] = ""
    if "pickupPostalCode" not in draft:
        draft["pickupPostalCode"] = ""
    if "deliveryAddress" not in draft:
        draft["deliveryAddress"] = ""
    if "deliveryPostalCode" not in draft:
        draft["deliveryPostalCode"] = ""
    if "deliveryDate" not in draft:
        draft["deliveryDate"] = draft.get("loadingDate")
    if "budget" not in draft:
        draft["budget"] = 0


def sync_widget_keys_from_state() -> None:
    company = st.session_state.company_profile
    carrier = st.session_state.carrier_profile
    draft = st.session_state.draft_announcement
    filters = st.session_state.filters

    widget_defaults = {
        "company_legalName": company["legalName"],
        "company_businessNumber": company["businessNumber"],
        "company_contactName": company["contactName"],
        "company_email": company["email"],
        "company_phone": company["phone"],
        "company_city": company["city"],
        "company_province": company["province"],
        "company_industry": company["industry"],
        "carrier_transportCompany": carrier["transportCompany"],
        "carrier_businessNumber": carrier["businessNumber"],
        "carrier_insuranceNumber": carrier["insuranceNumber"],
        "carrier_contactName": carrier["contactName"],
        "carrier_email": carrier["email"],
        "carrier_phone": carrier["phone"],
        "carrier_fleetSize": carrier["fleetSize"],
        "carrier_regions": carrier["regions"],
        "carrier_equipmentTypes": carrier["equipmentTypes"],
        "company_ai_prompt": st.session_state.company_ai["requestText"],
        "carrier_ai_prompt": st.session_state.carrier_ai["requestText"],
        "announcement_title": draft["title"],
        "announcement_pickupAddress": draft["pickupAddress"],
        "announcement_pickupCity": draft["pickupCity"],
        "announcement_pickupPostalCode": draft["pickupPostalCode"],
        "announcement_deliveryAddress": draft["deliveryAddress"],
        "announcement_deliveryCity": draft["deliveryCity"],
        "announcement_deliveryPostalCode": draft["deliveryPostalCode"],
        "announcement_equipment": draft["equipment"],
        "announcement_loadingDate": draft["loadingDate"],
        "announcement_deliveryDate": draft.get("deliveryDate"),
        "announcement_tripsTotal": int(draft["tripsTotal"] or 1),
        "announcement_budget": int(draft["budget"] or 0),
        "announcement_notes": draft["notes"],
        "filter_pickupCity": filters["pickupCity"],
        "filter_deliveryCity": filters["deliveryCity"],
        "filter_cargoType": filters["cargoType"],
        "filter_equipment": filters["equipment"],
    }

    cargo_selection = draft["cargoType"] or ""
    if draft["cargoTypeOther"]:
        cargo_selection = OTHER_CARGO_VALUE
    widget_defaults["announcement_cargoType"] = cargo_selection
    widget_defaults["announcement_cargoTypeOther"] = draft["cargoTypeOther"]

    for key, value in widget_defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def apply_pending_widget_syncs() -> None:
    if st.session_state.get("sync_draft_widgets"):
        apply_draft_to_widgets()
        st.session_state.sync_draft_widgets = False

    if st.session_state.get("sync_filter_widgets"):
        apply_filters_to_widgets()
        st.session_state.sync_filter_widgets = False

    if st.session_state.get("sync_company_ai_prompt_widget"):
        st.session_state.company_ai_prompt = st.session_state.company_ai["requestText"]
        st.session_state.sync_company_ai_prompt_widget = False

    if st.session_state.get("sync_carrier_ai_prompt_widget"):
        st.session_state.carrier_ai_prompt = st.session_state.carrier_ai["requestText"]
        st.session_state.sync_carrier_ai_prompt_widget = False


def gemini_is_configured() -> bool:
    return bool(GEMINI_API_KEY)


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def strip_accents(value: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFD", value)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def normalize_for_match(value: Any) -> str:
    return strip_accents(normalize_text(value)).lower()


def normalize_equipment_for_match(value: Any) -> str:
    normalized = normalize_for_match(value)
    aliases = {
        "dry box": "drybox",
        "drybox": "drybox",
        "dribox": "drybox",
        "dry van": "drybox",
        "remorque fermee": "drybox",
        "flatbed": "flatbed",
        "plateforme": "flatbed",
        "reefer": "refrigere",
        "refrigere": "refrigere",
        "refrigerated": "refrigere",
        "porte autos": "porte-autos",
        "porte-autos": "porte-autos",
        "car hauler": "porte-autos",
    }
    return aliases.get(normalized, normalized)


def normalize_equipment_option(value: Any) -> str:
    normalized = normalize_equipment_for_match(value)
    for option in EQUIPMENT_OPTIONS:
        if normalize_equipment_for_match(option) == normalized:
            return option
    return ""


def normalize_cargo_option(value: Any) -> tuple[str, str]:
    text = normalize_text(value)
    if not text:
        return "", ""

    normalized = normalize_for_match(text)
    for option in SUGGESTED_CARGO_OPTIONS:
        if normalize_for_match(option) == normalized:
            return option, ""
    return OTHER_CARGO_VALUE, text


def normalize_date_value(value: Any) -> Any:
    if value in (None, ""):
        return None
    if hasattr(value, "strftime"):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def format_date(value: Any) -> str:
    date_obj = normalize_date_value(value)
    if not date_obj:
        return "Date a confirmer"
    return date_obj.strftime("%Y-%m-%d")


def format_currency(value: Any) -> str:
    number = int(float(value or 0))
    return f"{number:,.0f} $ CAD".replace(",", " ")


def combine_location_parts(*parts: Any) -> str:
    clean_parts = [normalize_text(part) for part in parts if normalize_text(part)]
    return ", ".join(clean_parts)


def format_exact_location(address: Any, city: Any, postal_code: Any) -> str:
    return combine_location_parts(address, city, postal_code) or "Non precise"


def geocode_stop(address: Any, city: Any, postal_code: Any) -> tuple[float, float] | None:
    exact_query = combine_location_parts(address, city, postal_code)
    if exact_query:
        exact_coords = geocode_location(exact_query)
        if exact_coords:
            return exact_coords

    fallback_query = combine_location_parts(city, postal_code) or normalize_text(city)
    if fallback_query:
        return geocode_location(fallback_query)
    return None


def get_delivery_date(announcement: dict[str, Any]) -> Any:
    return announcement.get("deliveryDate") or announcement.get("loadingDate")


def get_price_per_trip(announcement: dict[str, Any]) -> Any:
    return announcement.get("budget", 0)


def is_announcement_expired(announcement: dict[str, Any]) -> bool:
    return bool(normalize_text(announcement.get("expiredAt")))


def is_announcement_active(announcement: dict[str, Any]) -> bool:
    return int(announcement.get("remainingTrips", 0)) > 0 and not is_announcement_expired(
        announcement
    )


def get_role_label(role: str) -> str:
    return "entreprise" if role == "company" else "transporteur"


def get_verification_status(account: dict[str, Any] | None) -> str:
    if not account:
        return VERIFICATION_PENDING
    status = normalize_text(account.get("verificationStatus"))
    if status == VERIFICATION_VERIFIED:
        return VERIFICATION_VERIFIED
    return VERIFICATION_PENDING


def is_account_verified(account: dict[str, Any] | None) -> bool:
    return get_verification_status(account) == VERIFICATION_VERIFIED


def format_verification_label(status: str) -> str:
    return "Verifie" if normalize_text(status) == VERIFICATION_VERIFIED else "En attente"


def build_verification_badge_html(account: dict[str, Any] | None) -> str:
    status = get_verification_status(account)
    status_class = "status-pill" if status == VERIFICATION_VERIFIED else "status-pill ai"
    return f"<span class='{status_class}'>{format_verification_label(status)}</span>"


def is_owner_admin_account(account: dict[str, Any] | None) -> bool:
    if not account:
        return False
    return normalize_email(account.get("email")) == OWNER_ADMIN_EMAIL


def can_current_account_access_admin() -> bool:
    return is_owner_admin_account(st.session_state.current_account)


def get_current_account_role() -> str:
    account = st.session_state.current_account or {}
    return normalize_text(account.get("role"))


def render_verification_notice(account: dict[str, Any] | None, *, owner_label: str) -> None:
    if not account:
        return
    if is_account_verified(account):
        show_notice(
            "success",
            f"{owner_label} verifie",
            "Ce profil a ete approuve par l'administration de LoadSearch.",
        )
        return

    message = (
        f"Le profil {owner_label.lower()} peut etre complete et consulte, "
        "mais il doit etre verifie par l'administration avant de publier une annonce "
        "ou proposer des services."
    )
    if is_owner_admin_account(account):
        message += " Comme proprietaire, vous pouvez ouvrir l'espace admin pour verifier les comptes."
    show_notice(
        "warning",
        f"Verification {owner_label.lower()} en attente",
        message,
    )


def normalize_email(value: Any) -> str:
    return normalize_text(value).lower()


def get_legal_view() -> str:
    if hasattr(st, "query_params"):
        try:
            return normalize_text(st.query_params.get("legal", ""))
        except Exception:  # noqa: BLE001
            pass

    try:
        query_params = st.experimental_get_query_params()
        value = query_params.get("legal", [""])
        if isinstance(value, list):
            return normalize_text(value[0] if value else "")
        return normalize_text(value)
    except Exception:  # noqa: BLE001
        return ""


def find_account_by_email(email: str) -> dict[str, Any] | None:
    return get_account_by_email(email)


def clear_profile_session_state() -> None:
    st.session_state.company_profile = empty_company_profile()
    st.session_state.carrier_profile = empty_carrier_profile()

    company = st.session_state.company_profile
    carrier = st.session_state.carrier_profile

    st.session_state.company_legalName = company["legalName"]
    st.session_state.company_businessNumber = company["businessNumber"]
    st.session_state.company_contactName = company["contactName"]
    st.session_state.company_email = company["email"]
    st.session_state.company_phone = company["phone"]
    st.session_state.company_city = company["city"]
    st.session_state.company_province = company["province"]
    st.session_state.company_industry = company["industry"]

    st.session_state.carrier_transportCompany = carrier["transportCompany"]
    st.session_state.carrier_businessNumber = carrier["businessNumber"]
    st.session_state.carrier_insuranceNumber = carrier["insuranceNumber"]
    st.session_state.carrier_contactName = carrier["contactName"]
    st.session_state.carrier_email = carrier["email"]
    st.session_state.carrier_phone = carrier["phone"]
    st.session_state.carrier_fleetSize = carrier["fleetSize"]
    st.session_state.carrier_regions = carrier["regions"]
    st.session_state.carrier_equipmentTypes = carrier["equipmentTypes"]


def apply_account_to_profile(account: dict[str, Any], *, sync_widget_state: bool = True) -> None:
    if account["role"] == "company":
        profile = {
            "legalName": normalize_text(account.get("legalName") or account.get("businessName")),
            "businessNumber": normalize_text(account.get("businessNumber")),
            "contactName": normalize_text(account.get("contactName")),
            "email": normalize_text(account.get("email")),
            "phone": normalize_text(account.get("phone")),
            "city": normalize_text(account.get("city")),
            "province": normalize_text(account.get("province")),
            "industry": normalize_text(account.get("industry")),
        }
        st.session_state.company_profile = profile
        if sync_widget_state:
            st.session_state.company_legalName = profile["legalName"]
            st.session_state.company_businessNumber = profile["businessNumber"]
            st.session_state.company_contactName = profile["contactName"]
            st.session_state.company_email = profile["email"]
            st.session_state.company_phone = profile["phone"]
            st.session_state.company_city = profile["city"]
            st.session_state.company_province = profile["province"]
            st.session_state.company_industry = profile["industry"]
        return

    profile = {
        "transportCompany": normalize_text(
            account.get("transportCompany") or account.get("businessName")
        ),
        "businessNumber": normalize_text(account.get("businessNumber")),
        "insuranceNumber": normalize_text(account.get("insuranceNumber")),
        "contactName": normalize_text(account.get("contactName")),
        "email": normalize_text(account.get("email")),
        "phone": normalize_text(account.get("phone")),
        "fleetSize": max(1, int(account.get("fleetSize") or 1)),
        "regions": normalize_text(account.get("regions")),
        "equipmentTypes": list(account.get("equipmentTypes") or []),
    }
    st.session_state.carrier_profile = profile
    if sync_widget_state:
        st.session_state.carrier_transportCompany = profile["transportCompany"]
        st.session_state.carrier_businessNumber = profile["businessNumber"]
        st.session_state.carrier_insuranceNumber = profile["insuranceNumber"]
        st.session_state.carrier_contactName = profile["contactName"]
        st.session_state.carrier_email = profile["email"]
        st.session_state.carrier_phone = profile["phone"]
        st.session_state.carrier_fleetSize = profile["fleetSize"]
        st.session_state.carrier_regions = profile["regions"]
        st.session_state.carrier_equipmentTypes = profile["equipmentTypes"]


def continue_as_role(role: str) -> None:
    account = st.session_state.current_account
    if account and account["role"] == role:
        apply_account_to_profile(account)
        st.session_state.active_role = role
        st.session_state.auth_view = "landing"
        st.session_state.auth_message = ""
        st.rerun()

    st.session_state.pending_role = role
    st.session_state.auth_view = f"signup_{role}"
    st.session_state.auth_message = (
        f"Créez un compte {get_role_label(role)} pour continuer."
    )
    st.rerun()


def sign_out() -> None:
    st.session_state.current_account = None
    st.session_state.active_role = None
    st.session_state.auth_view = "landing"
    st.session_state.pending_role = ""
    st.session_state.auth_message = "Vous êtes déconnecté."
    clear_profile_session_state()


def open_admin_space() -> None:
    if not can_current_account_access_admin():
        st.session_state.auth_message = "Cet espace admin est reserve au proprietaire de l'application."
        return
    st.session_state.active_role = "admin"


def is_company_profile_complete() -> bool:
    profile = st.session_state.company_profile
    required = [
        "legalName",
        "businessNumber",
        "contactName",
        "email",
        "phone",
        "city",
        "province",
        "industry",
    ]
    return all(normalize_text(profile[key]) for key in required)


def is_carrier_profile_complete() -> bool:
    profile = st.session_state.carrier_profile
    required = [
        "transportCompany",
        "businessNumber",
        "insuranceNumber",
        "contactName",
        "email",
        "phone",
        "regions",
    ]
    return all(normalize_text(profile[key]) for key in required) and bool(profile["equipmentTypes"])


def get_active_announcements() -> list[dict[str, Any]]:
    return [
        announcement
        for announcement in st.session_state.announcements
        if is_announcement_active(announcement)
    ]


def get_company_announcements() -> list[dict[str, Any]]:
    current_account = st.session_state.current_account or {}
    company_account_id = normalize_text(current_account.get("id"))
    company_name = st.session_state.company_profile["legalName"]
    if company_account_id:
        return [
            announcement
            for announcement in st.session_state.announcements
            if normalize_text(announcement.get("companyAccountId")) == company_account_id
        ]
    return [
        announcement
        for announcement in st.session_state.announcements
        if announcement["companyName"] == company_name
    ]


def get_company_active_announcements() -> list[dict[str, Any]]:
    return [
        announcement
        for announcement in get_company_announcements()
        if is_announcement_active(announcement)
    ]


def get_current_company_notifications() -> list[dict[str, Any]]:
    current_account = st.session_state.current_account or {}
    company_account_id = normalize_text(current_account.get("id"))
    company_name = st.session_state.company_profile["legalName"]
    if company_account_id:
        return [
            notification
            for notification in st.session_state.notifications
            if notification["recipientRole"] == "company"
            and notification.get("recipientAccountId") == company_account_id
        ][::-1]
    return [
        notification
        for notification in st.session_state.notifications
        if notification["recipientRole"] == "company"
        and notification["recipientName"] == company_name
    ][::-1]


def get_current_carrier_notifications() -> list[dict[str, Any]]:
    current_account = st.session_state.current_account or {}
    carrier_account_id = normalize_text(current_account.get("id"))
    carrier_name = st.session_state.carrier_profile["transportCompany"]
    if carrier_account_id:
        return [
            notification
            for notification in st.session_state.notifications
            if notification["recipientRole"] == "carrier"
            and notification.get("recipientAccountId") == carrier_account_id
        ][::-1]
    return [
        notification
        for notification in st.session_state.notifications
        if notification["recipientRole"] == "carrier"
        and notification["recipientName"] == carrier_name
    ][::-1]


def get_company_service_requests() -> list[dict[str, Any]]:
    current_account = st.session_state.current_account or {}
    company_account_id = normalize_text(current_account.get("id"))
    company_name = st.session_state.company_profile["legalName"]
    if company_account_id:
        return [
            request
            for request in st.session_state.service_requests
            if normalize_text(request.get("companyAccountId")) == company_account_id
        ][::-1]
    return [
        request
        for request in st.session_state.service_requests
        if request["companyName"] == company_name
    ][::-1]


def get_carrier_service_requests() -> list[dict[str, Any]]:
    current_account = st.session_state.current_account or {}
    carrier_account_id = normalize_text(current_account.get("id"))
    carrier_name = st.session_state.carrier_profile["transportCompany"]
    if carrier_account_id:
        return [
            request
            for request in st.session_state.service_requests
            if normalize_text(request.get("carrierAccountId")) == carrier_account_id
        ][::-1]
    return [
        request
        for request in st.session_state.service_requests
        if request["carrierName"] == carrier_name
    ][::-1]


def add_notification(
    recipient_role: str,
    recipient_name: str,
    title: str,
    message: str,
    recipient_account_id: str = "",
    related_announcement_id: str = "",
    related_request_id: str = "",
    related_alert_id: str = "",
) -> None:
    notification = {
        "id": f"notif-{datetime.now().timestamp()}-{secrets.token_hex(3)}",
        "recipientRole": normalize_text(recipient_role),
        "recipientName": normalize_text(recipient_name),
        "recipientAccountId": normalize_text(recipient_account_id),
        "title": normalize_text(title),
        "message": normalize_text(message),
        "relatedAnnouncementId": normalize_text(related_announcement_id),
        "relatedRequestId": normalize_text(related_request_id),
        "relatedAlertId": normalize_text(related_alert_id),
        "createdAt": datetime.now().isoformat(timespec="seconds"),
    }
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO notifications (
                id, recipient_role, recipient_name, recipient_account_id, title, message,
                related_announcement_id, related_request_id, related_alert_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                notification["id"],
                notification["recipientRole"],
                notification["recipientName"],
                notification["recipientAccountId"],
                notification["title"],
                notification["message"],
                notification["relatedAnnouncementId"],
                notification["relatedRequestId"],
                notification["relatedAlertId"],
                notification["createdAt"],
            ),
        )
    st.session_state.notifications.append(notification)


def expire_outdated_announcements() -> None:
    today = datetime.now().date()
    has_changes = False

    for announcement in st.session_state.announcements:
        if is_announcement_expired(announcement):
            continue
        if int(announcement.get("remainingTrips", 0)) <= 0:
            continue

        delivery_date = normalize_date_value(get_delivery_date(announcement))
        if not delivery_date or delivery_date >= today:
            continue

        expired_at = datetime.now().isoformat(timespec="seconds")
        update_announcement_record(announcement["id"], expiredAt=expired_at)
        add_notification(
            recipient_role="company",
            recipient_name=announcement["companyName"],
            recipient_account_id=announcement.get("companyAccountId", ""),
            title="Annonce retirée automatiquement",
            message=(
                f"L'annonce \"{announcement['title']}\" a été retirée automatiquement "
                f"car sa date de livraison du {format_date(delivery_date)} est dépassée."
            ),
            related_announcement_id=announcement["id"],
        )
        has_changes = True

    if has_changes:
        load_persisted_data_into_session()


def create_service_request(
    announcement_id: str, requested_trips: int, message: str
) -> tuple[bool, str]:
    announcement = next(
        (item for item in st.session_state.announcements if item["id"] == announcement_id),
        None,
    )
    if not announcement:
        return False, "Annonce introuvable."
    if not is_announcement_active(announcement):
        return False, "Cette annonce n'est plus active."

    carrier = st.session_state.carrier_profile
    current_account = st.session_state.current_account or {}
    if not is_carrier_profile_complete():
        return False, "Le profil transporteur doit etre complet."
    if not is_account_verified(current_account) and not is_owner_admin_account(current_account):
        return (
            False,
            "Votre compte transporteur doit etre verifie par l'administration avant de proposer votre service.",
        )

    for request in st.session_state.service_requests:
        if (
            request["announcementId"] == announcement_id
            and (
                (
                    normalize_text(request.get("carrierAccountId"))
                    and normalize_text(request.get("carrierAccountId")) == normalize_text(current_account.get("id"))
                )
                or request["carrierName"] == carrier["transportCompany"]
            )
            and request["status"] == "pending"
        ):
            return False, "Une proposition en attente existe deja pour cette annonce."

    request_id = f"req-{datetime.now().timestamp()}"
    service_request = {
        "id": request_id,
        "announcementId": announcement_id,
        "announcementTitle": announcement["title"],
        "companyAccountId": announcement.get("companyAccountId", ""),
        "companyName": announcement["companyName"],
        "carrierAccountId": normalize_text(current_account.get("id")),
        "carrierName": carrier["transportCompany"],
        "carrierBusinessNumber": carrier["businessNumber"],
        "carrierInsuranceNumber": carrier["insuranceNumber"],
        "carrierContactName": carrier["contactName"],
        "carrierPhone": carrier["phone"],
        "carrierEmail": carrier["email"],
        "carrierFleetSize": int(carrier["fleetSize"]),
        "carrierEquipmentTypes": list(carrier["equipmentTypes"]),
        "requestedTrips": max(1, int(requested_trips)),
        "message": normalize_text(message),
        "status": "pending",
        "decisionMessage": "",
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    }
    create_service_request_record(service_request)
    add_notification(
        recipient_role="company",
        recipient_name=announcement["companyName"],
        recipient_account_id=announcement.get("companyAccountId", ""),
        title="Nouvelle proposition de transporteur",
        message=(
            f"{carrier['transportCompany']} propose son service pour "
            f"{announcement['title']} ({service_request['requestedTrips']} voyage(s))."
        ),
        related_announcement_id=announcement_id,
        related_request_id=request_id,
    )
    load_persisted_data_into_session()
    return True, "Votre proposition a ete envoyee a l'entreprise."


def find_announcement(announcement_id: str) -> dict[str, Any] | None:
    return next(
        (item for item in st.session_state.announcements if item["id"] == announcement_id),
        None,
    )


def process_service_request_decision(
    request_id: str, decision: str, decision_message: str = ""
) -> tuple[bool, str]:
    service_request = next(
        (item for item in st.session_state.service_requests if item["id"] == request_id),
        None,
    )
    if not service_request:
        return False, "Proposition introuvable."

    if service_request["status"] != "pending":
        return False, "Cette proposition a deja ete traitee."

    announcement = find_announcement(service_request["announcementId"])
    if not announcement:
        return False, "L'annonce liee est introuvable."
    if is_announcement_expired(announcement):
        return False, "Cette annonce a expiré et a été retirée automatiquement."

    if decision == "accepted":
        requested_trips = int(service_request["requestedTrips"])
        if int(announcement["remainingTrips"]) < requested_trips:
            return False, "Il ne reste pas assez de voyages disponibles."
        update_announcement_record(
            announcement["id"],
            remainingTrips=max(0, int(announcement["remainingTrips"]) - requested_trips),
        )
        update_service_request_record(
            request_id,
            status="accepted",
            decisionMessage=normalize_text(decision_message) or "Proposition acceptee.",
        )
        add_notification(
            recipient_role="carrier",
            recipient_name=service_request["carrierName"],
            recipient_account_id=service_request.get("carrierAccountId", ""),
            title="Proposition acceptee",
            message=(
                f"{announcement['companyName']} a accepte votre proposition pour "
                f"{announcement['title']}."
            ),
            related_announcement_id=announcement["id"],
            related_request_id=request_id,
        )
        load_persisted_data_into_session()
        return True, "Le transporteur a ete accepte."

    update_service_request_record(
        request_id,
        status="refused",
        decisionMessage=normalize_text(decision_message) or "Proposition refusee.",
    )
    add_notification(
        recipient_role="carrier",
        recipient_name=service_request["carrierName"],
        recipient_account_id=service_request.get("carrierAccountId", ""),
        title="Proposition refusee",
        message=(
            f"{announcement['companyName']} a refuse votre proposition pour "
            f"{announcement['title']}."
        ),
        related_announcement_id=announcement["id"],
        related_request_id=request_id,
    )
    load_persisted_data_into_session()
    return True, "Le transporteur a ete refuse."


def geocode_location(location_text: str) -> tuple[float, float] | None:
    query = normalize_text(location_text)
    if not query:
        return None

    normalized = normalize_for_match(query)
    if normalized in CITY_COORDINATES:
        return CITY_COORDINATES[normalized]

    cache = st.session_state.geocode_cache
    if normalized in cache:
        cached_value = cache[normalized]
        return tuple(cached_value) if cached_value else None

    elapsed = time.monotonic() - float(st.session_state.last_geocode_timestamp or 0.0)
    if elapsed < 1.05:
        time.sleep(1.05 - elapsed)

    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": query,
                "format": "jsonv2",
                "limit": 1,
                "countrycodes": "ca,us,mx",
            },
            headers={
                "User-Agent": "LoadSearch/0.1 (local prototype geocoding)",
                "Referer": "http://localhost:8501",
                "Accept-Language": "fr,en",
            },
            timeout=15,
        )
        st.session_state.last_geocode_timestamp = time.monotonic()
        response.raise_for_status()
        results = response.json()
        if results:
            lat = float(results[0]["lat"])
            lon = float(results[0]["lon"])
            cache[normalized] = [lat, lon]
            return lat, lon
    except Exception:  # noqa: BLE001
        st.session_state.last_geocode_timestamp = time.monotonic()

    cache[normalized] = None
    return None


def build_map_rows(announcements: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    points: list[dict[str, Any]] = []
    arcs: list[dict[str, Any]] = []

    for announcement in announcements:
        pickup_coords = geocode_stop(
            announcement.get("pickupAddress"),
            announcement.get("pickupCity"),
            announcement.get("pickupPostalCode"),
        )
        delivery_coords = geocode_stop(
            announcement.get("deliveryAddress"),
            announcement.get("deliveryCity"),
            announcement.get("deliveryPostalCode"),
        )
        pickup_label = normalize_text(announcement.get("pickupCity")) or format_exact_location(
            announcement.get("pickupAddress"),
            announcement.get("pickupCity"),
            announcement.get("pickupPostalCode"),
        )
        delivery_label = normalize_text(announcement.get("deliveryCity")) or format_exact_location(
            announcement.get("deliveryAddress"),
            announcement.get("deliveryCity"),
            announcement.get("deliveryPostalCode"),
        )
        map_details = {
            "pricePerTrip": format_currency(get_price_per_trip(announcement)),
            "deliveryDate": format_date(get_delivery_date(announcement)),
            "equipment": announcement["equipment"],
            "remainingTrips": announcement["remainingTrips"],
        }

        if pickup_coords:
            points.append(
                {
                    "announcementId": announcement["id"],
                    "announcementTitle": announcement["title"],
                    "city": pickup_label,
                    "kind": "Chargement",
                    "lat": pickup_coords[0],
                    "lon": pickup_coords[1],
                    "color": [11, 122, 117],
                    "companyName": announcement["companyName"],
                    **map_details,
                }
            )

        if delivery_coords:
            points.append(
                {
                    "announcementId": announcement["id"],
                    "announcementTitle": announcement["title"],
                    "city": delivery_label,
                    "kind": "Livraison",
                    "lat": delivery_coords[0],
                    "lon": delivery_coords[1],
                    "color": [213, 119, 65],
                    "companyName": announcement["companyName"],
                    **map_details,
                }
            )

        if pickup_coords and delivery_coords:
            arcs.append(
                {
                    "announcementId": announcement["id"],
                    "announcementTitle": announcement["title"],
                    "companyName": announcement["companyName"],
                    "city": f"{pickup_label} -> {delivery_label}",
                    "kind": "Trajet",
                    "source_lat": pickup_coords[0],
                    "source_lon": pickup_coords[1],
                    "target_lat": delivery_coords[0],
                    "target_lon": delivery_coords[1],
                    **map_details,
                }
            )

    return points, arcs


def extract_selected_announcement_id(chart_state: Any) -> str:
    if not chart_state:
        return ""

    selection = chart_state.get("selection", {})
    selected_objects = selection.get("objects", {})
    for layer_id in ["announcement-routes", "announcement-points"]:
        layer_objects = selected_objects.get(layer_id, [])
        if layer_objects:
            return normalize_text(layer_objects[0].get("announcementId"))
    return ""


def render_market_map(
    announcements: list[dict[str, Any]],
    title: str,
    subtitle: str,
    *,
    key: str = "market-map",
    selectable: bool = False,
) -> str:
    st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Carte interactive</span>", unsafe_allow_html=True)
    st.markdown(f"<div class='section-title'>{title}</div>", unsafe_allow_html=True)
    st.markdown(f"<p class='small-copy'>{subtitle}</p>", unsafe_allow_html=True)

    if not announcements:
        empty_deck = pdk.Deck(
            map_style=MAP_BASE_STYLE,
            initial_view_state=pdk.ViewState(
                latitude=45.5,
                longitude=-73.8,
                zoom=3.4,
                pitch=12,
            ),
            layers=[],
        )
        st.pydeck_chart(
            empty_deck,
            width="stretch",
            height=520,
            selection_mode="single-object",
            on_select="ignore",
            key=f"{key}-empty",
        )
        st.caption("Aucune annonce active pour le moment.")
        st.markdown("</div>", unsafe_allow_html=True)
        return ""

    points, arcs = build_map_rows(announcements)
    if not points:
        show_notice(
            "info",
            "Carte indisponible pour certains lieux",
            "Entre une adresse complete avec ville et code postal pour maximiser la precision des points sur la carte.",
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return ""

    avg_lat = sum(item["lat"] for item in points) / len(points)
    avg_lon = sum(item["lon"] for item in points) / len(points)

    point_layer = pdk.Layer(
        "ScatterplotLayer",
        data=points,
        id="announcement-points",
        get_position="[lon, lat]",
        get_fill_color="color",
        get_radius=28000,
        pickable=True,
        auto_highlight=True,
        radius_min_pixels=5,
        radius_max_pixels=12,
    )
    layers = [point_layer]

    if arcs:
        arc_layer = pdk.Layer(
            "ArcLayer",
            data=arcs,
            id="announcement-routes",
            get_source_position="[source_lon, source_lat]",
            get_target_position="[target_lon, target_lat]",
            get_source_color=[11, 122, 117, 150],
            get_target_color=[213, 119, 65, 150],
            pickable=True,
            auto_highlight=True,
            get_width=5,
            width_min_pixels=4,
            width_max_pixels=9,
        )
        layers.insert(0, arc_layer)

    deck = pdk.Deck(
        map_style=MAP_BASE_STYLE,
        initial_view_state=pdk.ViewState(
            latitude=avg_lat,
            longitude=avg_lon,
            zoom=3.6,
            pitch=12,
        ),
        layers=layers,
        tooltip={
            "html": (
                "<b>{companyName}</b><br/>"
                "{city}<br/>"
                "Prix/voyage: {pricePerTrip}<br/>"
                "Date de livraison: {deliveryDate}<br/>"
                "Equipement requis: {equipment}<br/>"
                "Voyages disponibles: {remainingTrips}"
            ),
            "style": {"backgroundColor": "#020617", "color": "#e5f2ff"},
        },
    )
    chart_state = st.pydeck_chart(
        deck,
        width="stretch",
        height=520,
        selection_mode="single-object",
        on_select="rerun" if selectable else "ignore",
        key=key,
    )
    st.caption(
        "Clique sur un trajet ou un point pour selectionner une annonce. Clique a nouveau sur le meme trajet pour fermer."
        if selectable
        else "Carte routiere interactive avec villes et routes visibles. Geocodage: OpenStreetMap Nominatim avec cache local."
    )
    st.markdown("</div>", unsafe_allow_html=True)
    return extract_selected_announcement_id(chart_state) if selectable else ""


def region_matches(regions_text: str, city: str) -> bool:
    return normalize_for_match(city) in normalize_for_match(regions_text)


def equipment_matches(required_equipment: str, available_equipment: list[str]) -> bool:
    required = normalize_equipment_for_match(required_equipment)
    return any(normalize_equipment_for_match(item) == required for item in available_equipment)


def clamp_score(value: Any) -> int:
    try:
        return max(0, min(100, round(float(value))))
    except (TypeError, ValueError):
        return 0


def clamp_rating_score(value: Any) -> int:
    try:
        return max(1, min(5, int(float(value))))
    except (TypeError, ValueError):
        return 1


def get_display_star_count(score: Any, *, max_stars: int = 5) -> int:
    try:
        return max(0, min(max_stars, int(float(score) + 0.5)))
    except (TypeError, ValueError):
        return 0


def build_star_text(score: Any, *, max_stars: int = 5) -> str:
    rating = get_display_star_count(score, max_stars=max_stars)
    return f"{chr(9733) * rating}{chr(9734) * max(0, max_stars - rating)}"


def build_star_html(score: Any, *, max_stars: int = 5) -> str:
    rating = get_display_star_count(score, max_stars=max_stars)
    filled = "&#9733;" * rating
    empty = "&#9734;" * max(0, max_stars - rating)
    return f"<span class='rating-stars'>{filled}<span class='rating-stars-off'>{empty}</span></span>"


def get_ratings_for_account(account_id: str) -> list[dict[str, Any]]:
    normalized_account_id = normalize_text(account_id)
    if not normalized_account_id:
        return []
    ratings = [
        rating
        for rating in st.session_state.ratings
        if normalize_text(rating.get("revieweeAccountId")) == normalized_account_id
    ]
    return sorted(ratings, key=lambda item: item.get("createdAt", ""), reverse=True)


def get_public_rating_summary(account_id: str) -> dict[str, Any]:
    ratings = get_ratings_for_account(account_id)
    if not ratings:
        return {
            "average": 0.0,
            "count": 0,
            "starsText": build_star_text(0),
            "label": "Aucune evaluation publique",
        }

    average = round(sum(int(item["score"]) for item in ratings) / len(ratings), 1)
    rounded_stars = get_display_star_count(average)
    return {
        "average": average,
        "count": len(ratings),
        "starsText": build_star_text(rounded_stars),
        "label": f"{average:.1f}/5 ({len(ratings)} evaluation(s))",
    }


def find_existing_rating(
    request_id: str,
    reviewer_account_id: str,
    reviewee_account_id: str,
) -> dict[str, Any] | None:
    normalized_request_id = normalize_text(request_id)
    normalized_reviewer_id = normalize_text(reviewer_account_id)
    normalized_reviewee_id = normalize_text(reviewee_account_id)
    for rating in st.session_state.ratings:
        if (
            normalize_text(rating.get("requestId")) == normalized_request_id
            and normalize_text(rating.get("reviewerAccountId")) == normalized_reviewer_id
            and normalize_text(rating.get("revieweeAccountId")) == normalized_reviewee_id
        ):
            return rating
    return None


def render_public_rating_summary(account_id: str, *, empty_message: str) -> None:
    summary = get_public_rating_summary(account_id)
    if not summary["count"]:
        st.caption(empty_message)
        return

        st.markdown(
        (
            "<div class='rating-summary'>"
            f"{build_star_html(summary['average'])}"
            f"<strong>{summary['average']:.1f}/5</strong>"
            f"<span>{summary['count']} evaluation(s) publique(s)</span>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_public_reviews(account_id: str, *, empty_message: str, limit: int = 5) -> None:
    ratings = get_ratings_for_account(account_id)
    if not ratings:
        st.caption(empty_message)
        return

    for rating in ratings[:limit]:
        reviewer_label = "Entreprise" if rating["reviewerRole"] == "company" else "Transporteur"
        comment = html.escape(rating["comment"] or "Sans commentaire.")
        reviewer_name = html.escape(rating["reviewerName"] or reviewer_label)
        st.markdown(
            f"""
            <div class="review-card">
              <div>{build_star_html(rating['score'])} <strong>{rating['score']}/5</strong></div>
              <div class="review-meta">{reviewer_label} - {reviewer_name} - {html.escape(rating['createdAt'])}</div>
              <div class="small-copy">{comment}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def submit_public_rating(
    service_request: dict[str, Any],
    *,
    reviewer_role: str,
    score: Any,
    comment: str,
) -> tuple[bool, str]:
    if normalize_text(service_request.get("status")) not in RATABLE_REQUEST_STATUSES:
        return False, "Cette evaluation sera disponible seulement apres une collaboration acceptee."

    current_account = st.session_state.current_account or {}
    reviewer_account_id = normalize_text(current_account.get("id"))
    if not reviewer_account_id:
        return False, "Reconnectez-vous pour publier une evaluation."

    if reviewer_role == "company":
        reviewer_name = st.session_state.company_profile["legalName"]
        reviewee_role = "carrier"
        reviewee_account_id = normalize_text(service_request.get("carrierAccountId"))
        reviewee_name = service_request["carrierName"]
    else:
        reviewer_name = st.session_state.carrier_profile["transportCompany"]
        reviewee_role = "company"
        reviewee_account_id = normalize_text(service_request.get("companyAccountId"))
        reviewee_name = service_request["companyName"]

    if not reviewee_account_id:
        return False, "Le compte cible doit etre relie a l'annonce pour pouvoir etre evalue."

    if find_existing_rating(service_request["id"], reviewer_account_id, reviewee_account_id):
        return False, "Vous avez deja publie une evaluation pour cette collaboration."

    try:
        create_rating_record(
            {
                "requestId": service_request["id"],
                "announcementId": service_request.get("announcementId", ""),
                "reviewerAccountId": reviewer_account_id,
                "reviewerRole": reviewer_role,
                "reviewerName": reviewer_name,
                "revieweeAccountId": reviewee_account_id,
                "revieweeRole": reviewee_role,
                "revieweeName": reviewee_name,
                "score": clamp_rating_score(score),
                "comment": normalize_text(comment),
            }
        )
    except sqlite3.IntegrityError:
        return False, "Une evaluation existe deja pour cette collaboration."

    add_notification(
        recipient_role=reviewee_role,
        recipient_name=reviewee_name,
        recipient_account_id=reviewee_account_id,
        title="Nouvelle evaluation publique",
        message=(
            f"{reviewer_name} a publie une evaluation de {clamp_rating_score(score)}/5 "
            f"apres la collaboration sur {service_request['announcementTitle']}."
        ),
        related_announcement_id=service_request.get("announcementId", ""),
        related_request_id=service_request["id"],
    )
    load_persisted_data_into_session()
    return True, "Votre evaluation publique a ete enregistree."


def render_rating_form_for_request(
    service_request: dict[str, Any],
    *,
    reviewer_role: str,
) -> None:
    if normalize_text(service_request.get("status")) not in RATABLE_REQUEST_STATUSES:
        return

    reviewee_role = "transporteur" if reviewer_role == "company" else "entreprise"
    reviewee_account_id = normalize_text(
        service_request.get("carrierAccountId" if reviewer_role == "company" else "companyAccountId")
    )
    reviewer_account_id = normalize_text((st.session_state.current_account or {}).get("id"))
    existing_rating = find_existing_rating(
        service_request["id"],
        reviewer_account_id,
        reviewee_account_id,
    )

    if existing_rating:
        show_notice(
            "success",
            "Evaluation deja publiee",
            (
                f"Votre note pour ce {reviewee_role} est de {existing_rating['score']}/5. "
                f"Commentaire: {existing_rating['comment'] or 'Sans commentaire.'}"
            ),
        )
        return

    with st.form(f"rating-form-{reviewer_role}-{service_request['id']}"):
        score = st.select_slider(
            "Note de 1 a 5 etoiles",
            options=[1, 2, 3, 4, 5],
            value=5,
            format_func=lambda value: f"{value}/5 - {build_star_text(value)}",
        )
        comment = st.text_area(
            "Commentaire public (optionnel)",
            key=f"rating-comment-{reviewer_role}-{service_request['id']}",
            height=90,
            placeholder="Partagez votre experience de collaboration si vous le souhaitez.",
        )
        submit_rating = st.form_submit_button(
            f"Publier mon evaluation du {reviewee_role}",
            use_container_width=True,
        )

    if submit_rating:
        ok, message = submit_public_rating(
            service_request,
            reviewer_role=reviewer_role,
            score=score,
            comment=comment,
        )
        if ok:
            st.success(message)
            st.rerun()
        st.error(message)


def calculate_local_compatibility(
    profile: dict[str, Any], announcement: dict[str, Any]
) -> int:
    score = 30
    if equipment_matches(announcement["equipment"], profile["equipmentTypes"]):
        score += 40
    else:
        score -= 15

    if region_matches(profile["regions"], announcement["pickupCity"]):
        score += 15
    if region_matches(profile["regions"], announcement["deliveryCity"]):
        score += 15
    if int(profile["fleetSize"] or 1) >= 2 and int(announcement["remainingTrips"]) >= 2:
        score += 8
    return clamp_score(score)


def get_filtered_announcements() -> list[dict[str, Any]]:
    filters = st.session_state.filters
    results = []
    for announcement in get_active_announcements():
        if not announcement_matches_filter_values(
            announcement,
            pickup_city=filters["pickupCity"],
            delivery_city=filters["deliveryCity"],
            cargo_type=filters["cargoType"],
            equipment=filters["equipment"],
        ):
            continue
        results.append(announcement)
    return results


def announcement_matches_filter_values(
    announcement: dict[str, Any],
    *,
    pickup_city: str = "",
    delivery_city: str = "",
    cargo_type: str = "",
    equipment: str = "",
) -> bool:
    if pickup_city and normalize_for_match(pickup_city) not in normalize_for_match(
        announcement["pickupCity"]
    ):
        return False
    if delivery_city and normalize_for_match(delivery_city) not in normalize_for_match(
        announcement["deliveryCity"]
    ):
        return False
    if cargo_type and normalize_for_match(cargo_type) not in normalize_for_match(
        announcement["cargoType"]
    ):
        return False
    if equipment and normalize_equipment_for_match(equipment) != normalize_equipment_for_match(
        announcement["equipment"]
    ):
        return False
    return True


def alert_matches_announcement(alert: dict[str, Any], announcement: dict[str, Any]) -> bool:
    return announcement_matches_filter_values(
        announcement,
        pickup_city=alert.get("pickupCity", ""),
        delivery_city=alert.get("deliveryCity", ""),
        cargo_type=alert.get("cargoType", ""),
        equipment=alert.get("equipment", ""),
    )


def notify_matching_carrier_alerts(announcement: dict[str, Any]) -> int:
    with get_db_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM carrier_alerts WHERE is_active = 1 ORDER BY created_at ASC"
        ).fetchall()
    alerts = [item for item in (serialize_alert_row(row) for row in rows) if item]
    notifications_sent = 0

    for alert in alerts:
        if not alert_matches_announcement(alert, announcement):
            continue
        if notification_exists(
            recipient_account_id=alert["carrierAccountId"],
            related_announcement_id=announcement["id"],
            related_alert_id=alert["id"],
        ):
            continue
        add_notification(
            recipient_role="carrier",
            recipient_name=alert["carrierName"],
            recipient_account_id=alert["carrierAccountId"],
            title="Nouvelle annonce correspondant a votre alerte",
            message=(
                f"{announcement['companyName']} a publie {announcement['title']} "
                f"({announcement['pickupCity']} -> {announcement['deliveryCity']})."
            ),
            related_announcement_id=announcement["id"],
            related_alert_id=alert["id"],
        )
        notifications_sent += 1

    return notifications_sent


def send_request_message(request_id: str, body: str) -> tuple[bool, str]:
    cleaned_body = normalize_text(body)
    if not cleaned_body:
        return False, "Ecrivez un message avant de l'envoyer."

    service_request = next(
        (item for item in st.session_state.service_requests if item["id"] == request_id),
        None,
    )
    if not service_request:
        return False, "Conversation introuvable."

    current_account = st.session_state.current_account or {}
    sender_role = normalize_text(current_account.get("role")) or st.session_state.active_role or ""
    sender_name = (
        st.session_state.company_profile["legalName"]
        if sender_role == "company"
        else st.session_state.carrier_profile["transportCompany"]
    )
    sender_account_id = normalize_text(current_account.get("id"))

    create_message_record(
        request_id,
        sender_role=sender_role,
        sender_name=sender_name,
        sender_account_id=sender_account_id,
        body=cleaned_body,
    )

    if sender_role == "company":
        add_notification(
            recipient_role="carrier",
            recipient_name=service_request["carrierName"],
            recipient_account_id=service_request.get("carrierAccountId", ""),
            title="Nouveau message de l'entreprise",
            message=f"Nouveau message concernant {service_request['announcementTitle']}.",
            related_announcement_id=service_request["announcementId"],
            related_request_id=request_id,
        )
    else:
        add_notification(
            recipient_role="company",
            recipient_name=service_request["companyName"],
            recipient_account_id=service_request.get("companyAccountId", ""),
            title="Nouveau message du transporteur",
            message=f"Nouveau message concernant {service_request['announcementTitle']}.",
            related_announcement_id=service_request["announcementId"],
            related_request_id=request_id,
        )

    load_persisted_data_into_session()
    return True, "Message envoye."


def render_documents_for_owner(owner_type: str, owner_id: str, *, empty_message: str) -> None:
    documents = list_documents(owner_type, owner_id)
    if not documents:
        st.caption(empty_message)
        return

    for document in documents:
        document_path = Path(document["filePath"])
        if not document_path.exists():
            st.caption(f"{document['fileName']} (fichier introuvable)")
            continue
        st.download_button(
            label=f"Telecharger {document['fileName']}",
            data=document_path.read_bytes(),
            file_name=document["fileName"],
            mime=document["contentType"] or "application/octet-stream",
            key=f"download-{document['id']}",
            use_container_width=True,
        )


def render_request_messages(service_request: dict[str, Any]) -> None:
    messages = list_messages_for_request(service_request["id"])
    if not messages:
        st.caption("Aucun message pour le moment.")
    else:
        for item in messages:
            role_label = "Entreprise" if item["senderRole"] == "company" else "Transporteur"
            st.markdown(
                f"""
                <div class="result-card">
                  <div class="small-copy">
                    <strong>{role_label}</strong> - {item['senderName']}<br>
                    {item['body']}<br>
                    <span style="color:#7e97b8;">{item['createdAt']}</span>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with st.form(f"message-form-{service_request['id']}"):
        body = st.text_area(
            "Envoyer un message",
            key=f"message-body-{service_request['id']}",
            height=80,
            placeholder="Ecrivez ici un message pour l'autre partie.",
        )
        submit_message = st.form_submit_button("Envoyer le message", use_container_width=True)
    if submit_message:
        ok, message = send_request_message(service_request["id"], body)
        if ok:
            st.success(message)
            st.rerun()
        st.error(message)


def ranked_carrier_results() -> list[dict[str, Any]]:
    ai_map = {
        match["announcementId"]: match
        for match in st.session_state.carrier_ai["matches"]
        if match.get("announcementId")
    }
    profile = st.session_state.carrier_profile
    results = []
    for announcement in get_filtered_announcements():
        ai_match = ai_map.get(announcement["id"])
        local_score = calculate_local_compatibility(profile, announcement)
        results.append(
            {
                "announcement": announcement,
                "localScore": local_score,
                "aiScore": clamp_score(ai_match["score"]) if ai_match else None,
                "aiReasoning": ai_match["reasoning"] if ai_match else "",
            }
        )

    def sort_key(item: dict[str, Any]) -> int:
        return item["aiScore"] if item["aiScore"] is not None else item["localScore"]

    return sorted(results, key=sort_key, reverse=True)


def get_cargo_filter_options() -> list[str]:
    cargo_values = set(SUGGESTED_CARGO_OPTIONS)
    for announcement in st.session_state.announcements:
        if announcement["cargoType"]:
            cargo_values.add(announcement["cargoType"])
    return sorted(cargo_values, key=lambda item: normalize_for_match(item))


def show_notice(kind: str, title: str, message: str = "") -> None:
    css_class = {
        "info": "notice notice-info",
        "success": "notice notice-success",
        "warning": "notice notice-warning",
        "error": "notice notice-error",
    }[kind]

    title_html = f"<strong>{title}</strong>" if title else ""
    body_html = f"<div>{message}</div>" if message else ""
    st.markdown(f"<div class='{css_class}'>{title_html}{body_html}</div>", unsafe_allow_html=True)


def call_gemini_json(system_instruction: str, user_prompt: str) -> dict[str, Any]:
    if not GEMINI_API_KEY:
        raise RuntimeError("Gemini n'est pas configure dans .env.")

    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY,
        },
        json={
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.35,
            },
        },
        timeout=60,
    )
    payload = response.json()
    if not response.ok:
        message = payload.get("error", {}).get("message", "Erreur Gemini.")
        raise RuntimeError(message)

    text = ""
    candidates = payload.get("candidates", [])
    if candidates:
        for part in candidates[0].get("content", {}).get("parts", []):
            if isinstance(part.get("text"), str):
                text = part["text"]
                break

    if not text:
        raise RuntimeError("Gemini n'a renvoye aucun contenu exploitable.")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        text = extract_json_like_text(text)
        return json.loads(text)


def humanize_ai_error(message: str) -> str:
    normalized = normalize_for_match(message)

    if "high demand" in normalized or "temporarily unavailable" in normalized:
        return "L'assistant est temporairement tres sollicite. Reessaie dans quelques instants."
    if "invalid api key" in normalized:
        return "L'assistant n'est pas configure correctement pour le moment."
    if "quota" in normalized or "rate limit" in normalized:
        return "La limite d'utilisation de l'assistant a ete atteinte temporairement. Reessaie plus tard."
    if "configure dans .env" in normalized:
        return "L'assistant n'est pas encore active sur cette installation."

    return "L'assistant n'a pas pu traiter la demande pour le moment."


def extract_json_like_text(text: str) -> str:
    if "```" in text:
        for chunk in text.split("```"):
            chunk = chunk.strip()
            if chunk.startswith("json"):
                chunk = chunk[4:].strip()
            if chunk.startswith("{") and chunk.endswith("}"):
                return chunk
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        return text[first : last + 1]
    raise json.JSONDecodeError("JSON introuvable", text, 0)


def company_assistant() -> None:
    st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Assistant</span>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Transformer un texte libre en annonce</div>", unsafe_allow_html=True)

    if not gemini_is_configured():
        show_notice(
            "warning",
            "Assistant indisponible",
            "L'assistant n'est pas encore actif sur cette installation.",
        )

    with st.form("company_ai_form", clear_on_submit=False):
        request_text = st.text_area(
            "Decris le voyage comme tu le dirais au telephone",
            key="company_ai_prompt",
            height=150,
            placeholder="Exemple: J'ai 2 voyages de tuyaux a faire de Drummondville vers Sherbrooke mardi avec une plateforme...",
        )
        action_col1, action_col2 = st.columns([1.3, 1])
        with action_col1:
            generate = st.form_submit_button(
                "Generer mon annonce",
                type="primary",
                disabled=not gemini_is_configured(),
                use_container_width=True,
            )
        with action_col2:
            use_example = st.form_submit_button("Inserer un exemple", use_container_width=True)

    if use_example:
        st.session_state.company_ai["requestText"] = COMPANY_EXAMPLE_PROMPT
        st.session_state.sync_company_ai_prompt_widget = True
        st.rerun()

    if generate:
        st.session_state.company_ai["requestText"] = request_text
        with st.spinner("Preparation du brouillon en cours..."):
            try:
                payload = call_gemini_json(
                    system_instruction=(
                        "Tu es un assistant logistique. Tu dois repondre uniquement en JSON valide. "
                        "Tu aides une PME a transformer une description libre en annonce structuree. "
                        "Si une information est inconnue, renvoie une chaine vide ou 0."
                    ),
                    user_prompt=build_company_prompt(request_text),
                )
                apply_company_ai_response(payload)
                st.rerun()
            except Exception as error:  # noqa: BLE001
                st.session_state.company_ai["error"] = humanize_ai_error(str(error))
                st.rerun()

    if st.session_state.company_ai["assistantMessage"]:
        show_notice("success", "Suggestion prete", st.session_state.company_ai["assistantMessage"])
    if st.session_state.company_ai["missingFields"]:
        missing_html = "".join(
            f"<li>{item}</li>" for item in st.session_state.company_ai["missingFields"]
        )
        st.markdown(
            f"<div class='notice notice-warning'><strong>Points a verifier</strong><ul class='helper-list'>{missing_html}</ul></div>",
            unsafe_allow_html=True,
        )
    if st.session_state.company_ai["error"]:
        show_notice("error", "Erreur de l'assistant", st.session_state.company_ai["error"])

    st.markdown("</div>", unsafe_allow_html=True)


def build_company_prompt(request_text: str) -> str:
    payload = {
        "profile": st.session_state.company_profile,
        "currentDraft": export_current_draft(),
        "requestText": request_text,
    }
    template = {
        "announcement": {
            "title": "",
            "pickupAddress": "",
            "pickupCity": "",
            "pickupPostalCode": "",
            "deliveryAddress": "",
            "deliveryCity": "",
            "deliveryPostalCode": "",
            "cargoType": "",
            "equipment": "",
            "loadingDate": "",
            "deliveryDate": "",
            "tripsTotal": 0,
            "budget": 0,
            "notes": "",
        },
        "assistantMessage": "",
        "missingFields": ["", ""],
    }
    return (
        "Contexte:\n"
        + json.dumps(payload, ensure_ascii=True, indent=2)
        + "\n\nRetourne exactement cet objet JSON:\n"
        + json.dumps(template, ensure_ascii=True, indent=2)
        + "\n\nRegles:\n"
        + "- pickupAddress et deliveryAddress doivent contenir l'adresse exacte si elle est connue.\n"
        + "- pickupPostalCode et deliveryPostalCode doivent contenir le code postal si possible.\n"
        + "- loadingDate doit etre YYYY-MM-DD si possible.\n"
        + "- deliveryDate doit etre YYYY-MM-DD si possible et represente la date de livraison.\n"
        + "- tripsTotal et budget doivent etre des nombres; budget represente le prix par voyage.\n"
        + "- title doit etre court et utile.\n"
        + "- missingFields liste ce qui reste flou avant publication."
    )


def apply_company_ai_response(payload: dict[str, Any]) -> None:
    announcement = payload.get("announcement", {})
    cargo_type, cargo_other = normalize_cargo_option(announcement.get("cargoType"))
    current_draft = st.session_state.draft_announcement
    draft = {
        "title": normalize_text(announcement.get("title")),
        "pickupAddress": normalize_text(announcement.get("pickupAddress"))
        or current_draft.get("pickupAddress", ""),
        "pickupCity": normalize_text(announcement.get("pickupCity")),
        "pickupPostalCode": normalize_text(announcement.get("pickupPostalCode"))
        or current_draft.get("pickupPostalCode", ""),
        "deliveryAddress": normalize_text(announcement.get("deliveryAddress"))
        or current_draft.get("deliveryAddress", ""),
        "deliveryCity": normalize_text(announcement.get("deliveryCity")),
        "deliveryPostalCode": normalize_text(announcement.get("deliveryPostalCode"))
        or current_draft.get("deliveryPostalCode", ""),
        "cargoType": cargo_type,
        "cargoTypeOther": cargo_other,
        "equipment": normalize_equipment_option(announcement.get("equipment")),
        "loadingDate": normalize_date_value(announcement.get("loadingDate")),
        "deliveryDate": normalize_date_value(
            announcement.get("deliveryDate") or announcement.get("loadingDate")
        ),
        "tripsTotal": max(1, int(float(announcement.get("tripsTotal") or 1))),
        "budget": max(0, int(float(announcement.get("budget") or 0))),
        "notes": normalize_text(announcement.get("notes")),
    }
    st.session_state.draft_announcement = draft
    st.session_state.company_ai["assistantMessage"] = normalize_text(
        payload.get("assistantMessage")
    ) or "Le brouillon d'annonce a ete prepare."
    st.session_state.company_ai["missingFields"] = [
        normalize_text(item)
        for item in payload.get("missingFields", [])
        if normalize_text(item)
    ]
    st.session_state.company_ai["error"] = ""
    st.session_state.sync_draft_widgets = True


def carrier_assistant() -> None:
    st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Assistant</span>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Trouver tes meilleurs matchs</div>", unsafe_allow_html=True)

    if not gemini_is_configured():
        show_notice(
            "warning",
            "Assistant indisponible",
            "L'assistant n'est pas encore actif sur cette installation.",
        )

    with st.form("carrier_ai_form", clear_on_submit=False):
        request_text = st.text_area(
            "Explique simplement ce que tu cherches",
            key="carrier_ai_prompt",
            height=150,
            placeholder="Exemple: Je veux surtout des voyages flatbed ou drybox entre Montreal, Quebec et Ottawa.",
        )
        action_col1, action_col2 = st.columns([1.3, 1])
        with action_col1:
            analyze = st.form_submit_button(
                "Trouver mes meilleurs voyages",
                type="primary",
                disabled=not gemini_is_configured(),
                use_container_width=True,
            )
        with action_col2:
            use_example = st.form_submit_button("Inserer un exemple", use_container_width=True)

    if use_example:
        st.session_state.carrier_ai["requestText"] = CARRIER_EXAMPLE_PROMPT
        st.session_state.sync_carrier_ai_prompt_widget = True
        st.rerun()

    if analyze:
        st.session_state.carrier_ai["requestText"] = request_text
        with st.spinner("Analyse des meilleurs trajets en cours..."):
            try:
                payload = call_gemini_json(
                    system_instruction=(
                        "Tu aides un petit transporteur a classer les meilleures annonces. "
                        "Tu dois repondre uniquement en JSON valide. "
                        "Tu peux suggerer des filtres utiles."
                    ),
                    user_prompt=build_carrier_prompt(request_text),
                )
                apply_carrier_ai_response(payload)
                st.rerun()
            except Exception as error:  # noqa: BLE001
                st.session_state.carrier_ai["error"] = humanize_ai_error(str(error))
                st.rerun()

    if st.session_state.carrier_ai["assistantMessage"]:
        show_notice("success", "Analyse prete", st.session_state.carrier_ai["assistantMessage"])
    if any(st.session_state.carrier_ai["suggestedFilters"].values()):
        filters_html = " ".join(
            f"<span class='status-pill ai'>{label}: {value}</span>"
            for label, value in render_suggested_filters().items()
        )
        st.markdown(
            f"<div class='notice notice-info'><strong>Filtres proposes</strong>{filters_html}</div>",
            unsafe_allow_html=True,
        )
        if st.button("Appliquer les filtres proposes", use_container_width=True):
            st.session_state.filters = copy.deepcopy(
                st.session_state.carrier_ai["suggestedFilters"]
            )
            st.session_state.sync_filter_widgets = True
            st.rerun()
    if st.session_state.carrier_ai["error"]:
        show_notice("error", "Erreur de l'assistant", st.session_state.carrier_ai["error"])

    st.markdown("</div>", unsafe_allow_html=True)


def build_carrier_prompt(request_text: str) -> str:
    payload = {
        "profile": st.session_state.carrier_profile,
        "currentFilters": st.session_state.filters,
        "requestText": request_text,
        "announcements": get_active_announcements(),
    }
    template = {
        "assistantMessage": "",
        "suggestedFilters": {
            "pickupCity": "",
            "deliveryCity": "",
            "cargoType": "",
            "equipment": "",
        },
        "matches": [
            {
                "announcementId": "",
                "score": 0,
                "reasoning": "",
            }
        ],
    }
    return (
        "Contexte:\n"
        + json.dumps(payload, ensure_ascii=True, indent=2)
        + "\n\nRetourne exactement cet objet JSON:\n"
        + json.dumps(template, ensure_ascii=True, indent=2)
        + "\n\nRegles:\n"
        + "- Matches: maximum 5.\n"
        + "- score: nombre entier de 0 a 100.\n"
        + "- announcementId doit correspondre exactement a une annonce fournie.\n"
        + "- reasoning doit etre bref et concret."
    )


def apply_carrier_ai_response(payload: dict[str, Any]) -> None:
    valid_ids = {announcement["id"] for announcement in get_active_announcements()}
    matches = []
    for item in payload.get("matches", []):
        announcement_id = normalize_text(item.get("announcementId"))
        if announcement_id in valid_ids:
            matches.append(
                {
                    "announcementId": announcement_id,
                    "score": clamp_score(item.get("score")),
                    "reasoning": normalize_text(item.get("reasoning")),
                }
            )
    suggested = payload.get("suggestedFilters", {})
    st.session_state.carrier_ai["assistantMessage"] = normalize_text(
        payload.get("assistantMessage")
    ) or "Les annonces les plus compatibles ont ete classees."
    st.session_state.carrier_ai["matches"] = matches
    st.session_state.carrier_ai["suggestedFilters"] = {
        "pickupCity": normalize_text(suggested.get("pickupCity")),
        "deliveryCity": normalize_text(suggested.get("deliveryCity")),
        "cargoType": normalize_text(suggested.get("cargoType")),
        "equipment": normalize_equipment_option(suggested.get("equipment")),
    }
    st.session_state.carrier_ai["error"] = ""


def render_suggested_filters() -> dict[str, str]:
    labels = {
        "pickupCity": "Chargement",
        "deliveryCity": "Livraison",
        "cargoType": "Marchandise",
        "equipment": "Equipement",
    }
    return {
        labels[key]: value
        for key, value in st.session_state.carrier_ai["suggestedFilters"].items()
        if normalize_text(value)
    }


def export_current_draft() -> dict[str, Any]:
    return {
        "title": st.session_state.announcement_title,
        "pickupAddress": st.session_state.announcement_pickupAddress,
        "pickupCity": st.session_state.announcement_pickupCity,
        "pickupPostalCode": st.session_state.announcement_pickupPostalCode,
        "deliveryAddress": st.session_state.announcement_deliveryAddress,
        "deliveryCity": st.session_state.announcement_deliveryCity,
        "deliveryPostalCode": st.session_state.announcement_deliveryPostalCode,
        "cargoType": (
            st.session_state.announcement_cargoTypeOther
            if st.session_state.announcement_cargoType == OTHER_CARGO_VALUE
            else st.session_state.announcement_cargoType
        ),
        "equipment": st.session_state.announcement_equipment,
        "loadingDate": format_date(st.session_state.announcement_loadingDate)
        if st.session_state.announcement_loadingDate
        else "",
        "deliveryDate": format_date(st.session_state.announcement_deliveryDate)
        if st.session_state.announcement_deliveryDate
        else "",
        "tripsTotal": st.session_state.announcement_tripsTotal,
        "budget": st.session_state.announcement_budget,
        "notes": st.session_state.announcement_notes,
    }


def apply_draft_to_widgets() -> None:
    draft = st.session_state.draft_announcement
    st.session_state.announcement_title = draft["title"]
    st.session_state.announcement_pickupAddress = draft["pickupAddress"]
    st.session_state.announcement_pickupCity = draft["pickupCity"]
    st.session_state.announcement_pickupPostalCode = draft["pickupPostalCode"]
    st.session_state.announcement_deliveryAddress = draft["deliveryAddress"]
    st.session_state.announcement_deliveryCity = draft["deliveryCity"]
    st.session_state.announcement_deliveryPostalCode = draft["deliveryPostalCode"]
    st.session_state.announcement_equipment = draft["equipment"]
    st.session_state.announcement_loadingDate = draft["loadingDate"]
    st.session_state.announcement_deliveryDate = draft.get("deliveryDate")
    st.session_state.announcement_tripsTotal = int(draft["tripsTotal"] or 1)
    st.session_state.announcement_budget = int(draft["budget"] or 0)
    st.session_state.announcement_notes = draft["notes"]
    st.session_state.announcement_cargoType = draft["cargoType"] or ""
    st.session_state.announcement_cargoTypeOther = draft["cargoTypeOther"]


def apply_filters_to_widgets() -> None:
    filters = st.session_state.filters
    st.session_state.filter_pickupCity = filters["pickupCity"]
    st.session_state.filter_deliveryCity = filters["deliveryCity"]
    st.session_state.filter_cargoType = filters["cargoType"]
    st.session_state.filter_equipment = filters["equipment"]


def get_company_announcement_status(announcement: dict[str, Any]) -> str:
    if is_announcement_expired(announcement):
        return "Expiree"
    if int(announcement["remainingTrips"]) > 0:
        return "Active"
    return "Completee"


def infer_notification_state(notification: dict[str, Any]) -> str:
    title = normalize_for_match(notification.get("title"))
    if "acceptee" in title or "accepte" in title:
        return "Acceptee"
    if "refusee" in title or "refuse" in title:
        return "Refusee"
    if "verifie" in title:
        return "Verifie"
    if "retiree" in title or "retire" in title:
        return "Retiree"
    if "nouvelle" in title:
        return "Nouvelle"
    return "Info"


def render_notifications_panel(
    notifications: list[dict[str, Any]], title: str, empty_message: str
) -> None:
    st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Notifications</span>", unsafe_allow_html=True)
    st.markdown(f"<div class='section-title'>{title}</div>", unsafe_allow_html=True)

    if not notifications:
        show_notice("info", "Aucune notification", empty_message)
        st.markdown("</div>", unsafe_allow_html=True)
        return

    for notification in notifications:
        notification_state = infer_notification_state(notification)
        expander_label = (
            f"{notification['title']} | {notification_state} | {notification['createdAt']}"
        )
        with st.expander(expander_label, expanded=False):
            st.caption("Etat")
            st.write(notification_state)
            st.caption("Date")
            st.write(notification["createdAt"] or "Non precisee")
            st.caption("Detail")
            st.write(notification["message"] or "Aucun detail disponible.")

    st.markdown("</div>", unsafe_allow_html=True)


def render_company_requests_panel() -> None:
    requests_list = get_company_service_requests()
    st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Demandes transporteurs</span>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Propositions a traiter</div>", unsafe_allow_html=True)

    if not requests_list:
        show_notice(
            "info",
            "Aucune proposition pour le moment",
            "Quand un transporteur proposera son service, tu le verras ici avec ses coordonnees et tu pourras accepter ou refuser.",
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    for service_request in requests_list:
        announcement = find_announcement(service_request["announcementId"])
        remaining_trips = announcement["remainingTrips"] if announcement else 0
        status_class = "status-pill" if service_request["status"] == "pending" else "status-pill ai"
        carrier_rating_summary = get_public_rating_summary(
            service_request.get("carrierAccountId", "")
        )
        st.markdown(
            f"""
            <div class="result-card">
              <div style="display:flex;justify-content:space-between;gap:1rem;align-items:flex-start;">
                <div>
                  <div class="section-title" style="font-size:1.1rem;margin-top:0;">{service_request['announcementTitle']}</div>
                  <div class="small-copy">
                    Transporteur: <strong>{service_request['carrierName']}</strong><br>
                    Note publique: <strong>{carrier_rating_summary['label']}</strong><br>
                    Contact: {service_request['carrierContactName']} | {service_request['carrierPhone']}<br>
                    Voyages demandes: <strong>{service_request['requestedTrips']}</strong><br>
                    Voyages restants dans l'annonce: <strong>{remaining_trips}</strong><br>
                    Message: {service_request['message'] or 'Aucun message.'}
                  </div>
                </div>
                <div class="{status_class}">{service_request['status']}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        equipment_types = service_request.get("carrierEquipmentTypes") or []
        equipment_html = " ".join(
            f"<span class='status-pill'>{item}</span>" for item in equipment_types
        )
        with st.expander(f"Voir le profil du transporteur - {service_request['carrierName']}"):
            profile_cols = st.columns(2)
            with profile_cols[0]:
                st.caption("Numero d'entreprise")
                st.write(service_request.get("carrierBusinessNumber") or "Non renseigne")
                st.caption("Preuve d'assurance")
                st.write(service_request.get("carrierInsuranceNumber") or "Non renseigne")
                st.caption("Nombre de camions")
                st.write(service_request.get("carrierFleetSize") or "Non renseigne")
            with profile_cols[1]:
                st.caption("Nom du responsable")
                st.write(service_request.get("carrierContactName") or "Non renseigne")
                st.caption("Telephone")
                st.write(service_request.get("carrierPhone") or "Non renseigne")
                st.caption("Courriel")
                st.write(service_request.get("carrierEmail") or "Non renseigne")

            st.caption("Evaluation publique moyenne")
            render_public_rating_summary(
                service_request.get("carrierAccountId", ""),
                empty_message="Aucune evaluation publique pour ce transporteur pour le moment.",
            )
            st.caption("Equipements")
            st.markdown(
                equipment_html or "<div class='small-copy'>Non renseigne</div>",
                unsafe_allow_html=True,
            )
            st.caption("Documents facultatifs")
            render_documents_for_owner(
                "carrier_profile",
                service_request.get("carrierAccountId", ""),
                empty_message="Aucun document de profil ajoute.",
            )
            st.caption("Commentaires publics recents")
            render_public_reviews(
                service_request.get("carrierAccountId", ""),
                empty_message="Aucun commentaire public pour ce transporteur.",
                limit=3,
            )

        with st.expander(f"Messagerie - {service_request['carrierName']}", expanded=False):
            render_request_messages(service_request)

        if service_request["status"] == "pending":
            with st.form(f"decision-form-{service_request['id']}"):
                decision_message = st.text_input(
                    "Message de reponse pour le transporteur",
                    key=f"decision-message-{service_request['id']}",
                )
                decision_cols = st.columns(2)
                with decision_cols[0]:
                    accept = st.form_submit_button(
                        "Accepter",
                        type="primary",
                        use_container_width=True,
                    )
                with decision_cols[1]:
                    refuse = st.form_submit_button("Refuser", use_container_width=True)

            if accept:
                ok, message = process_service_request_decision(
                    service_request["id"], "accepted", decision_message
                )
                if ok:
                    st.success(message)
                    st.rerun()
                st.error(message)
            if refuse:
                ok, message = process_service_request_decision(
                    service_request["id"], "refused", decision_message
                )
                if ok:
                    st.success(message)
                    st.rerun()
                st.error(message)
        else:
            show_notice(
                "info",
                "Decision deja prise",
                service_request["decisionMessage"] or "La demande a deja ete traitee.",
            )
            if normalize_text(service_request["status"]) in RATABLE_REQUEST_STATUSES:
                with st.expander(
                    f"Evaluer ce transporteur - {service_request['carrierName']}",
                    expanded=False,
                ):
                    render_rating_form_for_request(
                        service_request,
                        reviewer_role="company",
                    )

    st.markdown("</div>", unsafe_allow_html=True)


def render_carrier_requests_panel() -> None:
    requests_list = get_carrier_service_requests()
    st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Mes propositions</span>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Suivi des demandes envoyees</div>", unsafe_allow_html=True)

    if not requests_list:
        show_notice(
            "info",
            "Aucune proposition envoyee",
            "Propose ton service sur une annonce pour recevoir ensuite la decision de l'entreprise.",
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    for service_request in requests_list:
        status_class = "status-pill" if service_request["status"] == "pending" else "status-pill ai"
        company_rating_summary = get_public_rating_summary(
            service_request.get("companyAccountId", "")
        )
        st.markdown(
            f"""
            <div class="result-card">
              <div style="display:flex;justify-content:space-between;gap:1rem;align-items:flex-start;">
                <div>
                  <div class="section-title" style="font-size:1.1rem;margin-top:0;">{service_request['announcementTitle']}</div>
                  <div class="small-copy">
                    Entreprise: <strong>{service_request['companyName']}</strong><br>
                    Note publique: <strong>{company_rating_summary['label']}</strong><br>
                    Voyages demandes: <strong>{service_request['requestedTrips']}</strong><br>
                    Message envoye: {service_request['message'] or 'Aucun message.'}<br>
                    Reponse: {service_request['decisionMessage'] or 'En attente de decision.'}
                  </div>
                </div>
                <div class="{status_class}">{service_request['status']}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.expander(f"Voir les evaluations publiques de {service_request['companyName']}", expanded=False):
            render_public_rating_summary(
                service_request.get("companyAccountId", ""),
                empty_message="Aucune evaluation publique pour cette entreprise pour le moment.",
            )
            render_public_reviews(
                service_request.get("companyAccountId", ""),
                empty_message="Aucun commentaire public pour cette entreprise.",
                limit=3,
            )

        with st.expander(f"Messagerie - {service_request['companyName']}", expanded=False):
            render_request_messages(service_request)

        if normalize_text(service_request["status"]) in RATABLE_REQUEST_STATUSES:
            with st.expander(
                f"Evaluer cette entreprise - {service_request['companyName']}",
                expanded=False,
            ):
                render_rating_form_for_request(
                    service_request,
                    reviewer_role="carrier",
                )

    st.markdown("</div>", unsafe_allow_html=True)


def render_alerts_panel() -> None:
    st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Alertes</span>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Mes alertes transporteur</div>", unsafe_allow_html=True)

    current_account = st.session_state.current_account or {}
    carrier_account_id = normalize_text(current_account.get("id"))
    if not carrier_account_id:
        show_notice("info", "Connexion requise", "Connectez-vous pour enregistrer des alertes.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    with st.form("carrier_alert_form"):
        title = st.text_input(
            "Nom de l'alerte",
            placeholder="Exemple: Flatbed Quebec -> Maine",
        )
        alert_cols = st.columns(2)
        with alert_cols[0]:
            pickup_city = st.text_input(
                "Chargement contient",
                value=st.session_state.filters["pickupCity"],
            )
            cargo_type = st.selectbox(
                "Marchandise",
                options=[""] + get_cargo_filter_options(),
                format_func=lambda value: "Toutes" if not value else value,
            )
        with alert_cols[1]:
            delivery_city = st.text_input(
                "Livraison contient",
                value=st.session_state.filters["deliveryCity"],
            )
            equipment = st.selectbox(
                "Equipement requis",
                options=[""] + EQUIPMENT_OPTIONS,
                format_func=lambda value: "Tous" if not value else value,
            )
        submit_alert = st.form_submit_button("Creer l'alerte", use_container_width=True)

    if submit_alert:
        if not any(
            normalize_text(value)
            for value in [title, pickup_city, delivery_city, cargo_type, equipment]
        ):
            show_notice(
                "warning",
                "Critere manquant",
                "Ajoutez au moins un critere pour creer une alerte utile.",
            )
        else:
            alert = create_carrier_alert_record(
                {
                    "carrierAccountId": carrier_account_id,
                    "carrierName": st.session_state.carrier_profile["transportCompany"],
                    "title": normalize_text(title) or "Alerte transporteur",
                    "pickupCity": normalize_text(pickup_city),
                    "deliveryCity": normalize_text(delivery_city),
                    "cargoType": normalize_text(cargo_type),
                    "equipment": normalize_text(equipment),
                    "isActive": True,
                }
            )
            current_matches = sum(
                1 for announcement in get_active_announcements() if alert_matches_announcement(alert, announcement)
            )
            show_notice(
                "success",
                "Alerte enregistree",
                f"Votre alerte est active. {current_matches} annonce(s) active(s) correspondent deja a ces criteres.",
            )

    alerts = list_carrier_alerts(carrier_account_id)
    if not alerts:
        show_notice(
            "info",
            "Aucune alerte enregistree",
            "Créez une alerte pour etre averti quand une nouvelle annonce correspond a votre equipement ou a vos regions.",
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    for alert in alerts:
        matches_count = sum(
            1 for announcement in get_active_announcements() if alert_matches_announcement(alert, announcement)
        )
        label_parts = [
            alert["pickupCity"] or "Tous chargements",
            alert["deliveryCity"] or "Toutes livraisons",
            alert["cargoType"] or "Toute marchandise",
            alert["equipment"] or "Tout equipement",
        ]
        st.markdown(
            f"""
            <div class="result-card">
              <div style="display:flex;justify-content:space-between;gap:1rem;align-items:flex-start;">
                <div>
                  <div class="section-title" style="font-size:1.05rem;margin-top:0;">{alert['title']}</div>
                  <div class="small-copy">{' • '.join(label_parts)}<br>{matches_count} annonce(s) active(s) correspond(ent) actuellement.</div>
                </div>
                <div class="status-pill">Active</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Supprimer cette alerte", key=f"delete-alert-{alert['id']}", use_container_width=True):
            delete_carrier_alert_record(alert["id"])
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def process_account_verification(
    account_id: str,
    *,
    verification_status: str,
) -> tuple[bool, str]:
    account = get_account_by_id(account_id)
    if not account:
        return False, "Compte introuvable."

    updated_account = update_account_verification_record(
        account_id,
        verification_status=verification_status,
    )
    current_account = st.session_state.current_account or {}
    if normalize_text(current_account.get("id")) == updated_account["id"]:
        st.session_state.current_account = updated_account
        apply_account_to_profile(updated_account, sync_widget_state=False)

    if verification_status == VERIFICATION_VERIFIED:
        add_notification(
            recipient_role=updated_account["role"],
            recipient_name=updated_account["businessName"],
            recipient_account_id=updated_account["id"],
            title="Compte verifie",
            message=(
                f"Votre compte {get_role_label(updated_account['role'])} a ete verifie "
                "par l'administration de LoadSearch."
            ),
        )
        return_message = "Le compte a ete verifie."
    else:
        add_notification(
            recipient_role=updated_account["role"],
            recipient_name=updated_account["businessName"],
            recipient_account_id=updated_account["id"],
            title="Verification retiree",
            message=(
                f"Votre compte {get_role_label(updated_account['role'])} est revenu "
                "en attente de verification administrative."
            ),
        )
        return_message = "Le compte est repasse en attente de verification."

    load_persisted_data_into_session()
    return True, return_message


def render_admin_account_card(account: dict[str, Any]) -> None:
    role_label = "Entreprise" if account["role"] == "company" else "Transporteur"
    status_html = build_verification_badge_html(account)
    verified_at = normalize_text(account.get("verifiedAt"))
    account_label = account["legalName"] if account["role"] == "company" else account["transportCompany"]
    st.markdown(
        f"""
        <div class="result-card">
          <div style="display:flex;justify-content:space-between;gap:1rem;align-items:flex-start;">
            <div>
              <div class="section-title" style="font-size:1.15rem;margin-top:0;">{account_label}</div>
              <div class="small-copy">
                Type de compte: <strong>{role_label}</strong><br>
                Responsable: <strong>{account['contactName'] or 'Non renseigne'}</strong><br>
                Courriel: {account['email'] or 'Non renseigne'}<br>
                Telephone: {account['phone'] or 'Non renseigne'}<br>
                Numero d'entreprise: <strong>{account['businessNumber'] or 'Non renseigne'}</strong><br>
                Derniere verification: <strong>{verified_at or 'Jamais'}</strong>
              </div>
            </div>
            <div>{status_html}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    details_col1, details_col2 = st.columns(2)
    with details_col1:
        if account["role"] == "company":
            st.caption("Ville")
            st.write(account.get("city") or "Non renseignee")
            st.caption("Province")
            st.write(account.get("province") or "Non renseignee")
            st.caption("Secteur d'activite")
            st.write(account.get("industry") or "Non renseigne")
        else:
            st.caption("Numero d'assurance")
            st.write(account.get("insuranceNumber") or "Non renseigne")
            st.caption("Nombre de camions")
            st.write(account.get("fleetSize") or "Non renseigne")
            st.caption("Regions desservies")
            st.write(account.get("regions") or "Non renseignees")
    with details_col2:
        if account["role"] == "carrier":
            st.caption("Equipements")
            equipment_html = " ".join(
                f"<span class='status-pill'>{item}</span>"
                for item in (account.get("equipmentTypes") or [])
            )
            st.markdown(
                equipment_html or "<div class='small-copy'>Aucun equipement renseigne.</div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("Evaluation publique")
            render_public_rating_summary(
                account["id"],
                empty_message="Aucune evaluation publique pour cette entreprise.",
            )

    st.caption("Documents de profil")
    render_documents_for_owner(
        "company_profile" if account["role"] == "company" else "carrier_profile",
        account["id"],
        empty_message="Aucun document de profil ajoute.",
    )

    action_cols = st.columns(2)
    if is_account_verified(account):
        with action_cols[0]:
            if st.button(
                f"Retirer la verification - {account['id']}",
                key=f"admin-pending-{account['id']}",
                use_container_width=True,
            ):
                ok, message = process_account_verification(
                    account["id"],
                    verification_status=VERIFICATION_PENDING,
                )
                if ok:
                    st.success(message)
                    st.rerun()
                st.error(message)
    else:
        with action_cols[0]:
            if st.button(
                f"Verifier ce compte - {account['id']}",
                key=f"admin-verify-{account['id']}",
                type="primary",
                use_container_width=True,
            ):
                ok, message = process_account_verification(
                    account["id"],
                    verification_status=VERIFICATION_VERIFIED,
                )
                if ok:
                    st.success(message)
                    st.rerun()
                st.error(message)


def render_admin_accounts_section(accounts: list[dict[str, Any]], *, role: str) -> None:
    sorted_accounts = sorted(
        accounts,
        key=lambda item: (
            0 if get_verification_status(item) == VERIFICATION_PENDING else 1,
            normalize_for_match(item.get("businessName")),
        ),
    )
    if not sorted_accounts:
        role_label = "entreprise" if role == "company" else "transporteur"
        show_notice(
            "info",
            "Aucun compte a verifier",
            f"Aucun compte {role_label} n'a encore ete cree.",
        )
        return

    for account in sorted_accounts:
        render_admin_account_card(account)


def render_admin_dashboard() -> None:
    if not can_current_account_access_admin():
        show_notice(
            "error",
            "Acces refuse",
            "Cet espace est reserve au proprietaire de l'application.",
        )
        return

    company_accounts = list_accounts_by_role("company")
    carrier_accounts = list_accounts_by_role("carrier")
    pending_companies = sum(
        1 for account in company_accounts if get_verification_status(account) == VERIFICATION_PENDING
    )
    pending_carriers = sum(
        1 for account in carrier_accounts if get_verification_status(account) == VERIFICATION_PENDING
    )
    verified_total = sum(
        1
        for account in company_accounts + carrier_accounts
        if get_verification_status(account) == VERIFICATION_VERIFIED
    )

    metrics = st.columns(3)
    for column, label, value in [
        (metrics[0], "Entreprises en attente", pending_companies),
        (metrics[1], "Transporteurs en attente", pending_carriers),
        (metrics[2], "Comptes verifies", verified_total),
    ]:
        with column:
            st.markdown(
                f"""
                <div class="metric-card">
                  <div class="metric-label">{label}</div>
                  <div class="metric-value">{value}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Admin</span>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Verification des comptes</div>", unsafe_allow_html=True)
    st.markdown(
        "<p class='small-copy'>Revoyez les entreprises et transporteurs, consultez leurs informations de profil et leurs documents, puis approuvez ou retirez leur verification.</p>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    company_tab, carrier_tab = st.tabs(["Entreprises", "Transporteurs"])
    with company_tab:
        render_admin_accounts_section(company_accounts, role="company")
    with carrier_tab:
        render_admin_accounts_section(carrier_accounts, role="carrier")

def render_top_bar() -> None:
    if st.session_state.active_role is None:
        st.markdown(
            f"""
            <div class="top-shell" style="text-align:center;">
              <div class="brand-title">{APP_NAME}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    col1, col2 = st.columns([2.2, 1.2], vertical_alignment="center")
    with col1:
        st.markdown(
            f"""
            <div class="top-shell">
              <div class="brand-title">{APP_NAME}</div>
              <div class="brand-copy">Marketplace logistique pour PME et petits transporteurs, avec aide a la creation d'annonces et au matching.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        current_space = (
            "Accueil"
            if not st.session_state.active_role
            else ("Espace entreprise" if st.session_state.active_role == "company" else "Espace transporteur")
        )
        st.markdown(f"<div class='status-pill'>{current_space}</div>", unsafe_allow_html=True)
        if st.button("Retour à l'accueil", use_container_width=True):
            st.session_state.active_role = None
            st.rerun()
        if st.button("Se déconnecter", use_container_width=True, key="topbar-signout"):
            sign_out()
            st.rerun()
        if st.button("Réinitialiser la démo", use_container_width=True):
            reset_demo_data()
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()


def render_landing_contact() -> None:
    st.markdown(
        """
        <div class="contact-bar">
          <strong class="contact-title">Nous contacter</strong>
          <div class="contact-detail">
            <span>Courriel</span><br>
            <strong>willgagne30@gmail.com</strong>
          </div>
          <br>
          <div class="contact-detail">
            <span>Téléphone</span><br>
            <strong>418-222-8684</strong>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_privacy_footer() -> None:
    st.markdown(
        """
        <div class="policy-footer">
          En utilisant LoadSearch, vous acceptez que les renseignements nécessaires à la gestion
          de votre compte, de votre profil et des mises en relation soient utilisés de façon
          confidentielle dans le cadre du service.
          <br>
          <a class="policy-link" href="?legal=privacy" target="_self">Lire la politique de confidentialité</a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_privacy_policy_page() -> None:
    st.markdown(
        """
        <div class="landing-shell">
          <div class="landing-hero" style="text-align:left;">
            <span class="eyebrow">Confidentialité</span>
            <div class="section-title" style="font-size:2.3rem;margin-top:1rem;">Politique de confidentialité</div>
            <p class="landing-description" style="max-width:none;margin:0;color:#c3d2e7;">
              Cette page présente une version sommaire de la politique de confidentialité de LoadSearch
              pour l'utilisation actuelle de l'application.
            </p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="margin:1rem 0 1.4rem;"><a class="policy-link" href="?" target="_self">Retour à l’application</a></div>',
        unsafe_allow_html=True,
    )

    st.markdown("**Renseignements recueillis**")
    st.markdown(
        "LoadSearch peut recueillir les renseignements nécessaires à la création et à la gestion des comptes, "
        "des profils, des annonces et des mises en relation. Cela peut inclure le nom, le courriel, le numéro "
        "de téléphone, le numéro d’entreprise et, pour les transporteurs, le numéro de contrat ou de certificat d’assurance."
    )

    st.markdown("**Utilisation des renseignements**")
    st.markdown(
        "Ces renseignements servent à authentifier les utilisateurs, afficher les profils pertinents, faciliter "
        "les propositions de transport et communiquer avec les parties concernées dans le cadre du service."
    )

    st.markdown("**Protection et accès**")
    st.markdown(
        "LoadSearch applique des mesures raisonnables pour limiter l’accès aux renseignements et en protéger la "
        "confidentialité. Vous pouvez demander l’accès ou la correction de vos renseignements en écrivant à "
        "`willgagne30@gmail.com`."
    )

    st.markdown("**Conservation**")
    st.markdown(
        "Les renseignements sont conservés aussi longtemps que nécessaire au fonctionnement du service ou au respect "
        "des obligations applicables."
    )

    st.markdown("**Important**")
    st.markdown(
        "Cette version est une politique sommaire adaptée au prototype actuel. Une politique complète devrait être "
        "validée avant un déploiement public."
    )


def render_landing_auth_actions() -> None:
    account = st.session_state.current_account
    st.markdown("<div class='auth-action-bar'>", unsafe_allow_html=True)
    if account:
        st.markdown(
            f"""
            <div class="auth-state">
              Connecté comme <strong>{account['businessName']}</strong>
              ({get_role_label(account['role'])}).
            </div>
            """,
            unsafe_allow_html=True,
        )
        action_cols = st.columns(2)
        with action_cols[0]:
            if st.button("Continuer", type="primary", use_container_width=True):
                continue_as_role(account["role"])
        with action_cols[1]:
            if st.button("Se déconnecter", use_container_width=True):
                sign_out()
                st.rerun()
    else:
        action_cols = st.columns(2)
        with action_cols[0]:
            if st.button("Connexion", use_container_width=True):
                st.session_state.auth_view = "login"
                st.session_state.auth_message = ""
                st.rerun()
        with action_cols[1]:
            if st.button("S'inscrire", use_container_width=True):
                st.session_state.auth_view = "signup_choice"
                st.session_state.auth_message = ""
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_signup_choice() -> None:
    st.markdown("<div class='auth-panel'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Inscription</span>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Choisissez le type de compte</div>", unsafe_allow_html=True)
    st.markdown(
        "<p class='small-copy'>Le type de compte détermine l'interface à laquelle vous aurez accès.</p>",
        unsafe_allow_html=True,
    )
    choice_cols = st.columns(2)
    with choice_cols[0]:
        if st.button("Créer un compte entreprise", type="primary", use_container_width=True):
            st.session_state.auth_view = "signup_company"
            st.session_state.pending_role = "company"
            st.rerun()
    with choice_cols[1]:
        if st.button("Créer un compte transporteur", use_container_width=True):
            st.session_state.auth_view = "signup_carrier"
            st.session_state.pending_role = "carrier"
            st.rerun()
    if st.button("Retour à l'accueil", use_container_width=True, key="signup-choice-back"):
        st.session_state.auth_view = "landing"
        st.session_state.auth_message = ""
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_login_panel() -> None:
    st.markdown("<div class='auth-panel'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Connexion</span>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Connectez-vous pour continuer</div>", unsafe_allow_html=True)

    with st.form("login_form"):
        email = st.text_input("Courriel", key="login_email")
        password = st.text_input("Mot de passe", type="password", key="login_password")
        submit = st.form_submit_button("Se connecter", type="primary", use_container_width=True)

    if submit:
        user_row = get_user_row_by_email(email)
        account = serialize_account_row(user_row)
        if not user_row or not verify_password(password, str(user_row["password_hash"])):
            show_notice("error", "Connexion impossible", "Le courriel ou le mot de passe est incorrect.")
        else:
            st.session_state.current_account = account
            st.session_state.auth_view = "landing"
            st.session_state.auth_message = ""
            apply_account_to_profile(account)
            st.session_state.active_role = account["role"]
            st.rerun()

    action_cols = st.columns(2)
    with action_cols[0]:
        if st.button("Créer un compte", use_container_width=True, key="login-create-account"):
            st.session_state.auth_view = "signup_choice"
            st.rerun()
    with action_cols[1]:
        if st.button("Retour", use_container_width=True, key="login-back-home"):
            st.session_state.auth_view = "landing"
            st.session_state.auth_message = ""
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_signup_panel(role: str) -> None:
    role_label = get_role_label(role)
    business_label = "Nom de l'entreprise" if role == "company" else "Nom de la compagnie de transport"

    st.markdown("<div class='auth-panel'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Inscription</span>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='section-title'>Créer un compte {role_label}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p class='small-copy'>Après l'inscription, vous devrez compléter votre profil avant d'utiliser l'application.</p>",
        unsafe_allow_html=True,
    )

    with st.form(f"signup_{role}_form"):
        business_name = st.text_input(business_label, key=f"signup_{role}_business")
        contact_name = st.text_input("Nom du responsable", key=f"signup_{role}_contact")
        email = st.text_input("Courriel", key=f"signup_{role}_email")
        phone = st.text_input("Téléphone", key=f"signup_{role}_phone")
        insurance_number = ""
        if role == "carrier":
            insurance_number = st.text_input(
                "Numero du certificat ou contrat d'assurance",
                key=f"signup_{role}_insuranceNumber",
            )
        password = st.text_input("Mot de passe", type="password", key=f"signup_{role}_password")
        confirm_password = st.text_input(
            "Confirmer le mot de passe",
            type="password",
            key=f"signup_{role}_confirm_password",
        )
        submit = st.form_submit_button("Créer mon compte", type="primary", use_container_width=True)

    if submit:
        required_values = [business_name, contact_name, email, phone, password, confirm_password]
        if role == "carrier":
            required_values.append(insurance_number)
        if not all(normalize_text(value) for value in required_values):
            show_notice("warning", "Champs manquants", "Veuillez remplir tous les champs pour créer le compte.")
        elif password != confirm_password:
            show_notice("error", "Mot de passe différent", "La confirmation ne correspond pas au mot de passe.")
        elif find_account_by_email(email):
            show_notice("warning", "Compte déjà existant", "Un compte existe déjà avec ce courriel. Utilisez la connexion.")
        else:
            try:
                account = create_account_record(
                    role=role,
                    business_name=business_name,
                    contact_name=contact_name,
                    email=email,
                    phone=phone,
                    password=password,
                    insurance_number=insurance_number,
                )
                st.session_state.current_account = account
                st.session_state.auth_view = "landing"
                st.session_state.auth_message = ""
                apply_account_to_profile(account)
                st.session_state.active_role = role
                st.rerun()
            except sqlite3.IntegrityError:
                show_notice(
                    "warning",
                    "Courriel déjà utilisé",
                    "Cette adresse courriel est déjà utilisée par un autre compte.",
                )

    action_cols = st.columns(2)
    with action_cols[0]:
        if st.button("Déjà inscrit? Connexion", use_container_width=True, key=f"signup-login-{role}"):
            st.session_state.auth_view = "login"
            st.rerun()
    with action_cols[1]:
        if st.button("Retour", use_container_width=True, key=f"signup-back-{role}"):
            st.session_state.auth_view = "landing"
            st.session_state.auth_message = ""
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_landing() -> None:
    st.markdown(
        """
        <div class="landing-shell">
          <div class="landing-hero">
            <span class="eyebrow">Transport local et régional</span>
            <div class="landing-title">Trouver un voyage. Trouver un transporteur.</div>
            <p class="landing-description">
              LoadSearch met en relation les entreprises qui ont des produits à transporter
              avec de petits transporteurs à la recherche de voyages adaptés à leur équipement.
            </p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_landing_auth_actions()
    if st.session_state.auth_message:
        show_notice("info", "Accès", st.session_state.auth_message)

    auth_view = st.session_state.auth_view
    if auth_view == "login":
        render_login_panel()
        render_landing_contact()
        return
    if auth_view == "signup_choice":
        render_signup_choice()
        render_landing_contact()
        return
    if auth_view == "signup_company":
        render_signup_panel("company")
        render_landing_contact()
        return
    if auth_view == "signup_carrier":
        render_signup_panel("carrier")
        render_landing_contact()
        return

    choice_cols = st.columns(2, gap="large")
    with choice_cols[0]:
        st.markdown(
            """
            <div class="choice-card">
              <div class="choice-title">Entreprise</div>
              <div class="small-copy">Publiez vos voyages disponibles et recevez des propositions de transporteurs qualifiés.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button(
            "Je suis une entreprise",
            type="primary",
            use_container_width=True,
            key="landing_company_choice",
        ):
            continue_as_role("company")

    with choice_cols[1]:
        st.markdown(
            """
            <div class="choice-card">
              <div class="choice-title">Transporteur</div>
              <div class="small-copy">Repérez les trajets disponibles sur la carte et proposez votre service aux entreprises.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Je suis un transporteur", use_container_width=True, key="landing_carrier_choice"):
            continue_as_role("carrier")

    render_landing_contact()


def render_company_profile(*, edit_mode: bool = False) -> None:
    st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
    current_account = st.session_state.current_account
    if edit_mode:
        st.markdown("<span class='eyebrow'>Profil</span>", unsafe_allow_html=True)
        st.markdown("<div class='section-title'>Modifier votre profil entreprise</div>", unsafe_allow_html=True)
        st.markdown(
            "<p class='small-copy'>Mettez a jour vos informations d'entreprise et vos documents quand necessaire.</p>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown("<span class='eyebrow'>Etape 1</span>", unsafe_allow_html=True)
        st.markdown("<div class='section-title'>Completer votre profil entreprise</div>", unsafe_allow_html=True)
        st.markdown(
            "<p class='small-copy'>Tant que ce profil n'est pas rempli, vous ne pouvez pas publier d'annonce.</p>",
            unsafe_allow_html=True,
        )
    if current_account and current_account.get("role") == "company":
        render_verification_notice(current_account, owner_label="Compte entreprise")

    form_key = "company_profile_form_edit" if edit_mode else "company_profile_form"
    submit_label = "Enregistrer les modifications" if edit_mode else "Enregistrer le profil et continuer"

    with st.form(form_key):
        col1, col2 = st.columns(2)
        with col1:
            st.text_input("Nom legal de l'entreprise", key="company_legalName")
            st.text_input("Nom du responsable", key="company_contactName")
            st.text_input("Telephone", key="company_phone")
            st.text_input("Ville", key="company_city")
        with col2:
            st.text_input("Numero d'entreprise", key="company_businessNumber")
            st.text_input("Courriel", key="company_email")
            st.selectbox(
                "Province",
                options=[""] + PROVINCE_OPTIONS,
                key="company_province",
            )
            st.text_input("Secteur d'activite", key="company_industry")
        company_profile_docs = st.file_uploader(
            "Documents facultatifs de l'entreprise",
            accept_multiple_files=True,
            key="company_profile_docs_edit" if edit_mode else "company_profile_docs",
            help="Exemple: preuve d'entreprise ou document interne utile.",
        )
        submitted = st.form_submit_button(submit_label, type="primary")

    if submitted:
        company_profile = {
            "legalName": st.session_state.company_legalName,
            "businessNumber": st.session_state.company_businessNumber,
            "contactName": st.session_state.company_contactName,
            "email": st.session_state.company_email,
            "phone": st.session_state.company_phone,
            "city": st.session_state.company_city,
            "province": st.session_state.company_province,
            "industry": st.session_state.company_industry,
        }
        if not st.session_state.current_account:
            show_notice("error", "Session invalide", "Reconnectez-vous pour enregistrer ce profil.")
        else:
            try:
                account = update_company_profile_record(
                    st.session_state.current_account["id"],
                    company_profile,
                )
                save_uploaded_documents(
                    company_profile_docs,
                    owner_type="company_profile",
                    owner_id=account["id"],
                    account_id=account["id"],
                    role="company",
                    description="Document de profil entreprise",
                )
                st.session_state.current_account = account
                apply_account_to_profile(account, sync_widget_state=False)
                st.rerun()
            except sqlite3.IntegrityError:
                show_notice(
                    "warning",
                    "Courriel déjà utilisé",
                    "Cette adresse courriel est déjà utilisée par un autre compte.",
                )

    st.markdown("</div>", unsafe_allow_html=True)
    if st.session_state.current_account:
        render_documents_for_owner(
            "company_profile",
            st.session_state.current_account["id"],
            empty_message="Aucun document de profil entreprise.",
        )


def render_carrier_profile(*, edit_mode: bool = False) -> None:
    st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
    current_account = st.session_state.current_account
    if edit_mode:
        st.markdown("<span class='eyebrow'>Profil</span>", unsafe_allow_html=True)
        st.markdown("<div class='section-title'>Modifier votre profil transporteur</div>", unsafe_allow_html=True)
        st.markdown(
            "<p class='small-copy'>Mettez a jour votre flotte, vos equipements et vos documents au besoin.</p>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown("<span class='eyebrow'>Etape 1</span>", unsafe_allow_html=True)
        st.markdown("<div class='section-title'>Completer votre profil transporteur</div>", unsafe_allow_html=True)
        st.markdown(
            "<p class='small-copy'>Tant que ce profil n'est pas rempli, vous ne pouvez pas chercher des voyages.</p>",
            unsafe_allow_html=True,
        )
    if current_account and current_account.get("role") == "carrier":
        render_verification_notice(current_account, owner_label="Compte transporteur")

    form_key = "carrier_profile_form_edit" if edit_mode else "carrier_profile_form"
    submit_label = "Enregistrer les modifications" if edit_mode else "Enregistrer le profil et continuer"

    with st.form(form_key):
        col1, col2 = st.columns(2)
        with col1:
            st.text_input("Nom de la compagnie de transport", key="carrier_transportCompany")
            st.text_input("Nom du responsable", key="carrier_contactName")
            st.text_input("Telephone", key="carrier_phone")
            st.number_input("Nombre de camions", min_value=1, max_value=4, step=1, key="carrier_fleetSize")
        with col2:
            st.text_input("Numero d'entreprise", key="carrier_businessNumber")
            st.text_input(
                "Numero du certificat ou contrat d'assurance",
                key="carrier_insuranceNumber",
            )
            st.text_input("Courriel", key="carrier_email")
            st.text_input("Regions desservies", key="carrier_regions")
            st.multiselect("Equipements disponibles", EQUIPMENT_OPTIONS, key="carrier_equipmentTypes")
        carrier_profile_docs = st.file_uploader(
            "Documents facultatifs du transporteur",
            accept_multiple_files=True,
            key="carrier_profile_docs_edit" if edit_mode else "carrier_profile_docs",
            help="Exemple: certificat d'assurance, preuve d'entreprise ou autres justificatifs.",
        )
        submitted = st.form_submit_button(submit_label, type="primary")

    if submitted:
        carrier_profile = {
            "transportCompany": st.session_state.carrier_transportCompany,
            "businessNumber": st.session_state.carrier_businessNumber,
            "insuranceNumber": st.session_state.carrier_insuranceNumber,
            "contactName": st.session_state.carrier_contactName,
            "email": st.session_state.carrier_email,
            "phone": st.session_state.carrier_phone,
            "fleetSize": int(st.session_state.carrier_fleetSize),
            "regions": st.session_state.carrier_regions,
            "equipmentTypes": st.session_state.carrier_equipmentTypes,
        }
        if not st.session_state.current_account:
            show_notice("error", "Session invalide", "Reconnectez-vous pour enregistrer ce profil.")
        else:
            try:
                account = update_carrier_profile_record(
                    st.session_state.current_account["id"],
                    carrier_profile,
                )
                save_uploaded_documents(
                    carrier_profile_docs,
                    owner_type="carrier_profile",
                    owner_id=account["id"],
                    account_id=account["id"],
                    role="carrier",
                    description="Document de profil transporteur",
                )
                st.session_state.current_account = account
                apply_account_to_profile(account, sync_widget_state=False)
                st.rerun()
            except sqlite3.IntegrityError:
                show_notice(
                    "warning",
                    "Courriel déjà utilisé",
                    "Cette adresse courriel est déjà utilisée par un autre compte.",
                )

    st.markdown("</div>", unsafe_allow_html=True)
    if st.session_state.current_account:
        render_documents_for_owner(
            "carrier_profile",
            st.session_state.current_account["id"],
            empty_message="Aucun document de profil transporteur.",
        )


def render_company_dashboard() -> None:
    render_verification_notice(
        st.session_state.current_account,
        owner_label="Compte entreprise",
    )
    company_announcements = get_company_announcements()
    active_count = sum(1 for item in company_announcements if is_announcement_active(item))
    complete_count = sum(
        1
        for item in company_announcements
        if is_announcement_expired(item) or int(item["remainingTrips"]) == 0
    )
    remaining_total = sum(
        int(item["remainingTrips"]) for item in company_announcements if is_announcement_active(item)
    )

    metrics = st.columns(3)
    for column, label, value in [
        (metrics[0], "Annonces actives", active_count),
        (metrics[1], "Voyages restants", remaining_total),
        (metrics[2], "Annonces completees", complete_count),
    ]:
        with column:
            st.markdown(
                f"""
                <div class="metric-card">
                  <div class="metric-label">{label}</div>
                  <div class="metric-value">{value}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    render_market_map(
        get_company_active_announcements(),
        title="Carte de vos annonces actives",
        subtitle="Cette carte affiche seulement les trajets publies par votre entreprise qui ont encore des voyages disponibles.",
        key="company-market-map",
    )

    with st.expander("Modifier mon profil entreprise", expanded=False):
        render_company_profile(edit_mode=True)

    left_col, right_col = st.columns([1.05, 0.95], gap="large")

    with left_col:
        company_assistant()
        render_announcement_form()
        render_company_requests_panel()

    with right_col:
        render_notifications_panel(
            get_current_company_notifications(),
            title="Alertes entreprise",
            empty_message="Les nouvelles propositions transporteurs apparaitront ici.",
        )
        st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
        st.markdown("<span class='eyebrow'>Vos annonces</span>", unsafe_allow_html=True)
        st.markdown("<div class='section-title'>Activite recente</div>", unsafe_allow_html=True)
        if not company_announcements:
            show_notice(
                "info",
                "Encore aucune annonce",
                "La premiere annonce creee ici apparaitra aussi dans l'espace transporteur si des voyages restent disponibles.",
            )
        for announcement in reversed(company_announcements):
            render_company_announcement_card(announcement)
        st.markdown("</div>", unsafe_allow_html=True)


def render_announcement_form() -> None:
    st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Nouvelle annonce</span>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Creer un besoin de transport</div>", unsafe_allow_html=True)
    current_account = st.session_state.current_account or {}
    publish_allowed = is_account_verified(current_account) or is_owner_admin_account(current_account)
    if not publish_allowed:
        show_notice(
            "warning",
            "Verification requise",
            "Votre entreprise doit etre verifiee par l'administration avant de publier une annonce.",
        )

    cargo_options = [""] + SUGGESTED_CARGO_OPTIONS + [OTHER_CARGO_VALUE]
    cargo_labels = {
        "": "Choisir",
        OTHER_CARGO_VALUE: "Autres (precisez)",
    }

    with st.form("announcement_form"):
        st.text_input("Titre de l'annonce", key="announcement_title")

        st.caption("Chargement")
        pickup_cols = st.columns([1.7, 1.1, 0.9])
        with pickup_cols[0]:
            st.text_input(
                "Adresse de chargement",
                key="announcement_pickupAddress",
                help="Exemple: 1250 rang Saint-Joseph",
            )
        with pickup_cols[1]:
            st.text_input(
                "Ville de chargement",
                key="announcement_pickupCity",
                help="Exemple: Saint-Aurelie",
            )
        with pickup_cols[2]:
            st.text_input(
                "Code postal de chargement",
                key="announcement_pickupPostalCode",
                help="Exemple: G0M 1R0",
            )

        st.caption("Livraison")
        delivery_cols = st.columns([1.7, 1.1, 0.9])
        with delivery_cols[0]:
            st.text_input(
                "Adresse de livraison",
                key="announcement_deliveryAddress",
                help="Exemple: 12 Industrial Park Road",
            )
        with delivery_cols[1]:
            st.text_input(
                "Ville de livraison",
                key="announcement_deliveryCity",
                help="Exemple: Boston",
            )
        with delivery_cols[2]:
            st.text_input(
                "Code postal de livraison",
                key="announcement_deliveryPostalCode",
                help="Exemple: 02110",
            )

        detail_cols = st.columns(2)
        with detail_cols[0]:
            st.selectbox(
                "Type de marchandise",
                options=cargo_options,
                format_func=lambda value: cargo_labels.get(value, value),
                key="announcement_cargoType",
            )
            if st.session_state.announcement_cargoType == OTHER_CARGO_VALUE:
                st.text_input("Precisez la marchandise", key="announcement_cargoTypeOther")
            st.selectbox(
                "Equipement requis",
                options=[""] + EQUIPMENT_OPTIONS,
                key="announcement_equipment",
            )
            st.number_input("Nombre de voyages disponibles", min_value=1, step=1, key="announcement_tripsTotal")
        with detail_cols[1]:
            st.date_input("Date de chargement", key="announcement_loadingDate")
            st.date_input("Date de livraison", key="announcement_deliveryDate")
            st.number_input("Prix/voyage (CAD)", min_value=0, step=50, key="announcement_budget")

        st.text_area("Consignes speciales", key="announcement_notes", height=110)
        announcement_documents = st.file_uploader(
            "Documents facultatifs lies a l'annonce",
            accept_multiple_files=True,
            key="announcement_documents",
            help="Exemple: photo, bon de commande ou consignes supplementaires.",
        )

        action_col1, action_col2 = st.columns(2)
        with action_col1:
            publish = st.form_submit_button("Publier l'annonce", type="primary", use_container_width=True)
        with action_col2:
            clear = st.form_submit_button("Vider le brouillon", use_container_width=True)

    if clear:
        st.session_state.draft_announcement = create_empty_draft()
        st.session_state.sync_draft_widgets = True
        st.rerun()

    if publish:
        cargo_value = (
            st.session_state.announcement_cargoTypeOther
            if st.session_state.announcement_cargoType == OTHER_CARGO_VALUE
            else st.session_state.announcement_cargoType
        )
        if not all(
            [
                normalize_text(st.session_state.announcement_title),
                normalize_text(st.session_state.announcement_pickupAddress),
                normalize_text(st.session_state.announcement_pickupCity),
                normalize_text(st.session_state.announcement_pickupPostalCode),
                normalize_text(st.session_state.announcement_deliveryAddress),
                normalize_text(st.session_state.announcement_deliveryCity),
                normalize_text(st.session_state.announcement_deliveryPostalCode),
                normalize_text(cargo_value),
                normalize_text(st.session_state.announcement_equipment),
                st.session_state.announcement_loadingDate,
                st.session_state.announcement_deliveryDate,
            ]
        ):
            show_notice("warning", "Champs manquants", "Completer les champs obligatoires avant de publier.")
        elif not st.session_state.current_account:
            show_notice("error", "Session invalide", "Reconnectez-vous pour publier une annonce.")
        elif not publish_allowed:
            show_notice(
                "error",
                "Compte non verifie",
                "L'administration doit verifier votre entreprise avant la publication d'annonces.",
            )
        else:
            announcement = {
                "id": f"user-{datetime.now().timestamp()}",
                "companyAccountId": st.session_state.current_account["id"],
                "title": normalize_text(st.session_state.announcement_title),
                "pickupAddress": normalize_text(st.session_state.announcement_pickupAddress),
                "pickupCity": normalize_text(st.session_state.announcement_pickupCity),
                "pickupPostalCode": normalize_text(st.session_state.announcement_pickupPostalCode),
                "deliveryAddress": normalize_text(st.session_state.announcement_deliveryAddress),
                "deliveryCity": normalize_text(st.session_state.announcement_deliveryCity),
                "deliveryPostalCode": normalize_text(st.session_state.announcement_deliveryPostalCode),
                "cargoType": normalize_text(cargo_value),
                "equipment": normalize_text(st.session_state.announcement_equipment),
                "loadingDate": st.session_state.announcement_loadingDate.isoformat(),
                "deliveryDate": st.session_state.announcement_deliveryDate.isoformat(),
                "tripsTotal": int(st.session_state.announcement_tripsTotal),
                "remainingTrips": int(st.session_state.announcement_tripsTotal),
                "budget": int(st.session_state.announcement_budget),
                "expiredAt": "",
                "notes": normalize_text(st.session_state.announcement_notes),
                "companyName": st.session_state.company_profile["legalName"],
            }
            saved_announcement = create_announcement_record(announcement)
            saved_docs = save_uploaded_documents(
                announcement_documents,
                owner_type="announcement",
                owner_id=saved_announcement["id"],
                account_id=st.session_state.current_account["id"],
                role="company",
                description="Document d'annonce",
            )
            alerts_count = notify_matching_carrier_alerts(saved_announcement)
            load_persisted_data_into_session()
            feedback = "Annonce publiee."
            if saved_docs:
                feedback += f" {saved_docs} document(s) ajoute(s)."
            if alerts_count:
                feedback += f" {alerts_count} alerte(s) transporteur notifiee(s)."
            st.session_state.company_ai["assistantMessage"] = feedback
            st.session_state.draft_announcement = create_empty_draft()
            st.session_state.sync_draft_widgets = True
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def render_company_announcement_card(announcement: dict[str, Any]) -> None:
    if is_announcement_expired(announcement):
        status = "Expirée"
    elif int(announcement["remainingTrips"]) > 0:
        status = "Active"
    else:
        status = "Complétée"
    status_class = "status-pill" if status == "Active" else "status-pill ai"
    st.markdown(
        f"""
        <div class="result-card">
          <div style="display:flex;justify-content:space-between;gap:1rem;align-items:flex-start;">
            <div>
              <div class="section-title" style="font-size:1.2rem;margin-top:0;">{announcement['title']}</div>
              <div class="small-copy">{announcement['companyName']}</div>
            </div>
            <div class="{status_class}">{status}</div>
          </div>
          <div class="route-row">{announcement['pickupCity']} -> {announcement['deliveryCity']}</div>
          <div class="small-copy">
            Chargement exact: <strong>{format_exact_location(announcement.get('pickupAddress'), announcement.get('pickupCity'), announcement.get('pickupPostalCode'))}</strong><br>
            Livraison exacte: <strong>{format_exact_location(announcement.get('deliveryAddress'), announcement.get('deliveryCity'), announcement.get('deliveryPostalCode'))}</strong><br>
            Marchandise: <strong>{announcement['cargoType']}</strong><br>
            Equipement: <strong>{announcement['equipment']}</strong><br>
            Livraison: <strong>{format_date(get_delivery_date(announcement))}</strong><br>
            Voyages restants: <strong>{announcement['remainingTrips']} / {announcement['tripsTotal']}</strong><br>
            Prix/voyage: <strong>{format_currency(get_price_per_trip(announcement))}</strong>
          </div>
          <p class="small-copy" style="margin-top:0.8rem;">{announcement['notes'] or 'Aucune consigne speciale ajoutee.'}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander(f"Documents - {announcement['title']}", expanded=False):
        render_documents_for_owner(
            "announcement",
            announcement["id"],
            empty_message="Aucun document lie a cette annonce.",
        )
    button_cols = st.columns(2)
    if is_announcement_active(announcement):
        with button_cols[0]:
            if st.button(f"Attribuer 1 voyage - {announcement['id']}", key=f"assign-1-{announcement['id']}", use_container_width=True):
                update_announcement_record(
                    announcement["id"],
                    remainingTrips=max(0, int(announcement["remainingTrips"]) - 1),
                )
                load_persisted_data_into_session()
                st.rerun()
        with button_cols[1]:
            if announcement["remainingTrips"] >= 2 and st.button(
                f"Attribuer 2 voyages - {announcement['id']}",
                key=f"assign-2-{announcement['id']}",
                use_container_width=True,
            ):
                update_announcement_record(
                    announcement["id"],
                    remainingTrips=max(0, int(announcement["remainingTrips"]) - 2),
                )
                load_persisted_data_into_session()
                st.rerun()


def render_service_proposal_form(announcement: dict[str, Any], form_key: str) -> None:
    with st.form(form_key):
        requested_trips = st.number_input(
            "Nombre de voyages demandes",
            min_value=1,
            max_value=max(1, int(announcement["remainingTrips"])),
            value=1,
            key=f"{form_key}-requested-trips",
        )
        proposal_message = st.text_area(
            "Message pour l'entreprise",
            key=f"{form_key}-message",
            placeholder="Exemple: Je peux prendre ce trajet avec mon flatbed des demain matin.",
            height=90,
        )
        submit_proposal = st.form_submit_button(
            "Envoyer ma proposition",
            type="primary",
            use_container_width=True,
        )

    if submit_proposal:
        ok, message = create_service_request(
            announcement["id"], requested_trips, proposal_message
        )
        if ok:
            st.success(message)
            st.rerun()
        st.error(message)


def render_map_proposal_panel(
    selected_announcement_id: str,
    visible_announcements: list[dict[str, Any]],
) -> None:
    st.markdown("<div class='soft-card map-selection-card'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Trajet selectionne</span>", unsafe_allow_html=True)

    if not visible_announcements:
        show_notice(
            "info",
            "Aucun trajet sur la carte",
            "Ajuste les filtres pour afficher des annonces, puis clique sur un trajet.",
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if not selected_announcement_id:
        show_notice(
            "info",
            "Clique sur la carte",
            "Selectionne un trajet ou un point sur la carte pour proposer ton service a l'entreprise.",
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    announcement = next(
        (item for item in visible_announcements if item["id"] == selected_announcement_id),
        None,
    )
    if not announcement:
        show_notice(
            "warning",
            "Trajet non visible avec ces filtres",
            "Le trajet selectionne n'est plus dans les resultats actuels. Clique sur un autre trajet ou reinitialise les filtres.",
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    local_score = calculate_local_compatibility(
        st.session_state.carrier_profile,
        announcement,
    )
    company_rating_summary = get_public_rating_summary(announcement.get("companyAccountId", ""))
    st.markdown(
        f"""
        <div class="result-card">
          <div style="display:flex;justify-content:space-between;gap:1rem;align-items:flex-start;">
            <div>
              <div class="section-title" style="font-size:1.2rem;margin-top:0;">{announcement['title']}</div>
              <div class="small-copy">{announcement['companyName']}<br>Note publique: <strong>{company_rating_summary['label']}</strong></div>
            </div>
            <div class="status-pill">{announcement['remainingTrips']} voyage(s) restant(s)</div>
          </div>
          <div class="route-row">{announcement['pickupCity']} -> {announcement['deliveryCity']}</div>
          <span class="score-pill score-local">Compatibilite locale {local_score}%</span>
          <div class="small-copy" style="margin-top:0.65rem;">
            Lieu exact de chargement: <strong>{format_exact_location(announcement.get('pickupAddress'), announcement.get('pickupCity'), announcement.get('pickupPostalCode'))}</strong><br>
            Lieu exact de livraison: <strong>{format_exact_location(announcement.get('deliveryAddress'), announcement.get('deliveryCity'), announcement.get('deliveryPostalCode'))}</strong><br>
            Chargement: <strong>{format_date(announcement['loadingDate'])}</strong><br>
            Livraison: <strong>{format_date(get_delivery_date(announcement))}</strong><br>
            Marchandise: <strong>{announcement['cargoType']}</strong><br>
            Equipement: <strong>{announcement['equipment']}</strong><br>
            Prix/voyage: <strong>{format_currency(get_price_per_trip(announcement))}</strong>
          </div>
          <p class="small-copy">{announcement['notes'] or 'Aucune consigne speciale ajoutee.'}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("Evaluation publique de l'entreprise")
    render_public_rating_summary(
        announcement.get("companyAccountId", ""),
        empty_message="Aucune evaluation publique pour cette entreprise pour le moment.",
    )
    with st.expander(
        f"Voir les commentaires publics sur {announcement['companyName']}",
        expanded=False,
    ):
        render_public_reviews(
            announcement.get("companyAccountId", ""),
            empty_message="Aucun commentaire public pour cette entreprise.",
            limit=5,
        )
    st.caption("Documents lies a l'annonce")
    render_documents_for_owner(
        "announcement",
        announcement["id"],
        empty_message="Aucun document joint a cette annonce.",
    )
    render_service_proposal_form(
        announcement,
        form_key=f"map-proposal-form-{announcement['id']}",
    )
    st.markdown("</div>", unsafe_allow_html=True)


def render_carrier_dashboard() -> None:
    render_verification_notice(
        st.session_state.current_account,
        owner_label="Compte transporteur",
    )
    metrics = st.columns(3)
    for column, label, value in [
        (metrics[0], "Camions declares", st.session_state.carrier_profile["fleetSize"]),
        (metrics[1], "Equipements", len(st.session_state.carrier_profile["equipmentTypes"])),
        (metrics[2], "Trajets actifs", len(get_active_announcements())),
    ]:
        with column:
            st.markdown(
                f"""
                <div class="metric-card">
                  <div class="metric-label">{label}</div>
                  <div class="metric-value">{value}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    filtered_announcements = get_filtered_announcements()
    map_key = f"carrier-market-map-{st.session_state.map_selection_version}"
    selected_announcement_id = render_market_map(
        filtered_announcements,
        title="Carte mondiale des annonces visibles",
        subtitle="Clique sur un trajet ou un point pour voir le detail et proposer ton service a l'entreprise.",
        key=map_key,
        selectable=True,
    )

    with st.expander("Modifier mon profil transporteur", expanded=False):
        render_carrier_profile(edit_mode=True)

    if selected_announcement_id:
        current_selection = st.session_state.selected_map_announcement_id
        st.session_state.selected_map_announcement_id = (
            "" if selected_announcement_id == current_selection else selected_announcement_id
        )
        st.session_state.map_selection_version += 1
        st.session_state.ignore_empty_map_selection = True
        st.rerun()
    elif st.session_state.ignore_empty_map_selection:
        st.session_state.ignore_empty_map_selection = False

    render_map_proposal_panel(
        st.session_state.selected_map_announcement_id,
        filtered_announcements,
    )

    left_col, right_col = st.columns([1.02, 0.98], gap="large")

    with left_col:
        carrier_assistant()
        render_filters_panel()
        render_alerts_panel()

    with right_col:
        render_notifications_panel(
            get_current_carrier_notifications(),
            title="Alertes transporteur",
            empty_message="Les decisions des entreprises apparaitront ici.",
        )
        render_carrier_requests_panel()

    with st.expander("Resume de ma flotte", expanded=False):
        profile = st.session_state.carrier_profile
        st.write(f"Regions: {profile['regions'] or 'Non precisees'}")
        st.write(
            "Equipements: "
            + (", ".join(profile["equipmentTypes"]) if profile["equipmentTypes"] else "Aucun")
        )


def render_filters_panel() -> None:
    st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Recherche</span>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Filtrer les annonces</div>", unsafe_allow_html=True)

    filter_cols = st.columns(2)
    with filter_cols[0]:
        st.text_input("Lieu de chargement", key="filter_pickupCity")
        st.selectbox(
            "Marchandise",
            options=[""] + get_cargo_filter_options(),
            format_func=lambda value: "Toutes" if not value else value,
            key="filter_cargoType",
        )
    with filter_cols[1]:
        st.text_input("Lieu de livraison", key="filter_deliveryCity")
        st.selectbox(
            "Equipement requis",
            options=[""] + EQUIPMENT_OPTIONS,
            format_func=lambda value: "Tous" if not value else value,
            key="filter_equipment",
        )
    action_cols = st.columns(2)
    with action_cols[0]:
        if st.button("Appliquer les filtres", type="primary", use_container_width=True):
            st.session_state.filters = {
                "pickupCity": st.session_state.filter_pickupCity,
                "deliveryCity": st.session_state.filter_deliveryCity,
                "cargoType": st.session_state.filter_cargoType,
                "equipment": st.session_state.filter_equipment,
            }
            st.rerun()
    with action_cols[1]:
        if st.button("Reinitialiser", use_container_width=True):
            st.session_state.filters = {
                "pickupCity": "",
                "deliveryCity": "",
                "cargoType": "",
                "equipment": "",
            }
            st.session_state.sync_filter_widgets = True
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def render_carrier_profile_summary() -> None:
    profile = st.session_state.carrier_profile
    st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Votre flotte</span>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Resume du profil</div>", unsafe_allow_html=True)
    st.markdown(
        f"<p class='small-copy'>Regions: {profile['regions']}</p>",
        unsafe_allow_html=True,
    )
    pills = " ".join(
        f"<span class='status-pill'>{item}</span>" for item in profile["equipmentTypes"]
    )
    st.markdown(pills or "<div class='small-copy'>Aucun equipement.</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_carrier_result_card(result: dict[str, Any]) -> None:
    announcement = result["announcement"]
    ai_score = result["aiScore"]
    score_html = f"<span class='score-pill score-local'>Compatibilite locale {result['localScore']}%</span>"
    if ai_score is not None:
        score_html += f"<span class='score-pill score-ai'>Compatibilite assistee {ai_score}%</span>"
    reasoning = (
        f"<p class='small-copy'>{result['aiReasoning']}</p>"
        if result["aiReasoning"]
        else ""
    )
    st.markdown(
        f"""
        <div class="result-card">
          <div style="display:flex;justify-content:space-between;gap:1rem;align-items:flex-start;">
            <div>
              <div class="section-title" style="font-size:1.2rem;margin-top:0;">{announcement['title']}</div>
              <div class="small-copy">{announcement['companyName']}</div>
            </div>
            <div class="status-pill">{announcement['remainingTrips']} voyage(s) restant(s)</div>
          </div>
          <div class="route-row">{announcement['pickupCity']} -> {announcement['deliveryCity']}</div>
          {score_html}
          <div class="small-copy" style="margin-top:0.65rem;">
            Chargement: <strong>{format_date(announcement['loadingDate'])}</strong><br>
            Livraison: <strong>{format_date(get_delivery_date(announcement))}</strong><br>
            Marchandise: <strong>{announcement['cargoType']}</strong><br>
            Equipement: <strong>{announcement['equipment']}</strong><br>
            Prix/voyage: <strong>{format_currency(get_price_per_trip(announcement))}</strong>
          </div>
          {reasoning}
          <p class="small-copy">{announcement['notes'] or 'Aucune consigne speciale ajoutee.'}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander(f"Proposer mon service pour {announcement['title']}", expanded=False):
        with st.form(f"proposal-form-{announcement['id']}"):
            requested_trips = st.number_input(
                "Nombre de voyages demandes",
                min_value=1,
                max_value=max(1, int(announcement["remainingTrips"])),
                value=1,
                key=f"requested-trips-{announcement['id']}",
            )
            proposal_message = st.text_area(
                "Message pour l'entreprise",
                key=f"proposal-message-{announcement['id']}",
                placeholder="Exemple: Je peux prendre ce trajet avec mon flatbed des demain matin.",
                height=90,
            )
            submit_proposal = st.form_submit_button(
                "Envoyer ma proposition",
                type="primary",
                use_container_width=True,
            )

        if submit_proposal:
            ok, message = create_service_request(
                announcement["id"], requested_trips, proposal_message
            )
            if ok:
                st.success(message)
                st.rerun()
            st.error(message)


def render_alerts_panel() -> None:
    st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Alertes</span>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Mes alertes transporteur</div>", unsafe_allow_html=True)

    current_account = st.session_state.current_account or {}
    carrier_account_id = normalize_text(current_account.get("id"))
    if not carrier_account_id:
        show_notice("info", "Connexion requise", "Connectez-vous pour enregistrer des alertes.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    with st.form("carrier_alert_form_compact"):
        title = st.text_input(
            "Nom de l'alerte",
            placeholder="Exemple: Flatbed Quebec -> Maine",
        )
        alert_cols = st.columns(2)
        with alert_cols[0]:
            pickup_city = st.text_input(
                "Chargement contient",
                value=st.session_state.filters["pickupCity"],
            )
            cargo_type = st.selectbox(
                "Marchandise",
                options=[""] + get_cargo_filter_options(),
                format_func=lambda value: "Toutes" if not value else value,
                key="carrier_alert_form_compact_cargoType",
            )
        with alert_cols[1]:
            delivery_city = st.text_input(
                "Livraison contient",
                value=st.session_state.filters["deliveryCity"],
            )
            equipment = st.selectbox(
                "Equipement requis",
                options=[""] + EQUIPMENT_OPTIONS,
                format_func=lambda value: "Tous" if not value else value,
                key="carrier_alert_form_compact_equipment",
            )
        submit_alert = st.form_submit_button("Creer l'alerte", use_container_width=True)

    if submit_alert:
        if not any(
            normalize_text(value)
            for value in [title, pickup_city, delivery_city, cargo_type, equipment]
        ):
            show_notice(
                "warning",
                "Critere manquant",
                "Ajoutez au moins un critere pour creer une alerte utile.",
            )
        else:
            alert = create_carrier_alert_record(
                {
                    "carrierAccountId": carrier_account_id,
                    "carrierName": st.session_state.carrier_profile["transportCompany"],
                    "title": normalize_text(title) or "Alerte transporteur",
                    "pickupCity": normalize_text(pickup_city),
                    "deliveryCity": normalize_text(delivery_city),
                    "cargoType": normalize_text(cargo_type),
                    "equipment": normalize_text(equipment),
                    "isActive": True,
                }
            )
            current_matches = sum(
                1
                for announcement in get_active_announcements()
                if alert_matches_announcement(alert, announcement)
            )
            show_notice(
                "success",
                "Alerte enregistree",
                f"Votre alerte est active. {current_matches} annonce(s) active(s) correspondent deja a ces criteres.",
            )

    alerts = list_carrier_alerts(carrier_account_id)
    if not alerts:
        show_notice(
            "info",
            "Aucune alerte enregistree",
            "Creez une alerte pour etre averti quand une nouvelle annonce correspond a votre equipement ou a vos regions.",
        )
        st.markdown("</div>", unsafe_allow_html=True)
        return

    for alert in alerts:
        matches_count = sum(
            1
            for announcement in get_active_announcements()
            if alert_matches_announcement(alert, announcement)
        )
        label_parts = [
            alert["pickupCity"] or "Tous chargements",
            alert["deliveryCity"] or "Toutes livraisons",
            alert["cargoType"] or "Toute marchandise",
            alert["equipment"] or "Tout equipement",
        ]
        expander_label = f"{alert['title']} | Active | {matches_count} annonce(s)"
        with st.expander(expander_label, expanded=False):
            st.caption("Filtres")
            st.write(" | ".join(label_parts))
            st.caption("Correspondances actuelles")
            st.write(f"{matches_count} annonce(s) active(s) correspondent actuellement.")
            if st.button(
                "Supprimer cette alerte",
                key=f"delete-alert-compact-{alert['id']}",
                use_container_width=True,
            ):
                delete_carrier_alert_record(alert["id"])
                st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def render_company_announcement_card(announcement: dict[str, Any]) -> None:
    status = get_company_announcement_status(announcement)
    summary = (
        f"{announcement['title']} | {status} | "
        f"{announcement['remainingTrips']} / {announcement['tripsTotal']} voyage(s)"
    )

    with st.expander(summary, expanded=False):
        st.markdown(
            f"""
            <div class="small-copy">
              Trajet: <strong>{announcement['pickupCity']} -> {announcement['deliveryCity']}</strong><br>
              Chargement exact: <strong>{format_exact_location(announcement.get('pickupAddress'), announcement.get('pickupCity'), announcement.get('pickupPostalCode'))}</strong><br>
              Livraison exacte: <strong>{format_exact_location(announcement.get('deliveryAddress'), announcement.get('deliveryCity'), announcement.get('deliveryPostalCode'))}</strong><br>
              Marchandise: <strong>{announcement['cargoType']}</strong><br>
              Equipement: <strong>{announcement['equipment']}</strong><br>
              Livraison: <strong>{format_date(get_delivery_date(announcement))}</strong><br>
              Prix/voyage: <strong>{format_currency(get_price_per_trip(announcement))}</strong><br>
              Voyages restants: <strong>{announcement['remainingTrips']} / {announcement['tripsTotal']}</strong>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if normalize_text(announcement.get("notes")):
            st.caption("Consignes")
            st.write(announcement["notes"])
        st.caption("Documents")
        render_documents_for_owner(
            "announcement",
            announcement["id"],
            empty_message="Aucun document lie a cette annonce.",
        )
        if is_announcement_active(announcement):
            button_cols = st.columns(2)
            with button_cols[0]:
                if st.button(
                    f"Attribuer 1 voyage",
                    key=f"assign-1-compact-{announcement['id']}",
                    use_container_width=True,
                ):
                    update_announcement_record(
                        announcement["id"],
                        remainingTrips=max(0, int(announcement["remainingTrips"]) - 1),
                    )
                    load_persisted_data_into_session()
                    st.rerun()
            with button_cols[1]:
                if announcement["remainingTrips"] >= 2 and st.button(
                    "Attribuer 2 voyages",
                    key=f"assign-2-compact-{announcement['id']}",
                    use_container_width=True,
                ):
                    update_announcement_record(
                        announcement["id"],
                        remainingTrips=max(0, int(announcement["remainingTrips"]) - 2),
                    )
                    load_persisted_data_into_session()
                    st.rerun()


def render_landing_auth_actions() -> None:
    account = st.session_state.current_account
    st.markdown("<div class='auth-action-bar'>", unsafe_allow_html=True)
    if account:
        st.markdown(
            f"""
            <div class="auth-state">
              Connecte comme <strong>{account['businessName']}</strong>
              ({get_role_label(account['role'])}).
            </div>
            """,
            unsafe_allow_html=True,
        )
        action_cols = st.columns(3 if is_owner_admin_account(account) else 2)
        with action_cols[0]:
            if st.button("Continuer", type="primary", use_container_width=True, key="landing-continue-account"):
                continue_as_role(account["role"])
        with action_cols[1]:
            if st.button("Se deconnecter", use_container_width=True, key="landing-signout-account"):
                sign_out()
                st.rerun()
        if is_owner_admin_account(account):
            with action_cols[2]:
                if st.button("Espace admin", use_container_width=True, key="landing-admin-space"):
                    open_admin_space()
                    st.rerun()
    else:
        action_cols = st.columns(2)
        with action_cols[0]:
            if st.button("Connexion", use_container_width=True, key="landing-login-open"):
                st.session_state.auth_view = "login"
                st.session_state.auth_message = ""
                st.rerun()
        with action_cols[1]:
            if st.button("S'inscrire", use_container_width=True, key="landing-signup-open"):
                st.session_state.auth_view = "signup_choice"
                st.session_state.auth_message = ""
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_top_bar() -> None:
    if st.session_state.active_role is None:
        st.markdown(
            f"""
            <div class="top-shell" style="text-align:center;">
              <div class="brand-title">{APP_NAME}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    col1, col2 = st.columns([2.2, 1.2], vertical_alignment="center")
    with col1:
        st.markdown(
            f"""
            <div class="top-shell">
              <div class="brand-title">{APP_NAME}</div>
              <div class="brand-copy">Marketplace logistique pour PME et petits transporteurs, avec aide a la creation d'annonces et au matching.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        if st.session_state.active_role == "company":
            current_space = "Espace entreprise"
        elif st.session_state.active_role == "carrier":
            current_space = "Espace transporteur"
        else:
            current_space = "Espace admin"
        st.markdown(f"<div class='status-pill'>{current_space}</div>", unsafe_allow_html=True)
        if st.session_state.active_role == "admin":
            if st.button("Retour a mon espace", use_container_width=True, key="topbar-back-user-space"):
                st.session_state.active_role = get_current_account_role() or None
                st.rerun()
        else:
            if st.button("Retour a l'accueil", use_container_width=True, key="topbar-back-home"):
                st.session_state.active_role = None
                st.rerun()
            if can_current_account_access_admin() and st.button(
                "Espace admin",
                use_container_width=True,
                key="topbar-admin-space",
            ):
                open_admin_space()
                st.rerun()
        if st.button("Se deconnecter", use_container_width=True, key="topbar-signout"):
            sign_out()
            st.rerun()
        if st.button("Reinitialiser la demo", use_container_width=True, key="topbar-reset-demo"):
            reset_demo_data()
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()


def main() -> None:
    inject_styles()
    init_database()
    init_state()
    expire_outdated_announcements()
    apply_pending_widget_syncs()
    render_top_bar()

    if get_legal_view() == "privacy":
        render_privacy_policy_page()
        return

    if st.session_state.active_role is None:
        render_landing()
    elif st.session_state.active_role == "admin":
        if not can_current_account_access_admin():
            st.session_state.active_role = get_current_account_role() or None
            st.rerun()
        render_admin_dashboard()
    elif st.session_state.active_role == "company":
        if not is_company_profile_complete():
            render_company_profile()
        else:
            render_company_dashboard()
    else:
        if not is_carrier_profile_complete():
            render_carrier_profile()
        else:
            render_carrier_dashboard()

    render_privacy_footer()


if __name__ == "__main__":
    main()
