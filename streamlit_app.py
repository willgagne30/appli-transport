from __future__ import annotations

import copy
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pydeck as pdk
import requests
import streamlit as st

APP_NAME = "LoadSearch"
ENV_PATH = Path(__file__).with_name(".env")
OTHER_CARGO_VALUE = "__other_cargo__"
MAP_BASE_STYLE = pdk.map_styles.CARTO_ROAD

EQUIPMENT_OPTIONS = [
    "Flatbed",
    "Drybox",
    "Dribox",
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
    "Quebec",
    "Ontario",
    "Nouveau-Brunswick",
    "Nouvelle-Ecosse",
    "Manitoba",
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

DEMO_ANNOUNCEMENTS = [
    {
        "id": "demo-1",
        "title": "Bois d'oeuvre vers Laval",
        "pickupCity": "Trois-Rivieres",
        "deliveryCity": "Laval",
        "cargoType": "Bois",
        "equipment": "Flatbed",
        "loadingDate": "2026-04-24",
        "deliveryDate": "2026-04-25",
        "tripsTotal": 4,
        "remainingTrips": 3,
        "budget": 1650,
        "notes": "Chargement matinal, arrimage obligatoire.",
        "companyName": "Bois Martin Inc.",
    },
    {
        "id": "demo-2",
        "title": "Transport de tuyaux industriels",
        "pickupCity": "Drummondville",
        "deliveryCity": "Sherbrooke",
        "cargoType": "Tuyaux",
        "equipment": "Plateforme",
        "loadingDate": "2026-04-26",
        "deliveryDate": "2026-04-27",
        "tripsTotal": 2,
        "remainingTrips": 2,
        "budget": 1280,
        "notes": "Dechargement sur rendez-vous seulement.",
        "companyName": "Ateliers Nordex",
    },
    {
        "id": "demo-3",
        "title": "Livraison d'autos neuves",
        "pickupCity": "Brossard",
        "deliveryCity": "Ottawa",
        "cargoType": "Autos",
        "equipment": "Porte-autos",
        "loadingDate": "2026-04-28",
        "deliveryDate": "2026-04-29",
        "tripsTotal": 3,
        "remainingTrips": 1,
        "budget": 2450,
        "notes": "Inspection photo avant depart demandee.",
        "companyName": "AutoNova Distribution",
    },
]

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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

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
        "pickupCity": "",
        "deliveryCity": "",
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
        "company_profile": {
            "legalName": "",
            "businessNumber": "",
            "contactName": "",
            "email": "",
            "phone": "",
            "city": "",
            "province": "",
            "industry": "",
        },
        "carrier_profile": {
            "transportCompany": "",
            "businessNumber": "",
            "contactName": "",
            "email": "",
            "phone": "",
            "fleetSize": 1,
            "regions": "",
            "equipmentTypes": [],
        },
        "announcements": copy.deepcopy(DEMO_ANNOUNCEMENTS),
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
        "selected_map_announcement_id": "",
        "map_selection_version": 0,
        "ignore_empty_map_selection": False,
        "sync_draft_widgets": False,
        "sync_filter_widgets": False,
        "geocode_cache": {},
        "last_geocode_timestamp": 0.0,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    ensure_state_shape()
    sync_widget_keys_from_state()


def ensure_state_shape() -> None:
    for announcement in st.session_state.announcements:
        if "deliveryDate" not in announcement:
            announcement["deliveryDate"] = announcement.get("loadingDate", "")
        if "budget" not in announcement:
            announcement["budget"] = 0

    draft = st.session_state.draft_announcement
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
        "carrier_contactName": carrier["contactName"],
        "carrier_email": carrier["email"],
        "carrier_phone": carrier["phone"],
        "carrier_fleetSize": carrier["fleetSize"],
        "carrier_regions": carrier["regions"],
        "carrier_equipmentTypes": carrier["equipmentTypes"],
        "company_ai_prompt": st.session_state.company_ai["requestText"],
        "carrier_ai_prompt": st.session_state.carrier_ai["requestText"],
        "announcement_title": draft["title"],
        "announcement_pickupCity": draft["pickupCity"],
        "announcement_deliveryCity": draft["deliveryCity"],
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


def get_delivery_date(announcement: dict[str, Any]) -> Any:
    return announcement.get("deliveryDate") or announcement.get("loadingDate")


def get_price_per_trip(announcement: dict[str, Any]) -> Any:
    return announcement.get("budget", 0)


def get_role_label(role: str) -> str:
    return "entreprise" if role == "company" else "transporteur"


def normalize_email(value: Any) -> str:
    return normalize_text(value).lower()


def find_account_by_email(email: str) -> dict[str, Any] | None:
    normalized_email = normalize_email(email)
    return next(
        (
            account
            for account in st.session_state.registered_accounts
            if normalize_email(account["email"]) == normalized_email
        ),
        None,
    )


def apply_account_to_profile(account: dict[str, Any]) -> None:
    if account["role"] == "company":
        profile = st.session_state.company_profile
        profile["legalName"] = profile["legalName"] or account["businessName"]
        profile["contactName"] = profile["contactName"] or account["contactName"]
        profile["email"] = profile["email"] or account["email"]
        profile["phone"] = profile["phone"] or account["phone"]
        st.session_state.company_legalName = profile["legalName"]
        st.session_state.company_contactName = profile["contactName"]
        st.session_state.company_email = profile["email"]
        st.session_state.company_phone = profile["phone"]
        return

    profile = st.session_state.carrier_profile
    profile["transportCompany"] = profile["transportCompany"] or account["businessName"]
    profile["contactName"] = profile["contactName"] or account["contactName"]
    profile["email"] = profile["email"] or account["email"]
    profile["phone"] = profile["phone"] or account["phone"]
    st.session_state.carrier_transportCompany = profile["transportCompany"]
    st.session_state.carrier_contactName = profile["contactName"]
    st.session_state.carrier_email = profile["email"]
    st.session_state.carrier_phone = profile["phone"]


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
        if int(announcement["remainingTrips"]) > 0
    ]


