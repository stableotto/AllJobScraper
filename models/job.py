"""Unified Job data model used across all ATS scrapers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import ClassVar, Optional


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

    # Classification
    is_nursing: bool = False
    categories: list[str] = field(default_factory=list)

    # Metadata
    scraped_at: datetime = field(default_factory=datetime.utcnow)
    raw_data: Optional[dict] = field(default=None, repr=False)

    # --- Nursing-specific keywords for classification ---
    # Title keywords — high confidence, matched against job title only
    NURSING_TITLE_KEYWORDS: ClassVar = {
        "nurse", "nursing", "rn ", " rn", "lpn", "lvn", "cna",
        "aprn", "nurse practitioner", "bsn", "msn", "dnp",
        "clinical nurse", "charge nurse", "staff nurse",
        "registered nurse", "licensed practical nurse",
        "certified nursing assistant",
        "icu nurse", "er nurse", "or nurse",
        "med-surg", "oncology nurse", "pediatric nurse",
        "nicu nurse", "l&d nurse", "hospice nurse",
        "home health nurse", "travel nurse",
        "patient care tech", "patient care assistant",
        "nurse manager", "nurse supervisor", "nurse educator",
        "nurse anesthetist", "crna",
    }

    # Description keywords — only very strong signals (avoid boilerplate matches)
    NURSING_DESCRIPTION_KEYWORDS: ClassVar = {
        "registered nurse required",
        "rn license required",
        "nursing license",
        "active rn license",
        "current rn license",
        "nursing degree required",
        "bsn required",
        "msn required",
        "nclex",
    }

    @property
    def unique_key(self) -> str:
        """Generate a deduplication key."""
        raw = f"{self.source_ats}:{self.company_name}:{self.id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def classify_nursing(self) -> bool:
        """Determine if this is a nursing/clinical role based on title (primary) and description (secondary)."""
        title_lower = self.title.lower()

        # Primary: Check title (most reliable)
        for keyword in self.NURSING_TITLE_KEYWORDS:
            if keyword in title_lower:
                self.is_nursing = True
                return True

        # Secondary: Check department name
        dept_lower = self.department.lower()
        if any(kw in dept_lower for kw in ("nursing", "nurse", "nicu", "icu nurse")):
            self.is_nursing = True
            return True

        # Tertiary: Check description for very strong signals only
        desc_lower = self.description.lower()
        for keyword in self.NURSING_DESCRIPTION_KEYWORDS:
            if keyword in desc_lower:
                self.is_nursing = True
                return True

        self.is_nursing = False
        return False

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
            "is_nursing": self.is_nursing,
            "categories": "; ".join(self.categories),
            "salary_range": self.salary_range or "",
            "description": self.description[:500],  # Truncate for CSV
            "qualifications": self.qualifications[:500],
            "scraped_at": self.scraped_at.isoformat(),
        }

    def save_to_db(self, conn: sqlite3.Connection, portal_id: int) -> int:
        """Upsert this job into the SQLite database. Returns the row id."""
        from storage.database import upsert_job, _parse_salary

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
            is_nursing=self.is_nursing,
            categories=self.categories,
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

        cats = []
        if row["categories"]:
            try:
                cats = json.loads(row["categories"])
            except (json.JSONDecodeError, TypeError):
                pass

        salary = None
        if row["salary_min"] or row["salary_max"]:
            parts = []
            if row["salary_min"]:
                parts.append(f"${row['salary_min']:,.0f}")
            if row["salary_max"]:
                parts.append(f"${row['salary_max']:,.0f}")
            salary = " - ".join(parts)

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
            salary_range=salary,
            is_nursing=bool(row["is_nursing"]),
            categories=cats,
            scraped_at=scraped,
        )

