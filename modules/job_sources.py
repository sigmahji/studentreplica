"""Public remote listings used when AI-powered web research is unavailable."""

from __future__ import annotations

import json
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from storage.context import UserContext


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def jobicy_sources(ctx: UserContext, profile: dict[str, Any]) -> dict[str, Any]:
    """Filter public records locally; no student details are sent to the feed."""
    request = Request(
        "https://jobicy.com/api/v2/remote-jobs?count=100&geo=anywhere",
        headers={"User-Agent": "StudentTwin/1.0", "Accept": "application/json"},
    )
    with urlopen(request, timeout=12) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Public job response exceeds the input limit")
    data = json.loads(raw)
    terms = set(
        re.findall(
            r"[a-z]{3,}",
            " ".join(
                [str(profile.get("degree", "")), str(profile.get("field_of_study", ""))]
                + list(profile.get("career_goals", []))
                + list(profile.get("interests", []))
                + list(profile.get("skills", []))
            ).casefold(),
        )
    ) - {
        "and",
        "the",
        "with",
        "degree",
        "bachelor",
        "science",
        "student",
        "career",
        "jobs",
    }
    candidates = []
    for record in data.get("jobs", [])[:100]:
        if not isinstance(record, dict):
            continue
        parsed = urlsplit(str(record.get("url", "")))
        if (
            parsed.scheme != "https"
            or parsed.hostname != "jobicy.com"
            or parsed.username
            or not parsed.path.startswith("/jobs/")
        ):
            continue
        if str(record.get("jobGeo", "")).casefold() not in {"anywhere", "worldwide"}:
            continue
        title = unescape(str(record.get("jobTitle", "")))[:200].strip()
        if not title:
            continue
        parser = _PlainText()
        parser.feed(str(record.get("jobDescription", ""))[:30000])
        description = " ".join(" ".join(parser.parts).split())
        title_words = set(re.findall(r"[a-z]{3,}", title.casefold()))
        text_words = set(re.findall(r"[a-z]{3,}", description.casefold()))
        relevance = 3 * len(title_words & terms) + len(text_words & terms)
        if relevance:
            candidates.append((relevance, record, title, description))
    candidates.sort(key=lambda item: item[0], reverse=True)
    sources, openings = [], []
    for i, (_, record, title, description) in enumerate(candidates[:6]):
        source_id = f"source_{i + 1}"
        company = unescape(str(record.get("companyName") or "Not supplied"))[:150]
        level = str(record.get("jobLevel") or "Not supplied")[:80]
        snippet = f"{title}. Company: {company}. Remote location eligibility: Anywhere. Level: {level}. {description}"[
            :1800
        ]
        sources.append(
            {
                "id": source_id,
                "url": record["url"],
                "title": title,
                "snippet": snippet,
                "published_date": record.get("pubDate"),
                "publisher": "Jobicy",
            }
        )
        openings.append(
            {
                "id": f"jobicy_{record['id']}",
                "source_id": source_id,
                "title": title,
                "company": company,
                "location": "Remote - Anywhere",
                "url": record["url"],
                "published_date": record.get("pubDate"),
                "description": snippet,
                "required_skills": [],
                "live_source": True,
                "publisher": "Jobicy",
                "experience_level": level,
            }
        )
    return {"sources": sources, "feed_openings": openings}
