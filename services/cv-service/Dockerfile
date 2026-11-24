FROM python:3.12.16-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
WORKDIR /service
COPY packages/elo-shared /shared
COPY services/cv-service/pyproject.toml ./
COPY services/cv-service/app ./app
RUN pip install --no-cache-dir /shared . && useradd --uid 10001 --create-home service && mkdir -p /app/uploads && chown service:service /app/uploads && chmod 700 /app/uploads && install -d -m 0700 -o service -g service /var/lib/elo-model-budget
USER service
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
