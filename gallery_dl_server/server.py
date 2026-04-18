# -*- coding: utf-8 -*-

import asyncio
import mimetypes
import multiprocessing
import os
import queue
import shutil
import signal
import struct
import tempfile
import time
import zlib
import zipfile

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path, PureWindowsPath
from multiprocessing.queues import Queue
from types import FrameType
from typing import Any
from urllib.parse import urlparse

import aiofiles
import watchfiles

from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.datastructures import UploadFile
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse, JSONResponse, StreamingResponse, FileResponse
from starlette.requests import Request
from starlette.routing import Route, WebSocketRoute, Mount
from starlette.staticfiles import StaticFiles
from starlette.status import (
    HTTP_200_OK,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from starlette.templating import Jinja2Templates
from starlette.types import ASGIApp
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

import gallery_dl.version
import yt_dlp.version

from . import download, output, utils, version

custom_args = output.args
cors_allow_origins = custom_args.cors_allow_origins if custom_args else ["*"]

log_file = output.LOG_FILE

log = output.initialise_logging(__name__)


class ServerState:
    """Shared server state stored on the app instance."""

    def __init__(self):
        self.active_connections: set[WebSocket] = set()
        self.connections_lock = asyncio.Lock()
        self.shutdown_event = asyncio.Event()
        self.shutdown_in_progress = False
        self.last_line = ""
        self.last_position = 0


async def redirect(request: Request):
    """Redirect to homepage on request."""
    return RedirectResponse(url="/gallery-dl")


async def homepage(request: Request):
    """Return homepage template response."""
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_version": version.__version__,
            "gallery_dl_version": gallery_dl.version.__version__,
            "yt_dlp_version": yt_dlp.version.__version__,
        },
    )


async def submit_form(request: Request):
    """Process form submission data and start download in the background."""
    content_type = request.headers.get("content-type", "")
    url = None
    video_opts = None

    if "application/json" in content_type:
        try:
            payload = await request.json()
        except ValueError:
            payload = {}

        if isinstance(payload, dict):
            url = payload.get("url")
            video_opts = payload.get("video-opts")
    else:
        form_data = await request.form()

        keys = ("url", "video-opts")
        values = tuple(form_data.get(key) for key in keys)

        url, video_opts = (None if isinstance(value, UploadFile) else value for value in values)

    if not isinstance(url, str) or not url.strip():
        log.error("No URL provided.")

        return JSONResponse(
            {
                "success": False,
                "error": "/q called without a 'url' in form data",
            },
        )

    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        log.error("Invalid URL provided: %s", url)
        return JSONResponse(
            {
                "success": False,
                "error": "Invalid URL provided.",
            }
        )

    if not video_opts:
        video_opts = "none-selected"

    request_options = {"video-options": video_opts}

    task = BackgroundTask(download_task, url, request_options)

    log.info("Added URL to the download queue: %s", url)

    return JSONResponse(
        {
            "success": True,
            "url": url,
            "options": request_options,
        },
        background=task,
    )


def get_default_download_root():
    """Return fallback download root based on runtime environment."""
    if utils.CONTAINER:
        return "/gallery-dl"

    return utils.normalise_path("./gallery-dl")


def get_download_root():
    """Resolve the active gallery-dl base directory.

    This supports Docker volume mappings by honoring the configured
    `extractor.base-directory`, and falls back to `/gallery-dl` in containers.
    """
    root = get_default_download_root()

    try:
        from . import config

        config.clear()
        config.load()
        base_directory = config.get(["extractor", "base-directory"])

        # Support both current and legacy gallery-dl config styles.
        if not isinstance(base_directory, str) or not base_directory.strip():
            base_directory = config.get(["base-directory"])

        if isinstance(base_directory, str) and base_directory.strip():
            root = utils.normalise_path(base_directory)
    except SystemExit as e:
        log.debug("Using fallback download root due to config exit: %s", e)
    except Exception as e:
        log.debug("Using fallback download root due to config load error: %s", e)

    os.makedirs(root, exist_ok=True)
    return root


