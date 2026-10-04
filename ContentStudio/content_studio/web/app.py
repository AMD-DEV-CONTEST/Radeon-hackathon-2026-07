"""FastAPI 应用入口。"""
from __future__ import annotations

from fastapi import FastAPI

from content_studio.web.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="Content Studio")
    app.include_router(router)
    return app


app = create_app()


def main():
    import uvicorn
    uvicorn.run("content_studio.web.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
