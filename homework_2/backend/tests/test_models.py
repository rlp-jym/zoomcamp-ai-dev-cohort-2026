"""Tests for the deferred models skeletons.

Model names mirror the expected payload nesting, but no fields are declared
until recorded fixtures exist (build order step 4). The shells accept
anything, so a schema surprise can never raise at construction.
"""

from pydantic import BaseModel

from nexus.riot import models


def test_model_names_exist() -> None:
    for name in ("WindowFrame", "WindowTeam", "EventDetails", "LiveEvent"):
        assert issubclass(getattr(models, name), BaseModel), name


def test_empty_construction_never_raises() -> None:
    assert models.WindowFrame().model_dump() == {}
    assert models.EventDetails().model_dump() == {}


def test_unknown_fields_are_kept_not_rejected() -> None:
    frame = models.WindowFrame(foo="bar", nested={"a": 1})
    assert frame.model_dump() == {"foo": "bar", "nested": {"a": 1}}
