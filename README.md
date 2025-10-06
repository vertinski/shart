```text
  ███████╗██╗  ██╗ █████╗ ██████╗ ████████╗
  ██╔════╝██║  ██║██╔══██╗██╔══██╗╚══██╔══╝
  ███████╗███████║███████║██████╔╝   ██║   
  ╚════██║██╔══██║██╔══██║██╔══██╗   ██║   
  ███████║██║  ██║██║  ██║██║  ██║   ██║   
  ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   
               (oc) Vertinski 2025, 2026
```

# Shart - Airdrop-like utility for fast file sharing

Temporary, local-first file upload/share server built with FastAPI. It prints a QR code to your terminal so you can quickly open an upload or download page from your phone or another device on the same network. Links automatically expire after a configurable TTL.

> Intended for quick, trusted, same-network transfers. Not a hardened internet-facing service.

## Features
- Upload multiple files from any device via a simple web page
- Share one or more files or entire directories (dirs are auto-zipped)
- Time-limited links guarded by per-session tokens
- QR code printed in the terminal for easy device access
- Optional auto-exit after first successful upload/download
- Clean, minimalist UI served from `/static`

## Requirements
- Python ≥ 3.10

Runtime dependencies (installed automatically):
- fastapi, uvicorn[standard], qrcode, python-multipart

## Install
```bash
# Clone the repo
git clone https://github.com/your-user/shart.git
cd shart

# (Recommended) create a virtualenv
python -m venv .venv
. .venv/bin/activate

# Install
pip install -U pip
pip install -e .
```

You can also run the script directly without installing:
```bash
python main.py --help
```

## Quick Start
Start in upload mode (default):
```bash
python main.py
```
You will see:
- A QR code printed in the terminal
- A URL like `http://<your-local-ip>:<port>/upload/<token>`
Open the URL on your phone/laptop and upload files. Files are saved under `uploads/` by default, with a timestamp prefix.

Start in share mode to send files/directories to another device:
```bash
python main.py --share path/to/file1 path/to/dir2
```
You will see a share page URL like `http://<local-ip>:<port>/share/<token>` listing downloadable items.

## CLI Reference
```text
usage: main.py [-h] [--host HOST] [--port PORT] [--ttl-minutes TTL_MINUTES]
              [--upload-dir UPLOAD_DIR] [--exit-on-upload]
              [--share SHARE [SHARE ...]]
```
- `--host` (default: `0.0.0.0`): bind address
- `--port` (default: auto): port to bind (random free port if omitted)
- `--ttl-minutes` (default: `15`): minutes until the token expires
- `--upload-dir` (default: `uploads`): where uploaded files are stored
- `--exit-on-upload`: exit server after the first successful upload/download
- `--share ...`: enable share mode and list one or more files/dirs to share

Tips:
- Add `--exit-on-upload` if you just want a one-off transfer session.
- Directories listed with `--share` are zipped automatically into temporary files.

## How It Works
- On startup, a random token is generated and stored with an expiration (
  `--ttl-minutes`).
- The server binds to `--host` and either the given `--port` or an available
  ephemeral port.
- The local IPv4 address is detected and used to construct the share/upload URL.
- A QR code of the URL is rendered in the terminal for quick device access.
- In upload mode:
  - `GET /upload/{token}` serves a page with a drag-and-drop uploader.
  - Files are sent as `multipart/form-data` under field name `files`.
  - Saved filenames are sanitized and prefixed with a UTC timestamp.
- In share mode:
  - `GET /share/{token}` lists files; `GET /download/{token}/{item_id}` serves the item.
  - Directories are zipped into a temporary directory for the session lifetime.
- If `--exit-on-upload` is set, the server exits after the first successful
  upload (or first completed download in share mode).

## API
All routes require a valid, non-expired `{token}`. Invalid/expired tokens return 404.

**Common**
- `GET /health` → `"ok"` (text)

**Upload mode**
- `GET /upload/{token}` → HTML upload UI
- `POST /api/upload/{token}` → JSON
  - Request: `multipart/form-data` with one or more `files` parts
  - Response: `{ "saved": ["20250101T120000_filename.ext", ...] }`

**Share mode**
- `GET /share/{token}` → HTML list of shared items
- `GET /download/{token}/{item_id}` → file download (sets `Content-Disposition`)

### cURL examples
Upload two files:
```bash
curl -fSsi -X POST \
  -F "files=@/path/to/a.txt" \
  -F "files=@/path/to/photo.jpg" \
  "http://<ip>:<port>/api/upload/<token>"
```
Download the first item listed on the share page:
```bash
curl -fSLo downloaded.bin "http://<ip>:<port>/download/<token>/0"
```

## Configuration Notes
- Upload directory: controlled by `--upload-dir` (created if missing)
- Filenames: sanitized to alphanumerics plus `-_.() ` and timestamp-prefixed
- Directory sharing: zipped via `shutil.make_archive` into a temp dir
- Static assets: served under `/static` from `static/`
- ASCII logo: if `ascii_logo.txt` exists, it is printed at startup and embedded in pages

## Security Considerations
- Token and TTL only provide basic access control; there is no authentication.
- Designed for same-network use. Do not expose directly to the public internet.
- Files are stored on disk; review and clean `uploads/` after use.
- Tokens are in-memory only; restarting the process invalidates prior links.

## Troubleshooting
- QR code not scannable: ensure your device is on the same network and your terminal supports unicode; enlarge your window if needed.
- Can’t connect from phone: check firewall rules; ensure the host IP is reachable from your device.
- Port in use: specify a free port with `--port`.
- 404 on upload/share page: token may have expired (default 15 minutes). Restart or increase `--ttl-minutes`.

## Development
Run locally without install:
```bash
python main.py --ttl-minutes 60
```
Edit static assets under `static/`. The FastAPI app mounts them at `/static`.

Project layout:
```text
.
├── main.py           # App entrypoint and FastAPI app builders
├── static/           # Frontend HTML/CSS/JS for upload/share pages
├── uploads/          # Default upload destination (created at runtime)
├── ascii_logo.txt    # Optional ASCII art embedded in UI/terminal
├── pyproject.toml    # Project metadata and dependencies
└── README.md         # This file
```

### Running via module
```bash
python -m main --help
```

### Packaging
This project uses `pyproject.toml` with `setuptools`. Editable install is supported:
```bash
pip install -e .
```

## License
This project is licensed under MIT license.
