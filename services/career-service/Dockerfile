FROM python:3.12-slim
WORKDIR /service
ENV TIKTOKEN_CACHE_DIR=/opt/tokenizer-cache
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
COPY packages/elo-shared /shared
COPY services/career-service/pyproject.toml ./
COPY services/career-service/app ./app
RUN pip install --no-cache-dir /shared . && python -c "import tiktoken; tiktoken.get_encoding('o200k_harmony')" && chmod -R a+rX /opt/tokenizer-cache && python -m playwright install --with-deps chromium --only-shell && chmod -R a+rX /opt/playwright && rm -rf /var/lib/apt/lists/* && useradd --uid 10001 --create-home service
USER service
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
