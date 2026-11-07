# Tested 2026-11-07: docker compose up --build, base image (no extras). See docs/DEPLOY.md.
FROM python:3.12-slim
ARG EXTRAS=""
WORKDIR /srv
# Editable install: app/api/main.py finds web/ relative to the source tree, so the tree must stay in place.
COPY pyproject.toml ./
COPY app ./app
COPY web ./web
COPY mocks ./mocks
COPY eval ./eval
RUN pip install --no-cache-dir -e ".${EXTRAS}"
# Rules, compiled rules and designs live on volumes (see docker-compose.yml), not in the image.
EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
