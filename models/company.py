"""Company / portal registry model."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Company:
    """Represents a company/hospital and its career portal."""

    name: str
    ats_type: str  # "icims" | "workday" | "taleo" | "oracle"
    portal_url: str  # Public career site URL
    sector: str = "hospital"  # hospital | medical_group | health_system | university_hospital

    # ATS-specific identifiers (populated during discovery)
    ats_slug: str = ""  # e.g., "uci" for careers-uci.icims.com
    ats_customer_id: str = ""  # e.g., "1234" for iCIMS customer ID
    ats_portal_id: str = ""  # e.g., portal identifier within the ATS

    # Metadata
    location: str = ""  # HQ location
    state: str = ""
    verified: bool = False  # Has this portal been confirmed as active?
    last_scraped: Optional[datetime] = None
    job_count: int = 0  # Jobs found in last scrape

    # Discovery metadata
    discovered_via: str = ""  # "seed_list" | "google_dork" | "subdomain_enum"
    discovered_at: Optional[datetime] = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        d = asdict(self)
        for key in ("last_scraped", "discovered_at"):
            if d[key] is not None:
                d[key] = d[key].isoformat()
        return d

    def save_to_db(self, conn: sqlite3.Connection) -> int:
        """Upsert this company/portal into the SQLite database. Returns the row id."""
        from storage.database import upsert_portal

        subdomain = ""
        if self.ats_slug and self.ats_type == "icims":
            subdomain = f"{self.ats_slug}.icims.com"
        elif self.portal_url:
            from urllib.parse import urlparse
            subdomain = urlparse(self.portal_url).hostname or self.ats_slug

        return upsert_portal(
            conn,
            subdomain=subdomain,
            slug=self.ats_slug or self.name.lower().replace(" ", "-"),
            name=self.name,
            url=self.portal_url,
            ats_type=self.ats_type,
            sector=self.sector,
            state=self.state,
            city=self.location,
            verified=self.verified,
        )

    @classmethod
    def from_db_row(cls, row: sqlite3.Row) -> "Company":
        """Reconstruct a Company from a SQLite portals row."""
        return cls(
            name=row["name"] or "",
            ats_type=row["ats_type"] or "icims",
            portal_url=row["url"] or "",
            sector=row["sector"] or "",
            ats_slug=row["slug"] or "",
            state=row["state"] or "",
            location=row["city"] or "",
            verified=bool(row["verified"]),
            discovered_at=datetime.fromisoformat(row["discovered_at"])
            if row["discovered_at"] else None,
        )
