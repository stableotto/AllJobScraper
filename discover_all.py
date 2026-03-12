#!/usr/bin/env python3
"""
Mass iCIMS Portal Discovery

Finds ALL companies using iCIMS by aggregating subdomains from multiple sources:
  1. Certificate Transparency logs (crt.sh)
  2. DNS scan databases (HackerTarget, RapidDNS, Anubis/jldc.me)
  3. Web archive indexes (Wayback Machine CDX)
  4. URLScan.io crowd-sourced scans
  5. High-speed concurrent HTTP probing

Note: iCIMS uses a wildcard cert (*.icims.com), so CT logs alone only reveal
infrastructure subdomains. DNS scan databases are the primary source of customer
portal subdomains.

Usage:
    python discover_all.py [--output data/discovered_portals.yaml]
    python discover_all.py --ct-only          # just dump raw subdomains
    python discover_all.py --skip-probe       # discover without HTTP probing
    python discover_all.py --healthcare-only  # only output healthcare portals
"""

import argparse
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests
import yaml

from config.settings import DB_PATH
from storage.database import init_db, db_session, upsert_portal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

REQUESTS_HEADERS = {"User-Agent": "Mozilla/5.0 (research; iCIMS portal discovery)"}
REQUEST_TIMEOUT = 60

# iCIMS infrastructure subdomains to exclude from customer results
INFRA_SUBDOMAINS = {
    "icims.com", "www.icims.com", "www2.icims.com", "www3.icims.com", "www4.icims.com",
    "api.icims.com", "api-dev.icims.com", "api-stg.icims.com",
    "api-us-east-1.icims.com", "api-us-west-2.icims.com",
    "api-eu-central-1.icims.com", "api-eu-west-1.icims.com",
    "api-ca-central-1.icims.com", "api-ca1.icims.com",
    "api-eu1.icims.com", "api-eu2.icims.com",
    "api-us1.icims.com", "api-us2.icims.com",
    "dev.icims.com", "login.icims.com", "login-us2.icims.com", "login-usw2.icims.com",
    "help.icims.com", "care.icims.com", "docs.icims.com", "status.icims.com",
    "statuspage.icims.com", "trust.icims.com",
    "careers.icims.com", "www.careers.icims.com",
    "social.icims.com", "social-api.icims.com", "social-dev.icims.com",
    "social-demo.icims.com", "social-perf.icims.com", "social-prod.icims.com",
    "social-staging.icims.com", "social-test.icims.com", "social-test2.icims.com",
    "social-test-admin.icims.com", "social-training.icims.com",
    "admin.social.icims.com", "staging.social.icims.com",
    "community.icims.com", "www.community.icims.com",
    "noaccess.community.icims.com", "preview.community.icims.com",
    "select.community.icims.com",
    "marketplace.icims.com", "www.marketplace.icims.com",
    "academy.icims.com", "www.academy.icims.com",
    "developer.icims.com", "developers.icims.com",
    "developer-community.icims.com", "developer-community-dev.icims.com",
    "developer-community-stg.icims.com",
    "www.developer-community.icims.com",
    "www.developer-community-dev.icims.com",
    "www.developer-community-stg.icims.com",
    "login-community.icims.com", "login-community-dev.icims.com",
    "login-community-stg.icims.com",
    "playground.developer.icims.com",
    "partnerportal.icims.com", "www.partnerportal.icims.com",
    "partners.icims.com", "partnertraining.icims.com",
    "analytics.icims.com", "analytics-api.icims.com",
    "billing.icims.com", "email.icims.com", "click.icims.com",
    "engage.icims.com", "events.icims.com", "go.icims.com",
    "gslink.icims.com", "i.icims.com", "hrjobs.icims.com",
    "investors.icims.com", "nurture.icims.com", "salesloft.icims.com",
    "team.icims.com", "teams.icims.com", "talent.icims.com",
    "talent.dev.icims.com", "unifi.icims.com",
    "mobile-webservices.icims.com", "mobile.www.icims.com",
    "forms-marketplace.icims.com", "brandit-tools.icims.com",
    "design-system.icims.com", "autodiscover.icims.com",
    "monitoring-tools.icims.com", "nexpose-console-tools.icims.com",
    "nginxtest.icims.com", "notacustomerusw.icims.com",
    "nsintegrations.icims.com", "nsintegrationsuat.icims.com",
    "www.nsintegrations.icims.com", "www.nsintegrationsuat.icims.com",
    "postman-tools.icims.com", "postman-tools-dev.dev.icims.com",
    "agents.icims.com", "agents.dev.icims.com",
    "img.hrinsights.icims.com", "r.hrinsights.icims.com",
    "test955.icims.com", "2fwww.icims.com",
    "customers-hiring.icims.com", "jobs-inhouse.icims.com",
}


