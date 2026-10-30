# Nation Inc. Autopilot

Every country explained as if it were a company — made automatically on GitHub Actions:
research → 30-day plan → verified data (World Bank + Wikidata) → script (Gemini) → voice → footage + flags + charts
→ Remotion edit (company card, revenue charts, captions) → thumbnail + upload kit + 4 Shorts → **Releases** page.

- Schedule: Mon / Wed / Fri (see `.github/workflows/autopilot.yml`), research on the 1st and 16th.
- Secrets: `GEMINI_API_KEY`, `PIXABAY_API_KEY`, `YOUTUBE_API_KEY`. Optional variable: `CHANNEL_NAME`.
- Finished videos: repo → **Releases** (kept 5 days).
