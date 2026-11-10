"""Map persisted publication identity/version to the existing COD-364 boundary."""

from typing import cast

from bipme.intelligence.postmortems import PublishedPost, VersionMatchState
from bipme.persistence.models import CanonicalPost


def postmortem_publication(post: CanonicalPost) -> PublishedPost:
    if post.source_assessment_id is None:
        raise ValueError("publication_not_linked")
    state = post.version_match_state or "unknown"
    return PublishedPost(
        creator_key=str(post.creator_id),
        post_id=str(post.id),
        published_at=post.published_at,
        source_assessment_id=str(post.source_assessment_id),
        version_match_state=cast(VersionMatchState, state),
    )