# ──────────────────────────────────────────────
# Source: Certificate Transparency Logs (crt.sh)
# ──────────────────────────────────────────────

def fetch_crtsh(retries: int = 3) -> set[str]:
    """Fetch subdomains from crt.sh JSON API with retries."""
    subdomains = set()
    for attempt in range(retries):
        try:
            logger.info(f"crt.sh: attempt {attempt + 1}/{retries}...")
            resp = requests.get(
                "https://crt.sh/?q=%25.icims.com&output=json",
                timeout=120, headers=REQUESTS_HEADERS,
            )
            if resp.status_code == 200:
                for entry in resp.json():
                    for line in entry.get("name_value", "").split("\n"):
                        line = line.strip().lower()
                        if line.endswith(".icims.com") and not line.startswith("*"):
                            subdomains.add(line)
                logger.info(f"crt.sh: {len(subdomains)} subdomains")
                return subdomains
            logger.warning(f"crt.sh: HTTP {resp.status_code}, retrying in 10s...")
            time.sleep(10)
        except Exception as e:
            logger.warning(f"crt.sh: {e}")
            time.sleep(10)
    return subdomains


# ──────────────────────────────────────────────
# Source: Certspotter
# ──────────────────────────────────────────────

def fetch_certspotter() -> set[str]:
    subdomains = set()
    try:
        resp = requests.get(
            "https://api.certspotter.com/v1/issuances"
            "?domain=icims.com&include_subdomains=true&expand=dns_names",
            timeout=REQUEST_TIMEOUT, headers=REQUESTS_HEADERS,
        )
        if resp.status_code == 200:
            for entry in resp.json():
                for name in entry.get("dns_names", []):
                    name = name.strip().lower()
                    if name.endswith(".icims.com") and not name.startswith("*"):
                        subdomains.add(name)
        logger.info(f"certspotter: {len(subdomains)} subdomains")
    except Exception as e:
        logger.warning(f"certspotter: {e}")
    return subdomains


# ──────────────────────────────────────────────
# Source: HackerTarget (DNS scan database)
# ──────────────────────────────────────────────

