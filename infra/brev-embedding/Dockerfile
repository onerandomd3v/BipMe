FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/model-cache \
    TRANSFORMERS_CACHE=/model-cache

RUN pip install --no-cache-dir \
    fastapi==0.115.12 \
    uvicorn[standard]==0.34.2 \
    sentence-transformers==5.7.0

WORKDIR /app
COPY app.py /app/app.py
RUN useradd --system --uid 10001 --create-home app \
    && mkdir -p /model-cache \
    && chown app:app /model-cache
USER app
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
