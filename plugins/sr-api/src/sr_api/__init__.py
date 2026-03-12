"""REST API Source Plugin — fetch candidates and jobs from any REST API."""

from __future__ import annotations

import base64
from typing import Any

import httpx

from narrowfield import (
    CandidateImport,
    JobImport,
    PluginInfo,
    SkillDefinition,
)


def _resolve(obj: Any, path: str) -> Any:
    """Walk a dotted path like 'data.results' into a nested dict."""
    for key in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return None
    return obj


def _get(row: dict, field_map: dict[str, str], key: str, default: str = "") -> str:
    """Look up a value in *row* using the field mapping, falling back to *key* itself."""
    mapped = field_map.get(key, key)
    return str(row.get(mapped, default))


class Plugin:
    """Import candidates and jobs from a remote REST API.

    Supports bearer-token, API-key, and basic authentication, configurable
    endpoints and field mapping, and simple pagination.
    """

    def __init__(self) -> None:
        self.base_url: str = ""
        self.auth_type: str = "none"
        self.auth_token: str = ""
        self.auth_header_name: str = "Authorization"
        self.username: str = ""
        self.password: str = ""

        self.candidates_endpoint: str = "/candidates"
        self.jobs_endpoint: str = "/jobs"

        # Dotted path into the JSON response where the list lives,
        # e.g. "data.candidates".  Empty means the root is the list.
        self.candidates_results_key: str = ""
        self.jobs_results_key: str = ""

        self.candidate_field_map: dict[str, str] = {}
        self.job_field_map: dict[str, str] = {}

        # Pagination
        self.page_param: str = "page"
        self.per_page_param: str = "per_page"
        self.per_page: int = 100
        self.max_pages: int = 100

        self.timeout: float = 30.0

    # ── metadata ──

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="api",
            display_name="REST API Import",
            version="0.1.0",
            description="Fetch candidates and jobs from any REST API",
            capabilities=["source:candidates", "source:jobs"],
        )

    # ── configuration ──

    def configure(self, config: dict[str, Any]) -> None:
        self.base_url = config.get("base_url", "").rstrip("/")

        self.auth_type = config.get("auth_type", "none")
        self.auth_token = config.get("auth_token", "")
        self.auth_header_name = config.get("auth_header_name", "Authorization")
        self.username = config.get("username", "")
        self.password = config.get("password", "")

        self.candidates_endpoint = config.get("candidates_endpoint", "/candidates")
        self.jobs_endpoint = config.get("jobs_endpoint", "/jobs")

        self.candidates_results_key = config.get("candidates_results_key", "")
        self.jobs_results_key = config.get("jobs_results_key", "")

        self.candidate_field_map = config.get("candidate_field_map", {})
        self.job_field_map = config.get("job_field_map", {})

        self.page_param = config.get("page_param", "page")
        self.per_page_param = config.get("per_page_param", "per_page")
        self.per_page = int(config.get("per_page", 100))
        self.max_pages = int(config.get("max_pages", 100))

        self.timeout = float(config.get("timeout", 30))

    # ── connection ──

    def test_connection(self) -> dict[str, Any]:
        if not self.base_url:
            return {"ok": False, "message": "No base_url configured"}
        try:
            resp = self._request("GET", self.candidates_endpoint, params={self.per_page_param: "1"})
            return {"ok": resp.status_code < 400, "message": f"HTTP {resp.status_code}"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    # ── fetch candidates ──

    def fetch_candidates(self, job_id: str = "", **filters: Any) -> list[CandidateImport]:
        endpoint = self.candidates_endpoint
        params: dict[str, str] = {}

        if job_id:
            params["job_id"] = job_id
        for key, val in filters.items():
            params[key] = str(val)

        rows = self._paginate("GET", endpoint, params, self.candidates_results_key)

        fm = self.candidate_field_map
        candidates: list[CandidateImport] = []
        for row in rows:
            skills_raw = _get(row, fm, "skills")
            skills = [
                SkillDefinition(name=s.strip())
                for s in skills_raw.split(",") if s.strip()
            ] if skills_raw else []

            candidates.append(CandidateImport(
                name=_get(row, fm, "name"),
                email=_get(row, fm, "email"),
                phone=_get(row, fm, "phone"),
                resume_text=_get(row, fm, "resume_text"),
                resume_url=_get(row, fm, "resume_url"),
                skills=skills,
                experience_years=int(_get(row, fm, "experience_years", "0") or 0),
                current_title=_get(row, fm, "current_title"),
                current_company=_get(row, fm, "current_company"),
                source=_get(row, fm, "source") or "api",
                external_id=_get(row, fm, "external_id") or _get(row, fm, "id"),
                external_url=_get(row, fm, "external_url"),
                applied_to=_get(row, fm, "applied_to") or job_id,
                raw=row,
            ))
        return candidates

    # ── fetch jobs ──

    def fetch_jobs(self, **filters: Any) -> list[JobImport]:
        params: dict[str, str] = {}
        for key, val in filters.items():
            params[key] = str(val)

        rows = self._paginate("GET", self.jobs_endpoint, params, self.jobs_results_key)

        fm = self.job_field_map
        jobs: list[JobImport] = []
        for row in rows:
            req_raw = _get(row, fm, "required_skills")
            required = [
                SkillDefinition(name=s.strip())
                for s in req_raw.split(",") if s.strip()
            ] if req_raw else []

            pref_raw = _get(row, fm, "preferred_skills")
            preferred = [
                SkillDefinition(name=s.strip())
                for s in pref_raw.split(",") if s.strip()
            ] if pref_raw else []

            jobs.append(JobImport(
                title=_get(row, fm, "title"),
                description=_get(row, fm, "description"),
                department=_get(row, fm, "department"),
                required_skills=required,
                preferred_skills=preferred,
                location=_get(row, fm, "location"),
                employment_type=_get(row, fm, "employment_type"),
                external_id=_get(row, fm, "external_id") or _get(row, fm, "id"),
                external_url=_get(row, fm, "external_url"),
                raw=row,
            ))
        return jobs

    # ── fetch skills (not typical for a generic API) ──

    def fetch_skills(self) -> list[SkillDefinition]:
        return []

    # ── internal helpers ──

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.auth_type == "bearer":
            headers[self.auth_header_name] = f"Bearer {self.auth_token}"
        elif self.auth_type == "api_key":
            headers[self.auth_header_name] = self.auth_token
        elif self.auth_type == "basic":
            creds = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            headers["Authorization"] = f"Basic {creds}"
        return headers

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.base_url}{endpoint}"
        headers = self._build_headers()
        return httpx.request(method, url, headers=headers, timeout=self.timeout, **kwargs)

    def _paginate(
        self,
        method: str,
        endpoint: str,
        params: dict[str, str],
        results_key: str,
    ) -> list[dict[str, Any]]:
        """Fetch all pages and return the combined list of result dicts."""
        all_rows: list[dict[str, Any]] = []

        for page in range(1, self.max_pages + 1):
            page_params = {
                **params,
                self.page_param: str(page),
                self.per_page_param: str(self.per_page),
            }
            resp = self._request(method, endpoint, params=page_params)
            resp.raise_for_status()
            body = resp.json()

            if results_key:
                rows = _resolve(body, results_key)
            else:
                rows = body

            if not isinstance(rows, list):
                rows = [rows] if rows else []

            if not rows:
                break

            all_rows.extend(rows)

            if len(rows) < self.per_page:
                break

        return all_rows
