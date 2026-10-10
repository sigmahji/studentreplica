"""Public remote listings remain source-backed, private and correctly labelled."""

from __future__ import annotations

import json
from io import BytesIO

from ai.client import MockClient
from ai.service import AIService
from modules.job_sources import jobicy_sources
from modules.market_research import research_local_market
from storage.repository import TwinRepository
from storage.twin_schema import empty_twin


def records() -> list[dict]:
    return [
        {
            "id": 123,
            "url": "https://jobicy.com/jobs/123-python-developer",
            "jobTitle": "Python Developer",
            "companyName": "Example Company",
            "jobGeo": "Anywhere",
            "jobLevel": "Senior",
            "jobDescription": "<p>Build software with <strong>Python</strong> and SQL.</p>",
            "pubDate": "2026-10-10T00:00:00Z",
        },
        {
            "id": 124,
            "url": "https://jobicy.com/jobs/124-nursing",
            "jobTitle": "Nurse",
            "companyName": "Example Hospital",
            "jobGeo": "Anywhere",
            "jobDescription": "Nursing care and patient safety.",
        },
        {
            "id": 125,
            "url": "https://jobicy.com/jobs/125-python-us-only",
            "jobTitle": "Python Developer",
            "jobGeo": "USA",
            "jobDescription": "Python software.",
        },
        {
            "id": 126,
            "url": "https://untrusted.example/jobs/126",
            "jobTitle": "Python Intern",
            "jobGeo": "Anywhere",
            "jobDescription": "Python software.",
        },
    ]


def test_public_feed_never_receives_student_data_and_preserves_eligibility(
    ctx_a, monkeypatch
) -> None:
    import modules.job_sources as source_module

    requests = []

    def fetch(request, timeout):
        requests.append(request.full_url)
        assert timeout <= 15
        return BytesIO(json.dumps({"jobs": records()}).encode())

    monkeypatch.setattr(source_module, "urlopen", fetch)
    result = jobicy_sources(
        ctx_a,
        {
            "name": "PRIVATE_NAME",
            "degree": "Software Engineering",
            "skills": ["Python"],
        },
    )
    assert "PRIVATE" not in str(requests) and ctx_a.user_id not in str(requests)
    assert len(result["feed_openings"]) == 1
    opening = result["feed_openings"][0]
    assert opening["title"] == "Python Developer"
    assert opening["experience_level"] == "Senior"
    assert opening["location"] == "Remote - Anywhere"
    assert opening["required_skills"] == []
    assert "<strong>" not in opening["description"]
    assert result["sources"][0]["publisher"] == "Jobicy"


def test_local_only_students_are_not_given_remote_fallbacks(ctx_a, monkeypatch) -> None:
    import modules.job_sources as source_module
    import modules.market_research as market_module

    monkeypatch.setattr(market_module, "GROQ_API_KEY", "")
    monkeypatch.setattr(
        source_module,
        "jobicy_sources",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("Remote feed must not be called")
        ),
    )
    result = research_local_market(
        ctx_a,
        {"city": "Karachi", "work_preference": "Local"},
        api_key="",
        allow_groq=True,
    )
    assert result["mode"] == "reference" and not result["sources"]


def test_groq_search_quota_uses_attributed_remote_sources(ctx_a, monkeypatch) -> None:
    import modules.job_sources as source_module
    import modules.market_research as market_module

    class SearchQuotaError(RuntimeError):
        status_code = 429

    def quota(*args):
        raise SearchQuotaError()

    monkeypatch.setattr(market_module, "GROQ_API_KEY", "test-only")
    monkeypatch.setattr(market_module, "AI_PROVIDER", "groq")
    monkeypatch.setattr(market_module, "_groq_sources", quota)
    monkeypatch.setattr(
        source_module,
        "urlopen",
        lambda *args, **kwargs: BytesIO(json.dumps({"jobs": records()}).encode()),
    )
    result = research_local_market(
        ctx_a,
        {
            "city": "Karachi",
            "degree": "Software Engineering",
            "skills": ["Python"],
            "work_preference": "Local or remote",
        },
        api_key="",
        allow_groq=True,
    )
    assert result["mode"] == "live_web" and result["scope"] == "remote"
    assert (
        "Jobicy" in result["notice"]
        and "Local demand is unverified" in result["notice"]
    )


def test_real_feed_listings_survive_offline_analysis_and_research_is_reused(
    open_session, ctx_a, monkeypatch
) -> None:
    import modules.job_sources as source_module
    import modules.market_research as market_module

    monkeypatch.setattr(
        source_module,
        "urlopen",
        lambda *args, **kwargs: BytesIO(json.dumps({"jobs": records()}).encode()),
    )
    profile = {
        "city": "Karachi",
        "degree": "Software Engineering",
        "skills": ["Python"],
    }
    feed = jobicy_sources(ctx_a, profile)
    calls = []

    def research(*args, **kwargs):
        calls.append(1)
        return {
            "mode": "live_web",
            "scope": "remote",
            "location": "Remote - worldwide eligibility",
            "notice": "Source: Jobicy; local demand unverified",
            "retrieved_at": "2026-10-10T00:00:00Z",
            **feed,
        }

    monkeypatch.setattr(market_module, "research_local_market", research)
    service = AIService(client=MockClient())
    with open_session() as session:
        repo = TwinRepository(session)
        twin = empty_twin("Private Feed Student")
        twin["profile"].update(degree="Software Engineering", city="Karachi")
        twin["skills"] = [{"name": "Python", "proficiency": 80}]
        repo.save_twin(ctx_a, twin)
        service.generate_student_career_plan(session, ctx_a)
        result = service.analyze_live_market(session, ctx_a)
        assert len(calls) == 1
        assert result["offline_mode"]
        assert result["jobs"][0]["url"] == records()[0]["url"]
        assert result["jobs"][0]["match_score"] is None
        assert result["jobs"][0]["publisher"] == "Jobicy"
