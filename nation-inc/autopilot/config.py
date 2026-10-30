import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
MUSIC = ROOT / "music"
STATE = ROOT / "state"
OUT = ROOT / "out"
WORK = ROOT / "work"


def load_config() -> dict:
    with open(ROOT / "config.json", encoding="utf-8") as f:
        cfg = json.load(f)
    env = os.environ
    cfg["gemini_key"] = env.get("GEMINI_API_KEY", "").strip()
    cfg["pixabay_key"] = env.get("PIXABAY_API_KEY", "").strip()
    cfg["pexels_key"] = env.get("PEXELS_API_KEY", "").strip()
    cfg["elevenlabs_key"] = env.get("ELEVENLABS_API_KEY", "").strip()
    cfg["google_client_id"] = env.get("GOOGLE_CLIENT_ID", "").strip()
    cfg["google_client_secret"] = env.get("GOOGLE_CLIENT_SECRET", "").strip()
    cfg["google_refresh_token"] = env.get("GOOGLE_REFRESH_TOKEN", "").strip()
    cfg["sheet_id"] = env.get("SHEET_ID", "").strip() or _saved_sheet_id()
    cfg["youtube_api_key"] = env.get("YOUTUBE_API_KEY", "").strip()
    if env.get("CHANNEL_NAME"):
        cfg["channel_name"] = env["CHANNEL_NAME"].strip()
    return cfg


def _saved_sheet_id() -> str:
    p = STATE / "sheet.json"
    if p.exists():
        return json.loads(p.read_text()).get("sheet_id", "")
    return ""


def save_sheet_id(sheet_id: str, url: str) -> None:
    STATE.mkdir(exist_ok=True)
    (STATE / "sheet.json").write_text(json.dumps({"sheet_id": sheet_id, "url": url}, indent=2))


def require(cfg: dict, *keys: str) -> None:
    names = {
        "gemini_key": "GEMINI_API_KEY",
        "pixabay_key": "PIXABAY_API_KEY",
        "pexels_key": "PEXELS_API_KEY",
        "elevenlabs_key": "ELEVENLABS_API_KEY",
        "google_client_id": "GOOGLE_CLIENT_ID",
        "google_client_secret": "GOOGLE_CLIENT_SECRET",
        "google_refresh_token": "GOOGLE_REFRESH_TOKEN",
        "youtube_api_key": "YOUTUBE_API_KEY",
    }
    missing = [names.get(k, k) for k in keys if not cfg.get(k)]
    if missing:
        raise SystemExit("Missing GitHub secrets: " + ", ".join(missing) + " (Settings → Secrets and variables → Actions)")
