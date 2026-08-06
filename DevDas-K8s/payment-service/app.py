import os
import psycopg2
from contextlib import asynccontextmanager
from fastapi import FastAPI

database_url = os.getenv("DATABASE_URL")

if not database_url:
    raise RuntimeError("DATABASE_URL environment variable is missing")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Connecting to PostgreSQL...", flush=True)

    conn = psycopg2.connect(database_url)

    print("Successfully connected!", flush=True)

    conn.close()

    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
def root():
    return {"status": "Payment Service Running"}