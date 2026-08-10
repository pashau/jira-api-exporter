FROM python:3.11-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

FROM base AS builder

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM base

COPY --from=builder /install /usr/local
COPY jira_exporter/ ./jira_exporter/

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "jira_exporter"]