def resolve_relative_path(relative_path: str):
    """Resolve and validate a path under the downloads root."""
    root = Path(get_download_root()).resolve()
    safe_relative = (relative_path or "").strip().lstrip("/\\")

    if PureWindowsPath(safe_relative).is_absolute() or Path(safe_relative).is_absolute():
        raise ValueError("Path is outside the downloads root")

    try:
        absolute_path = (root / safe_relative).resolve(strict=False)
    except (OSError, RuntimeError) as e:
        raise ValueError("Path is outside the downloads root") from e

    if not absolute_path.is_relative_to(root):
        raise ValueError("Path is outside the downloads root")

    rel_path = absolute_path.relative_to(root)
    rel_path_str = "" if rel_path == Path(".") else str(rel_path)

    return str(root), str(absolute_path), rel_path_str


def list_download_entries(directory_path: str, root_path: str):
    """Return directory entries for downloads browser view."""
    entries: list[dict[str, Any]] = []

    with os.scandir(directory_path) as scandir_entries:
        for entry in scandir_entries:
            try:
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue

            entry_path = os.path.relpath(entry.path, root_path)

            entries.append(
                {
                    "name": entry.name,
                    "path": "" if entry_path == "." else entry_path,
                    "is_dir": entry.is_dir(follow_symlinks=False),
                    "size": stat.st_size,
                    "modified": int(stat.st_mtime),
                }
            )

    entries.sort(key=lambda item: (not item["is_dir"], item["name"].lower()))

    return entries


def _read_and_compress(file_path: str, arcname: str):
    """Read and deflate-compress a file in a worker thread.

    zlib.compress releases the GIL, enabling true parallel compression
    across threads for the CPU-bound deflation step.
    """
    with open(file_path, "rb") as f:
        raw = f.read()

    cobj = zlib.compressobj(6, zlib.DEFLATED, -15)
    deflated = cobj.compress(raw) + cobj.flush()
    crc = zlib.crc32(raw) & 0xFFFFFFFF
    mtime = time.localtime(os.path.getmtime(file_path))[:6]

    return arcname, len(raw), deflated, crc, mtime


def create_downloads_archive(root_path: str, archive_path: str):
    """Create a ZIP archive containing all files in the downloads root.

    Uses 4 threads to compress files in parallel for better performance.
    zlib releases the GIL during compression, enabling true parallelism.
    Pre-compressed raw deflate streams are injected directly into the ZIP.
    """
    file_list = []
    for current_root, _, files in os.walk(root_path):
        for filename in files:
            file_path = os.path.join(current_root, filename)
            if os.path.islink(file_path):
                continue
            arcname = os.path.relpath(file_path, root_path)
            file_list.append((file_path, arcname))

    if not file_list:
        with zipfile.ZipFile(archive_path, mode="w"):
            pass
        return 0

    # Compress all files in parallel across 4 threads
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_read_and_compress, fp, an) for fp, an in file_list]
        results = [f.result() for f in futures]

    # Build ZIP manually — write local file headers + pre-compressed data,
    # then the central directory. This avoids zipfile re-compressing.
    _write_zip_from_compressed(archive_path, results)

    return len(results)


