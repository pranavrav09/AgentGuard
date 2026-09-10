FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system agentguard && adduser --system --ingroup agentguard agentguard

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY migrations ./migrations
RUN pip install --upgrade pip && pip install .

USER agentguard
EXPOSE 8000

CMD ["agentguard-api"]