def fetch_hackertarget() -> set[str]:
    subdomains = set()
    try:
        resp = requests.get(
            "https://api.hackertarget.com/hostsearch/?q=icims.com",
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200 and "API count exceeded" not in resp.text:
            for line in resp.text.split("\n"):
                parts = line.split(",")
                host = parts[0].strip().lower()
                if host.endswith(".icims.com"):
                    subdomains.add(host)
        logger.info(f"hackertarget: {len(subdomains)} subdomains")
    except Exception as e:
        logger.warning(f"hackertarget: {e}")
    return subdomains


# ──────────────────────────────────────────────
# Source: RapidDNS.io
# ──────────────────────────────────────────────

def fetch_rapiddns() -> set[str]:
    subdomains = set()
    try:
        resp = requests.get(
            "https://rapiddns.io/subdomain/icims.com?full=1",
            timeout=REQUEST_TIMEOUT, headers=REQUESTS_HEADERS,
        )
        if resp.status_code == 200:
            matches = re.findall(r"([a-zA-Z0-9_.-]+\.icims\.com)", resp.text)
            for m in matches:
                subdomains.add(m.lower())
        logger.info(f"rapiddns: {len(subdomains)} subdomains")
    except Exception as e:
        logger.warning(f"rapiddns: {e}")
    return subdomains


# ──────────────────────────────────────────────
# Source: Anubis (jldc.me)
# ──────────────────────────────────────────────

def fetch_anubis() -> set[str]:
    subdomains = set()
    try:
        resp = requests.get(
            "https://jldc.me/anubis/subdomains/icims.com",
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            for s in resp.json():
                s = s.strip().lower()
                if s.endswith(".icims.com"):
                    subdomains.add(s)
        logger.info(f"anubis: {len(subdomains)} subdomains")
    except Exception as e:
        logger.warning(f"anubis: {e}")
    return subdomains


# ──────────────────────────────────────────────
# Source: Wayback Machine CDX
# ──────────────────────────────────────────────

def fetch_wayback() -> set[str]:
    subdomains = set()
    try:
        resp = requests.get(
            "https://web.archive.org/cdx/search/cdx"
            "?url=*.icims.com&output=text&fl=original&collapse=urlkey&limit=50000",
            timeout=120, headers=REQUESTS_HEADERS,
        )
        if resp.status_code == 200:
            for line in resp.text.split("\n"):
                match = re.search(r"https?://([a-zA-Z0-9_.-]+\.icims\.com)", line)
                if match:
                    subdomains.add(match.group(1).lower())
        logger.info(f"wayback: {len(subdomains)} subdomains")
    except Exception as e:
        logger.warning(f"wayback: {e}")
    return subdomains


# ──────────────────────────────────────────────
# Source: URLScan.io
# ──────────────────────────────────────────────

def fetch_urlscan() -> set[str]:
    subdomains = set()
    try:
        resp = requests.get(
            "https://urlscan.io/api/v1/search/?q=domain:icims.com&size=10000",
            timeout=REQUEST_TIMEOUT, headers=REQUESTS_HEADERS,
        )
        if resp.status_code == 200:
            for result in resp.json().get("results", []):
                domain = result.get("page", {}).get("domain", "").lower()
                if domain.endswith(".icims.com"):
                    subdomains.add(domain)
        logger.info(f"urlscan: {len(subdomains)} subdomains")
    except Exception as e:
        logger.warning(f"urlscan: {e}")
    return subdomains


# ──────────────────────────────────────────────
# Source: AlienVault OTX
# ──────────────────────────────────────────────

def fetch_alienvault() -> set[str]:
    subdomains = set()
    try:
        page = 1
        while page <= 20:
            resp = requests.get(
                f"https://otx.alienvault.com/api/v1/indicators/domain/icims.com"
                f"/passive_dns?limit=500&page={page}",
                timeout=REQUEST_TIMEOUT, headers=REQUESTS_HEADERS,
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            records = data.get("passive_dns", [])
            if not records:
                break
            for r in records:
                hostname = r.get("hostname", "").lower()
                if hostname.endswith(".icims.com"):
                    subdomains.add(hostname)
            if not data.get("has_next", False):
                break
            page += 1
        logger.info(f"alienvault: {len(subdomains)} subdomains")
    except Exception as e:
        logger.warning(f"alienvault: {e}")
    return subdomains


# ──────────────────────────────────────────────
# Aggregator
# ──────────────────────────────────────────────

ALL_SOURCES = [
    ("crt.sh", fetch_crtsh),
    ("certspotter", fetch_certspotter),
    ("hackertarget", fetch_hackertarget),
    ("rapiddns", fetch_rapiddns),
    ("anubis", fetch_anubis),
    ("wayback", fetch_wayback),
    ("urlscan", fetch_urlscan),
    ("alienvault", fetch_alienvault),
]


def fetch_all_subdomains() -> set[str]:
    """Query all sources and merge results."""
    combined = set()
    for name, fetcher in ALL_SOURCES:
        logger.info(f"Querying {name}...")
        try:
            result = fetcher()
            new = result - combined
            combined |= result
            logger.info(f"  +{len(new)} new → {len(combined)} total")
        except Exception as e:
            logger.warning(f"  {name} failed: {e}")
    return combined


def filter_customer_portals(subdomains: set[str]) -> list[str]:
    """Remove iCIMS infrastructure subdomains, keep only customer portals."""
    customers = []
    for s in sorted(subdomains):
        if s in INFRA_SUBDOMAINS:
            continue
        if s == "icims.com":
            continue
        customers.append(s)
    return customers


# ──────────────────────────────────────────────
# Fast HTTP Probing
# ──────────────────────────────────────────────

def probe_subdomain(subdomain: str, timeout: int = 8) -> Optional[dict]:
    """Probe a single subdomain to check if it's an active portal."""
    url = f"https://{subdomain}"
    try:
        resp = requests.head(
            url, timeout=timeout, allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"}, verify=True,
        )
        if resp.status_code < 400:
            final_url = resp.url
            return {
                "subdomain": subdomain,
                "url": final_url,
                "status": resp.status_code,
                "redirected": final_url != url and final_url != url + "/",
            }
    except Exception:
        pass
    return None


def mass_probe(subdomains: list[str], max_workers: int = 50) -> list[dict]:
    """Probe many subdomains concurrently."""
    active = []
    total = len(subdomains)
    done = 0

    logger.info(f"Probing {total} subdomains with {max_workers} workers...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_sub = {
            executor.submit(probe_subdomain, sub): sub for sub in subdomains
        }
        for future in as_completed(future_to_sub):
            done += 1
            result = future.result()
            if result:
                active.append(result)
            if done % 100 == 0 or done == total:
                logger.info(f"  Progress: {done}/{total} probed, {len(active)} active")

    logger.info(f"Probing complete: {len(active)} active out of {total}")
    return active


# ──────────────────────────────────────────────
# Slug Extraction & Categorization
# ──────────────────────────────────────────────

def extract_slug(subdomain: str) -> str:
    """Extract the company slug from an iCIMS subdomain."""
    return subdomain.replace(".icims.com", "")


def categorize_portal(subdomain: str, url: str) -> dict:
    slug = extract_slug(subdomain)
    healthcare_signals = [
        "health", "hospital", "medical", "clinic", "care",
        "nurse", "pharma", "dental", "therapy", "rehab",
        "surgery", "pediatric", "children", "cancer",
        "cardio", "ortho", "neuro", "mercy", "baptist",
        "methodist", "adventist", "trinity", "providence",
        "kaiser", "cigna", "aetna", "humana", "anthem",
        "centura", "ascension", "beaumont", "cedars",
    ]
    is_healthcare = any(signal in slug.lower() for signal in healthcare_signals)
    return {
        "slug": slug,
        "subdomain": subdomain,
        "url": url,
        "is_healthcare": is_healthcare,
        "sector": "healthcare" if is_healthcare else "other",
    }


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Mass iCIMS Portal Discovery")
    parser.add_argument("--output", default="data/discovered_portals.yaml", help="Output file")
    parser.add_argument("--workers", type=int, default=50, help="Concurrent probe workers")
    parser.add_argument("--healthcare-only", action="store_true", help="Only output healthcare portals")
    parser.add_argument("--ct-only", action="store_true", help="Just dump raw subdomains, no probing")
    parser.add_argument("--skip-probe", action="store_true", help="Discover without HTTP probing")
    parser.add_argument("--raw-file", default="data/ct_raw_subdomains.txt", help="Raw subdomain list file")
    args = parser.parse_args()

    start = time.time()

    # Step 1: Fetch subdomains from all sources
    logger.info("=" * 60)
    logger.info("STEP 1: Subdomain Enumeration (CT logs + DNS databases)")
    logger.info("=" * 60)
    all_subdomains = fetch_all_subdomains()

    # Save raw list
    raw_path = Path(args.raw_file)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with open(raw_path, "w") as f:
        for s in sorted(all_subdomains):
            f.write(s + "\n")
    logger.info(f"Raw subdomain list ({len(all_subdomains)}) saved to {raw_path}")

    if args.ct_only:
        logger.info("--ct-only: stopping after subdomain dump")
        return

    # Step 2: Filter to customer portals
    logger.info("=" * 60)
    logger.info("STEP 2: Filtering to customer portals")
    logger.info("=" * 60)
    customer_subs = filter_customer_portals(all_subdomains)
    logger.info(f"Customer portal candidates: {len(customer_subs)} "
                f"(excluded {len(all_subdomains) - len(customer_subs)} infrastructure subdomains)")

    if args.skip_probe:
        # Save unprobed list
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        yaml_data = {
            "discovery_metadata": {
                "total_subdomains_found": len(all_subdomains),
                "customer_portal_candidates": len(customer_subs),
                "probed": False,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sources": [name for name, _ in ALL_SOURCES],
            },
            "icims_portals": [
                {
                    "name": extract_slug(s).replace("-", " ").title(),
                    "subdomain": s,
                    "url": f"https://{s}",
                    "ats_slug": extract_slug(s),
                }
                for s in customer_subs
            ],
        }
        with open(output_path, "w") as f:
            yaml.dump(yaml_data, f, default_flow_style=False, sort_keys=False)
        logger.info(f"Saved {len(customer_subs)} unprobed candidates to {output_path}")
        return

    # Step 3: Mass HTTP probe
    logger.info("=" * 60)
    logger.info("STEP 3: Mass HTTP probing")
    logger.info("=" * 60)
    active_portals = mass_probe(customer_subs, max_workers=args.workers)

    # Step 4: Categorize & deduplicate
    logger.info("=" * 60)
    logger.info("STEP 4: Categorizing results")
    logger.info("=" * 60)

    seen_urls = {}
    for portal in active_portals:
        final_url = portal["url"].rstrip("/")
        if final_url not in seen_urls:
            info = categorize_portal(portal["subdomain"], portal["url"])
            info["status"] = portal["status"]
            info["redirected"] = portal["redirected"]
            seen_urls[final_url] = info

    results = list(seen_urls.values())
    healthcare = [r for r in results if r["is_healthcare"]]
    other = [r for r in results if not r["is_healthcare"]]

    elapsed = time.time() - start
    logger.info("=" * 60)
    logger.info(f"DISCOVERY COMPLETE in {elapsed:.1f}s")
    logger.info(f"  Sources queried:       {len(ALL_SOURCES)}")
    logger.info(f"  Raw subdomains found:  {len(all_subdomains)}")
    logger.info(f"  Customer candidates:   {len(customer_subs)}")
    logger.info(f"  Active portals:        {len(results)}")
    logger.info(f"  Healthcare portals:    {len(healthcare)}")
    logger.info(f"  Other portals:         {len(other)}")
    logger.info("=" * 60)

    output_list = healthcare if args.healthcare_only else results
    print(f"\n{'=' * 100}")
    print(f"{'SLUG':<45} {'URL':<65} {'SECTOR'}")
    print(f"{'=' * 100}")
    for r in sorted(output_list, key=lambda x: x["slug"]):
        print(f"{r['slug']:<45} {r['url']:<65} {r['sector']}")

    # Save to YAML
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    yaml_data = {
        "discovery_metadata": {
            "total_subdomains_found": len(all_subdomains),
            "customer_candidates_probed": len(customer_subs),
            "active_portals": len(results),
            "healthcare_portals": len(healthcare),
            "other_portals": len(other),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "elapsed_seconds": round(elapsed, 1),
            "sources": [name for name, _ in ALL_SOURCES],
        },
        "icims_portals": [
            {
                "name": r["slug"].replace("-", " ").title(),
                "url": r["url"],
                "ats_slug": r["slug"],
                "sector": r["sector"],
                "subdomain": r["subdomain"],
            }
            for r in sorted(output_list, key=lambda x: x["slug"])
        ],
    }

    with open(output_path, "w") as f:
        yaml.dump(yaml_data, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Results saved to {output_path}")

    # Step 5: Upsert into SQLite database
    logger.info("=" * 60)
    logger.info("STEP 5: Saving to SQLite database")
    logger.info("=" * 60)
    init_db(DB_PATH)
    with db_session(DB_PATH) as conn:
        db_count = 0
        for r in results:
            upsert_portal(
                conn,
                subdomain=r["subdomain"],
                slug=r["slug"],
                name=r["slug"].replace("-", " ").title(),
                url=r["url"],
                ats_type="icims",
                sector=r["sector"],
                verified=True,
            )
            db_count += 1
        logger.info(f"Upserted {db_count} portals into {DB_PATH}")


if __name__ == "__main__":
    main()
