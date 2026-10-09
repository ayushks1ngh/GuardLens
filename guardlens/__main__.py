"""Entry point: ``python -m guardlens`` starts the server."""
from __future__ import annotations

import uvicorn

from guardlens.config import load_config


def main() -> None:
    cfg = load_config()
    uvicorn.run("guardlens.app:app", host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
