FROM python:3.12-slim
WORKDIR /service
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home service && mkdir -p /app/uploads && chown service:service /app/uploads && chmod 700 /app/uploads
USER service
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
