FROM python:3.12.16-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
WORKDIR /service
# Playwright's bundled Node needs libatomic before it can install Chromium.
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 && rm -rf /var/lib/apt/lists/*
ENV TIKTOKEN_CACHE_DIR=/opt/tokenizer-cache
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
COPY packages/elo-shared /shared
COPY services/career-service/pyproject.toml ./
COPY services/career-service/app ./app
RUN pip install --no-cache-dir /shared . && python -c "import tiktoken; tiktoken.get_encoding('o200k_harmony')" && chmod -R a+rX /opt/tokenizer-cache && python -m playwright install --with-deps chromium --only-shell && chmod -R a+rX /opt/playwright && rm -rf /var/lib/apt/lists/* && useradd --uid 10001 --create-home service && install -d -m 0700 -o service -g service /var/lib/elo-model-budget
USER service
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