def get_company_announcements() -> list[dict[str, Any]]:
    company_name = st.session_state.company_profile["legalName"]
    return [
        announcement
        for announcement in st.session_state.announcements
        if announcement["companyName"] == company_name
    ]


def get_company_active_announcements() -> list[dict[str, Any]]:
    return [
        announcement
        for announcement in get_company_announcements()
        if int(announcement["remainingTrips"]) > 0
    ]


def get_current_company_notifications() -> list[dict[str, Any]]:
    company_name = st.session_state.company_profile["legalName"]
    return [
        notification
        for notification in st.session_state.notifications
        if notification["recipientRole"] == "company"
        and notification["recipientName"] == company_name
    ][::-1]


def get_current_carrier_notifications() -> list[dict[str, Any]]:
    carrier_name = st.session_state.carrier_profile["transportCompany"]
    return [
        notification
        for notification in st.session_state.notifications
        if notification["recipientRole"] == "carrier"
        and notification["recipientName"] == carrier_name
    ][::-1]


def get_company_service_requests() -> list[dict[str, Any]]:
    company_name = st.session_state.company_profile["legalName"]
    return [
        request
        for request in st.session_state.service_requests
        if request["companyName"] == company_name
    ][::-1]


def get_carrier_service_requests() -> list[dict[str, Any]]:
    carrier_name = st.session_state.carrier_profile["transportCompany"]
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
    related_announcement_id: str = "",
    related_request_id: str = "",
) -> None:
    st.session_state.notifications.append(
        {
            "id": f"notif-{datetime.now().timestamp()}",
            "recipientRole": recipient_role,
            "recipientName": recipient_name,
            "title": title,
            "message": message,
            "relatedAnnouncementId": related_announcement_id,
            "relatedRequestId": related_request_id,
            "createdAt": datetime.now().isoformat(timespec="seconds"),
        }
    )


