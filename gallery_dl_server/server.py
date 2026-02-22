# -*- coding: utf-8 -*-

import os
import queue
import shutil
import signal
import time
import threading
import multiprocessing
import atexit
from pathlib import Path
from urllib.parse import quote

from typing import Any

from flask import Flask, request, jsonify, render_template, redirect, Response, send_file
from flask_sock import Sock
from flask_cors import CORS

import gallery_dl.version
import yt_dlp.version

from . import download, output, utils, version

custom_args = output.args
log_file = output.LOG_FILE
default_download_dir = "/gallery-dl" if utils.CONTAINER else os.path.join(os.getcwd(), "gallery-dl")
download_dir = utils.normalise_path(os.environ.get("DOWNLOAD_DIR", default_download_dir))
download_root = Path(download_dir).resolve()

download_depth = None
if (depth_env := os.environ.get("DOWNLOAD_DEPTH")) is not None:
    try:
        depth_value = int(depth_env)
        if depth_value >= 0:
            download_depth = depth_value
    except ValueError:
        download_depth = None

log = output.initialise_logging(__name__)

app = Flask(
    __name__,
    template_folder=utils.resource_path("templates"),
    static_folder=utils.resource_path("static"),
    static_url_path='/static'
)

CORS(app)
sock = Sock(app)

shutdown_in_progress = False
active_sockets = set()
socket_lock = threading.Lock()

@app.after_request
def add_csp_headers(response):
    csp = (
        "default-src 'self'; "
        "connect-src 'self'; "
        "form-action 'self'; "
        "manifest-src 'self'; "
        "img-src 'self' data:; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
        "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com;"
    )
    if "Content-Security-Policy" not in response.headers:
        response.headers["Content-Security-Policy"] = csp
    return response

@app.route("/", methods=["GET"])
def redirect_home():
    return redirect("/gallery-dl")

@app.route("/gallery-dl", methods=["GET"])
def homepage():
    return render_template(
        "index.html",
        app_version=version.__version__,
        gallery_dl_version=gallery_dl.version.__version__,
        yt_dlp_version=yt_dlp.version.__version__,
    )

@app.route("/gallery-dl/q", methods=["POST"])
def submit_form():
    url = request.form.get("url")
    video_opts = request.form.get("video-opts")

    if not url:
        log.error("No URL provided.")
        return jsonify({"success": False, "error": "/q called without a 'url' in form data"}), 400

    if not video_opts:
        video_opts = "none-selected"

    request_options = {"video-options": video_opts}
    url_stripped = url.strip()

    def run_task():
        download_task(url_stripped, request_options)

    threading.Thread(target=run_task, daemon=True).start()

    log.info("Added URL to the download queue: %s", url_stripped)
    return jsonify({"success": True, "url": url_stripped, "options": request_options}), 202

def download_task(url: str, request_options: dict):
    log_queue = multiprocessing.Queue()
    return_status = multiprocessing.Queue()

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

@app.route("/gallery-dl/logs", methods=["GET"])
def log_route():
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            logs = f.read()
    except FileNotFoundError:
        logs = "Log file not found."
    except Exception as e:
        log.debug(f"Exception: {type(e).__name__}: {e}")
        logs = f"An error occurred: {e}"

    if not logs:
        logs = "No logs to display."

    return render_template("logs.html", app_version=version.__version__, logs=logs)

@app.route("/gallery-dl/logs/clear", methods=["POST"])
def clear_logs():
    try:
        with open(log_file, "w") as file:
            file.write("")
        return jsonify({"success": True, "message": "Logs successfully cleared."}), 200
    except FileNotFoundError:
        return jsonify({"success": False, "error": "Log file not found."}), 404
    except IOError:
        return jsonify({"success": False, "error": "An error occurred while accessing the log file."}), 500
    except Exception as e:
        log.debug(f"Exception: {type(e).__name__}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/stream/logs", methods=["GET"])
def stream_logs():
    def generate():
        try:
            with open(log_file, "r", encoding="utf-8") as file:
                while True:
                    chunk = file.read(64 * 1024)
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

    return Response(generate(), mimetype="text/plain")

@app.route("/gallery-dl/downloads", methods=["GET"])
def list_downloads():
    if not download_root.exists() or not download_root.is_dir():
        return jsonify({"success": True, "directory": str(download_root), "files": []}), 200

    files = []
    try:
        for path in download_root.rglob("*"):
            try:
                relative_path = path.relative_to(download_root)
            except ValueError:
                continue
            if download_depth is not None:
                directory_depth = max(len(relative_path.parts) - 1, 0)
                if directory_depth > download_depth:
                    continue
            if path.is_file():
                relative_path_str = relative_path.as_posix()
                files.append({
                    "name": path.name,
                    "path": relative_path_str,
                    "url": f"/gallery-dl/downloads/{quote(relative_path_str)}",
                })
    except OSError:
        log.error("Failed to scan download directory.")
        return jsonify({"success": False, "error": "Unable to scan download directory.", "files": []}), 500

    files.sort(key=lambda item: item["path"].lower())
    return jsonify({"success": True, "directory": str(download_root), "files": files}), 200

@app.route("/gallery-dl/downloads/<path:path>", methods=["GET"])
def get_download_file(path):
    if not path:
        return jsonify({"success": False, "error": "Missing download path."}), 404

    target = (download_root / path).resolve()
    try:
        target.relative_to(download_root)
    except ValueError:
        return jsonify({"success": False, "error": "Invalid download path."}), 404

    if not target.is_file():
        return jsonify({"success": False, "error": "Download not found."}), 404

    return send_file(target)

@sock.route("/ws/logs")
def log_update(ws):
    with socket_lock:
        active_sockets.add(ws)

    last_position = 0
    last_line = ""

    log.debug(f"Accepted WebSocket connection: {ws}")

    try:
        with open(log_file, "r", encoding="utf-8") as file:
            file.seek(0, os.SEEK_END)
            last_size = os.path.getsize(log_file)

            while True:
                time.sleep(0.1)
                
                try:
                    current_size = os.path.getsize(log_file)
                except OSError:
                    continue

                if current_size < last_size:
                    file.seek(0)
                    last_size = 0
                elif current_size > last_size:
                    new_content = ""
                    do_update_state = False
                    
                    try:
                        previous_line, position = output.read_previous_line(log_file, last_position)
                        if "B/s" in previous_line and previous_line != last_line:
                            new_content = previous_line
                            do_update_state = True
                    except Exception:
                        position = last_position
                        previous_line = last_line
                    
                    new_lines = file.read()
                    if new_lines.strip():
                        new_content += new_lines

                    if new_content.strip():
                        ws.send(new_content)

                        if do_update_state:
                            last_line = previous_line
                            last_position = position
                        else:
                            last_line = ""
                            last_position = 0
                            
                    last_size = current_size

    except Exception as e:
        log.debug(f"Exception: {type(e).__name__}: {e}")
    finally:
        with socket_lock:
            if ws in active_sockets:
                active_sockets.remove(ws)
        log.debug("WebSocket removed")

setup_done = False
@app.before_request
def setup_logging():
    global setup_done
    if not setup_done:
        output.configure_default_loggers()
        setup_done = True

@atexit.register
def shutdown_hooks():
    if utils.CONTAINER and os.path.isdir("/config"):
        if os.path.isfile(log_file) and os.path.getsize(log_file) > 0:
            dst_dir = "/config/logs"
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, "app_" + time.strftime("%Y-%m-%d_%H-%M-%S") + ".log")
            try:
                shutil.copy2(log_file, dst)
            except Exception:
                pass
    output.close_handlers()
