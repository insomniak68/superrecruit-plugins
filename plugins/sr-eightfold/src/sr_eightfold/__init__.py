"""Eightfold AI Source Plugin — fetch positions and applicants from CareerHub.

Supports three authentication modes:

  1. **cookie** (default) — No admin access needed!
     Log in to CareerHub in your browser, open DevTools → Application → Cookies,
     and copy the ``session`` and ``remember_token`` cookie values.

  2. **oauth** — Eightfold API OAuth (requires admin-provisioned username & API key)

  3. **bearer** — Paste a Bearer token from the Eightfold API

Data flow:
  fetch_jobs()        → GET /api/feedback/boot → extract unique positions
  fetch_candidates()  → GET /api/feedback/boot → list assigned candidates
                        GET /api/profile-v2/{id}/basic_info → enrich with skills & experience
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from narrowfield import (
    CandidateImport,
    JobImport,
    PluginInfo,
    PluginError,
    SkillDefinition,
)

log = logging.getLogger("sr_eightfold")

_DEFAULT_BASE_URL = "https://careerhub.microsoft.com"

# Eightfold OAuth regional endpoints
_REGION_AUTH: dict[str, dict[str, str]] = {
    "us": {
        "api_base": "https://apiv2.eightfold.ai",
        "basic": "MU92YTg4T1JyMlFBVktEZG8wc1dycTdEOnBOY1NoMno1RlFBMTZ6V2QwN3cyeUFvc3QwTU05MmZmaXFFRDM4ZzJ4SFVyMGRDaw==",
    },
    "eu": {
        "api_base": "https://apiv2.eightfold-eu.ai",
        "basic": "Vmd6RlF4YklLUnI2d0tNZWRpdVZTOFhJOmdiM1pjYzUyUzNIRmhsNzd5c2VmNTgyOG5jVk05djl1dGVtQ2tmNVEyMnRpV1VJVQ==",
    },
}


class Plugin:
    """Import positions and applicants from Eightfold AI / Microsoft CareerHub.

    Uses the internal CareerHub web API with browser cookies (no admin access
    required), or the official Eightfold API v2 with OAuth/Bearer tokens.
    """

    def __init__(self) -> None:
        self.base_url: str = _DEFAULT_BASE_URL
        self.domain: str = "microsoft.eightfold.ai"

        # Auth: "cookie" (default), "oauth", or "bearer"
        self.auth_mode: str = "cookie"

        # Cookie auth (from browser)
        self.session_cookie: str = ""
        self.remember_token: str = ""

        # OAuth credentials (Eightfold admin console)
        self.oauth_username: str = ""
        self.oauth_password: str = ""
        self.region: str = "us"

        # Bearer token
        self.bearer_token: str = ""

        # Options
        self.enrich_profiles: bool = True
        self.download_resumes: bool = True
        self.feedback_status: str = "REQUESTED"
        self.timeout: float = 30.0

        self._client: httpx.Client | None = None

    # ── metadata ──────────────────────────────────────────────────

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="eightfold",
            display_name="Eightfold AI / CareerHub",
            version="0.1.5",
            description="Fetch positions and applicants from Eightfold AI (CareerHub)",
            capabilities=["source:jobs", "source:candidates"],
        )

    # ── configuration ─────────────────────────────────────────────

    def configure(self, config: dict[str, Any]) -> None:
        # Invalidate cached client so new credentials take effect
        self._client = None

        self.base_url = config.get("base_url", _DEFAULT_BASE_URL).rstrip("/")
        self.domain = config.get("domain", "microsoft.eightfold.ai")

        self.auth_mode = config.get("auth_mode", "cookie")

        # Cookie auth
        self.session_cookie = config.get("session_cookie", "")
        self.remember_token = config.get("remember_token", "")

        # OAuth
        self.oauth_username = config.get("oauth_username", "")
        self.oauth_password = config.get("oauth_password", "")
        self.region = config.get("region", "us").lower()

        # Bearer
        token = config.get("bearer_token", "")
        self.bearer_token = token.removeprefix("Bearer ").strip() if token else ""

        # Options
        self.enrich_profiles = config.get("enrich_profiles", True)
        self.download_resumes = config.get("download_resumes", True)
        self.feedback_status = config.get("feedback_status", "REQUESTED")
        self.timeout = float(config.get("timeout", 30))

    # ── connection test ───────────────────────────────────────────

    def test_connection(self) -> dict[str, Any]:
        try:
            client = self._build_client()
            resp = client.get(
                f"{self.base_url}/api/feedback/boot",
                params={"view": "interviewer", "status": self.feedback_status},
            )
            if resp.status_code == 500:
                return {
                    "ok": False,
                    "message": (
                        "CareerHub returned 500 — your session cookies have "
                        "likely expired. Refresh them from DevTools."
                    ),
                }
            if resp.status_code < 400:
                body = resp.json()
                count = body.get("feedback_count", {}).get("interviewer", {})
                return {
                    "ok": True,
                    "message": (
                        f"Connected to CareerHub — "
                        f"{count.get('REQUESTED', 0)} pending, "
                        f"{count.get('SUBMITTED', 0)} submitted"
                    ),
                }
            return {"ok": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    # ── fetch positions (jobs) ────────────────────────────────────

    def fetch_jobs(self, **filters: Any) -> list[JobImport]:
        feedback_data = self._fetch_feedback_data()

        # Deduplicate positions
        positions: dict[str, dict[str, Any]] = {}
        for entry in feedback_data:
            pid = str(entry.get("position_id", ""))
            if pid and pid not in positions:
                positions[pid] = entry

        jobs: list[JobImport] = []
        for pid, entry in positions.items():
            jobs.append(JobImport(
                title=entry.get("position_name", ""),
                external_id=pid,
                external_url=entry.get("position_url", ""),
                metadata={
                    "display_job_id": entry.get("position_display_job_id", ""),
                    "position_type": entry.get("position_type", ""),
                    "recruiter": entry.get("recruiter_fullname", ""),
                },
                raw=entry,
            ))
        return jobs

    # ── fetch candidates ──────────────────────────────────────────

    def fetch_candidates(self, job_id: str = "", **filters: Any) -> list[CandidateImport]:
        feedback_data = self._fetch_feedback_data()

        if job_id:
            feedback_data = [
                e for e in feedback_data
                if str(e.get("position_id", "")) == job_id
            ]

        seen: set[str] = set()
        candidates: list[CandidateImport] = []

        for entry in feedback_data:
            enc_id = entry.get("enc_profile_id", "")
            if not enc_id or enc_id in seen:
                continue
            seen.add(enc_id)

            candidate = self._build_candidate_from_feedback(entry)

            if self.enrich_profiles:
                candidate = self._enrich_candidate(candidate, enc_id)

            candidates.append(candidate)

        return candidates

    def _build_candidate_from_feedback(self, entry: dict[str, Any]) -> CandidateImport:
        """Build a basic CandidateImport from a feedback_data entry."""
        position_id = str(entry.get("position_id", ""))
        profile_id = str(entry.get("profile_id", ""))

        return CandidateImport(
            name=entry.get("candidate_name", ""),
            email="",
            current_title=entry.get("candidate_title", ""),
            source="careerhub",
            external_id=profile_id,
            external_url=f"https://{self.domain}/profile/{entry.get('enc_profile_id', '')}",
            applied_to=position_id,
            metadata={
                "enc_profile_id": entry.get("enc_profile_id", ""),
                "position_name": entry.get("position_name", ""),
                "feedback_url": entry.get("feedback_url", ""),
                "feedback_status": entry.get("status", ""),
                "recruiter": entry.get("recruiter_fullname", ""),
                "requested_time": entry.get("requested_time", ""),
            },
            raw=entry,
        )

    def _enrich_candidate(self, candidate: CandidateImport, enc_id: str) -> CandidateImport:
        """Fetch the full profile and enrich the candidate with skills & experience."""
        try:
            client = self._build_client()
            resp = client.get(
                f"{self.base_url}/api/profile-v2/{enc_id}/basic_info",
                params={"minimal": "true", "is_resourcing_view": "false", "feedback_view": "true"},
            )
            if resp.status_code >= 400:
                log.warning("Failed to fetch profile %s: HTTP %d", enc_id, resp.status_code)
                return candidate

            body = resp.json()
            profile = body.get("data", {})
            if not profile:
                return candidate

        except Exception as exc:
            log.warning("Error fetching profile %s: %s", enc_id, exc)
            return candidate

        # Skills
        ranked_skills = profile.get("rankedSkills", [])
        candidate.skills = [
            SkillDefinition(name=s) for s in ranked_skills if isinstance(s, str)
        ]

        # Experience
        experience = profile.get("experience", []) or []
        if experience:
            latest = experience[0]
            candidate.current_title = latest.get("title", "") or candidate.current_title
            candidate.current_company = latest.get("work", "")
            candidate.experience_years = _total_experience_years(experience)

        # Name (prefer full profile name)
        candidate.name = profile.get("fullName", "") or candidate.name

        # Contact info
        custom_info = profile.get("customInfo", {})
        more = custom_info.get("moreCandidate", {}).get("dataFields", {})
        personal_email = more.get("custPersonalemail")
        if personal_email:
            if isinstance(personal_email, list):
                personal_email = personal_email[0] if personal_email else ""
            candidate.email = str(personal_email)

        # Resume download
        if self.download_resumes:
            pdf_bytes, pdf_filename = self._download_resume(enc_id)
            if pdf_bytes:
                candidate.resume_bytes = pdf_bytes
                candidate.resume_filename = pdf_filename

        # Profile URL
        candidate.external_url = f"https://{self.domain}/profile/{enc_id}"

        # Location in metadata
        location = profile.get("location", "")
        if location:
            candidate.metadata["location"] = location

        # Education in metadata
        education = profile.get("education", []) or []
        if education:
            candidate.metadata["education"] = [
                {
                    "school": e.get("school", ""),
                    "degree": e.get("degree", ""),
                    "major": e.get("major", ""),
                }
                for e in education
            ]

        # Experience details in metadata
        if experience:
            candidate.metadata["experience"] = [
                {
                    "title": e.get("title", ""),
                    "company": e.get("work", ""),
                    "duration_months": e.get("durationMonths", 0),
                    "description": e.get("description", "")[:500],
                }
                for e in experience
            ]

        return candidate

    def _download_resume(self, enc_id: str) -> tuple[bytes, str]:
        """Download a candidate's resume PDF from CareerHub.

        Fetches the resume page HTML, parses the embedded iframe src to find
        the actual PDF URL, then downloads the PDF bytes.

        Returns (pdf_bytes, filename) or (b"", "") on failure.
        """
        try:
            client = self._build_client()
            # Fetch resume page HTML
            resp = client.get(
                f"{self.base_url}/profile/{enc_id}/resume",
                params={
                    "anon": "0",
                    "feedback_view": "true",
                    "profile_v2_view": "true",
                    "hide_download_options": "false",
                },
                headers={"Accept": "text/html,application/xhtml+xml,*/*"},
            )
            if resp.status_code >= 400:
                log.debug("Resume page returned %d for %s", resp.status_code, enc_id)
                return b"", ""

            html = resp.text

            # Parse iframe src — the resume is embedded as:
            #   <iframe src="/profile/{enc_id}?export=ats/.../attachments/{file}&amp;inline=true&amp;group_id=...">
            match = re.search(r'<iframe[^>]+src="([^"]+)"', html, re.IGNORECASE)
            if not match:
                log.debug("No iframe found in resume page for %s", enc_id)
                return b"", ""

            iframe_src = match.group(1)
            # Decode HTML entities (&amp; → &)
            iframe_src = iframe_src.replace("&amp;", "&")

            # Extract filename from the export parameter
            filename_match = re.search(r'attachments/([^&"]+)', iframe_src)
            filename = filename_match.group(1) if filename_match else f"{enc_id}.bin"

            # Build absolute URL if relative
            if iframe_src.startswith("/"):
                pdf_url = f"{self.base_url}{iframe_src}"
            else:
                pdf_url = iframe_src

            # Download the resume (may be PDF, DOCX, or DOC)
            doc_resp = client.get(
                pdf_url,
                headers={"Accept": "application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/msword,*/*"},
                timeout=60.0,
            )
            if doc_resp.status_code >= 400:
                log.debug("Resume download returned %d for %s", doc_resp.status_code, enc_id)
                return b"", ""

            content_type = doc_resp.headers.get("content-type", "")
            known_types = ("pdf", "word", "msword", "officedocument", "octet-stream")
            if not any(t in content_type for t in known_types) and len(doc_resp.content) < 100:
                log.debug("Resume response doesn't look like a document for %s (type=%s)", enc_id, content_type)
                return b"", ""

            log.info("Downloaded resume for %s (%d bytes, type=%s)", enc_id, len(doc_resp.content), content_type)
            return doc_resp.content, filename

        except Exception as exc:
            log.warning("Error downloading resume for %s: %s", enc_id, exc)
            return b"", ""

    # ── fetch skills (not applicable) ─────────────────────────────

    def fetch_skills(self) -> list[SkillDefinition]:
        return []

    # ── internal: fetch feedback data ─────────────────────────────

    def _fetch_feedback_data(self) -> list[dict[str, Any]]:
        """Call /api/feedback/boot and return the feedback_data list."""
        client = self._build_client()
        resp = client.get(
            f"{self.base_url}/api/feedback/boot",
            params={
                "view": "interviewer",
                "status": self.feedback_status,
                "sort_by": "profile_feedback.requested_timestamp desc",
            },
        )
        if resp.status_code == 500:
            raise PluginError(
                "CareerHub returned 500 — your session cookies have likely expired. "
                "Log in to CareerHub in your browser, open DevTools → Application → "
                "Cookies, and copy fresh 'session' and 'remember_token' values into "
                "plugins.yaml, then restart."
            )
        if resp.status_code in (401, 403):
            raise PluginError(
                f"CareerHub returned {resp.status_code} — authentication failed. "
                "Please refresh your cookies in plugins.yaml."
            )
        resp.raise_for_status()
        body = resp.json()
        return body.get("feedback_data", [])

    # ── HTTP client ───────────────────────────────────────────────

    def _build_client(self) -> httpx.Client:
        """Build an httpx client with the appropriate auth."""
        if self._client is not None:
            return self._client

        headers: dict[str, str] = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
            ),
            "Referer": f"{self.base_url}/",
        }
        cookies: dict[str, str] = {}

        if self.auth_mode == "cookie":
            if not self.session_cookie and not self.remember_token:
                raise PluginError(
                    "No cookies configured. Log in to CareerHub, open "
                    "DevTools → Application → Cookies, and copy the "
                    "'session' and 'remember_token' values into plugins.yaml."
                )
            if self.session_cookie:
                cookies["session"] = self.session_cookie
            if self.remember_token:
                cookies["remember_token"] = self.remember_token

        elif self.auth_mode == "bearer":
            if not self.bearer_token:
                raise PluginError("No bearer_token configured.")
            headers["Authorization"] = f"Bearer {self.bearer_token}"

        elif self.auth_mode == "oauth":
            token = self._oauth_authenticate()
            headers["Authorization"] = f"Bearer {token}"

        else:
            raise PluginError(f"Unknown auth_mode: {self.auth_mode!r}")

        self._client = httpx.Client(
            headers=headers,
            cookies=cookies,
            timeout=self.timeout,
            follow_redirects=True,
        )
        return self._client

    def _oauth_authenticate(self) -> str:
        """Exchange OAuth username + password for an access token."""
        if not self.oauth_username or not self.oauth_password:
            raise PluginError("oauth_username and oauth_password are required for OAuth auth")

        region_info = _REGION_AUTH.get(self.region, _REGION_AUTH["us"])
        url = f"{region_info['api_base']}/oauth/v1/authenticate"
        headers = {
            "Authorization": f"Basic {region_info['basic']}",
            "Content-Type": "application/json",
        }
        payload = {
            "grantType": "password",
            "username": self.oauth_username,
            "password": self.oauth_password,
        }

        resp = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
        if resp.status_code >= 400:
            raise PluginError(f"OAuth failed: HTTP {resp.status_code} — {resp.text[:300]}")

        data = resp.json().get("data", {})
        token = data.get("access_token", "")
        if not token:
            raise PluginError(f"No access_token in OAuth response: {resp.text[:300]}")

        log.info("Eightfold OAuth token acquired (expires in %ss)", data.get("expires_in", "?"))
        return token


# ── utility functions ─────────────────────────────────────────────

def _total_experience_years(experience: list[dict[str, Any]]) -> int:
    """Sum up experience duration from durationMonths fields."""
    total_months = 0
    for entry in experience:
        months = entry.get("durationMonths", 0)
        if months:
            total_months += int(months)
    return total_months // 12
