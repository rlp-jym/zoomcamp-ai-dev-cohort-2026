"""Jinja2 template configuration."""

from fastapi.templating import Jinja2Templates

from backend.config import TEMPLATES_DIR
from backend.services import stub_data

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
# Make persona list available in all templates without per-route plumbing.
templates.env.globals["PERSONAS"] = stub_data.PERSONAS