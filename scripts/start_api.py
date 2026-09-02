from __future__ import annotations

import uvicorn

from app.config import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run("app.main:app", host=settings.api_host, port=settings.api_port, reload=False)


if __name__ == "__main__":
    main()
