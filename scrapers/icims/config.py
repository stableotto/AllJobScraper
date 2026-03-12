"""iCIMS-specific configuration."""

# Many iCIMS portals use a Jibe frontend wrapper.
# The Jibe API endpoint pattern is: {portal_url}/api/jobs
# The raw iCIMS endpoint pattern is: careers-{slug}.icims.com/jobs/search
#
# We attempt the Jibe API first (cleaner, returns full job data in JSON),
# and fall back to scraping the raw iCIMS portal if needed.

# Default Jibe API path
JIBE_API_PATH = "/api/jobs"

# Raw iCIMS search path (fallback)
ICIMS_SEARCH_PATH = "/jobs/search"
ICIMS_JOB_DETAIL_PATH = "/jobs/{job_id}/job"

# iCIMS portal base domain
ICIMS_DOMAIN = "icims.com"

# Jibe domain (used for discovery)
JIBE_DOMAIN = "jibeapply.com"

# Default page size (Jibe API typically returns 10-20 per page)
DEFAULT_PAGE_SIZE = 20

# Maximum pages to fetch (safety limit)
MAX_PAGES = 100

# Categories commonly used for nursing in iCIMS portals
NURSING_CATEGORIES = [
    "Nursing",
    "Clinical Professional",
    "Patient Care",
    "Clinical",
    "Registered Nurse",
]