def _write_zip_from_compressed(archive_path: str, entries):
    """Write a ZIP file from pre-compressed deflate entries.

    Constructs the binary ZIP structure directly to avoid double-compression.
    """
    central_entries = []

    with open(archive_path, "wb") as f:
        for arcname, file_size, deflated, crc, mtime in entries:
            encoded_name = arcname.encode("utf-8")

            # DOS date/time from mtime tuple (year, month, day, hour, min, sec)
            dos_time = (mtime[3] << 11) | (mtime[4] << 5) | (mtime[5] // 2)
            dos_date = ((mtime[0] - 1980) << 9) | (mtime[1] << 5) | mtime[2]

            offset = f.tell()

            # Local file header
            local_header = struct.pack(
                "<4sHHHHHIIIHH",
                b"PK\x03\x04",      # signature
                20,                   # version needed (2.0)
                0x800,                # flags: UTF-8 filenames
                8,                    # compression: deflated
                dos_time,
                dos_date,
                crc,
                len(deflated),        # compressed size
                file_size,            # uncompressed size
                len(encoded_name),    # filename length
                0,                    # extra field length
            )
            f.write(local_header)
            f.write(encoded_name)
            f.write(deflated)

            central_entries.append((encoded_name, dos_time, dos_date, crc,
                                    len(deflated), file_size, offset))

        # Central directory
        cd_offset = f.tell()
        for (encoded_name, dos_time, dos_date, crc,
             comp_size, uncomp_size, offset) in central_entries:
            cd_header = struct.pack(
                "<4sHHHHHHIIIHHHHHII",
                b"PK\x01\x02",      # signature
                20,                   # version made by (2.0)
                20,                   # version needed (2.0)
                0x800,                # flags: UTF-8
                8,                    # compression: deflated
                dos_time,
                dos_date,
                crc,
                comp_size,
                uncomp_size,
                len(encoded_name),    # filename length
                0,                    # extra field length
                0,                    # file comment length
                0,                    # disk number start
                0,                    # internal file attributes
                (0o644 << 16),        # external file attributes
                offset,               # local header offset
            )
            f.write(cd_header)
            f.write(encoded_name)

        cd_size = f.tell() - cd_offset

        # End of central directory
        eocd = struct.pack(
            "<4sHHHHIIH",
            b"PK\x05\x06",          # signature
            0,                        # disk number
            0,                        # disk with central directory
            len(central_entries),     # entries on this disk
            len(central_entries),     # total entries
            cd_size,                  # central directory size
            cd_offset,                # central directory offset
            0,                        # comment length
        )
        f.write(eocd)


def remove_directory(path: str):
    """Best-effort cleanup for temporary directories."""
    shutil.rmtree(path, ignore_errors=True)


async def downloads_list(request: Request):
    """Return filebrowser-style directory listing for downloads."""
    relative_path = request.query_params.get("path", "")

    try:
        root_path, absolute_path, rel_path = resolve_relative_path(relative_path)
    except ValueError as e:
        return JSONResponse(
            {
                "success": False,
                "error": str(e),
            },
            status_code=HTTP_404_NOT_FOUND,
        )

    if not os.path.exists(absolute_path):
        return JSONResponse(
            {
                "success": False,
                "error": "Path does not exist",
            },
            status_code=HTTP_404_NOT_FOUND,
        )

    if not os.path.isdir(absolute_path):
        return JSONResponse(
            {
                "success": False,
                "error": "Path is not a directory",
            },
            status_code=HTTP_404_NOT_FOUND,
        )

    parent_path = ""
    if rel_path:
        parent_path = os.path.dirname(rel_path)

    return JSONResponse(
        {
            "success": True,
            "root": root_path,
            "path": rel_path,
            "parent": parent_path,
            "entries": list_download_entries(absolute_path, root_path),
        },
        status_code=HTTP_200_OK,
    )


async def downloads_content(request: Request):
    """Serve a downloaded file for browser viewing."""
    relative_path = request.query_params.get("path", "")

    try:
        _, absolute_path, _ = resolve_relative_path(relative_path)
    except ValueError as e:
        return JSONResponse(
            {
                "success": False,
                "error": str(e),
            },
            status_code=HTTP_404_NOT_FOUND,
        )

    if not os.path.isfile(absolute_path):
        return JSONResponse(
            {
                "success": False,
                "error": "File not found",
            },
            status_code=HTTP_404_NOT_FOUND,
        )

    media_type, _ = mimetypes.guess_type(absolute_path)

    return FileResponse(absolute_path, media_type=media_type or "application/octet-stream")


async def downloads_file(request: Request):
    """Serve a downloaded file as an attachment."""
    relative_path = request.query_params.get("path", "")

    try:
        _, absolute_path, _ = resolve_relative_path(relative_path)
    except ValueError as e:
        return JSONResponse(
            {
                "success": False,
                "error": str(e),
            },
            status_code=HTTP_404_NOT_FOUND,
        )

    if not os.path.isfile(absolute_path):
        return JSONResponse(
            {
                "success": False,
                "error": "File not found",
            },
            status_code=HTTP_404_NOT_FOUND,
        )

    return FileResponse(
        absolute_path,
        media_type="application/octet-stream",
        filename=os.path.basename(absolute_path),
    )


async def downloads_archive(request: Request):
    """Create a ZIP archive from downloads and return it.

    Accepts an optional ``path`` query parameter to archive a subfolder.
    If the path points to a single file, serves it directly without compression.
    """
    relative_path = request.query_params.get("path", "")

    try:
        root_path, target_path, rel_path = resolve_relative_path(relative_path)
    except ValueError as e:
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=HTTP_404_NOT_FOUND,
        )

    if not os.path.exists(target_path):
        return JSONResponse(
            {"success": False, "error": "Path does not exist"},
            status_code=HTTP_404_NOT_FOUND,
        )

    # Single file — serve directly without compression
    if os.path.isfile(target_path):
        return FileResponse(
            target_path,
            media_type="application/octet-stream",
            filename=os.path.basename(target_path),
        )

    if not os.path.isdir(target_path):
        return JSONResponse(
            {"success": False, "error": "Downloads directory not found"},
            status_code=HTTP_404_NOT_FOUND,
        )

    folder_name = os.path.basename(target_path) or "downloads"
    temp_dir = tempfile.mkdtemp(prefix="gallery-dl-server-")
    archive_name = f"gallery-dl-{folder_name}-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    archive_path = os.path.join(temp_dir, archive_name)

    try:
        archived_files = await asyncio.to_thread(create_downloads_archive, target_path, archive_path)

        if archived_files == 0:
            remove_directory(temp_dir)
            return JSONResponse(
                {
                    "success": False,
                    "error": "No downloaded files available to archive",
                },
                status_code=HTTP_404_NOT_FOUND,
            )

        return FileResponse(
            archive_path,
            media_type="application/zip",
            filename=archive_name,
            background=BackgroundTask(remove_directory, temp_dir),
        )
    except Exception as e:
        remove_directory(temp_dir)
        log.error("Failed to create downloads archive: %s", e)
        return JSONResponse(
            {
                "success": False,
                "error": "Failed to create archive",
            },
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        )


