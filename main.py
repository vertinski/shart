import argparse
import os
import signal
import socket
import sys
import threading
import time
import uuid
import shutil
import tempfile
import atexit
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import qrcode
import uvicorn
import html as html_lib


class TokenStore:
    """In-memory token store with expiry, guarded by a lock."""

    def __init__(self) -> None:
        self._token_to_expiry: Dict[str, datetime] = {}
        self._lock = threading.Lock()

    def add_token(self, token: str, expires_at: datetime) -> None:
        with self._lock:
            self._token_to_expiry[token] = expires_at

    def is_valid(self, token: str) -> bool:
        with self._lock:
            expires_at = self._token_to_expiry.get(token)
        if expires_at is None:
            return False
        return datetime.now(timezone.utc) <= expires_at


def sanitize_filename(filename: str) -> str:
    """Conservatively sanitize a filename for saving on disk."""
    keep = "-_.() "
    sanitized = "".join(c for c in filename if c.isalnum() or c in keep)
    if not sanitized:
        return f"file_{int(time.time())}"
    return sanitized


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def get_local_ip() -> str:
    """Best-effort retrieval of the primary local IPv4 address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            return ip
    except OSError:
        return "127.0.0.1"


def choose_available_port(requested_port: int | None) -> int:
    if requested_port is not None:
        return requested_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def build_app(token_store: TokenStore, upload_dir: Path, exit_on_upload: bool) -> FastAPI:
    app = FastAPI()
    shutdown_triggered = False
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/upload/{token}", response_class=HTMLResponse)
    async def upload_page(token: str, request: Request) -> HTMLResponse:
        if not token_store.is_valid(token):
            raise HTTPException(status_code=404, detail="Upload link expired or invalid")
        index_path = static_dir / "index.html"
        try:
            html = index_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read index.html: {exc}")
        html = html.replace("__TOKEN_PLACEHOLDER__", token)
        # Inject ASCII logo if available
        logo_path = Path(__file__).resolve().parent / "ascii_logo.txt"
        try:
            raw_logo = logo_path.read_text(encoding="utf-8", errors="replace").rstrip("\n")
        except OSError:
            raw_logo = ""
        logo_text = trim_common_left_spaces(raw_logo)
        logo_html = f"<pre class=\"logo\">{html_lib.escape(logo_text)}</pre>" if logo_text.strip() else ""
        html = html.replace("__ASCII_LOGO__", logo_html)
        return HTMLResponse(content=html)

    @app.post("/api/upload/{token}")
    async def upload_files(token: str, files: List[UploadFile] = File(...)) -> JSONResponse:
        if not token_store.is_valid(token):
            raise HTTPException(status_code=404, detail="Upload link expired or invalid")
        ensure_directory(upload_dir)
        saved_names: List[str] = []
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        for file in files:
            original = sanitize_filename(file.filename)
            target_name = f"{timestamp}_{original}"
            target_path = upload_dir / target_name
            contents = await file.read()
            try:
                target_path.write_bytes(contents)
            except OSError as exc:
                raise HTTPException(status_code=500, detail=f"Failed to save '{original}': {exc}")
            finally:
                await file.close()
            saved_names.append(target_name)
        # trigger shutdown in background after first successful upload if enabled
        if exit_on_upload:
            nonlocal shutdown_triggered
            if not shutdown_triggered:
                shutdown_triggered = True
                def _shutdown():
                    # Give the response a moment to flush before stopping
                    time.sleep(0.25)
                    # Send SIGINT to trigger graceful shutdown
                    os.kill(os.getpid(), signal.SIGINT)
                threading.Thread(target=_shutdown, daemon=True).start()
        return JSONResponse({"saved": saved_names})

    @app.get("/health", response_class=PlainTextResponse)
    async def health() -> str:
        return "ok"

    return app


def print_ascii_logo() -> None:
    """Print the ASCII logo from ascii_logo.txt if present.

    On read errors, emit a concise warning to stderr and continue.
    """
    project_dir = Path(__file__).resolve().parent
    logo_path = project_dir / "ascii_logo.txt"
    try:
        text = logo_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return
    except OSError as exc:
        print(f"[warning] Failed to read ascii_logo.txt: {exc}", file=sys.stderr)
        return
    if text.strip():
        print("\n")
        if sys.stdout.isatty():
            grey = "\033[90m"  # bright black / light grey
            reset = "\033[0m"
            print(f"{grey}{text}{reset}")
        else:
            print(text)


def print_qr(url: str) -> None:
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    # Print ASCII QR to terminal
    qr.print_ascii(invert=True)


def human_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024.0


def trim_common_left_spaces(text: str) -> str:
    """Trim common leading spaces across all non-empty lines.

    Tabs are preserved; only spaces are considered for trimming.
    """
    lines = text.splitlines()
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return text
    common = min(len(line) - len(line.lstrip(' ')) for line in non_empty)
    if common <= 0:
        return text
    return "\n".join(line[common:] if len(line) >= common else "" for line in lines)


def prepare_share_items(paths: List[str]) -> Tuple[List[Tuple[str, Path]], str | None]:
    """Prepare items to be shared.

    - Files are shared as-is.
    - Directories are zipped into a temporary directory and shared as single .zip files.

    Returns (items, temp_dir). Caller is responsible for removing temp_dir when not None.
    """
    items: List[Tuple[str, Path]] = []
    temp_dir: str | None = None

    # Normalize and validate inputs
    normalized: List[Path] = []
    for p in paths:
        pp = Path(p).expanduser().resolve()
        if not pp.exists():
            raise FileNotFoundError(f"Path does not exist: {p}")
        normalized.append(pp)

    # If any directories, create a temp dir to store zips
    if any(pp.is_dir() for pp in normalized):
        temp_dir = tempfile.mkdtemp(prefix="shart_share_")

    for pp in normalized:
        if pp.is_file():
            display = sanitize_filename(pp.name)
            items.append((display, pp))
        elif pp.is_dir():
            # Zip directory into temp dir
            base_name = sanitize_filename(pp.name) or "dir"
            zip_base_path = Path(temp_dir) / base_name  # make_archive adds extension
            archive_path = shutil.make_archive(str(zip_base_path), "zip", root_dir=str(pp))
            items.append((f"{base_name}.zip", Path(archive_path)))
        else:
            # Skip special files
            continue

    return items, temp_dir


def build_share_app(token_store: TokenStore, items: List[Tuple[str, Path]], exit_on_download: bool) -> FastAPI:
    app = FastAPI()
    shutdown_triggered = False
    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    def ensure_valid(token: str) -> None:
        if not token_store.is_valid(token):
            raise HTTPException(status_code=404, detail="Share link expired or invalid")

    @app.get("/share/{token}", response_class=HTMLResponse)
    async def share_page(token: str, request: Request) -> HTMLResponse:
        ensure_valid(token)
        # Build the list items and inject into template
        list_items: List[str] = []
        for idx, (display, path) in enumerate(items):
            try:
                size_str = human_size(path.stat().st_size)
            except OSError:
                size_str = "?"
            list_items.append(f'<li><a href="/download/{token}/{idx}">{display}</a> <span class="muted">({size_str})</span></li>')

        share_path = static_dir / "share.html"
        try:
            html = share_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read share.html: {exc}")
        html = html.replace("__LIST_ITEMS__", "".join(list_items))
        # Inject ASCII logo if available
        logo_path = Path(__file__).resolve().parent / "ascii_logo.txt"
        try:
            raw_logo = logo_path.read_text(encoding="utf-8", errors="replace").rstrip("\n")
        except OSError:
            raw_logo = ""
        logo_text = trim_common_left_spaces(raw_logo)
        logo_html = f"<pre class=\"logo\">{html_lib.escape(logo_text)}</pre>" if logo_text.strip() else ""
        html = html.replace("__ASCII_LOGO__", logo_html)
        return HTMLResponse(content=html)

    @app.get("/download/{token}/{item_id}")
    async def download_item(token: str, item_id: int) -> FileResponse:
        ensure_valid(token)
        if item_id < 0 or item_id >= len(items):
            raise HTTPException(status_code=404, detail="Item not found")
        display, path = items[item_id]
        if not path.exists():
            raise HTTPException(status_code=404, detail="File no longer available")

        # Trigger shutdown after first completed download if enabled
        if exit_on_download:
            nonlocal shutdown_triggered
            if not shutdown_triggered:
                shutdown_triggered = True
                def _shutdown():
                    time.sleep(0.25)
                    os.kill(os.getpid(), signal.SIGINT)
                threading.Thread(target=_shutdown, daemon=True).start()

        return FileResponse(path=path, filename=display)

    @app.get("/health", response_class=PlainTextResponse)
    async def health() -> str:
        return "ok"

    return app


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Temporary file upload/share server with QR code link")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help="Port to bind (default: auto)")
    parser.add_argument("--ttl-minutes", type=int, default=15, help="Minutes until the upload link expires")
    parser.add_argument("--upload-dir", type=str, default="uploads", help="Directory to store uploaded files")
    parser.add_argument("--exit-on-upload", action="store_true", help="Exit the server after the first successful upload")
    parser.add_argument("--share", nargs="+", help="Share one or more files or directories")
    args = parser.parse_args(argv)

    # Print banner/logo at startup (if available)
    print_ascii_logo()

    token_store = TokenStore()
    token = uuid.uuid4().hex
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=args.ttl_minutes)
    token_store.add_token(token, expires_at)

    port = choose_available_port(args.port)
    local_ip = get_local_ip()

    # Share mode
    if args.share is not None:
        try:
            items, temp_dir = prepare_share_items(args.share)
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        # Ensure temporary artifacts are cleaned up on exit
        if temp_dir is not None:
            atexit.register(lambda: shutil.rmtree(temp_dir, ignore_errors=True))

        app = build_share_app(token_store=token_store, items=items, exit_on_download=args.exit_on_upload)
        url = f"http://{local_ip}:{port}/share/{token}"

        print('\nStart with "--exit-on-upload" to exit the server after the first successful upload.')
        print("\nScan this QR code to open the share page on your local network:\n")
        print_qr(url)
        print(f"\nURL: {url}")
        print(f"Expires at (UTC): {expires_at.isoformat()}\n")
        print("Press Ctrl+C to stop the server.")
        uvicorn.run(app, host=args.host, port=port, log_level="info")
        return 0

    # Upload mode (default)
    upload_dir = Path(args.upload_dir).resolve()
    ensure_directory(upload_dir)
    app = build_app(token_store=token_store, upload_dir=upload_dir, exit_on_upload=args.exit_on_upload)
    url = f"http://{local_ip}:{port}/upload/{token}"

    print('\nStart with "--exit-on-upload" to exit the server after the first successful upload.')
    print("\nScan this QR code to open the upload page on your local network:\n")
    print_qr(url)
    print(f"\nURL: {url}")
    print(f"Expires at (UTC): {expires_at.isoformat()}\n")
    print("Press Ctrl+C to stop the server.")
    uvicorn.run(app, host=args.host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\nShutting down…")
        raise


