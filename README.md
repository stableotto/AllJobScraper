# NurseScraper — ATS Job Scraper for Healthcare

Modular scraper system targeting major ATS platforms to collect nursing/clinical job postings from hospitals and medical groups.

## Supported ATS Platforms

| Platform | Status | Method |
|----------|--------|--------|
| **iCIMS** | ✅ Ready | Jibe API (JSON) + raw HTML fallback |
| **Workday** | 🔜 Planned | — |
| **Taleo** | 🔜 Planned | — |
| **Oracle** | 🔜 Planned | — |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Scrape all iCIMS portals (nursing jobs only)
python main.py scrape --ats icims

# Scrape a specific portal
python main.py scrape --ats icims --portal uci

# Scrape all jobs (not just nursing)
python main.py scrape --ats icims --all-jobs

# Dry run (no export, just preview)
python main.py scrape --ats icims --portal uci --dry-run

# Discover iCIMS portals (with subdomain enumeration)
python main.py discover --ats icims --enum

# Verbose logging
python main.py -v scrape --ats icims --portal uci
```

## Project Structure

```
NurseScraper/
├── scrapers/
│   ├── base.py              # Abstract base scraper (rate limiting, retries, UA rotation)
│   └── icims/
│       ├── scraper.py        # iCIMS job scraper (Jibe API + raw HTML)
│       ├── discovery.py      # Find companies using iCIMS
│       └── config.py         # iCIMS-specific settings
├── models/
│   ├── job.py                # Unified Job data model
│   └── company.py            # Company/portal registry
├── storage/
│   └── export.py             # CSV + JSON export with deduplication
├── config/
│   ├── portals.yaml          # Registry of portals to scrape
│   └── settings.py           # Global settings
├── .github/workflows/
│   └── scrape.yml            # GitHub Actions (every 6h + manual)
├── data/                     # Output directory (gitignored)
├── main.py                   # CLI entry point
└── requirements.txt
```

## Adding New Portals

Edit `config/portals.yaml` to add new iCIMS portals:

```yaml
icims:
  - name: "Hospital Name"
    url: "https://careers.hospital.org"
    ats_slug: "hospital"
    sector: "hospital"
    state: "CA"
```

## GitHub Actions

The scraper runs automatically every 6 hours via GitHub Actions. You can also trigger it manually:

1. Go to **Actions** → **ATS Job Scraper**
2. Click **Run workflow**
3. Choose the ATS platform and optional portal filter

Scraped data is committed back to the `data/` directory and also uploaded as a workflow artifact.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SCRAPE_RATE_LIMIT` | `1.5` | Seconds between requests |
| `SCRAPE_TIMEOUT` | `30` | Request timeout in seconds |
| `SCRAPE_MAX_RETRIES` | `3` | Max retry attempts |
| `OUTPUT_FORMAT` | `both` | `csv`, `json`, or `both` |
| `LOG_LEVEL` | `INFO` | Logging level |