def download_task(url: str, request_options: dict[str, str]):
    """Initiate download as a subprocess and log the output."""
    log_queue: Queue[dict[str, Any]] = multiprocessing.Queue()
    return_status: Queue[int] = multiprocessing.Queue()

    args = (url, request_options, log_queue, return_status, custom_args)

    process = multiprocessing.Process(target=download.run, args=args)
    process.start()

    while True:
        if log_queue.empty() and not process.is_alive():
            break
        try:
            record_dict = log_queue.get(timeout=1)
            record = output.dict_to_record(record_dict)

            if record.levelno >= output.LOG_LEVEL_MIN:
                log.handle(record)

            if "Video should already be available" in record.getMessage():
                log.warning("Terminating process as video is not available")
                process.kill()
        except queue.Empty:
            continue

    process.join()

    try:
        exit_code = return_status.get(block=False)
    except queue.Empty:
        exit_code = process.exitcode

    if exit_code == 0:
        log.info("Download process exited successfully")
    else:
        log.error("Download failed with exit code: %s", exit_code)


async def log_route(request: Request):
    """Return logs page template response."""

    async def read_log_file(file_path: str):
        log_contents = ""
        try:
            async with aiofiles.open(file_path, mode="r", encoding="utf-8") as file:
                async for line in file:
                    log_contents += line
        except FileNotFoundError:
            return "Log file not found."
        except Exception as e:
            log.debug(f"Exception: {type(e).__name__}: {e}")
            return f"An error occurred: {e}"

        return log_contents if log_contents else "No logs to display."

    logs = await read_log_file(log_file)

    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "app_version": version.__version__,
            "logs": logs,
        },
    )


