"""Phone notifications to the channel owner.

Telegram (recommended, free and reliable):
  1. In Telegram open @BotFather → /newbot → give any name → it replies with a TOKEN.
  2. Open your new bot in Telegram and press START (or send "hi").
  3. Add GitHub secret TELEGRAM_BOT_TOKEN = that token. (TELEGRAM_CHAT_ID is optional — it is found
     automatically from your message and remembered in state/telegram.json.)

WhatsApp (CallMeBot, optional): secrets WHATSAPP_PHONE + WHATSAPP_APIKEY.

If nothing is set up, messages are just printed in the log.
"""
import json
import os
from pathlib import Path

import requests

STATE = Path(__file__).resolve().parent.parent / "state" / "telegram.json"


def log(msg):
    print(f"[notify] {msg}", flush=True)


def _telegram_chat(token):
    cid = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if cid:
        return cid
    try:
        cid = json.loads(STATE.read_text()).get("chat_id")
        if cid:
            return str(cid)
    except Exception:
        pass
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30).json()
        for u in reversed(r.get("result", [])):
            msg = u.get("message") or u.get("edited_message") or {}
            chat = msg.get("chat", {})
            if chat.get("type") == "private" and chat.get("id"):
                cid = str(chat["id"])
                STATE.parent.mkdir(parents=True, exist_ok=True)
                STATE.write_text(json.dumps({"chat_id": cid}))
                log("Telegram chat found and saved")
                return cid
    except Exception as e:
        log(f"Telegram chat lookup failed: {e}")
    return None


def telegram(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return False
    cid = _telegram_chat(token)
    if not cid:
        log("Telegram: no chat found — open your bot in Telegram, press START, then run again.")
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": cid, "text": text[:4000], "disable_web_page_preview": "true"}, timeout=60)
        ok = r.status_code == 200 and r.json().get("ok")
        log("Telegram message sent" if ok else f"Telegram send failed ({r.status_code}): {r.text[:200]}")
        return bool(ok)
    except requests.RequestException as e:
        log(f"Telegram send failed: {e}")
        return False


def _whatsapp(text: str) -> bool:
    phone = os.environ.get("WHATSAPP_PHONE", "").strip()
    key = os.environ.get("WHATSAPP_APIKEY", "").strip()
    if not phone or not key:
        return False
    try:
        r = requests.get("https://api.callmebot.com/whatsapp.php",
                         params={"phone": phone, "text": text[:1500], "apikey": key}, timeout=60)
        ok = r.status_code == 200 and "error" not in r.text.lower()[:200]
        log("WhatsApp message sent" if ok else f"WhatsApp send failed ({r.status_code}): {r.text[:200]}")
        return ok
    except requests.RequestException as e:
        log(f"WhatsApp send failed: {e}")
        return False


def send(text: str) -> bool:
    """Sends to every channel that is set up (Telegram and/or WhatsApp)."""
    sent = telegram(text)
    sent = _whatsapp(text) or sent
    if not sent:
        log("No phone notification set up (TELEGRAM_BOT_TOKEN or WHATSAPP_*) — message was:\n" + text)
    return sent


# old name, kept so the rest of the code works unchanged
whatsapp = send
