"""TalentBrew/Radancy scraper configuration."""

# Pagination
DEFAULT_PAGE_SIZE = 15  # TalentBrew typically shows 15 jobs per page
MAX_PAGES = 50  # Safety limit
MAX_JOBS = 1000  # Safety limit

# Request settings
REQUEST_TIMEOUT = 30
RATE_LIMIT = 1.5  # seconds between requests

# TalentBrew detection patterns
TALENTBREW_INDICATORS = [
    "tbcdn.talentbrew.com",
    "talentbrew.com",
    "radancy.net",
]