def create_service_request(
    announcement_id: str, requested_trips: int, message: str
) -> tuple[bool, str]:
    announcement = next(
        (item for item in st.session_state.announcements if item["id"] == announcement_id),
        None,
    )
    if not announcement:
        return False, "Annonce introuvable."

    carrier = st.session_state.carrier_profile
    if not carrier["transportCompany"]:
        return False, "Le profil transporteur doit etre complet."

    for request in st.session_state.service_requests:
        if (
            request["announcementId"] == announcement_id
            and request["carrierName"] == carrier["transportCompany"]
            and request["status"] == "pending"
        ):
            return False, "Une proposition en attente existe deja pour cette annonce."

    request_id = f"req-{datetime.now().timestamp()}"
    service_request = {
        "id": request_id,
        "announcementId": announcement_id,
        "announcementTitle": announcement["title"],
        "companyName": announcement["companyName"],
        "carrierName": carrier["transportCompany"],
        "carrierContactName": carrier["contactName"],
        "carrierPhone": carrier["phone"],
        "carrierEmail": carrier["email"],
        "requestedTrips": max(1, int(requested_trips)),
        "message": normalize_text(message),
        "status": "pending",
        "decisionMessage": "",
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    }
    st.session_state.service_requests.append(service_request)
    add_notification(
        recipient_role="company",
        recipient_name=announcement["companyName"],
        title="Nouvelle proposition de transporteur",
        message=(
            f"{carrier['transportCompany']} propose son service pour "
            f"{announcement['title']} ({service_request['requestedTrips']} voyage(s))."
        ),
        related_announcement_id=announcement_id,
        related_request_id=request_id,
    )
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

    if decision == "accepted":
        requested_trips = int(service_request["requestedTrips"])
        if int(announcement["remainingTrips"]) < requested_trips:
            return False, "Il ne reste pas assez de voyages disponibles."
        announcement["remainingTrips"] = int(announcement["remainingTrips"]) - requested_trips
        service_request["status"] = "accepted"
        service_request["decisionMessage"] = normalize_text(decision_message) or "Proposition acceptee."
        service_request["updatedAt"] = datetime.now().isoformat(timespec="seconds")
        add_notification(
            recipient_role="carrier",
            recipient_name=service_request["carrierName"],
            title="Proposition acceptee",
            message=(
                f"{announcement['companyName']} a accepte votre proposition pour "
                f"{announcement['title']}."
            ),
            related_announcement_id=announcement["id"],
            related_request_id=request_id,
        )
        return True, "Le transporteur a ete accepte."

    service_request["status"] = "refused"
    service_request["decisionMessage"] = normalize_text(decision_message) or "Proposition refusee."
    service_request["updatedAt"] = datetime.now().isoformat(timespec="seconds")
    add_notification(
        recipient_role="carrier",
        recipient_name=service_request["carrierName"],
        title="Proposition refusee",
        message=(
            f"{announcement['companyName']} a refuse votre proposition pour "
            f"{announcement['title']}."
        ),
        related_announcement_id=announcement["id"],
        related_request_id=request_id,
    )
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
        pickup_coords = geocode_location(announcement["pickupCity"])
        delivery_coords = geocode_location(announcement["deliveryCity"])
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
                    "city": announcement["pickupCity"],
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
                    "city": announcement["deliveryCity"],
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
                    "city": f"{announcement['pickupCity']} -> {announcement['deliveryCity']}",
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

    points, arcs = build_map_rows(announcements)
    if not points:
        show_notice(
            "info",
            "Carte indisponible pour certains lieux",
            "Entre un lieu complet comme 'Saint-Aurelie, QC' ou 'Boston, MA' pour maximiser les chances de geocodage.",
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
                "<b>{city}</b><br/>"
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
        if filters["pickupCity"] and normalize_for_match(filters["pickupCity"]) not in normalize_for_match(
            announcement["pickupCity"]
        ):
            continue
        if filters["deliveryCity"] and normalize_for_match(filters["deliveryCity"]) not in normalize_for_match(
            announcement["deliveryCity"]
        ):
            continue
        if filters["cargoType"] and normalize_for_match(filters["cargoType"]) not in normalize_for_match(
            announcement["cargoType"]
        ):
            continue
        if filters["equipment"] and normalize_equipment_for_match(filters["equipment"]) != normalize_equipment_for_match(
            announcement["equipment"]
        ):
            continue
        results.append(announcement)
    return results


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
        st.session_state.company_ai_prompt = COMPANY_EXAMPLE_PROMPT
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
            "pickupCity": "",
            "deliveryCity": "",
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
        + "- loadingDate doit etre YYYY-MM-DD si possible.\n"
        + "- deliveryDate doit etre YYYY-MM-DD si possible et represente la date de livraison.\n"
        + "- tripsTotal et budget doivent etre des nombres; budget represente le prix par voyage.\n"
        + "- title doit etre court et utile.\n"
        + "- missingFields liste ce qui reste flou avant publication."
    )


