"""Content calendar stored in the GitHub repo (state/calendar.csv).

Used until Google Sheets is connected; same methods as google_apis.Calendar so the rest of the code
doesn't care where the calendar lives. The workflow commits state/ after every run.
"""
import csv

from .config import STATE

PATH = STATE / "calendar.csv"
FIELDS = ["Date", "Title", "Angle", "Status", "YouTube link", "Notes", "Updated"]


class RepoCalendar:
    url = "GitHub repo → state/calendar.csv"

    def _read(self):
        if not PATH.exists():
            return []
        with open(PATH, newline="", encoding="utf-8") as f:
            return [r for r in csv.DictReader(f)]

    def _write(self, rows):
        STATE.mkdir(exist_ok=True)
        with open(PATH, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in FIELDS})

    def rows(self):
        out = []
        for i, r in enumerate(self._read()):
            if not (r.get("Title") or "").strip():
                continue
            out.append({"row": i + 2, "date": (r.get("Date") or "").strip(), "title": r["Title"].strip(),
                        "angle": (r.get("Angle") or "").strip(), "status": (r.get("Status") or "").strip() or "Planned",
                        "link": r.get("YouTube link", ""), "notes": r.get("Notes", "")})
        return out

    def append(self, items):
        rows = self._read()
        for it in items:
            rows.append({"Date": it["date"], "Title": it["title"], "Angle": it.get("angle", ""), "Status": "Planned",
                         "Notes": it.get("notes", "")})
        self._write(rows)

    def update(self, row, status=None, link=None, notes=None, now=""):
        rows = self._read()
        i = row - 2
        if 0 <= i < len(rows):
            if status is not None:
                rows[i]["Status"] = status
            if link is not None:
                rows[i]["YouTube link"] = link
            if notes is not None:
                rows[i]["Notes"] = notes
            rows[i]["Updated"] = now
            self._write(rows)

    def write_research(self, data):
        pass   # research is already saved as state/research.md
