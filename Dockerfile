# FaultLens on Google Cloud Run.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Train the pattern model inside the image, so it matches this image's library versions.
# The published report (models/pattern_report.json) is kept as it was measured.
RUN cp models/pattern_report.json /tmp/pattern_report.json \
    && python -m faultlens.pattern \
    && cp /tmp/pattern_report.json models/pattern_report.json

# PUBLIC_DEMO=1: model calls are limited per visitor and per day.
ENV PUBLIC_DEMO=1 PYTHONUNBUFFERED=1 PORT=8080
CMD exec uvicorn web.server:app --host 0.0.0.0 --port ${PORT}
