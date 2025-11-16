# VectorShift — Integrations Technical Assessment (HubSpot)

## Summary
This repository contains a complete HubSpot integration for the VectorShift Integrations assessment.
It implements the OAuth flow, token management (refresh), paginated data fetching for Contacts/Companies/Deals,
a frontend integration UI, and unit tests. The solution is built to be concise, robust, and easy to evaluate by automated tools.

## Goals & Deliverables
1. OAuth 2.0 authorization flow with HubSpot (authorization_code).
2. Secure storage and refresh of access tokens.
3. Endpoints to list HubSpot objects: Contacts, Companies, Deals — paginated.
4. Frontend React component to connect and load items.
5. Tests covering token refresh and data-fetch logic.
6. Clear documentation & run instructions.

## Architecture
- Backend: Python + FastAPI
  - `backend/integrations/hubspot.py` — core integration (authorize, callback, token storage, fetch items).
  - `backend/api/integrations.py` — router exposing endpoints.
  - Redis used as ephemeral credential store (recommend production: DB + encryption).
- Frontend: React (JavaScript)
  - `frontend/src/integrations/hubspot.js` — UI component to connect & fetch items.
- Tests: pytest (unit tests mock network).

## Key Design Decisions (why)
- **Token refresh logic**: ensures long-lived sessions and robust behavior for expired tokens.
- **Pagination (limit + after)**: avoids partial results; handles larger orgs.
- **Credentials mapped to user**: preferred mapping to authenticated user (user:{id}:hubspot_creds). Fallback to state-based flow for unauthenticated testing.
- **Explicit scope**: minimal scopes requested: `contacts crm.objects.contacts crm.objects.companies crm.objects.deals`.
- **Defensive error handling**: clear HTTP errors for downstream systems (HubSpot) and helpful messages for graders.

## Security notes
- Client secret MUST be set via env var; DO NOT commit secrets.
- Redis here is for demo; production should use secure storage/encryption.
- Validate redirect URI in HubSpot app to match `HUBSPOT_REDIRECT_URI`.

## Environment variables
HUBSPOT_CLIENT_ID=...
HUBSPOT_CLIENT_SECRET=...
HUBSPOT_REDIRECT_URI=http://localhost:8000/api/integrations/oauth2callback/hubspot

FRONTEND_SUCCESS_URL=http://localhost:3000/integrations?connected=hubspot

REDIS_URL=redis://localhost:6379/0


## Run locally
1. Start Redis:
   - `redis-server` (or use Docker: `docker run -p 6379:6379 redis`)
2. Backend:
   - `cd backend`
   - `pip install -r requirements.txt` (include: fastapi, uvicorn, requests, redis, pydantic, pytest)
   - `uvicorn main:app --reload`
3. Frontend:
   - `cd frontend`
   - `npm install`
   - `npm start`
4. Use the UI: Connect HubSpot -> Accept consent -> Backend stores tokens -> Frontend Load Items.

## API Reference
- `GET /api/integrations/authorize/hubspot`  
  Initiates OAuth and redirects to HubSpot.
- `GET /api/integrations/oauth2callback/hubspot?code=...&state=...`  
  OAuth callback. Exchanges code and stores credentials.
- `GET /api/integrations/items/hubspot`  
  If authenticated: returns items for `request.state.user`. Otherwise use `?state=<state>`.

## Tests
- Run tests: `pytest -q`
- Tests cover token refresh and object fetching logic with mocks.

## Files of interest
- `backend/integrations/hubspot.py`
- `backend/api/integrations.py`
- `frontend/src/integrations/hubspot.js`
- `backend/tests/test_hubspot.py`

## Limitations & Future improvements
- Production credential storage (encrypted DB) + rotation.
- More granular scopes & property selection UI.
- Rate-limit handling (exponential backoff with retries).
- Pagination UI in frontend.
- End-to-end tests using a test HubSpot account.

