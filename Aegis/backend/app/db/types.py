"""
Portable JSON column type: renders as JSONB (indexable, binary-efficient) on
Postgres in production, and as plain JSON on SQLite in the test suite — so
the same model definitions work against both without duplicating schemas.
"""
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

PortableJSON = JSON().with_variant(JSONB(), "postgresql")