async def clear_logs(request: Request):
    """Clear the log file on request."""
    try:
        async with aiofiles.open(log_file, "w", encoding="utf-8") as file:
            await file.write("")

        return JSONResponse(
            {
                "success": True,
                "message": "Logs successfully cleared.",
            },
            status_code=HTTP_200_OK,
        )
    except FileNotFoundError:
        return JSONResponse(
            {
                "success": False,
                "error": "Log file not found.",
            },
            status_code=HTTP_404_NOT_FOUND,
        )
    except IOError:
        return JSONResponse(
            {
                "success": False,
                "error": "An error occurred while accessing the log file.",
            },
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        )
    except Exception as e:
        log.debug(f"Exception: {type(e).__name__}: {e}")

        return JSONResponse(
            {
                "success": False,
                "error": str(e),
            },
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        )


async def log_stream(request: Request):
    """Stream the full contents of the log file."""

    async def file_iterator(file_path: str):
        try:
            async with aiofiles.open(file_path, mode="r", encoding="utf-8") as file:
                while True:
                    chunk = await file.read(64 * 1024)
                    if not chunk:
                        break
                    if utils.WINDOWS:
                        yield chunk.replace("\n", "\r\n")
                    else:
                        yield chunk
        except FileNotFoundError:
            yield "Log file not found."
        except Exception as e:
            log.debug(f"Exception: {type(e).__name__}: {e}")
            yield f"An error occurred: {type(e).__name__}: {e}"

    return StreamingResponse(file_iterator(log_file), media_type="text/plain")


async def log_update(websocket: WebSocket):
    """Stream log file updates over WebSocket connection."""
    state = websocket.app.state.server_state
    await websocket.accept()
    log.debug(f"Accepted WebSocket connection: {websocket}")

    async with state.connections_lock:
        state.active_connections.add(websocket)
        log.debug("WebSocket added to active connections")
    try:
        async with aiofiles.open(log_file, mode="r", encoding="utf-8") as file:
            await file.seek(0, os.SEEK_END)

            async for changes in watchfiles.awatch(
                log_file,
                stop_event=state.shutdown_event,
                rust_timeout=100,
                yield_on_timeout=True,
            ):
                new_content = ""
                do_update_state = False

                previous_line, position = await asyncio.to_thread(
                    output.read_previous_line, log_file, state.last_position
                )
                if "B/s" in previous_line and previous_line != state.last_line:
                    new_content = previous_line
                    do_update_state = True

                new_lines = await file.read()
                if new_lines.strip():
                    new_content += new_lines

                if new_content.strip():
                    await websocket.send_text(new_content)

                    if do_update_state:
                        state.last_line = previous_line
                        state.last_position = position
                    else:
                        state.last_line = ""
                        state.last_position = 0
    except asyncio.CancelledError as e:
        log.debug(f"Exception: {type(e).__name__}")
    except WebSocketDisconnect as e:
        log.debug(f"Exception: {type(e).__name__}")
    except Exception as e:
        log.error("WebSocket error: %s", e, exc_info=True)
    finally:
        async with state.connections_lock:
            state.active_connections.discard(websocket)
            log.debug("WebSocket removed from active connections")


@asynccontextmanager
async def lifespan(app: Starlette):
    """Run server startup and shutdown tasks."""
    app.state.server_state = ServerState()
    output.configure_default_loggers()

    uvicorn_log = output.get_logger("uvicorn")
    uvicorn_log.info(f"Starting {type(app).__name__} application.")

    await shutdown_override(app)
    try:
        yield
    except asyncio.CancelledError:
        pass
    finally:
        if utils.CONTAINER and os.path.isdir("/config"):
            if os.path.isfile(log_file) and os.path.getsize(log_file) > 0:
                dst_dir = "/config/logs"

                os.makedirs(dst_dir, exist_ok=True)

                dst = os.path.join(dst_dir, "app_" + time.strftime("%Y-%m-%d_%H-%M-%S") + ".log")
                shutil.copy2(log_file, dst)


