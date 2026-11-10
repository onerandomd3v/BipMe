"""Synthetic API coverage for COD-361 manual publication linking."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from bipme.api.app import create_app
from bipme.api.dependencies import (
    AuthenticatedCreator,
    get_authenticated_creator,
    get_current_time,
    get_db_session,
)
from bipme.api.errors import ApiError
from bipme.api.publications import _text_fingerprint, get_x_publication_verifier, parse_x_post_id
from bipme.auth.crypto import TokenCipher
from bipme.integrations.x_publication import (
    HttpXPublishedPostProvider,
    PublishedPostEvidence,
    XPublicationSettings,
    XPublicationUnavailable,
    XPublishedPostVerifier,
)
from bipme.persistence.base import Base, EncryptedTokenEnvelope
from bipme.persistence.models import (
    CanonicalPost,
    Creator,
    CreatorPlatformIdentity,
    DraftAssessment,
    XAccountConnection,
)

CREATOR_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_CREATOR_ID = UUID("22222222-2222-4222-8222-222222222222")
ASSESSMENT_ID = UUID("33333333-3333-4333-8333-333333333333")
SECOND_ASSESSMENT_ID = UUID("77777777-7777-4777-8777-777777777777")
NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)


class FakeVerifier:
    def __init__(self, result: PublishedPostEvidence | Exception) -> None:
        self.result = result
        self.calls: list[str] = []

    def verify(self, _db: Session, *, creator_id: UUID, post_id: str, now: datetime):
        del creator_id, now
        self.calls.append(post_id)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def publication_api() -> Iterator[tuple[TestClient, sessionmaker[Session], FakeVerifier]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Creator.__table__,
        CreatorPlatformIdentity.__table__,
        XAccountConnection.__table__,
        DraftAssessment.__table__,
        CanonicalPost.__table__,
    ]
    postgres_only: list[tuple[object, CheckConstraint]] = []
    for table in tables:
        for constraint in list(table.constraints):
            if isinstance(constraint, CheckConstraint) and any(
                marker in str(constraint.sqltext)
                for marker in ("jsonb_typeof", "substring(", "left(")
            ):
                postgres_only.append((table, constraint))
                table.constraints.remove(constraint)
    try:
        Base.metadata.create_all(engine, tables=tables)
    finally:
        for table, constraint in postgres_only:
            table.constraints.add(constraint)

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add_all(
            (
                Creator(id=CREATOR_ID),
                Creator(id=OTHER_CREATOR_ID),
                CreatorPlatformIdentity(
                    id=uuid4(),
                    creator_id=CREATOR_ID,
                    platform="x",
                    external_creator_id="987654321",
                ),
            )
        )
        db.flush()
        identity = db.scalar(
            select(CreatorPlatformIdentity).where(CreatorPlatformIdentity.creator_id == CREATOR_ID)
        )
        assert identity is not None
        db.add(
            XAccountConnection(
                id=uuid4(),
                creator_id=CREATOR_ID,
                creator_identity_id=identity.id,
                platform="x",
                state="connected",
                scopes=["tweet.read", "users.read"],
                encrypted_access_token=EncryptedTokenEnvelope.prefix + b"synthetic",
                key_version="v1",
                access_token_expires_at=NOW + timedelta(hours=1),
            )
        )
        db.add(_assessment())
        db.commit()

    evidence = PublishedPostEvidence(
        external_post_id="123456789",
        author_id="987654321",
        text="Original draft",
        published_at=NOW + timedelta(minutes=5),
        topology="original",
        media_present=False,
    )
    verifier = FakeVerifier(evidence)
    app = create_app()
    app.dependency_overrides[get_authenticated_creator] = lambda: AuthenticatedCreator(CREATOR_ID)
    app.dependency_overrides[get_current_time] = lambda: NOW + timedelta(minutes=10)
    app.dependency_overrides[get_x_publication_verifier] = lambda: verifier

    def override_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db_session] = override_db
    with TestClient(app) as client:
        yield client, factory, verifier
    engine.dispose()


def _assessment(
    *, assessment_id: UUID = ASSESSMENT_ID, creator_id: UUID = CREATOR_ID
) -> DraftAssessment:
    return DraftAssessment(
        id=assessment_id,
        creator_id=creator_id,
        assessment_key=f"assessment-{assessment_id}",
        assessed_at=NOW,
        content_fingerprint="sha256:" + "a" * 64,
        outlook_version="outlook-v1",
        decision_snapshot={
            "_cod361_linking": {
                "assessed_text_fingerprint": _text_fingerprint("Original draft"),
                "topology": "original",
                "media_present": False,
            }
        },
        accepted_hypothesis={
            "question": "Will this prompt discussion?",
            "metric": "replies",
            "metric_definition": "public_reply_count_v1",
            "unit": "replies",
            "window_kind": "age_aligned",
            "window_key": "age:24h",
            "expected_direction": "higher",
        },
    )


def test_parse_x_post_id_accepts_ids_and_strict_urls() -> None:
    assert parse_x_post_id("123456789") == "123456789"
    assert parse_x_post_id("https://x.com/example/status/123456789") == "123456789"
    assert parse_x_post_id("https://twitter.com/i/status/123456789") == "123456789"
    with pytest.raises(ApiError):
        parse_x_post_id("http://x.com/example/status/123456789")
    with pytest.raises(ApiError):
        parse_x_post_id("https://x.com/example/status/123456789?utm_source=test")
    with pytest.raises(ApiError):
        parse_x_post_id("https://x.com:443/example/status/123456789")
    with pytest.raises(ApiError):
        parse_x_post_id("https://x.com/example/status/not-a-number")


def test_http_provider_normalizes_read_only_post_evidence() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "id": "123456789",
                    "author_id": "987654321",
                    "text": "Original draft",
                    "created_at": "2026-11-09T12:05:00Z",
                    "referenced_tweets": [{"type": "replied_to", "id": "11"}],
                    "attachments": {"media_keys": ["3_1"]},
                }
            },
        )

    provider = HttpXPublishedPostProvider(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    evidence = provider.published_post(access_token="token", post_id="123456789")
    assert evidence == PublishedPostEvidence(
        external_post_id="123456789",
        author_id="987654321",
        text="Original draft",
        published_at=datetime(2026, 11, 9, 12, 5, tzinfo=UTC),
        topology="reply",
        media_present=True,
        reply_to_external_post_id="11",
    )
    assert requests[0].url.path == "/2/tweets/123456789"
    assert requests[0].headers["Authorization"] == "Bearer token"


def test_http_provider_maps_missing_post_without_writes() -> None:
    provider = HttpXPublishedPostProvider(
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(404))
        ),
        max_retries=0,
    )
    with pytest.raises(XPublicationUnavailable, match="post_not_found"):
        provider.published_post(access_token="token", post_id="123456789")


def test_verifier_fails_closed_before_any_external_call_when_gates_are_unverified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "BIPME_X_PUBLICATION_LINK_ENABLED",
        "BIPME_X_PUBLICATION_ACCOUNT_ENTITLEMENT_VERIFIED",
        "BIPME_X_PUBLICATION_DATA_RIGHTS_VERIFIED",
        "BIPME_X_ALLOWED_USER_ID",
        "BIPME_X_PUBLICATION_READ_ESTIMATED_COST_USD",
        "BIPME_X_PUBLICATION_DAILY_COST_LIMIT_USD",
    ):
        monkeypatch.delenv(name, raising=False)

    class NeverCalledProvider:
        max_request_attempts = 1

        def published_post(self, *, access_token: str, post_id: str) -> PublishedPostEvidence:
            raise AssertionError(f"unexpected provider call: {access_token}:{post_id}")

    verifier = XPublishedPostVerifier(
        provider=NeverCalledProvider(),
        cipher=TokenCipher({"v1": Fernet.generate_key().decode("ascii")}, "v1"),
        settings=XPublicationSettings.from_environment(),
    )
    with pytest.raises(XPublicationUnavailable, match="external_gate_unverified"):
        verifier.verify(
            object(),  # type: ignore[arg-type]
            creator_id=CREATOR_ID,
            post_id="123456789",
            now=NOW,
        )


def test_links_post_preserves_assessment_and_provider_timestamps(
    publication_api: tuple[TestClient, sessionmaker[Session], FakeVerifier],
) -> None:
    client, factory, verifier = publication_api
    response = client.post(
        f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/publication",
        json={"post_url_or_id": "https://x.com/example/status/123456789"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["assessment_id"] == str(ASSESSMENT_ID)
    assert body["assessed_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert body["external_post_id"] == "123456789"
    assert body["published_at"] == (NOW + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    assert body["version_match_state"] == "match"
    assert body["accepted_hypothesis"]["question"] == "Will this prompt discussion?"
    assert verifier.calls == ["123456789"]
    with factory() as db:
        post = db.scalar(select(CanonicalPost).where(CanonicalPost.external_post_id == "123456789"))
        assert post is not None
        assert post.source_assessment_id == ASSESSMENT_ID


def test_duplicate_request_replays_without_second_provider_call(
    publication_api: tuple[TestClient, sessionmaker[Session], FakeVerifier],
) -> None:
    client, _factory, verifier = publication_api
    path = f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/publication"
    assert client.post(path, json={"post_url_or_id": "123456789"}).status_code == 201
    replay = client.post(path, json={"post_url_or_id": "https://x.com/example/status/123456789"})
    assert replay.status_code == 200
    assert len(verifier.calls) == 1


def test_changed_text_is_mismatch_and_missing_evidence_is_unknown(
    publication_api: tuple[TestClient, sessionmaker[Session], FakeVerifier],
) -> None:
    client, _factory, verifier = publication_api
    path = f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/publication"
    verifier.result = PublishedPostEvidence(
        external_post_id="123456790",
        author_id="987654321",
        text="Changed published copy",
        published_at=NOW + timedelta(minutes=5),
        media_present=False,
    )
    mismatch = client.post(path, json={"post_url_or_id": "123456790"})
    assert mismatch.status_code == 201
    assert mismatch.json()["version_match_state"] == "mismatch"

    with _factory() as db:
        db.add(_assessment(assessment_id=SECOND_ASSESSMENT_ID))
        db.commit()
    verifier.result = PublishedPostEvidence(
        external_post_id="123456791",
        author_id="987654321",
        text=None,
        published_at=NOW + timedelta(minutes=5),
        media_present=None,
    )
    unknown = client.post(
        f"/api/v1/creators/me/draft-assessments/{SECOND_ASSESSMENT_ID}/publication",
        json={"post_url_or_id": "123456791"},
    )
    assert unknown.status_code == 201
    assert unknown.json()["version_match_state"] == "unknown"


def test_invalid_reference_is_rejected_before_provider_call(
    publication_api: tuple[TestClient, sessionmaker[Session], FakeVerifier],
) -> None:
    client, _factory, verifier = publication_api
    response = client.post(
        f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/publication",
        json={"post_url_or_id": "https://x.com/example/status/not-an-id"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_post_reference"
    assert verifier.calls == []


def test_wrong_account_and_revoked_access_never_create_attachment(
    publication_api: tuple[TestClient, sessionmaker[Session], FakeVerifier],
) -> None:
    client, factory, verifier = publication_api
    verifier.result = PublishedPostEvidence(
        external_post_id="123456789",
        author_id="000000001",
        text="Original draft",
        published_at=NOW + timedelta(minutes=5),
        media_present=False,
    )
    response = client.post(
        f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/publication",
        json={"post_url_or_id": "123456789"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "published_post_owner_mismatch"
    verifier.result = XPublicationUnavailable("connection_unavailable")
    response = client.post(
        f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/publication",
        json={"post_url_or_id": "123456790"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "x_account_unavailable"
    with factory() as db:
        assert (
            db.scalar(select(CanonicalPost).where(CanonicalPost.creator_id == CREATOR_ID)) is None
        )


@pytest.mark.parametrize("availability", ["deleted", "unavailable"])
@pytest.mark.parametrize("already_linked", [False, True])
def test_unavailable_or_deleted_posts_cannot_be_linked_or_replayed(
    publication_api: tuple[TestClient, sessionmaker[Session], FakeVerifier],
    availability: str,
    already_linked: bool,
) -> None:
    client, factory, verifier = publication_api
    external_post_id = "123456789"
    linked_id = ASSESSMENT_ID if already_linked else None
    with factory() as db:
        db.add(
            CanonicalPost(
                id=uuid4(),
                creator_id=CREATOR_ID,
                platform="x",
                external_post_id=external_post_id,
                published_at=NOW + timedelta(minutes=5),
                availability=availability,
                deleted_at=NOW if availability == "deleted" else None,
                topology="original",
                source_assessment_id=linked_id,
                version_match_state="unknown" if already_linked else None,
            )
        )
        db.commit()
    path = f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/publication"
    reply = client.post(path, json={"post_url_or_id": external_post_id})
    assert reply.status_code == 404
    assert reply.json()["error"]["code"] == "published_post_not_found"
    assert verifier.calls == []
    if already_linked:
        assert client.get(path).status_code == 404
    with factory() as db:
        persisted = db.scalar(
            select(CanonicalPost).where(CanonicalPost.external_post_id == external_post_id)
        )
        assert persisted is not None
        assert persisted.availability == availability
        assert persisted.source_assessment_id == linked_id
        assert persisted.text is None


def test_cross_creator_and_already_linked_posts_are_not_reassigned(
    publication_api: tuple[TestClient, sessionmaker[Session], FakeVerifier],
) -> None:
    client, factory, _verifier = publication_api
    other_assessment_id = UUID("44444444-4444-4444-8444-444444444444")
    with factory() as db:
        db.add(_assessment(assessment_id=other_assessment_id))
        db.add(
            CanonicalPost(
                id=uuid4(),
                creator_id=OTHER_CREATOR_ID,
                platform="x",
                external_post_id="555555555",
                published_at=NOW + timedelta(minutes=1),
                source_assessment_id=None,
                availability="available",
                topology="original",
            )
        )
        db.add(
            CanonicalPost(
                id=uuid4(),
                creator_id=CREATOR_ID,
                platform="x",
                external_post_id="666666666",
                published_at=NOW + timedelta(minutes=1),
                source_assessment_id=other_assessment_id,
                availability="available",
                topology="original",
                version_match_state="unknown",
            )
        )
        db.commit()
    path = f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/publication"
    assert client.post(path, json={"post_url_or_id": "555555555"}).status_code == 404
    assert client.post(path, json={"post_url_or_id": "666666666"}).status_code == 409


@pytest.mark.parametrize(
    "reference",
    ["https://x.com/a//status/123", "https://x.com/a/status/123\n", "https://x.com/a\\/status/123"],
)
def test_ambiguous_urls_are_rejected(reference):
    with pytest.raises(ApiError):
        parse_x_post_id(reference)


@pytest.mark.parametrize(
    "metadata", [{"media_present": True}, {"thread_role": "standalone"}, {"topology": "quote"}]
)
def test_same_text_does_not_verify_unobserved_media_thread_or_quote(metadata):
    from bipme.api.publications import _version_match_state

    assessment = _assessment()
    assessment.decision_snapshot["_cod361_linking"].update(metadata)
    evidence = PublishedPostEvidence(
        external_post_id="123",
        author_id="987654321",
        text="Original draft",
        published_at=NOW,
        topology=metadata.get("topology", "original"),
        media_present=metadata.get("media_present", False),
    )
    assert _version_match_state(assessment, evidence) == "unknown"


def test_status_uses_private_ownership_without_provider_call(publication_api):
    client, _factory, verifier = publication_api
    path = f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/publication"
    assert client.get(path).status_code == 404
    first = client.post(path, json={"post_url_or_id": "123456789"})
    assert first.status_code == 201
    assert client.get(path).json() == first.json()
    assert len(verifier.calls) == 1


@pytest.mark.parametrize("state", ["mismatch", "unknown"])
def test_persisted_publication_handoff_withholds_forecast_scoring(state):
    from dataclasses import replace

    from test_postmortems import _request

    from bipme.intelligence.postmortems import build_postmortem
    from bipme.posts.publications import postmortem_publication

    request = _request()
    post = CanonicalPost(
        id=uuid4(),
        creator_id=CREATOR_ID,
        source_assessment_id=ASSESSMENT_ID,
        published_at=request.published_post.published_at,
        version_match_state=state,
    )
    mapped = postmortem_publication(post)
    mapped = replace(
        mapped,
        creator_key=request.published_post.creator_key,
        post_id=request.published_post.post_id,
        source_assessment_id=request.published_post.source_assessment_id,
    )
    result = build_postmortem(replace(request, published_post=mapped))
    assert result.version_state == "unverified"
    assert all(
        item.status == "version_unverified" and item.deviation_from_median is None
        for item in result.metric_comparisons
    )


@pytest.mark.parametrize("value", ["0", "000123", "18446744073709551616"])
def test_noncanonical_numeric_post_ids_are_rejected(value):
    with pytest.raises(ApiError):
        parse_x_post_id(value)


def test_verifier_commit_cannot_overwrite_a_link_created_during_verification(publication_api):
    client, factory, verifier = publication_api
    with factory() as db:
        db.add(_assessment(assessment_id=SECOND_ASSESSMENT_ID))
        db.add(
            CanonicalPost(
                id=uuid4(),
                creator_id=CREATOR_ID,
                platform="x",
                external_post_id="123456789",
                published_at=NOW + timedelta(minutes=5),
                availability="available",
                topology="original",
            )
        )
        db.commit()
    original_verify = verifier.verify

    def claim_during_verification(db, **kwargs):
        # Equivalent to a competing transaction winning after the verifier's
        # reservation commit has released the initial canonical-post fence.
        post = db.scalar(select(CanonicalPost).where(CanonicalPost.external_post_id == "123456789"))
        post.source_assessment_id = SECOND_ASSESSMENT_ID
        post.version_match_state = "unknown"
        db.commit()
        return original_verify(db, **kwargs)

    verifier.verify = claim_during_verification
    result = client.post(
        f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/publication",
        json={"post_url_or_id": "123456789"},
    )
    assert result.status_code == 409
    with factory() as db:
        post = db.scalar(select(CanonicalPost).where(CanonicalPost.external_post_id == "123456789"))
        assert post.source_assessment_id == SECOND_ASSESSMENT_ID


def test_committed_digest_can_verify_text_without_retaining_raw_text_in_usage_metadata():
    from bipme.api.publications import _version_match_state

    evidence = PublishedPostEvidence(
        external_post_id="123",
        author_id="987654321",
        text=None,
        text_fingerprint=_text_fingerprint("Original draft"),
        published_at=NOW,
        topology="original",
        media_present=False,
    )
    assert _version_match_state(_assessment(), evidence) == "match"


@pytest.mark.parametrize("expires", [None, NOW - timedelta(seconds=1)])
def test_missing_or_stale_price_fails_before_database_or_provider(expires):
    class NeverCalled:
        max_request_attempts = 1

        def published_post(self, **kwargs):
            raise AssertionError("must not call provider")

    from decimal import Decimal

    from bipme.persistence.usage import XUsageLimits

    verifier = XPublishedPostVerifier(
        provider=NeverCalled(),
        cipher=TokenCipher({"v1": Fernet.generate_key().decode()}, "v1"),
        settings=XPublicationSettings(
            enabled=True,
            account_entitlement_verified=True,
            data_rights_verified=True,
            allowed_user_id="987654321",
            estimated_cost=Decimal("0.01"),
            limits=XUsageLimits(Decimal("1"), Decimal("1"), Decimal("1"), None),
            pricing_observed_at=NOW - timedelta(days=1),
            pricing_expires_at=expires,
            pricing_source="synthetic",
        ),
    )
    with pytest.raises(XPublicationUnavailable, match="external_gate_unverified"):
        verifier.verify(object(), creator_id=CREATOR_ID, post_id="123", now=NOW)
