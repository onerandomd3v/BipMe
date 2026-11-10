"""Small authenticated E5 inference service; bind reachability at the VM firewall/tunnel."""

from __future__ import annotations

import hmac
import logging
import math
import os
import threading
from importlib import import_module
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

MODEL = "intfloat/multilingual-e5-small"
REVISION = "fd1525a9fd15316a2d503bf26ab031a61d056e98"
logging.basicConfig(level=os.getenv("LOG_LEVEL", "WARNING"))
logger = logging.getLogger("brev_embedding")
app = FastAPI(title="BipMe private embeddings", docs_url=None, redoc_url=None, openapi_url=None)
inference_slot = threading.BoundedSemaphore(1)
model_lock = threading.Lock()
loaded_model: Any | None = None
MAX_REQUEST_BYTES = 400 * 1024


class RequestSizeLimitMiddleware:
    """Bound the JSON body before FastAPI parses it, including chunked requests."""

    def __init__(self, application: Any, *, max_body_bytes: int) -> None:
        self.application = application
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if not (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and scope.get("path") == "/embed"
        ):
            await self.application(scope, receive, send)
            return

        content_length = next(
            (
                value.decode("latin-1")
                for key, value in scope.get("headers", [])
                if key == b"content-length"
            ),
            None,
        )
        if content_length is not None:
            try:
                if int(content_length) > self.max_body_bytes:
                    await self._too_large(send)
                    return
            except ValueError:
                pass

        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_body_bytes:
                await self._too_large(send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)
        delivered = False

        async def replay_body() -> Any:
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.application(scope, replay_body, send)

    @staticmethod
    async def _too_large(send: Any) -> None:
        body = b'{"detail":"request too large"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


app.add_middleware(RequestSizeLimitMiddleware, max_body_bytes=MAX_REQUEST_BYTES)


class EmbedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texts: list[str] = Field(min_length=1, max_length=8)
    role: Literal["query", "passage"]


def model() -> Any:
    global loaded_model
    with model_lock:
        if loaded_model is None:
            sentence_transformers = import_module("sentence_transformers")
            loaded_model = sentence_transformers.SentenceTransformer(
                MODEL, revision=REVISION, device="cuda", trust_remote_code=False
            )
        return loaded_model


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    del request, exc
    return JSONResponse(status_code=422, content={"detail": "invalid request"})


def require_token(authorization: str | None) -> None:
    expected = os.getenv("BIPME_EMBEDDING_TOKEN", "")
    if (
        not expected
        or not authorization
        or not hmac.compare_digest(authorization, f"Bearer {expected}")
    ):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/health")
def health() -> dict[str, str | int]:
    try:
        model()
    except Exception as exc:
        logger.error("model readiness failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="model unavailable") from None
    return {"status": "ok", "model": MODEL, "revision": REVISION, "dimensions": 384}


@app.post("/embed")
def embed(
    request: EmbedRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    require_token(authorization)
    if any(not text.strip() or len(text) > 8000 for text in request.texts):
        raise HTTPException(status_code=422, detail="invalid input")
    if not inference_slot.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="inference busy")
    try:
        try:
            values = model().encode(
                [f"{request.role}: {text.strip()}" for text in request.texts],
                batch_size=8,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            vectors = [[float(value) for value in row] for row in values]
            if len(vectors) != len(request.texts) or any(
                len(vector) != 384
                or not all(math.isfinite(value) for value in vector)
                or not math.isclose(
                    math.sqrt(math.fsum(value * value for value in vector)), 1.0, abs_tol=1e-3
                )
                for vector in vectors
            ):
                raise ValueError("invalid model output")
        except Exception as exc:
            logger.error("inference failed (%s)", type(exc).__name__)
            raise HTTPException(status_code=503, detail="inference unavailable") from None
    finally:
        inference_slot.release()
    return {"model": MODEL, "revision": REVISION, "dimensions": 384, "embeddings": vectors}
