"""Parse human-readable mute durations."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from core.exceptions import ValidationError

_DURATION_PATTERN = re.compile(r"^(\d+)\s*([mhd])$", re.IGNORECASE)
_MIN_DURATION = timedelta(minutes=1)
_MAX_DURATION = timedelta(days=28)


def parse_duration(value: str) -> timedelta:
    """
    Parse duration strings like ``10m``, ``2h``, ``3d``.

    :raises ValidationError: on invalid format or out-of-range values.
    """
    cleaned = value.strip().lower()
    if not cleaned:
        raise ValidationError(
            "Неверный срок. Используйте формат: 10m, 2h, 3d (максимум 28 дней)."
        )

    match = _DURATION_PATTERN.fullmatch(cleaned)
    if not match:
        raise ValidationError(
            "Неверный срок. Используйте формат: 10m, 2h, 3d (максимум 28 дней)."
        )

    amount = int(match.group(1))
    if amount <= 0:
        raise ValidationError(
            "Неверный срок. Используйте формат: 10m, 2h, 3d (максимум 28 дней)."
        )

    unit = match.group(2)
    if unit == "m":
        delta = timedelta(minutes=amount)
    elif unit == "h":
        delta = timedelta(hours=amount)
    else:
        delta = timedelta(days=amount)

    if delta < _MIN_DURATION:
        raise ValidationError(
            "Неверный срок. Минимальная длительность — 1 минута."
        )
    if delta > _MAX_DURATION:
        raise ValidationError(
            "Неверный срок. Используйте формат: 10m, 2h, 3d (максимум 28 дней)."
        )

    return delta


def compute_expire_at(duration: timedelta, *, now: datetime | None = None) -> datetime:
    """Return UTC expiry datetime for a new or extended mute."""
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base + duration
