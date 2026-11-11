# Same PostgreSQL/pgvector image as the existing Compose deployment.
# Release CI records the resulting immutable digest and never overwrites SHA tags.
FROM pgvector/pgvector:pg17
