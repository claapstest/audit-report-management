from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ASSET_VERSION = int((BASE_DIR / "static" / "style.css").stat().st_mtime)
