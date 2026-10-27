FROM python:3.12-slim
WORKDIR /service
ENV TIKTOKEN_CACHE_DIR=/opt/tokenizer-cache
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir . && python -c "import tiktoken; tiktoken.get_encoding('o200k_harmony')" && chmod -R a+rX /opt/tokenizer-cache && useradd --uid 10001 --create-home service
USER service
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
