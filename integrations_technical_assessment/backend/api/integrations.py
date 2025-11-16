# backend/api/integrations.py
from fastapi import APIRouter, Request, Depends, HTTPException
from starlette.responses import JSONResponse
import integrations.hubspot as hubspot

# Import your real dependency; fallback shown below
try:
    from auth.deps import get_current_user
except Exception:
    # fallback: attempt to get request.state.user and return None if not present
    async def get_current_user(request: Request):
        user = getattr(request.state, "user", None)
        if user is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return user

router = APIRouter()

@router.get("/api/integrations/authorize/hubspot")
async def authorize_hubspot(request: Request):
    return hubspot.authorize_hubspot(request)

@router.get("/api/integrations/oauth2callback/hubspot")
async def oauth2callback_hubspot(request: Request):
    return hubspot.oauth2callback_hubspot(request)

@router.get("/api/integrations/items/hubspot")
async def items_hubspot(request: Request, state: Optional[str] = None, user = Depends(get_current_user)):
    """
    If authenticated, use user's stored credentials. Otherwise, allow passing ?state=<state>.
    """
    user_id = getattr(user, "id", None) if user else None
    try:
        if user_id:
            items = hubspot.get_items_hubspot(user_id=user_id)
        elif state:
            items = hubspot.get_items_hubspot(state_key=state)
        else:
            raise HTTPException(status_code=400, detail="No user session or state provided")
        return JSONResponse([dict(i) for i in items])
    except Exception as ex:
        return JSONResponse({"error": str(ex)}, status_code=400)
