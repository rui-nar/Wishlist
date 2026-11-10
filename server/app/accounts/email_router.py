"""Signing in with an email address and a password (sign-in plan D5, D9, D10)."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["accounts"])
