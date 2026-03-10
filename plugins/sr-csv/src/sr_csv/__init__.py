"""CSV Source Plugin — import jobs and candidates from CSV files."""

import csv
from pathlib import Path
from typing import Any

from narrowfield import (
    PluginInfo,
    JobImport,
    CandidateImport,
    SkillDefinition,
)


class Plugin:
    """Import jobs and candidates from local CSV files."""

    def __init__(self):
        self.jobs_path: str = ""
        self.candidates_path: str = ""

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="csv",
            display_name="CSV Import",
            version="0.1.0",
            description="Import jobs and candidates from CSV files",
            capabilities=["source:jobs", "source:candidates"],
        )

    def configure(self, config: dict[str, Any]) -> None:
        self.jobs_path = config.get("jobs_path", "")
        self.candidates_path = config.get("candidates_path", "")

    def test_connection(self) -> dict[str, Any]:
        errors = []
        if self.jobs_path and not Path(self.jobs_path).exists():
            errors.append(f"Jobs file not found: {self.jobs_path}")
        if self.candidates_path and not Path(self.candidates_path).exists():
            errors.append(f"Candidates file not found: {self.candidates_path}")
        if errors:
            return {"ok": False, "message": "; ".join(errors)}
        return {"ok": True, "message": "CSV files accessible"}

    def fetch_jobs(self, **filters) -> list[JobImport]:
        if not self.jobs_path:
            return []

        jobs = []
        with open(self.jobs_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                skills_raw = row.get("required_skills", "")
                required = [SkillDefinition(name=s.strip()) for s in skills_raw.split(",") if s.strip()]

                preferred_raw = row.get("preferred_skills", "")
                preferred = [SkillDefinition(name=s.strip()) for s in preferred_raw.split(",") if s.strip()]

                jobs.append(JobImport(
                    title=row.get("title", ""),
                    description=row.get("description", ""),
                    department=row.get("department", ""),
                    required_skills=required,
                    preferred_skills=preferred,
                    location=row.get("location", ""),
                    employment_type=row.get("employment_type", "full_time"),
                    external_id=row.get("id", row.get("external_id", "")),
                ))
        return jobs

    def fetch_candidates(self, job_id: str = "", **filters) -> list[CandidateImport]:
        if not self.candidates_path:
            return []

        candidates = []
        with open(self.candidates_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if job_id and row.get("applied_to", "") != job_id:
                    continue

                skills_raw = row.get("skills", "")
                skills = [SkillDefinition(name=s.strip()) for s in skills_raw.split(",") if s.strip()]

                candidates.append(CandidateImport(
                    name=row.get("name", ""),
                    email=row.get("email", ""),
                    phone=row.get("phone", ""),
                    resume_text=row.get("resume_text", ""),
                    skills=skills,
                    current_title=row.get("current_title", ""),
                    current_company=row.get("current_company", ""),
                    source=row.get("source", "applied"),
                    external_id=row.get("id", row.get("external_id", "")),
                    applied_to=row.get("applied_to", ""),
                ))
        return candidates

    def fetch_skills(self) -> list[SkillDefinition]:
        return []
