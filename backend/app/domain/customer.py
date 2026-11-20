"""Customer input model."""
from datetime import date
from typing import Annotated

from pydantic import BaseModel, StringConstraints


class CustomerInput(BaseModel):
    full_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    pan: Annotated[str, StringConstraints(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")] | None = None
    date_of_birth: date | None = None
    email: Annotated[str, StringConstraints(max_length=254)] | None = None
