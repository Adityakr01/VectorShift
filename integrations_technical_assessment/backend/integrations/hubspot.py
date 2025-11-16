# backend/integrations/hubspot.py
"""
HubSpot integration module.
Provides:
- authorize_hubspot(request): Redirects to HubSpot OAuth screen (state stored).
- oauth2callback_hubspot(request): Handles callback, exchanges code for tokens, stores creds.
- get_items_hubspot(user_id=None, state_key=None): Returns list of IntegrationItem dicts for Contacts, Companies, Deals.
"""

from __future__ import annotations

import os
import json
import uuid
import time
import logging
from typing import Dict, List, Optional

import requests
from fastapi import Request, HTTPException
from starlette.responses import RedirectResponse

# Try to import IntegrationItem model from repo, otherwise provide minimal structure
try:
    from .base import IntegrationItem  # type: ignore
except Exception:
    class IntegrationItem(dict):
        def __init__(self, id: str, title: str, parameters: Dict = None):
            super().__init__({
                "id": id,
                "title": title,
                "parameters": parameters or {}
            })

# Redis for token storage (demo). In production, use secure storage.
import redis

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
r = redis.from_url(REDIS_URL, decode_responses=True)

HUBSPOT_CLIENT_ID = os.getenv("HUBSPOT_CLIENT_ID")
HUBSPOT_CLIENT_SECRET = os.getenv("HUBSPOT_CLIENT_SECRET")
HUBSPOT_REDIRECT_URI = os.getenv("HUBSPOT_REDIRECT_URI", "http://localhost:8000/api/integrations/oauth2callback/hubspot")
FRONTEND_SUCCESS_URL = os.getenv("FRONTEND_SUCCESS_URL", "http://localhost:3000/integrations?connected=hubspot")

AUTHORIZE_URL = "https://app.hubspot.com/oauth/authorize"
TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"
API_BASE = "https://api.hubapi.com"

STATE_TTL_SECONDS = 300
CRED_TTL_SECONDS = 30 * 24 * 3600  # 30 days

# ----------------- Helpers -----------------

def _make_state() -> str:
    return str(uuid.uuid4())

def _redis_setex(key: str, value: Dict, ttl: int = CRED_TTL_SECONDS) -> None:
    r.setex(key, ttl, json.dumps(value))

def _redis_get(key: str) -> Dict:
    data = r.get(key)
    return json.loads(data) if data else {}

# ----------------- OAuth start -----------------

def authorize_hubspot(request: Request):
    """
    Start OAuth flow: create state and redirect to HubSpot authorize URL.
    State is stored in Redis for short TTL.
    """
    if not HUBSPOT_CLIENT_ID:
        logger.error("HUBSPOT_CLIENT_ID not configured")
        raise HTTPException(status_code=500, detail="HUBSPOT_CLIENT_ID not configured")

    state = _make_state()

    # Optionally attach user id if request.state.user exists
    user = getattr(request.state, "user", None)
    user_id = getattr(user, "id", None) if user else None
    _redis_setex(f"hubspot:state:{state}", {"created_at": int(time.time()), "user_id": user_id}, ttl=STATE_TTL_SECONDS)

    params = {
        "client_id": HUBSPOT_CLIENT_ID,
        "redirect_uri": HUBSPOT_REDIRECT_URI,
        "scope": "contacts crm.objects.contacts crm.objects.companies crm.objects.deals oauth",
        "state": state
    }
    query = "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())
    redirect_url = f"{AUTHORIZE_URL}?{query}"
    logger.info("Redirecting to HubSpot authorize URL (state=%s)", state)
    return RedirectResponse(redirect_url)

# ----------------- OAuth callback -----------------

