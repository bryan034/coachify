FROM python:3.12-slim
WORKDIR /service
COPY packages/elo-shared /shared
COPY services/profile-service/pyproject.toml ./
COPY services/profile-service/app ./app
RUN pip install --no-cache-dir /shared . && useradd --uid 10001 --create-home service
USER service
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
