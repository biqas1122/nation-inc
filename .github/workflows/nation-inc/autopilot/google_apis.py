"""Google auth (one refresh token) + Sheets calendar + YouTube upload."""
import datetime as dt
import time

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]
TAB = "Calendar"
HEADER = ["Date", "Title", "Angle", "Status", "YouTube link", "Notes", "Updated"]
STATUSES = ["Planned", "Producing", "Ready", "Uploaded", "Failed", "Skip"]


def creds(cfg) -> Credentials:
    c = Credentials(
        token=None,
        refresh_token=cfg["google_refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=cfg["google_client_id"],
        client_secret=cfg["google_client_secret"],
        scopes=SCOPES,
    )
    try:
        c.refresh(Request())
    except Exception as e:
        raise RuntimeError(
            "Google login failed — the refresh token is invalid or expired. If your OAuth app is in 'Testing' mode, "
            "tokens expire after 7 days: publish the app ('In production') and create a new token. Details: " + str(e))
    return c


# ---------------- Sheets ----------------

class Calendar:
    def __init__(self, cfg, credentials):
        self.cfg = cfg
        self.api = build("sheets", "v4", credentials=credentials, cache_discovery=False).spreadsheets()
        self.id = cfg.get("sheet_id")

    @property
    def url(self):
        return f"https://docs.google.com/spreadsheets/d/{self.id}/edit"

    def ensure(self):
        """Creates the calendar spreadsheet on first run. Returns True if newly created."""
        if self.id:
            meta = self.api.get(spreadsheetId=self.id).execute()
            if not any(s["properties"]["title"] == TAB for s in meta["sheets"]):
                self.api.batchUpdate(spreadsheetId=self.id, body={"requests": [{"addSheet": {"properties": {"title": TAB}}}]}).execute()
                self._format(self._tab_id())
            return False
        body = {"properties": {"title": "Tube Autopilot — Content Calendar"}, "sheets": [{"properties": {"title": TAB}}]}
        res = self.api.create(body=body, fields="spreadsheetId,sheets.properties.sheetId").execute()
        self.id = res["spreadsheetId"]
        self._format(res["sheets"][0]["properties"]["sheetId"])
        return True

    def _tab_id(self):
        meta = self.api.get(spreadsheetId=self.id).execute()
        return next(s["properties"]["sheetId"] for s in meta["sheets"] if s["properties"]["title"] == TAB)

    def _format(self, sid):
        self.api.values().update(spreadsheetId=self.id, range=f"{TAB}!A1:G1", valueInputOption="RAW", body={"values": [HEADER]}).execute()
        widths = [110, 380, 420, 110, 260, 320, 150]
        reqs = [
            {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
            {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                            "cell": {"userEnteredFormat": {"backgroundColor": {"red": 0.05, "green": 0.05, "blue": 0.05},
                                                           "textFormat": {"bold": True, "foregroundColor": {"red": 0.83, "green": 0.69, "blue": 0.22}}}},
                            "fields": "userEnteredFormat(backgroundColor,textFormat)"}},
            {"setDataValidation": {"range": {"sheetId": sid, "startRowIndex": 1, "startColumnIndex": 3, "endColumnIndex": 4},
                                   "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": s} for s in STATUSES]}, "showCustomUi": True}}},
        ] + [{"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
                                            "properties": {"pixelSize": w}, "fields": "pixelSize"}} for i, w in enumerate(widths)]
        self.api.batchUpdate(spreadsheetId=self.id, body={"requests": reqs}).execute()

    def write_research(self, data):
        """Replaces the 'Research' tab with the latest competitor outliers."""
        tab = "Research"
        meta = self.api.get(spreadsheetId=self.id).execute()
        if not any(sh["properties"]["title"] == tab for sh in meta["sheets"]):
            self.api.batchUpdate(spreadsheetId=self.id, body={"requests": [{"addSheet": {"properties": {"title": tab}}}]}).execute()
        rows = [[f"Updated {data.get('updated', '')} — videos that beat their own channel's median the most (last 12 months)"],
                ["Multiple", "Views", "Title", "Channel", "Published", "Minutes", "Link"]]
        for v in data.get("top_videos", []):
            rows.append([v["multiple"], v["views"], v["title"], v["channel"], v["published"], v["minutes"], v["url"]])
        rows += [[""], ["Competitor", "Subscribers", "Median views", "Long videos (12 months)"]]
        for c in data.get("competitors", []):
            rows.append([c["title"], c["subs"], c["median_views"], c["long_videos_12m"]])
        self.api.values().clear(spreadsheetId=self.id, range=f"{tab}!A:Z").execute()
        self.api.values().update(spreadsheetId=self.id, range=f"{tab}!A1", valueInputOption="RAW",
                                 body={"values": rows}).execute()

    def rows(self):
        vals = self.api.values().get(spreadsheetId=self.id, range=f"{TAB}!A2:G").execute().get("values", [])
        out = []
        for i, r in enumerate(vals):
            r = (r + [""] * 7)[:7]
            out.append({"row": i + 2, "date": r[0].strip(), "title": r[1].strip(), "angle": r[2].strip(),
                        "status": r[3].strip() or "Planned", "link": r[4], "notes": r[5]})
        return [r for r in out if r["title"]]

    def append(self, items):
        values = [[i["date"], i["title"], i.get("angle", ""), "Planned", "", i.get("notes", ""), ""] for i in items]
        self.api.values().append(spreadsheetId=self.id, range=f"{TAB}!A:G", valueInputOption="USER_ENTERED",
                                 insertDataOption="INSERT_ROWS", body={"values": values}).execute()

    def update(self, row, status=None, link=None, notes=None, now=""):
        cur = self.api.values().get(spreadsheetId=self.id, range=f"{TAB}!D{row}:G{row}").execute().get("values", [[]])
        cur = ((cur[0] if cur else []) + [""] * 4)[:4]
        new = [status if status is not None else cur[0], link if link is not None else cur[1],
               notes if notes is not None else cur[2], now]
        self.api.values().update(spreadsheetId=self.id, range=f"{TAB}!D{row}:G{row}", valueInputOption="USER_ENTERED",
                                 body={"values": [new]}).execute()


