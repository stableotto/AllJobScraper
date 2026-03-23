"""Abstract base scraper with rate limiting, retries, and User-Agent rotation."""

from __future__ import annotations

import abc
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests
from fake_useragent import UserAgent
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from models.job import Job
from models.company import Company

logger = logging.getLogger(__name__)


class BaseScraper(abc.ABC):
    """Base class all ATS scrapers must extend."""

    ATS_NAME: str = "base"  # Override in subclass

    def __init__(
        self,
        company: Company,
        *,
        rate_limit: float = 1.5,  # seconds between requests
        max_retries: int = 3,
        timeout: int = 30,
    ):
        self.company = company
        self.rate_limit = rate_limit
        self.max_retries = max_retries
        self.timeout = timeout
        self._session = self._build_session()
        self._last_request_time = 0.0
        self._request_lock = threading.Lock()
        self._ua = UserAgent(fallback="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")

    def _build_session(self) -> requests.Session:
        """Create a requests session with default headers."""
        session = requests.Session()
        session.headers.update(
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
            }
        )
        return session

    def _rotate_user_agent(self) -> None:
        """Rotate the User-Agent header to avoid detection."""
        self._session.headers["User-Agent"] = self._ua.random

    def _throttle(self) -> None:
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        jitter = random.uniform(0, 0.5)
        wait_time = self.rate_limit + jitter - elapsed
        if wait_time > 0:
            time.sleep(wait_time)
        self._last_request_time = time.time()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
        before_sleep=lambda retry_state: logger.warning(
            f"Retrying request (attempt {retry_state.attempt_number})..."
        ),
    )
    def _get(self, url: str, **kwargs) -> requests.Response:
        """Rate-limited GET request with retries and UA rotation."""
        with self._request_lock:
            self._throttle()
            self._rotate_user_agent()
        kwargs.setdefault("timeout", self.timeout)
        response = self._session.get(url, **kwargs)
        response.raise_for_status()
        return response

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    )
    def _post(self, url: str, **kwargs) -> requests.Response:
        """Rate-limited POST request with retries and UA rotation."""
        with self._request_lock:
            self._throttle()
            self._rotate_user_agent()
        kwargs.setdefault("timeout", self.timeout)
        response = self._session.post(url, **kwargs)
        response.raise_for_status()
        return response

    # --- Abstract interface ---

    @abc.abstractmethod
    def discover_jobs(self, keyword: Optional[str] = None, **kwargs) -> list[Job]:
        """
        Fetch all job listings from this company's portal.

        Args:
            keyword: Optional keyword filter (e.g., "nurse", "RN")
            **kwargs: Additional options (e.g., today_only for early termination)

        Returns:
            List of Job objects
        """
        ...

    @abc.abstractmethod
    def scrape_job_detail(self, job: Job) -> Job:
        """
        Fetch full details for a single job posting.

        Args:
            job: A Job with at minimum an id and url populated

        Returns:
            The same Job object enriched with full details
        """
        ...

    @staticmethod
    def extract_salary_from_text(text: str) -> Optional[str]:
        """Extract salary range from description text or HTML.

        Handles formats found across ATS platforms:
          - "Minimum $56.96 Midpoint $74.05 Maximum $91.14"
          - "Pay Range: $50,000 - $70,000"
          - "Salary ranges ... (USD):$100,000 - $100,000"
          - "The base pay for this position is $218,700.00 – $437,300.00"
          - "$25.00 - $35.00 per hour"
        """
        import re as _re

        if not text:
            return None

        # Strip HTML tags for cleaner matching
        clean = _re.sub(r"<[^>]+>", " ", text)
        # Normalise whitespace
        clean = _re.sub(r"\s+", " ", clean)

        patterns = [
            # Minimum / Maximum (Workday)
            (r"Minimum\s*\$?([\d,]+\.?\d*)\s*(?:Midpoint\s*\$?[\d,]+\.?\d*)?\s*Maximum\s*\$?([\d,]+\.?\d*)", False),
            # Keyword-prefixed range: "Pay Range:", "Salary:", "Base pay ... is", "Compensation:"
            (r"(?:pay\s*range|salary\s*range|base\s*pay|compensation|hourly\s*range|wage)[^$]{0,40}\$\s*([\d,]+\.?\d*)\s*[-–—to]+\s*\$\s*([\d,]+\.?\d*)", False),
            # Per-hour / per-year suffix (allow small amounts like $25/hr)
            (r"\$([\d,]+\.?\d*)\s*[-–—to]+\s*\$([\d,]+\.?\d*)\s*(?:per\s*(?:hour|year)|/hr|/yr|hourly|annually)", False),
            # Generic $X – $Y (require amounts >= $1,000 to avoid false positives)
            (r"\$([\d,]+\.?\d*)\s*[-–—]\s*\$([\d,]+\.?\d*)", True),
        ]

        for pattern, check_min in patterns:
            match = _re.search(pattern, clean, _re.IGNORECASE)
            if match:
                groups = [g for g in match.groups() if g]
                if len(groups) >= 2:
                    hi = float(groups[-1].replace(",", ""))
                    # For the generic pattern, skip small amounts (likely false positives)
                    if check_min and hi < 1000:
                        continue
                    return f"${groups[0]} - ${groups[-1]}"
        return None

    def _filter_recent_jobs(self, jobs: list[Job]) -> list[Job]:
        """
        Filter jobs to only those posted within the last 2 days.

        Uses listing data (raw_data) before details are fetched when possible.
        This enables filtering BEFORE the expensive detail fetch.
        """
        import re
        from datetime import date, timedelta

        today = date.today()
        cutoff = today - timedelta(days=2)
        filtered = []

        for job in jobs:
            # Check posted_date if already parsed
            if job.posted_date:
                job_date = job.posted_date.date() if hasattr(job.posted_date, 'date') else job.posted_date
                if job_date >= cutoff:
                    filtered.append(job)
                    continue

            # Check raw listing data for posted text
            raw = job.raw_data or {}
            posted_on = ""

            # Workday: listing.posted_on
            if "listing" in raw:
                posted_on = raw["listing"].get("posted_on", "")
            # iCIMS: posted_date or postedOn
            elif "posted_date" in raw:
                posted_on = raw.get("posted_date", "")
            elif "postedOn" in raw:
                posted_on = raw.get("postedOn", "")

            if not posted_on:
                continue

            posted_lower = posted_on.lower().strip()

            # Match "Posted Today", "Just Posted", "Posted Yesterday"
            if any(term in posted_lower for term in ["today", "yesterday", "just posted", "new"]):
                filtered.append(job)
                continue

            # Match "Posted X Days Ago" — allow up to 2 days
            days_match = re.search(r'(\d+)\+?\s*day', posted_lower)
            if days_match:
                days_ago = int(days_match.group(1))
                if days_ago <= 2:
                    filtered.append(job)
                continue

            # Try parsing as an actual date string (e.g., "2026-03-22", "03/22/2026")
            try:
                from dateutil.parser import parse as parse_date
                parsed = parse_date(posted_on, fuzzy=True)
                if parsed.date() >= cutoff:
                    filtered.append(job)
            except (ValueError, TypeError, OverflowError):
                pass

        return filtered

    def _fetch_details_concurrent(
        self, jobs: list[Job], max_workers: int = 6
    ) -> list[Job]:
        """Fetch job details using a thread pool for speed.

        Temporarily lowers the per-request rate limit so threads can overlap
        network I/O while still spacing requests enough to avoid blocks.
        """
        if not jobs:
            return []

        total = len(jobs)
        results: list[tuple[int, Job]] = []
        failed = 0

        # Lower rate limit during concurrent fetch — the lock still serialises
        # the throttle check, so effective request rate ≈ 1/rate_limit.
        # 0.3s × 6 workers ≈ 1.8s per batch of 6 → ~3.3 req/s overall.
        saved_rate = self.rate_limit
        self.rate_limit = 0.3

        def _fetch_one(idx_job: tuple[int, Job]) -> tuple[int, Job | None]:
            idx, job = idx_job
            try:
                return idx, self.scrape_job_detail(job)
            except Exception as e:
                logger.error(f"[{self.ATS_NAME}] Failed job {job.id}: {e}")
                return idx, None

        try:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(_fetch_one, (i, j)): i for i, j in enumerate(jobs)}
                done_count = 0
                for future in as_completed(futures):
                    idx, enriched = future.result()
                    done_count += 1
                    if enriched is not None:
                        results.append((idx, enriched))
                    else:
                        failed += 1
                    if done_count % 50 == 0:
                        logger.info(f"[{self.ATS_NAME}] Detail progress: {done_count}/{total}")
        finally:
            self.rate_limit = saved_rate

        if failed:
            logger.warning(f"[{self.ATS_NAME}] {failed}/{total} detail fetches failed")

        # Return in original order
        results.sort(key=lambda x: x[0])
        return [job for _, job in results]

    def scrape_all(
        self,
        keyword: Optional[str] = None,
        fetch_details: bool = True,
        max_detail_jobs: int = 0,
        today_only: bool = False,
    ) -> list[Job]:
        """
        Full scrape workflow: discover jobs and optionally fetch details.

        Args:
            keyword: Optional keyword filter for the search
            fetch_details: If True, fetch full details for each job (slow).
                          If False, return only listing info (fast).
            max_detail_jobs: Max jobs to fetch details for. 0 = no limit.
                            Only applies when fetch_details=True.
            today_only: If True, filter to jobs posted today/yesterday BEFORE
                       fetching details (much faster for large portals).

        Returns:
            List of Job objects
        """
        logger.info(f"[{self.ATS_NAME}] Scraping {self.company.name} ({self.company.portal_url})")

        # Step 1: Discover all job listings (pass today_only for early termination)
        jobs = self.discover_jobs(keyword=keyword, today_only=today_only)
        logger.info(f"[{self.ATS_NAME}] Found {len(jobs)} job listings")

        # Step 2: Try to filter to today's jobs BEFORE fetching details (huge speedup)
        # If filter drops ALL jobs but we had some, listings likely lack date info —
        # defer filtering to after detail fetch instead
        filter_after_details = False
        if today_only:
            filtered = self._filter_recent_jobs(jobs)
            if filtered or not jobs:
                jobs = filtered
                logger.info(f"[{self.ATS_NAME}] Filtered to {len(jobs)} recent jobs (today/yesterday)")
            else:
                # Listings lack date info; will filter after detail fetch
                filter_after_details = True
                logger.info(f"[{self.ATS_NAME}] Listings lack dates, deferring filter to after detail fetch")

        # Step 3: Optionally fetch full details for each job
        if not fetch_details:
            logger.info(f"[{self.ATS_NAME}] Skipping detail fetch (--skip-details)")
            detailed_jobs = jobs
        else:
            jobs_to_detail = jobs
            if max_detail_jobs > 0 and len(jobs) > max_detail_jobs:
                jobs_to_detail = jobs[:max_detail_jobs]
                logger.info(f"[{self.ATS_NAME}] Fetching details for first {max_detail_jobs} jobs (of {len(jobs)})")

            detailed_jobs = self._fetch_details_concurrent(jobs_to_detail)

        # Step 4: Filter after detail fetch if we deferred earlier
        if filter_after_details:
            # Only filter if at least some jobs have dates — some ATS sites
            # don't expose posted dates at all, so filtering would drop everything
            has_any_dates = any(j.posted_date for j in detailed_jobs)
            if has_any_dates:
                detailed_jobs = self._filter_recent_jobs(detailed_jobs)
                logger.info(f"[{self.ATS_NAME}] Filtered to {len(detailed_jobs)} recent jobs (last 2 days)")
            else:
                logger.info(f"[{self.ATS_NAME}] No posted dates found on detail pages, skipping date filter")

        logger.info(f"[{self.ATS_NAME}] Scraped {len(detailed_jobs)} jobs total")

        # Update company metadata
        self.company.job_count = len(detailed_jobs)
        self.company.verified = True

        return detailed_jobs