def apply_company_ai_response(payload: dict[str, Any]) -> None:
    announcement = payload.get("announcement", {})
    cargo_type, cargo_other = normalize_cargo_option(announcement.get("cargoType"))
    draft = {
        "title": normalize_text(announcement.get("title")),
        "pickupCity": normalize_text(announcement.get("pickupCity")),
        "deliveryCity": normalize_text(announcement.get("deliveryCity")),
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
        st.session_state.carrier_ai_prompt = CARRIER_EXAMPLE_PROMPT
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
        "pickupCity": st.session_state.announcement_pickupCity,
        "deliveryCity": st.session_state.announcement_deliveryCity,
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
    st.session_state.announcement_pickupCity = draft["pickupCity"]
    st.session_state.announcement_deliveryCity = draft["deliveryCity"]
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
        st.markdown(
            f"""
            <div class="result-card">
              <div style="display:flex;justify-content:space-between;gap:1rem;align-items:flex-start;">
                <div>
                  <div class="section-title" style="font-size:1.05rem;margin-top:0;">{notification['title']}</div>
                  <div class="small-copy">{notification['message']}</div>
                </div>
                <div class="status-pill ai">{notification['createdAt']}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

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
        st.markdown(
            f"""
            <div class="result-card">
              <div style="display:flex;justify-content:space-between;gap:1rem;align-items:flex-start;">
                <div>
                  <div class="section-title" style="font-size:1.1rem;margin-top:0;">{service_request['announcementTitle']}</div>
                  <div class="small-copy">
                    Transporteur: <strong>{service_request['carrierName']}</strong><br>
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
        st.markdown(
            f"""
            <div class="result-card">
              <div style="display:flex;justify-content:space-between;gap:1rem;align-items:flex-start;">
                <div>
                  <div class="section-title" style="font-size:1.1rem;margin-top:0;">{service_request['announcementTitle']}</div>
                  <div class="small-copy">
                    Entreprise: <strong>{service_request['companyName']}</strong><br>
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
        account = find_account_by_email(email)
        if not account or account["password"] != password:
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
        password = st.text_input("Mot de passe", type="password", key=f"signup_{role}_password")
        confirm_password = st.text_input(
            "Confirmer le mot de passe",
            type="password",
            key=f"signup_{role}_confirm_password",
        )
        submit = st.form_submit_button("Créer mon compte", type="primary", use_container_width=True)

    if submit:
        required_values = [business_name, contact_name, email, phone, password, confirm_password]
        if not all(normalize_text(value) for value in required_values):
            show_notice("warning", "Champs manquants", "Veuillez remplir tous les champs pour créer le compte.")
        elif password != confirm_password:
            show_notice("error", "Mot de passe différent", "La confirmation ne correspond pas au mot de passe.")
        elif find_account_by_email(email):
            show_notice("warning", "Compte déjà existant", "Un compte existe déjà avec ce courriel. Utilisez la connexion.")
        else:
            account = {
                "id": f"account-{datetime.now().timestamp()}",
                "role": role,
                "businessName": normalize_text(business_name),
                "contactName": normalize_text(contact_name),
                "email": normalize_email(email),
                "phone": normalize_text(phone),
                "password": password,
                "createdAt": datetime.now().isoformat(timespec="seconds"),
            }
            st.session_state.registered_accounts.append(account)
            st.session_state.current_account = account
            st.session_state.auth_view = "landing"
            st.session_state.auth_message = ""
            apply_account_to_profile(account)
            st.session_state.active_role = role
            st.rerun()

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


def render_company_profile() -> None:
    st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Etape 1</span>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Completer votre profil entreprise</div>", unsafe_allow_html=True)
    st.markdown(
        "<p class='small-copy'>Tant que ce profil n'est pas rempli, vous ne pouvez pas publier d'annonce.</p>",
        unsafe_allow_html=True,
    )

    with st.form("company_profile_form"):
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
        submitted = st.form_submit_button("Enregistrer le profil et continuer", type="primary")

    if submitted:
        st.session_state.company_profile = {
            "legalName": st.session_state.company_legalName,
            "businessNumber": st.session_state.company_businessNumber,
            "contactName": st.session_state.company_contactName,
            "email": st.session_state.company_email,
            "phone": st.session_state.company_phone,
            "city": st.session_state.company_city,
            "province": st.session_state.company_province,
            "industry": st.session_state.company_industry,
        }
        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def render_carrier_profile() -> None:
    st.markdown("<div class='soft-card'>", unsafe_allow_html=True)
    st.markdown("<span class='eyebrow'>Etape 1</span>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Completer votre profil transporteur</div>", unsafe_allow_html=True)
    st.markdown(
        "<p class='small-copy'>Tant que ce profil n'est pas rempli, vous ne pouvez pas chercher des voyages.</p>",
        unsafe_allow_html=True,
    )

    with st.form("carrier_profile_form"):
        col1, col2 = st.columns(2)
        with col1:
            st.text_input("Nom de la compagnie de transport", key="carrier_transportCompany")
            st.text_input("Nom du responsable", key="carrier_contactName")
            st.text_input("Telephone", key="carrier_phone")
            st.number_input("Nombre de camions", min_value=1, max_value=4, step=1, key="carrier_fleetSize")
        with col2:
            st.text_input("Numero d'entreprise", key="carrier_businessNumber")
            st.text_input("Courriel", key="carrier_email")
            st.text_input("Regions desservies", key="carrier_regions")
            st.multiselect("Equipements disponibles", EQUIPMENT_OPTIONS, key="carrier_equipmentTypes")
        submitted = st.form_submit_button("Enregistrer le profil et continuer", type="primary")

    if submitted:
        st.session_state.carrier_profile = {
            "transportCompany": st.session_state.carrier_transportCompany,
            "businessNumber": st.session_state.carrier_businessNumber,
            "contactName": st.session_state.carrier_contactName,
            "email": st.session_state.carrier_email,
            "phone": st.session_state.carrier_phone,
            "fleetSize": int(st.session_state.carrier_fleetSize),
            "regions": st.session_state.carrier_regions,
            "equipmentTypes": st.session_state.carrier_equipmentTypes,
        }
        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def render_company_dashboard() -> None:
    company_announcements = get_company_announcements()
    active_count = sum(1 for item in company_announcements if int(item["remainingTrips"]) > 0)
    complete_count = sum(1 for item in company_announcements if int(item["remainingTrips"]) == 0)
    remaining_total = sum(int(item["remainingTrips"]) for item in company_announcements)

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

    cargo_options = [""] + SUGGESTED_CARGO_OPTIONS + [OTHER_CARGO_VALUE]
    cargo_labels = {
        "": "Choisir",
        OTHER_CARGO_VALUE: "Autres (precisez)",
    }

    with st.form("announcement_form"):
        col1, col2 = st.columns(2)
        with col1:
            st.text_input("Titre de l'annonce", key="announcement_title")
            st.text_input(
                "Lieu de chargement",
                key="announcement_pickupCity",
                help="Exemple: Saint-Aurelie, QC",
            )
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
        with col2:
            st.text_input(
                "Lieu de livraison",
                key="announcement_deliveryCity",
                help="Exemple: Boston, MA",
            )
            st.date_input("Date de chargement", key="announcement_loadingDate")
            st.date_input("Date de livraison", key="announcement_deliveryDate")
            st.number_input("Nombre de voyages disponibles", min_value=1, step=1, key="announcement_tripsTotal")
            st.number_input("Prix/voyage (CAD)", min_value=0, step=50, key="announcement_budget")
            st.text_area("Consignes speciales", key="announcement_notes", height=110)

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
                normalize_text(st.session_state.announcement_pickupCity),
                normalize_text(st.session_state.announcement_deliveryCity),
                normalize_text(cargo_value),
                normalize_text(st.session_state.announcement_equipment),
                st.session_state.announcement_loadingDate,
                st.session_state.announcement_deliveryDate,
            ]
        ):
            show_notice("warning", "Champs manquants", "Completer les champs obligatoires avant de publier.")
        else:
            announcement = {
                "id": f"user-{datetime.now().timestamp()}",
                "title": normalize_text(st.session_state.announcement_title),
                "pickupCity": normalize_text(st.session_state.announcement_pickupCity),
                "deliveryCity": normalize_text(st.session_state.announcement_deliveryCity),
                "cargoType": normalize_text(cargo_value),
                "equipment": normalize_text(st.session_state.announcement_equipment),
                "loadingDate": st.session_state.announcement_loadingDate.isoformat(),
                "deliveryDate": st.session_state.announcement_deliveryDate.isoformat(),
                "tripsTotal": int(st.session_state.announcement_tripsTotal),
                "remainingTrips": int(st.session_state.announcement_tripsTotal),
                "budget": int(st.session_state.announcement_budget),
                "notes": normalize_text(st.session_state.announcement_notes),
                "companyName": st.session_state.company_profile["legalName"],
            }
            st.session_state.announcements.append(announcement)
            st.session_state.company_ai["assistantMessage"] = "Annonce publiee."
            st.session_state.draft_announcement = create_empty_draft()
            st.session_state.sync_draft_widgets = True
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


def render_company_announcement_card(announcement: dict[str, Any]) -> None:
    status = "Active" if int(announcement["remainingTrips"]) > 0 else "Completee"
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
    button_cols = st.columns(2)
    if announcement["remainingTrips"] > 0:
        with button_cols[0]:
            if st.button(f"Attribuer 1 voyage - {announcement['id']}", key=f"assign-1-{announcement['id']}", use_container_width=True):
                announcement["remainingTrips"] = max(0, int(announcement["remainingTrips"]) - 1)
                st.rerun()
        with button_cols[1]:
            if announcement["remainingTrips"] >= 2 and st.button(
                f"Attribuer 2 voyages - {announcement['id']}",
                key=f"assign-2-{announcement['id']}",
                use_container_width=True,
            ):
                announcement["remainingTrips"] = max(0, int(announcement["remainingTrips"]) - 2)
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
          <span class="score-pill score-local">Compatibilite locale {local_score}%</span>
          <div class="small-copy" style="margin-top:0.65rem;">
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
    render_service_proposal_form(
        announcement,
        form_key=f"map-proposal-form-{announcement['id']}",
    )
    st.markdown("</div>", unsafe_allow_html=True)


def render_carrier_dashboard() -> None:
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


def main() -> None:
    inject_styles()
    init_state()
    apply_pending_widget_syncs()
    render_top_bar()

    if st.session_state.active_role is None:
        render_landing()
        return

    if st.session_state.active_role == "company":
        if not is_company_profile_complete():
            render_company_profile()
        else:
            render_company_dashboard()
        return

    if not is_carrier_profile_complete():
        render_carrier_profile()
    else:
        render_carrier_dashboard()


if __name__ == "__main__":
    main()