# ---------------- YouTube ----------------

def _clean_tags(tags):
    out, n = [], 0
    for t in tags or []:
        t = str(t).replace("<", "").replace(">", "").strip()
        add = len(t) + (2 if " " in t else 0) + 1
        if t and n + add <= 480:
            out.append(t)
            n += add
    return out


def upload_video(credentials, cfg, video_path, thumb_path, title, description, tags, publish_at: dt.datetime | None):
    yt = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    mode = cfg.get("publish_mode", "private")
    status = {"selfDeclaredMadeForKids": False}
    if mode == "scheduled" and publish_at:
        status.update(privacyStatus="private", publishAt=publish_at.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    else:
        status["privacyStatus"] = mode if mode in ("public", "unlisted", "private") else "private"
    body = {
        "snippet": {
            "title": str(title).replace("<", "").replace(">", "")[:100],
            "description": str(description).replace("<", "").replace(">", "")[:4900],
            "tags": _clean_tags(tags),
            "categoryId": str(cfg.get("category_id", "27")),
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": status,
    }
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", chunksize=16 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp, retries = None, 0
    while resp is None:
        try:
            st, resp = req.next_chunk()
            if st:
                print(f"[youtube] upload {int(st.progress() * 100)}%", flush=True)
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and retries < 6:
                retries += 1
                time.sleep(5 * retries)
                continue
            raise RuntimeError(f"YouTube upload failed: {e}")
    vid = resp["id"]
    print(f"[youtube] uploaded https://youtu.be/{vid}", flush=True)
    if thumb_path:
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb_path), mimetype="image/jpeg")).execute()
            print("[youtube] thumbnail set", flush=True)
        except HttpError as e:
            print(f"[youtube] thumbnail not set (channel must be phone-verified): {e}", flush=True)
    return vid