def oauth2callback_hubspot(request: Request):
    """
    Exchange code for tokens and store credentials.
    Stores under user:{user_id}:hubspot_creds if user_id present in state metadata,
    otherwise under hubspot:creds:{state}.
    Redirects to FRONTEND_SUCCESS_URL and appends &state=<state> for frontend consumption.
    """
    params = dict(request.query_params)
    code = params.get("code")
    state = params.get("state")
    error = params.get("error")

    if error:
        logger.error("HubSpot OAuth returned error: %s", error)
        raise HTTPException(status_code=400, detail=f"HubSpot OAuth error: {error}")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    state_key = f"hubspot:state:{state}"
    if not r.exists(state_key):
        logger.error("Invalid or expired state: %s", state)
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    state_meta = _redis_get(state_key)
    r.delete(state_key)

    # Exchange authorization code for tokens
    data = {
        "grant_type": "authorization_code",
        "client_id": HUBSPOT_CLIENT_ID,
        "client_secret": HUBSPOT_CLIENT_SECRET,
        "redirect_uri": HUBSPOT_REDIRECT_URI,
        "code": code
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(TOKEN_URL, data=data, headers=headers)
    if resp.status_code != 200:
        logger.exception("Failed to exchange code: %s", resp.text)
        raise HTTPException(status_code=500, detail=f"Failed to exchange code: {resp.text}")

    token_data = resp.json()
    to_store = {
        "access_token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "expires_at": int(time.time()) + int(token_data.get("expires_in", 0)),
        "raw": token_data
    }

    # Prefer mapping to user if state_meta contains user_id
    user_id = state_meta.get("user_id")
    if user_id:
        cred_key = f"user:{user_id}:hubspot_creds"
    else:
        cred_key = f"hubspot:creds:{state}"

    _redis_setex(cred_key, to_store, ttl=CRED_TTL_SECONDS)
    logger.info("Stored HubSpot credentials at key=%s", cred_key)

    # Ensure frontend receives state for state-only flow
    connector = "&" if "?" in FRONTEND_SUCCESS_URL else "?"
    return RedirectResponse(f"{FRONTEND_SUCCESS_URL}{connector}state={state}")

# ----------------- Token refresh -----------------

def _refresh_access_token_if_needed(stored: Dict) -> Dict:
    """
    Refresh access_token using refresh_token if expired or near expiry.
    Returns updated stored dict.
    Raises Exception on failure.
    """
    expires_at = stored.get("expires_at", 0)
    now = int(time.time())
    if now < (expires_at - 60):
        return stored  # still valid

    refresh_token = stored.get("refresh_token")
    if not refresh_token:
        logger.error("No refresh token available")
        raise Exception("No refresh token available")

    data = {
        "grant_type": "refresh_token",
        "client_id": HUBSPOT_CLIENT_ID,
        "client_secret": HUBSPOT_CLIENT_SECRET,
        "refresh_token": refresh_token
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(TOKEN_URL, data=data, headers=headers)
    if resp.status_code != 200:
        logger.exception("Failed to refresh token: %s", resp.text)
        raise Exception(f"Failed to refresh HubSpot token: {resp.text}")

    token_data = resp.json()
    stored["access_token"] = token_data.get("access_token")
    if token_data.get("refresh_token"):
        stored["refresh_token"] = token_data.get("refresh_token")
    stored["expires_at"] = int(time.time()) + int(token_data.get("expires_in", 0))
    return stored

def get_hubspot_credentials_for_user(user_id: Optional[str] = None, state_key: Optional[str] = None) -> Dict:
    """
    Retrieve credentials for a given user_id (preferred) or state_key (fallback).
    Refresh tokens if necessary and persist the refreshed tokens.
    """
    if user_id:
        key = f"user:{user_id}:hubspot_creds"
    elif state_key:
        key = f"hubspot:creds:{state_key}"
    else:
        raise Exception("user_id or state_key required")

    if not r.exists(key):
        raise Exception("No HubSpot credentials found for the provided identifier")

    stored = _redis_get(key)
    stored = _refresh_access_token_if_needed(stored)
    _redis_setex(key, stored, ttl=CRED_TTL_SECONDS)
    return stored

# ----------------- Low-level API call -----------------

def _call_hubspot_api(path: str, access_token: str, params: Dict = None) -> Dict:
    url = f"{API_BASE}{path}"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    resp = requests.get(url, headers=headers, params=params, timeout=20)
    if resp.status_code == 401:
        logger.warning("HubSpot returned 401 for path=%s", path)
        raise HTTPException(status_code=401, detail="HubSpot returned 401 Unauthorized")
    if resp.status_code >= 400:
        logger.error("HubSpot API error: %s", resp.text)
        raise HTTPException(status_code=resp.status_code, detail=f"HubSpot API error: {resp.text}")
    return resp.json()

# ----------------- Pagination helper -----------------

def _fetch_all_objects(path: str, access_token: str, properties: str = None, limit: int = 100, max_pages: int = 20) -> List[Dict]:
    """
    Fetch all objects from HubSpot CRM v3 endpoint using pagination (limit + after).
    Returns list of raw object dicts.
    """
    results: List[Dict] = []
    params = {"limit": limit}
    if properties:
        params["properties"] = properties
    after = None
    pages = 0

    while True:
        if after:
            params["after"] = after
        data = _call_hubspot_api(path, access_token, params=params)
        batch = data.get("results", [])
        results.extend(batch)
        paging = data.get("paging", {})
        next_cursor = paging.get("next", {}).get("after")
        pages += 1
        if not next_cursor or pages >= max_pages:
            break
        after = next_cursor
    return results

# ----------------- Public: get_items_hubspot -----------------

def get_items_hubspot(user_id: Optional[str] = None, state_key: Optional[str] = None) -> List[IntegrationItem]:
    """
    Fetch Contacts, Companies, Deals from HubSpot and return as list of IntegrationItem.
    Maps to user_id if present; else state_key fallback.
    """
    creds = get_hubspot_credentials_for_user(user_id=user_id, state_key=state_key)
    access_token = creds.get("access_token")
    if not access_token:
        raise Exception("No access token available")

    items: List[IntegrationItem] = []

    # Contacts
    try:
        contacts = _fetch_all_objects("/crm/v3/objects/contacts", access_token, properties="firstname,lastname,email", limit=100)
        for obj in contacts:
            props = obj.get("properties", {})
            title = (f"{props.get('firstname','')} {props.get('lastname','')}").strip() or props.get("email") or obj.get("id")
            parameters = {
                "email": props.get("email"),
                "firstName": props.get("firstname"),
                "lastName": props.get("lastname"),
                "hubspotId": obj.get("id"),
                "objectType": "contact"
            }
            items.append(IntegrationItem(id=str(obj.get("id")), title=title, parameters=parameters))
    except Exception as ex:
        logger.exception("Error fetching contacts: %s", ex)
        items.append(IntegrationItem(id="error_contacts", title="Contacts fetch error", parameters={"error": str(ex)}))

    # Companies
    try:
        companies = _fetch_all_objects("/crm/v3/objects/companies", access_token, properties="name,domain", limit=100)
        for obj in companies:
            props = obj.get("properties", {})
            title = props.get("name") or props.get("domain") or obj.get("id")
            parameters = {
                "name": props.get("name"),
                "domain": props.get("domain"),
                "hubspotId": obj.get("id"),
                "objectType": "company"
            }
            items.append(IntegrationItem(id=str(obj.get("id")), title=title, parameters=parameters))
    except Exception as ex:
        logger.exception("Error fetching companies: %s", ex)
        items.append(IntegrationItem(id="error_companies", title="Companies fetch error", parameters={"error": str(ex)}))

    # Deals
    try:
        deals = _fetch_all_objects("/crm/v3/objects/deals", access_token, properties="dealname,amount,dealstage", limit=100)
        for obj in deals:
            props = obj.get("properties", {})
            title = props.get("dealname") or f"Deal {obj.get('id')}"
            parameters = {
                "dealName": props.get("dealname"),
                "amount": props.get("amount"),
                "dealStage": props.get("dealstage"),
                "hubspotId": obj.get("id"),
                "objectType": "deal"
            }
            items.append(IntegrationItem(id=str(obj.get("id")), title=title, parameters=parameters))
    except Exception as ex:
        logger.exception("Error fetching deals: %s", ex)
        items.append(IntegrationItem(id="error_deals", title="Deals fetch error", parameters={"error": str(ex)}))

    return items
