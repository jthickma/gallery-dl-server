import os
import sys
import subprocess
import logging
import re

from starlette.status import HTTP_303_SEE_OTHER
from starlette.applications import Starlette
from starlette.responses import JSONResponse, RedirectResponse, FileResponse
from starlette.routing import Route, Mount
from starlette.templating import Jinja2Templates
from starlette.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from gallery_dl import config, version as gdl_version
from yt_dlp import version as ydl_version

templates = Jinja2Templates(directory="templates")


async def dl_queue_list(request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "gallerydl_version": gdl_version.__version__,
            "ytdlp_version": ydl_version.__version__,
        },
    )


async def redirect(request):
    return RedirectResponse(url="/gallery-dl")


async def q_put(request):
    form = await request.form()
    url = form.get("url").strip()
    ui = form.get("ui")
    options = {"video-options": form.get("video-opts")}

    if not url:
        logger.error("No URL provided.")

        if not ui:
            return JSONResponse(
                {"success": False, "error": "/q called without a 'url' in form data"}
            )

        return RedirectResponse(url="/gallery-dl", status_code=HTTP_303_SEE_OTHER)

    task = BackgroundTask(download, url, options)

    logger.info("Added URL to the download queue: %s", url)

    if not ui:
        return JSONResponse(
            {"success": True, "url": url, "options": options}, background=task
        )

    return RedirectResponse(
        url="/gallery-dl?added=" + url, status_code=HTTP_303_SEE_OTHER, background=task
    )


async def update_route(scope, receive, send):
    task = BackgroundTask(update)
    return JSONResponse({"output": "Initiated package update."}, background=task)


def update():
    try:
        output = subprocess.check_output(
            [sys.executable, "-m", "pip", "install", "--upgrade", "gallery_dl"]
        )
        logger.info(output.decode("utf-8"))
    except subprocess.CalledProcessError as e:
        logger.error(e.output.decode("utf-8"))
    try:
        output = subprocess.check_output(
            [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"]
        )
        logger.info(output.decode("utf-8"))
    except subprocess.CalledProcessError as e:
        logger.error(e.output.decode("utf-8"))


async def log_route(request):
    return FileResponse(log_file)


def config_remove(path, key=None, value=None):
    entries = []
    removed_entries = []

    if isinstance(path, list):
        _list = path

        for entry in _list:
            if key:
                if value:
                    if entry.get(key) == value:
                        entries.append(entry)
                else:
                    if entry.get(key):
                        entries.append(entry)
            else:
                if entry == value:
                    entries.append(entry)

        for entry in entries:
            try:
                _list.remove(entry)
            except Exception as e:
                logger.error("Exception: %s", str(e))
            else:
                removed_entries.append(entry)

    if isinstance(path, dict):
        _dict = path

        if value:
            for k, v in _dict.items():
                if k == key and v == value:
                    entries.append(k)
        else:
            for k in _dict.keys():
                if k == key:
                    entries.append(k)

        for entry in entries:
            try:
                _dict.pop(entry)
            except Exception as e:
                logger.error("Exception: %s", str(e))
            else:
                removed_entries.append(entry)

    return removed_entries


def config_update(request_options):
    requested_format = request_options.get("video-options", "none-selected")

    if requested_format == "download-video":
        try:
            cmdline_args = (
                config._config.get("extractor", {})
                .get("ytdl", {})
                .get("cmdline-args", [])
            )
        except AttributeError:
            pass
        else:
            config_remove(cmdline_args, None, "--extract-audio")
            config_remove(cmdline_args, None, "-x")

        try:
            raw_options = (
                config._config.get("extractor", {})
                .get("ytdl", {})
                .get("raw-options", {})
            )
        except AttributeError:
            pass
        else:
            config_remove(raw_options, "writethumbnail", False)

        try:
            postprocessors = (
                config._config.get("extractor", {})
                .get("ytdl", {})
                .get("raw-options", {})
                .get("postprocessors", [])
            )
        except AttributeError:
            pass
        else:
            config_remove(postprocessors, "key", "FFmpegExtractAudio")

    if requested_format == "extract-audio":
        config.set(
            ("extractor", "ytdl"),
            "raw-options",
            {
                "writethumbnail": False,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "best",
                        "preferredquality": 320,
                    }
                ],
            },
        )


def remove_ansi_escape_sequences(text):
    ansi_escape_pattern = re.compile(r"\x1B\[[0-?9;]*[mGKH]")
    return ansi_escape_pattern.sub("", text)


def download(url, request_options):
    config.clear()
    config.load()

    logger.info("Reloaded gallery-dl configuration.")

    config_update(request_options)

    logger.info(
        "Requested download with the following overriding options: %s", request_options
    )

    cmd = ["gallery-dl", url]
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )

    while True:
        output = process.stdout.readline()
        if output == "" and process.poll() is not None:
            break
        if output:
            formatted_output = output.strip()
            formatted_output = remove_ansi_escape_sequences(formatted_output)
            if formatted_output.startswith("#"):
                logger.warning(
                    "File already exists and/or its ID is in a download archive."
                )
            else:
                logger.info(formatted_output)

    stderr_output = process.stderr.read()
    if stderr_output:
        stderr_output = remove_ansi_escape_sequences(stderr_output.strip())
        logger.error(stderr_output)

    exit_code = process.wait()
    if exit_code == 0:
        logger.info("Download task completed.")
    else:
        logger.error(f"Download failed with exit code: {exit_code}")

    return exit_code


routes = [
    Route("/", endpoint=redirect),
    Route("/gallery-dl", endpoint=dl_queue_list),
    Route("/gallery-dl/q", endpoint=q_put, methods=["POST"]),
    Route("/gallery-dl/update", endpoint=update_route, methods=["PUT"]),
    Route("/gallery-dl/logs", endpoint=log_route),
    Mount("/icons", StaticFiles(directory="icons"), name="icons"),
]

app = Starlette(debug=True, routes=routes)


class LogFilter(logging.Filter):
    """Filters (lets through) all messages with level < LEVEL"""

    def __init__(self, level):
        self.level = level

    def filter(self, record):
        return record.levelno < self.level


MIN_LEVEL = logging.INFO

MIN_LEVEL_STDOUT = MIN_LEVEL

MIN_LEVEL_STDERR = logging.WARNING

log_filter = LogFilter(MIN_LEVEL_STDERR)

formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%d/%m/%Y %H:%M"
)

handler_console_stdout = logging.StreamHandler(sys.stdout)
handler_console_stdout.addFilter(log_filter)
handler_console_stdout.setLevel(MIN_LEVEL_STDOUT)
handler_console_stdout.setFormatter(formatter)

handler_console_stderr = logging.StreamHandler(sys.stderr)
handler_console_stderr.setLevel(max(MIN_LEVEL_STDOUT, MIN_LEVEL_STDERR))
handler_console_stderr.setFormatter(formatter)

log_file = os.path.join(os.path.dirname(__file__), "logs", "app.log")
os.makedirs(os.path.dirname(log_file), exist_ok=True)

handler_file = logging.FileHandler(log_file)
handler_file.setLevel(MIN_LEVEL)
handler_file.setFormatter(formatter)

logger_root = logging.getLogger()
logger_root.setLevel(MIN_LEVEL)
logger_root.addHandler(handler_console_stdout)
logger_root.addHandler(handler_console_stderr)
logger_root.addHandler(handler_file)

logger = logging.getLogger(__name__)
logger.setLevel(MIN_LEVEL)
logger.propagate = True

# logger.info("Initiated package update.")
# update()
