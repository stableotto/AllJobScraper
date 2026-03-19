"""Unified Job data model used across all ATS scrapers."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Job:
    """Normalized job posting from any ATS platform."""

    # Identifiers
    id: str  # ATS-specific job ID (e.g., "12345")
    source_ats: str  # "icims" | "workday" | "taleo" | "oracle"
    company_name: str

    # Core fields
    title: str
    department: str = ""
    location: str = ""  # "City, State" or "Remote"
    job_type: str = ""  # Full-time, Part-time, PRN, Per Diem, etc.
    posted_date: Optional[datetime] = None
    url: str = ""  # Direct link to job posting

    # Description
    description: str = ""
    qualifications: str = ""
    salary_range: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None

    # Metadata
    scraped_at: datetime = field(default_factory=datetime.utcnow)
    raw_data: Optional[dict] = field(default=None, repr=False)

    @property
    def unique_key(self) -> str:
        """Generate a deduplication key."""
        raw = f"{self.source_ats}:{self.company_name}:{self.id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _parse_salary(self) -> None:
        """Parse salary_range string into min/max floats."""
        if not self.salary_range:
            return

        # Extract all dollar amounts
        amounts = re.findall(r'\$?([\d,]+(?:\.\d{2})?)', self.salary_range.replace(',', ''))
        if amounts:
            try:
                values = [float(a) for a in amounts]
                # Normalize hourly to annual (assume 2080 hours/year)
                if any(x in self.salary_range.lower() for x in ['hour', '/hr', 'hourly']):
                    values = [v * 2080 for v in values]

                if len(values) >= 2:
                    self.salary_min = min(values)
                    self.salary_max = max(values)
                elif len(values) == 1:
                    self.salary_min = values[0]
                    self.salary_max = values[0]
            except (ValueError, TypeError):
                pass

    def to_dict(self) -> dict:
        """Convert to a serializable dictionary (excludes raw_data)."""
        d = asdict(self)
        d.pop("raw_data", None)
        # Convert datetimes to ISO strings
        for key in ("posted_date", "scraped_at"):
            if d[key] is not None:
                d[key] = d[key].isoformat()
        return d

    def to_csv_row(self) -> dict:
        """Flatten for CSV export."""
        return {
            "unique_key": self.unique_key,
            "source_ats": self.source_ats,
            "company_name": self.company_name,
            "job_id": self.id,
            "title": self.title,
            "department": self.department,
            "location": self.location,
            "job_type": self.job_type,
            "posted_date": self.posted_date.isoformat() if self.posted_date else "",
            "url": self.url,
            "salary_range": self.salary_range or "",
            "salary_min": self.salary_min or "",
            "salary_max": self.salary_max or "",
            "description": self.description[:500],  # Truncate for CSV
            "qualifications": self.qualifications[:500],
            "scraped_at": self.scraped_at.isoformat(),
        }

    def save_to_db(self, conn: sqlite3.Connection, portal_id: int) -> int:
        """Upsert this job into the SQLite database. Returns the row id."""
        from storage.database import upsert_job, _parse_salary

        # Use parsed values if available, otherwise parse from string
        salary_min = self.salary_min
        salary_max = self.salary_max
        if not salary_min and not salary_max and self.salary_range:
            salary_min, salary_max = _parse_salary(self.salary_range)

        return upsert_job(
            conn,
            portal_id=portal_id,
            external_id=self.id,
            title=self.title,
            unique_key=self.unique_key,
            department=self.department,
            location=self.location,
            job_type=self.job_type,
            salary_min=salary_min,
            salary_max=salary_max,
            posted_date=self.posted_date.isoformat() if self.posted_date else None,
            url=self.url,
            description=self.description,
            qualifications=self.qualifications,
        )

    @classmethod
    def from_db_row(cls, row: sqlite3.Row) -> "Job":
        """Reconstruct a Job from a SQLite row (as returned by query_jobs)."""
        posted = None
        if row["posted_date"]:
            try:
                posted = datetime.fromisoformat(row["posted_date"])
            except (ValueError, TypeError):
                pass

        scraped = datetime.utcnow()
        if row["scraped_at"]:
            try:
                scraped = datetime.fromisoformat(row["scraped_at"])
            except (ValueError, TypeError):
                pass

        salary_str = None
        if row["salary_min"] or row["salary_max"]:
            parts = []
            if row["salary_min"]:
                parts.append(f"${row['salary_min']:,.0f}")
            if row["salary_max"]:
                parts.append(f"${row['salary_max']:,.0f}")
            salary_str = " - ".join(parts)

        return cls(
            id=row["external_id"] or str(row["id"]),
            source_ats=row["ats_type"] if "ats_type" in row.keys() else "icims",
            company_name=row["company_name"] if "company_name" in row.keys() else "",
            title=row["title"],
            department=row["department"] or "",
            location=row["location"] or "",
            job_type=row["job_type"] or "",
            posted_date=posted,
            url=row["url"] or "",
            description=row["description"] or "",
            qualifications=row["qualifications"] or "",
            salary_range=salary_str,
            salary_min=row["salary_min"] if "salary_min" in row.keys() else None,
            salary_max=row["salary_max"] if "salary_max" in row.keys() else None,
            scraped_at=scraped,
        )
