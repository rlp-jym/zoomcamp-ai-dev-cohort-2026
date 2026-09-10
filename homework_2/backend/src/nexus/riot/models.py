"""Pydantic shells for raw Riot payloads (DEFERRED until step 5).

Class names mirror the expected payload nesting. No fields are declared
until recorded fixtures exist to write them against — a field list written
now would be a guess. ``extra="allow"`` keeps construction total over
unknown shapes: a schema surprise degrades, never raises.
"""

from pydantic import BaseModel, ConfigDict


class _TolerantModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class WindowFrame(_TolerantModel):
    """One raw livestats window frame. Fields arrive in step 5."""


class WindowTeam(_TolerantModel):
    """One raw team block inside a window frame. Fields arrive in step 5."""


class EventDetails(_TolerantModel):
    """Raw event-details payload. Fields arrive in step 5."""


class LiveEvent(_TolerantModel):
    """One raw live event entry. Fields arrive in step 5."""
