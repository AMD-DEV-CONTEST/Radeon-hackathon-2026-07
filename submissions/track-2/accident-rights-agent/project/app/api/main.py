"""Default loopback API application."""

from app.api.cases import create_app

app = create_app()
