"""Custom column types. SQLite has no exact decimal or tz-aware datetime."""
from datetime import timezone
from decimal import Decimal

from sqlalchemy import DateTime, String
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator):
    """Stores UTC without tzinfo; always returns timezone-aware UTC values."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not allowed; use timezone-aware UTC")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)


class DecimalText(TypeDecorator):
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("Floats are not allowed for monetary values; use Decimal")
        return str(Decimal(value))

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)
