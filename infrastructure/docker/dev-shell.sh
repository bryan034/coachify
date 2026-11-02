# Source from the repository root: source infrastructure/docker/dev-shell.sh
# Run dc commands from the repository root.
dc() {
  docker compose --env-file infrastructure/docker/.env \
    -f infrastructure/docker/compose.yaml \
    -f infrastructure/docker/compose.dev.yaml "$@"
}
