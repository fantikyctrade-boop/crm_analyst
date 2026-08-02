"""Environment-based bot configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    allowed_user_ids: frozenset[int]

    @classmethod
    def from_env(cls) -> Config:
        load_dotenv()
        token = os.getenv("BOT_TOKEN", "").strip()
        raw_user_ids = os.getenv("ALLOWED_USER_IDS", "").strip()

        if not token:
            raise ValueError("BOT_TOKEN is missing in .env.")
        if not raw_user_ids:
            raise ValueError("ALLOWED_USER_IDS is missing in .env.")

        if raw_user_ids == "*":
            user_ids = frozenset()
        else:
            try:
                user_ids = frozenset(
                    int(item.strip())
                    for item in raw_user_ids.split(",")
                    if item.strip()
                )
            except ValueError as error:
                raise ValueError(
                    "ALLOWED_USER_IDS must be '*' or a comma-separated "
                    "list of integers."
                ) from error

            if not user_ids:
                raise ValueError(
                    "ALLOWED_USER_IDS must contain at least one user ID."
                )
        return cls(bot_token=token, allowed_user_ids=user_ids)
