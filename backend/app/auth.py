"""
JWT authentication dependency for FastAPI routes.

Validates the Bearer token sent by the frontend against Supabase Auth.
Uses the service-role client so we can call auth.get_user() server-side.
The user object returned contains the verified user_id (uuid) we attach
to every conversation row.

Usage:
    @router.get("/something")
    async def handler(user: dict = Depends(get_current_user)):
        user_id = user["id"]
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .db import supabase

_bearer = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Extract and verify the Supabase JWT; return the user payload."""
    token = credentials.credentials
    try:
        response = supabase.auth.get_user(token)
        if response is None or response.user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        return {"id": str(response.user.id), "email": response.user.email}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
