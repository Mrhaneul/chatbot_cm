"""
app/admin_auth.py
-----------------
HTTP Basic Auth for Lance Admin Routes
CBU Campus Store

Usage:
    from app.admin_auth import verify_admin_credentials
    and apply as a FastAPI dependency on the admin router.

Credentials are read from environment variables:
    LANCE_ADMIN_USER     — admin username (default: "admin")
    LANCE_ADMIN_PASSWORD — admin password (NO default; must be set explicitly)

Setup:
    1. Add to your .env file (in project root):
            LANCE_ADMIN_USER=admin
            LANCE_ADMIN_PASSWORD=your_secure_password_here

    2. The admin router in app/admin.py picks this up automatically
       via the dependencies= parameter on the router.

Security notes:
    - Credentials are compared using secrets.compare_digest() to prevent
      timing attacks.
    - Passwords are never logged.
    - If LANCE_ADMIN_PASSWORD is not set, the server will refuse to start
      the admin router rather than run unprotected.
    - This is HTTP Basic Auth — suitable for internal/local use.
      For public-facing deployments, use HTTPS (handled at the reverse
      proxy level during the CBU IT network migration).
"""

import os
import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()


def verify_admin_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    """
    FastAPI dependency — validates HTTP Basic Auth credentials against
    environment variables LANCE_ADMIN_USER and LANCE_ADMIN_PASSWORD.

    Raises 401 if credentials are missing or wrong.
    Raises 500 if LANCE_ADMIN_PASSWORD has not been configured.
    """
    expected_user = os.environ.get("LANCE_ADMIN_USER", "admin")
    expected_pass = os.environ.get("LANCE_ADMIN_PASSWORD", "")

    if not expected_pass:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Admin password is not configured. "
                "Set LANCE_ADMIN_PASSWORD in your .env file before using the admin panel."
            )
        )

    # Use secrets.compare_digest to prevent timing attacks
    user_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        expected_user.encode("utf-8")
    )
    pass_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        expected_pass.encode("utf-8")
    )

    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username
