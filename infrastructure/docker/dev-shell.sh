dc() {
  docker compose --env-file infrastructure/docker/.env \
    -f infrastructure/docker/compose.yaml \
    -f infrastructure/docker/compose.dev.yaml "$@"
}
