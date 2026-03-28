# Expense Tracker Bot — Roadmap

## Backlog

### Phase 999.1: Automate Google Sheets sync (BACKLOG)

**Goal:** Write a Python script using gspread + sqlalchemy that queries Supabase for last month's expense totals and writes them into the Google Sheet. Store GCP service account JSON in Secret Manager. Schedule via GitHub Actions cron (1st of every month).
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd:review-backlog when ready)

### Phase 999.2: Consolidate data into Supabase (BACKLOG)

**Goal:** Add income and recurring_expenses tables to Supabase. Extend the Telegram bot with /income and /recurring commands following the existing handler pattern. Use pg_cron for auto-generating recurring entries monthly. Eliminates Google Sheets as a data source.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd:review-backlog when ready)

### Phase 999.3: Build Streamlit dashboard (BACKLOG)

**Goal:** Build a unified finance dashboard using Streamlit connected to Supabase Postgres. Visualize monthly inflow/outflow, spending by category, trends over time. Deploy to Streamlit Community Cloud for free hosting.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd:review-backlog when ready)
