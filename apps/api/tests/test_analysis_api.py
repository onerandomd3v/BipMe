"""HTTP contract and fail-closed authentication tests for COD-358."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from bipme.api.analysis import _content_fingerprint
from bipme.api.app import create_app
from bipme.api.dependencies import AuthenticatedCreator, get_authenticated_creator, get_db_session
from bipme.api.errors import ApiError
from bipme.api.schemas import DraftAnalysisRequest


def test_production_creator_route_fails_closed_before_database_access() -> None:
    client = TestClient(create_app())
    response = client.get(
        "/api/v1/creators/me/baseline",
        params={
            "metric": "impressions",
            "definition": "public_impressions_v1",
            "unit": "impressions",
            "window_kind": "age_aligned",
            "window_key": "age:24h",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "authentication_not_configured",
            "message": "Creator analysis is unavailable until secure account sessions are configured.",
            "fields": None,
        }
    }


def test_revoked_session_error_uses_the_shared_error_contract() -> None:
    app = create_app()

    def revoked_identity():
        raise ApiError(401, "session_revoked", "The creator session is no longer valid.")

    from bipme.api.dependencies import get_authenticated_creator

    app.dependency_overrides[get_authenticated_creator] = revoked_identity
    response = TestClient(app).get(
        "/api/v1/creators/me/draft-assessments/00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_revoked"


def test_invalid_draft_is_a_structured_validation_error() -> None:
    app = create_app()
    app.dependency_overrides[get_authenticated_creator] = lambda: AuthenticatedCreator(
        UUID("00000000-0000-0000-0000-000000000001")
    )
    app.dependency_overrides[get_db_session] = lambda: object()
    response = TestClient(app).post(
        "/api/v1/creators/me/draft-assessments",
        headers={"Idempotency-Key": "draft-invalid-001"},
        json={"text": "   "},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert "text" in response.json()["error"]["fields"][0]["field"]
    assert "   " not in response.text


def test_canonical_fingerprint_normalizes_unicode_and_newlines_but_preserves_whitespace() -> None:
    first = DraftAnalysisRequest(text="Cafe\u0301\r\nsecond line", topology="original")
    equivalent = DraftAnalysisRequest(text="Café\nsecond line", topology="original")
    changed = DraftAnalysisRequest(text="Café\n second line", topology="original")

    assert _content_fingerprint(first) == _content_fingerprint(equivalent)
    assert _content_fingerprint(first) != _content_fingerprint(changed)


def test_openapi_is_authoritative_and_documents_routes_errors_and_versioned_evidence() -> None:
    schema = create_app().openapi()
    paths = schema["paths"]
    assert "/api/v1/creators/me/baseline" in paths
    assert "/api/v1/creators/me/draft-assessments" in paths
    assert "/api/v1/creators/me/draft-assessments/{assessment_id}" in paths

    analysis = paths["/api/v1/creators/me/draft-assessments"]["post"]
    assert "Idempotency-Key" in str(analysis["parameters"])
    assert (
        "ErrorResponse"
        in analysis["responses"]["503"]["content"]["application/json"]["schema"]["$ref"]
    )
    response_schema = schema["components"]["schemas"]["DraftAnalysisResponse"]["properties"]
    assert {"input_fingerprint", "versions", "decision_state", "metrics", "observations"} <= set(
        response_schema
    )
    assert response_schema["observations"]["maxItems"] == 2


def test_committed_openapi_artifact_matches_fastapi_contract() -> None:
    artifact = Path(__file__).parents[1] / "openapi.json"

    assert json.loads(artifact.read_text(encoding="utf-8")) == create_app().openapi()
