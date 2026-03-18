"""
UI routes — serve HTML pages and file upload endpoints.
"""
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["ui"])

DASHBOARD_HTML = Path("dashboard.html")
KITE_LOGIN_HTML = Path("kite-login.html")
DEBUG_HTML = Path("debug.html")
ESP_SETUP_HTML = Path("esp-setup.html")
TEST_CORS_HTML = Path("test_cors.html")
API_EXPLORER_HTML = Path("api-explorer.html")
UPLOAD_DIR = Path("uploads")


def _read_html(path: Path, fallback: str) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return fallback


@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the main trading dashboard."""
    return _read_html(DASHBOARD_HTML, "<h1>Dashboard not found</h1>")


@router.get("/test-cors", response_class=HTMLResponse)
async def test_cors_page():
    """CORS test page."""
    return _read_html(TEST_CORS_HTML, "<h1>CORS test page not found</h1>")


@router.get("/esp-setup", response_class=HTMLResponse)
async def esp_setup_page():
    """ESP8266 hardware setup guide."""
    return _read_html(ESP_SETUP_HTML, "<h1>ESP Setup file not found</h1>")


@router.get("/kite-login", response_class=HTMLResponse)
async def kite_login_page():
    """Kite OAuth login / token exchange page."""
    return _read_html(KITE_LOGIN_HTML, "<h1>Kite login page not found</h1>")


@router.get("/debug", response_class=HTMLResponse)
async def debug_page():
    """Debug page."""
    return _read_html(DEBUG_HTML, "<h1>Debug file not found</h1>")


@router.get("/api-explorer", response_class=HTMLResponse)
async def api_explorer_page():
    """Melon API Explorer — Postman-style API testing UI."""
    return _read_html(API_EXPLORER_HTML, "<h1>API Explorer not found</h1>")


@router.get("/upload", response_class=HTMLResponse)
async def upload_page():
    """File upload page (served from dashboard.html fallback inline)."""
    # Prefer a standalone upload.html if present
    upload_html = Path("upload.html")
    if upload_html.exists():
        return upload_html.read_text(encoding="utf-8")
    # Minimal fallback
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Upload | Melon Bot</title>
    <style>body{background:#0d0d14;color:#e2e8f0;font-family:system-ui,sans-serif;padding:2rem;}</style>
</head>
<body>
<h1>Upload Files</h1>
<form action="/api/upload" method="post" enctype="multipart/form-data">
    <input type="file" name="file" required>
    <button type="submit">Upload</button>
</form>
<p><a href="/dashboard" style="color:#22c55e">← Dashboard</a></p>
</body>
</html>"""


@router.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Handle file upload."""
    UPLOAD_DIR.mkdir(exist_ok=True)
    file_path = UPLOAD_DIR / file.filename
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {
            "status": "success",
            "message": f"File '{file.filename}' uploaded successfully",
            "filename": file.filename,
            "path": str(file_path),
            "size": file_path.stat().st_size,
        }
    except Exception as e:
        return {"status": "error", "message": f"Upload failed: {e}"}
    finally:
        file.file.close()


@router.get("/api/uploaded-files")
async def list_uploaded_files():
    """List all uploaded files."""
    if not UPLOAD_DIR.exists():
        return {"files": []}
    files = [
        {
            "name": f.name,
            "size": f.stat().st_size,
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        }
        for f in UPLOAD_DIR.iterdir()
        if f.is_file()
    ]
    return {"files": sorted(files, key=lambda x: x["modified"], reverse=True)}
