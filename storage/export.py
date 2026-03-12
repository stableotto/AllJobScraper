"""CSV and JSON export utilities."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from models.job import Job

logger = logging.getLogger(__name__)


def export_to_csv(
    jobs: list[Job],
    output_dir: Path,
    filename: Optional[str] = None,
) -> Path:
    """
    Export jobs to a CSV file.

    Args:
        jobs: List of Job objects to export
        output_dir: Directory to write the CSV to
        filename: Optional filename (default: jobs_YYYY-MM-DD.csv)

    Returns:
        Path to the written CSV file
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if filename is None:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        filename = f"jobs_{date_str}.csv"

    filepath = output_dir / filename

    if not jobs:
        logger.warning("No jobs to export to CSV")
        return filepath

    # Deduplicate by unique_key
    seen = set()
    unique_jobs = []
    for job in jobs:
        if job.unique_key not in seen:
            seen.add(job.unique_key)
            unique_jobs.append(job)

    fieldnames = list(unique_jobs[0].to_csv_row().keys())

    # If file exists, read existing keys to avoid duplicates
    existing_keys = set()
    if filepath.exists():
        with open(filepath, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_keys.add(row.get("unique_key", ""))

    mode = "a" if filepath.exists() else "w"
    write_header = not filepath.exists()

    with open(filepath, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()

        new_count = 0
        for job in unique_jobs:
            if job.unique_key not in existing_keys:
                writer.writerow(job.to_csv_row())
                new_count += 1

    logger.info(f"Exported {new_count} new jobs to {filepath} ({len(existing_keys)} existing)")
    return filepath


def export_to_json(
    jobs: list[Job],
    output_dir: Path,
    filename: Optional[str] = None,
) -> Path:
    """
    Export jobs to a JSON file with incremental append.

    Args:
        jobs: List of Job objects to export
        output_dir: Directory to write the JSON to
        filename: Optional filename (default: jobs_YYYY-MM-DD.json)

    Returns:
        Path to the written JSON file
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if filename is None:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        filename = f"jobs_{date_str}.json"

    filepath = output_dir / filename

    # Load existing data if file exists
    existing_data = {}
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            try:
                existing_jobs = json.load(f)
                existing_data = {j["unique_key"]: j for j in existing_jobs if "unique_key" in j}
            except (json.JSONDecodeError, KeyError):
                existing_data = {}

    # Merge new jobs (dedup by unique_key)
    for job in jobs:
        job_dict = job.to_dict()
        job_dict["unique_key"] = job.unique_key
        existing_data[job.unique_key] = job_dict

    # Write all data
    all_jobs = list(existing_data.values())
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, indent=2, default=str)

    logger.info(f"Exported {len(all_jobs)} total jobs to {filepath}")
    return filepath
