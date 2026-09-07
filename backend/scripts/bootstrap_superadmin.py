#!/usr/bin/env python3
"""Explicit emergency bootstrap for PlanIQ Display.

This command is never called by Render startup or pre-deploy. It only creates a
superadministrator when no active administrator exists, and requires an
explicit confirmation flag plus ADMIN_PASSWORD in the environment.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException
from sqlmodel import Session, select

from service1.auth import get_password_hash, validate_password_strength
from service1.db import engine
from service1.models import User


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Opret en recovery-superadministrator eksplicit.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--confirm-create",
        action="store_true",
        help="Påkrævet bekræftelse; kommandoen ændrer ellers ikke databasen.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.confirm_create:
        print("Afvist: tilføj --confirm-create for at udføre recovery-oprettelsen.", file=sys.stderr)
        return 2

    password = os.getenv("ADMIN_PASSWORD", "")
    if not password:
        print("Afvist: ADMIN_PASSWORD skal sættes i miljøet.", file=sys.stderr)
        return 2
    try:
        validate_password_strength(password)
    except HTTPException as exc:
        print(f"Afvist: {exc.detail}", file=sys.stderr)
        return 2

    username = args.username.strip()
    email = args.email.strip().lower()
    if not username or "@" not in email:
        print("Afvist: gyldigt brugernavn og email er påkrævet.", file=sys.stderr)
        return 2

    with Session(engine) as session:
        active_admin = session.exec(
            select(User).where(User.role.in_(["admin", "superadmin"]), User.is_active)
        ).first()
        if active_admin:
            print("Afvist: databasen har allerede en aktiv administrator/superadministrator.", file=sys.stderr)
            return 3

        collision = session.exec(
            select(User).where((User.username == username) | (User.email == email))
        ).first()
        if collision:
            print("Afvist: brugernavn eller email findes allerede.", file=sys.stderr)
            return 3

        user = User(
            username=username,
            email=email,
            hashed_password=get_password_hash(password),
            role="superadmin",
            is_active=True,
            must_change_password=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        print(f"Recovery-superadministrator oprettet med user_id={user.id}.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
