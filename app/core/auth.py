# app/core/auth.py

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from app.core.config import settings
import secrets

security = HTTPBasic()

def verify_basic_auth(credentials: HTTPBasicCredentials = Depends(security)):
    """
    Simple HTTP Basic authentication using credentials from .env.
    """
    correct_username = secrets.compare_digest(credentials.username, settings.AUTH_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, settings.AUTH_PASSWORD)

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True
