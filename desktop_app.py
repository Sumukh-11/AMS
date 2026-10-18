from __future__ import annotations

import html
import multiprocessing
import os
import queue
import socket
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

import webview
from streamlit.web import bootstrap


BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP_SCRIPT = BUNDLE_ROOT / "app.py"
LOG_PATH = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Stride" / "desktop.log"


def log_startup(message: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.bind(("127.0.0.1", 0))
        return int(server_socket.getsockname()[1])


def start_streamlit(port: int, error_queue: multiprocessing.Queue) -> None:
    try:
        log_startup(f"Starting Streamlit child on 127.0.0.1:{port}; app={APP_SCRIPT}; exists={APP_SCRIPT.exists()}")
        flag_options = {
            "server.address": "127.0.0.1",
            "server.port": port,
            "server.headless": True,
            "server.fileWatcherType": "none",
            "browser.gatherUsageStats": False,
        }
        bootstrap.load_config_options(flag_options)
        bootstrap.run(str(APP_SCRIPT), False, [], flag_options)
    except Exception as error:
        detail = traceback.format_exc()
        log_startup(detail)
        error_queue.put(f"{type(error).__name__}: {error}")


def wait_for_streamlit(
    port: int,
    server_process: multiprocessing.Process,
    error_queue: multiprocessing.Queue,
    timeout_seconds: int = 30,
) -> bool:
    health_url = f"http://127.0.0.1:{port}/_stcore/health"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not server_process.is_alive():
            log_startup(f"Streamlit child exited with code {server_process.exitcode}")
            return False
        try:
            with urllib.request.urlopen(health_url, timeout=1) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.25)
    log_startup(f"Timed out waiting for Streamlit health at {health_url}")
    return False


def main() -> None:
    log_startup(f"Desktop host starting; bundle={BUNDLE_ROOT}; app={APP_SCRIPT}")
    if not APP_SCRIPT.exists():
        message = f"The packaged Stride app.py file is missing from {BUNDLE_ROOT}."
        webview.create_window("Stride startup error", html=f"<h2>Stride could not start</h2><p>{html.escape(message)}</p>")
        webview.start()
        return

    os.chdir(BUNDLE_ROOT)
    port = available_port()
    process_context = multiprocessing.get_context("spawn")
    error_queue = process_context.Queue()
    server_process = process_context.Process(
        target=start_streamlit,
        args=(port, error_queue),
        daemon=True,
        name="stride-streamlit",
    )
    server_process.start()
    log_startup(f"Started Streamlit child pid={server_process.pid} port={port}")
    if not wait_for_streamlit(port, server_process, error_queue):
        try:
            detail = error_queue.get_nowait()
        except queue.Empty:
            detail = "The local server did not become ready within 30 seconds."
        log_startup(f"Startup failed: {detail}")
        server_process.terminate()
        server_process.join(timeout=3)
        webview.create_window(
            "Stride startup error",
            html=f"<h2>Stride could not start</h2><p>{html.escape(detail)}</p><p>Diagnostic log: {html.escape(str(LOG_PATH))}</p>",
            width=720,
            height=360,
        )
        webview.start()
        return

    webview.create_window(
        "Stride | athlete workspace",
        f"http://127.0.0.1:{port}",
        width=1500,
        height=980,
        min_size=(980, 700),
        text_select=True,
    )
    webview.start()
    if server_process.is_alive():
        server_process.terminate()
        server_process.join(timeout=3)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()