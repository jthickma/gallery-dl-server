# -*- coding: utf-8 -*-

from . import options
from .server import app as flask_app
import logging

def main(
    app: str = "gallery_dl_server.server:app",
    args: options.CustomNamespace | None = None,
    is_main_module: bool = False,
):
    """Main entry point for gallery-dl-server."""
    if args is None:
        args = options.parse_args(is_main_module)

    kwargs = {
        "host": args.host,
        "port": args.port,
        "threaded": True,
    }

    try:
        # Use simple werkzeug server for start-up handling.
        # In a real production deployment, this might be wrapped in gunicorn in start.sh
        flask_app.run(host=args.host, port=args.port, threaded=True)
    except KeyboardInterrupt:
        pass