async def shutdown_override(app: Starlette):
    """Override uvicorn signal handlers to ensure a graceful shutdown."""
    sigint_handler = signal.getsignal(signal.SIGINT)
    sigterm_handler = signal.getsignal(signal.SIGTERM)

    def shutdown(sig: int, frame: FrameType | None = None):
        """Call shutdown handler and then original handler as a callback."""
        state = app.state.server_state
        if state.shutdown_in_progress:
            return

        state.shutdown_in_progress = True

        event_loop = asyncio.get_event_loop()
        future = asyncio.run_coroutine_threadsafe(shutdown_handler(app), event_loop)
        future.add_done_callback(lambda f: call_original_handler(sig, frame))

    def call_original_handler(sig: int, frame: FrameType | None = None):
        """Call the original signal handler for server shutdown."""
        if sig == signal.SIGINT and callable(sigint_handler):
            sigint_handler(sig, frame)
        elif sig == signal.SIGTERM and callable(sigterm_handler):
            sigterm_handler(sig, frame)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)


async def shutdown_handler(app: Starlette):
    """Initiate server shutdown."""
    state = app.state.server_state
    if not state.shutdown_event.is_set():
        state.shutdown_event.set()
        log.debug("Set shutdown event")

    await close_connections(app)
    output.close_handlers()


async def close_connections(app: Starlette):
    """Close WebSocket connections and clear the set of active connections."""
    state = app.state.server_state
    async with state.connections_lock:
        log.debug(f"Active connections before closing: {len(state.active_connections)}")
        log.debug(f"Active tasks before closing: {len(asyncio.all_tasks())}")

        close_connections = []
        for websocket in state.active_connections:
            if websocket.client_state == WebSocketState.CONNECTED:
                close_connections.append(websocket.close())
                log.debug(f"Scheduled WebSocket for closure: {websocket}")

        if close_connections:
            await asyncio.gather(*close_connections)
            log.debug("Closed all WebSocket connections")

        if state.active_connections:
            state.active_connections.clear()
            log.debug("Cleared active connections")


class CSPMiddleware(BaseHTTPMiddleware):
    """Enforce Content Security Policy for all requests."""

    def __init__(self, app: ASGIApp, csp_policy: str):
        super().__init__(app)
        self.csp_policy = csp_policy

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = self.csp_policy
        return response


templates = Jinja2Templates(directory=utils.resource_path("templates"))

routes = [
    Route("/", endpoint=redirect, methods=["GET"]),
    Route("/gallery-dl", endpoint=homepage, methods=["GET"]),
    Route("/gallery-dl/q", endpoint=submit_form, methods=["POST"]),
    Route("/gallery-dl/files", endpoint=downloads_list, methods=["GET"]),
    Route("/gallery-dl/files/content", endpoint=downloads_content, methods=["GET"]),
    Route("/gallery-dl/files/download", endpoint=downloads_file, methods=["GET"]),
    Route("/gallery-dl/files/archive", endpoint=downloads_archive, methods=["GET"]),
    Route("/gallery-dl/logs", endpoint=log_route, methods=["GET"]),
    Route("/gallery-dl/logs/clear", endpoint=clear_logs, methods=["POST"]),
    Route("/stream/logs", endpoint=log_stream, methods=["GET"]),
    WebSocketRoute("/ws/logs", endpoint=log_update),
    Mount("/static", app=StaticFiles(directory=utils.resource_path("static")), name="static"),
]

csp_policy = (
    "default-src 'self'; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "manifest-src 'self'; "
    "img-src 'self' data:; "
    "script-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'self' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com;"
)

middleware = [
    Middleware(CORSMiddleware, allow_origins=cors_allow_origins, allow_methods=["POST"]),
    Middleware(CSPMiddleware, csp_policy=csp_policy),
]

app = Starlette(debug=True, routes=routes, middleware=middleware, lifespan=lifespan)
