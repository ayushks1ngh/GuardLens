"""Entry point: ``python -m guardlens`` starts the server."""
from __future__ import annotations

import uvicorn

from guardlens.config import load_config


def main() -> None:
    cfg = load_config()
    kwargs = {"host": cfg.host, "port": cfg.port, "log_level": "info"}
    if cfg.ssl_certfile and cfg.ssl_keyfile:
        kwargs.update(ssl_certfile=cfg.ssl_certfile, ssl_keyfile=cfg.ssl_keyfile)
    uvicorn.run("guardlens.app:app", **kwargs)


if __name__ == "__main__":
    main()
