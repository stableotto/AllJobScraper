"""
iCIMS Company Discovery

Finds hospitals and medical groups that use iCIMS as their ATS.
Three discovery strategies:
  1. Google dorking for icims.com / jibeapply.com career pages
  2. Curated seed list from portals.yaml
  3. Subdomain enumeration (probe careers-{name}.icims.com)
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse

import requests
import yaml

from models.company import Company
from scrapers.icims.config import ICIMS_DOMAIN, JIBE_DOMAIN

logger = logging.getLogger(__name__)

# Common hospital system name suffixes to try during subdomain enumeration
HOSPITAL_SUFFIXES = [
    "health", "hospital", "medical", "healthcare", "medicine",
    "clinic", "care", "regional", "memorial", "community",
    "university", "pediatric", "childrens",
]

# Well-known hospital systems and healthcare organizations to probe
# Format: careers-{slug}.icims.com
KNOWN_HOSPITAL_SLUGS = [
    # --- Confirmed active (from previous enumeration) ---
    "uci", "hackensackmeridianhealth", "infirmaryhealth", "trilogyhs",
    "hopkinsmedicine", "commonspirit", "ascension", "piedmont", "uabmedicine",

    # --- Found via Google dorking ---
    "hhsys",             # Huntsville Hospital Health System
    "unchealth",         # UNC Health
    "unchealthcare",     # UNC Health (alt slug)
    "medcenterhealth",   # Med Center Health
    "hshs",              # Hospital Sisters Health System
    "nychealthandhospitals",  # NYC Health + Hospitals
    "nychhc",            # NYC Health + Hospitals (alt)
    "emoryhealthcare",   # Emory Healthcare
    "mainehealth",       # MaineHealth
    "trihealth",         # TriHealth (Cincinnati)
    "bridgeporthospital",# Bridgeport Hospital
    "mskcc",             # Memorial Sloan Kettering
    "mountsinai",        # Mount Sinai

    # --- Large health systems ---
    "northwell",         # Northwell Health
    "mayoclinic",        # Mayo Clinic
    "clevelandclinic",   # Cleveland Clinic
    "pennmedicine",      # Penn Medicine
    "massgeneral",       # Mass General Brigham
    "nyulangone",        # NYU Langone
    "cedarssinai",       # Cedars-Sinai
    "stanfordhealthcare",# Stanford Health Care
    "uchealth",          # UCHealth (Colorado)
    "baptisthealth",     # Baptist Health
    "adventhealth",      # AdventHealth
    "intermountain",     # Intermountain Health
    "providence",        # Providence Health
    "kaiser",            # Kaiser Permanente
    "hcahealthcare",     # HCA Healthcare
    "tenet",             # Tenet Healthcare
    "universalhealth",   # Universal Health Services
    "medstar",           # MedStar Health
    "ochsner",           # Ochsner Health
    "nuvancehealth",     # Nuvance Health
    "rwjbh",             # RWJBarnabas Health
    "emoryhealth",       # Emory Health
    "muhealth",          # MU Health Care
    "texashealth",       # Texas Health Resources
    "bswhealth",         # Baylor Scott & White
    "sentara",           # Sentara Healthcare
    "inova",             # Inova Health System
    "wellstar",          # Wellstar Health
    "prismahealth",      # Prisma Health
    "atrium",            # Atrium Health
    "atriumhealth",      # Atrium Health (alt)
    "novant",            # Novant Health
    "novanthealth",      # Novant Health (alt)
    "wakehealth",        # Wake Forest Baptist Health
    "duke",              # Duke Health
    "dukehealth",        # Duke Health (alt)
    "uva",               # UVA Health
    "uvahealth",         # UVA Health (alt)

    # --- Regional health systems ---
    "geisinger",         # Geisinger Health
    "henryford",         # Henry Ford Health
    "beaumont",          # Beaumont Health (MI)
    "spectrumhealth",    # Spectrum Health (MI)
    "corewell",          # Corewell Health (MI, formerly Beaumont+Spectrum)
    "froedtert",         # Froedtert Health (WI)
    "marshfield",        # Marshfield Clinic
    "gundersen",         # Gundersen Health
    "sanfordhealth",     # Sanford Health
    "avera",             # Avera Health
    "ssmhealth",         # SSM Health
    "mercyhealth",       # Mercy Health
    "mercy",             # Mercy (alt)
    "dignityhealth",     # Dignity Health
    "sutter",            # Sutter Health
    "sutterhealth",      # Sutter Health (alt)
    "scripps",           # Scripps Health
    "scrippshealth",     # Scripps Health (alt)
    "sharp",             # Sharp HealthCare
    "sharphealthcare",   # Sharp HealthCare (alt)
    "bannerheath",       # Banner Health
    "bannerhealth",      # Banner Health (alt)
    "chsmedical",        # Community Health Systems
    "lifepoint",         # Lifepoint Health
    "lifepointhealth",   # Lifepoint Health (alt)
    "ardent",            # Ardent Health Services
    "ardenthealth",      # Ardent Health (alt)
    "quorum",            # Quorum Health
    "prime",             # Prime Healthcare
    "primehealthcare",   # Prime Healthcare (alt)
    "steward",           # Steward Health Care
    "stewardhealth",     # Steward Health (alt)

    # --- University hospitals ---
    "umich",             # University of Michigan Health
    "uofmhealth",        # U of M Health (alt)
    "osumc",             # Ohio State Wexner Medical Center
    "ohiohealth",        # OhioHealth
    "iu",                # IU Health
    "iuhealth",          # IU Health (alt)
    "rush",              # Rush University Medical Center
    "nm",                # Northwestern Medicine
    "northwesternmedicine", # Northwestern Medicine (alt)
    "upmc",              # UPMC
    "jefferson",         # Jefferson Health
    "jeffersonhealth",   # Jefferson Health (alt)
    "yale",              # Yale New Haven Health
    "ynhh",              # Yale New Haven Health (alt)
    "partners",          # Mass General Brigham (formerly Partners)
    "ucsf",              # UCSF Health
    "ucsfhealth",        # UCSF Health (alt)
    "ucsd",              # UC San Diego Health
    "ucsdhealth",        # UC San Diego Health (alt)
    "ucdavis",           # UC Davis Health
    "ucla",              # UCLA Health
    "uclahealth",        # UCLA Health (alt)

    # --- Children's hospitals ---
    "childrensnational", # Children's National
    "childrenscolorado", # Children's Colorado
    "stlouischildrens",  # St. Louis Children's
    "cchmc",             # Cincinnati Children's
    "texaschildrens",    # Texas Children's
    "chop",              # Children's Hospital of Philadelphia
    "nationwidechildrens",# Nationwide Children's
    "seattlechildrens",  # Seattle Children's
    "luriechildrens",    # Lurie Children's

    # --- VA / Government ---
    "va",                # Veterans Affairs
    "ihs",               # Indian Health Service
]


class ICIMSDiscovery:
    """Discovers hospitals/medical groups using iCIMS."""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    # ──────────────────────────────────────────────
    # Strategy 1: Load from seed list (portals.yaml)
    # ──────────────────────────────────────────────

    def from_seed_list(self, yaml_path: str) -> list[Company]:
        """Load known iCIMS portals from the portals.yaml config."""
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)

        companies = []
        icims_entries = data.get("icims", [])

        for entry in icims_entries:
            company = Company(
                name=entry["name"],
                ats_type="icims",
                portal_url=entry["url"],
                ats_slug=entry.get("ats_slug", ""),
                sector=entry.get("sector", "hospital"),
                state=entry.get("state", ""),
                discovered_via="seed_list",
            )
            companies.append(company)

        logger.info(f"Loaded {len(companies)} iCIMS portals from seed list")
        return companies

    # ──────────────────────────────────────────────
    # Strategy 2: Subdomain enumeration
    # ──────────────────────────────────────────────

    def subdomain_enumeration(
        self,
        slugs: Optional[list[str]] = None,
        verify_ssl: bool = True,
    ) -> list[Company]:
        """
        Probe careers-{slug}.icims.com for known hospital slugs.

        Args:
            slugs: List of slugs to probe. Defaults to KNOWN_HOSPITAL_SLUGS.
            verify_ssl: Whether to verify SSL certificates.

        Returns:
            List of verified Company objects.
        """
        if slugs is None:
            slugs = KNOWN_HOSPITAL_SLUGS

        companies = []
        total = len(slugs)

        for i, slug in enumerate(slugs):
            icims_url = f"https://careers-{slug}.icims.com"

            try:
                resp = self._session.head(
                    icims_url,
                    timeout=self.timeout,
                    allow_redirects=True,
                    verify=verify_ssl,
                )

                if resp.status_code < 400:
                    # Portal exists! Try to determine the final URL
                    final_url = resp.url if resp.url != icims_url else icims_url

                    company = Company(
                        name=slug.replace("-", " ").title(),
                        ats_type="icims",
                        portal_url=final_url,
                        ats_slug=slug,
                        sector="hospital",
                        verified=True,
                        discovered_via="subdomain_enum",
                    )
                    companies.append(company)
                    logger.info(f"[{i+1}/{total}] ✓ Found: {icims_url} → {final_url}")
                else:
                    logger.debug(f"[{i+1}/{total}] ✗ {slug}: HTTP {resp.status_code}")

            except requests.exceptions.RequestException as e:
                logger.debug(f"[{i+1}/{total}] ✗ {slug}: {e}")
                continue

        logger.info(f"Subdomain enumeration found {len(companies)} active portals out of {total} probed")
        return companies

    # ──────────────────────────────────────────────
    # Strategy 3: Google dorking (requires manual usage)
    # ──────────────────────────────────────────────

    def google_dork_queries(self) -> list[str]:
        """
        Generate Google dork queries to find iCIMS portals.
        These must be run manually or via a SERP API (Google blocks automated searches).

        Returns:
            List of Google search queries.
        """
        queries = [
            # Direct iCIMS portals
            'site:icims.com "hospital" OR "health system" OR "medical center"',
            'site:icims.com "nursing" OR "registered nurse" OR "RN"',
            'site:icims.com "careers" "apply" "hospital"',

            # Jibe-powered portals (common in healthcare)
            'site:jibeapply.com "hospital" OR "health" OR "medical"',

            # Portal footprint detection
            '"Powered by iCIMS" "hospital" OR "health system" careers',
            '"careers-" site:icims.com',

            # Healthcare-specific
            'inurl:careers "icims" "nurse" OR "nursing"',
            'inurl:jobs "icims" "healthcare" OR "medical group"',
        ]
        return queries

    # ──────────────────────────────────────────────
    # Combined discovery
    # ──────────────────────────────────────────────

    def discover_all(
        self,
        yaml_path: Optional[str] = None,
        run_subdomain_enum: bool = True,
    ) -> list[Company]:
        """
        Run all discovery strategies and merge results.

        Args:
            yaml_path: Path to portals.yaml for seed list
            run_subdomain_enum: Whether to run subdomain enumeration

        Returns:
            Deduplicated list of Company objects
        """
        all_companies: dict[str, Company] = {}

        # Seed list
        if yaml_path:
            for company in self.from_seed_list(yaml_path):
                key = company.ats_slug or company.portal_url
                all_companies[key] = company

        # Subdomain enumeration
        if run_subdomain_enum:
            for company in self.subdomain_enumeration():
                key = company.ats_slug or company.portal_url
                if key not in all_companies:
                    all_companies[key] = company

        companies = list(all_companies.values())
        logger.info(f"Total discovered iCIMS portals: {len(companies)}")

        # Print Google dork queries for manual use
        logger.info("\n--- Google Dork Queries (run manually) ---")
        for q in self.google_dork_queries():
            logger.info(f"  {q}")

        return companies
