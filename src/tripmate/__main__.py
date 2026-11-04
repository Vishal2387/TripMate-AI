"""Run the development server: ``python -m tripmate`` or ``uv run tripmate``."""

import uvicorn

from tripmate.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "tripmate.app:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )


if __name__ == "__main__":
    main()
