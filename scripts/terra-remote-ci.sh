#!/bin/bash
# Runs ON TERRA (WSL2). Invoked by scripts/terra-ci.sh — do not run by hand
# unless you know the clone at ~/auction-run is what you want to test.
set -euo pipefail

BRANCH="${1:?usage: terra-remote-ci.sh <branch>}"

# Docker Desktop's Windows credential helper is unreachable from a non-
# interactive SSH session ("logon session does not exist"); use a bare
# config — the images we pull are public.
export DOCKER_CONFIG="$HOME/.docker-ci"
mkdir -p "$DOCKER_CONFIG"
echo '{}' > "$DOCKER_CONFIG/config.json"

cd ~/auction-run

git fetch -q origin "$BRANCH"
git checkout -q "$BRANCH"
git reset -q --hard "origin/$BRANCH"
echo "== terra-ci: $(git rev-parse --short HEAD) on $BRANCH =="

docker build -q -t dmr-dev:humble -f docker/Dockerfile.dev . >/dev/null
echo "== image ready =="

docker run --rm -v "$PWD:/ws" -w /ws dmr-dev:humble bash -lc '
    set -euo pipefail
    pip3 install -q -e "auction_core[dev]" 2>/dev/null
    echo "== core tests (in container) =="
    python3 -m pytest auction_core/tests -q
    if [ -d ros2_ws/src ] && [ -n "$(ls -A ros2_ws/src 2>/dev/null)" ]; then
        echo "== colcon build =="
        cd ros2_ws
        . /opt/ros/humble/setup.sh
        colcon build --symlink-install --event-handlers console_cohesion+
        echo "== colcon test =="
        colcon test --event-handlers console_cohesion+
        colcon test-result --verbose
    fi
'
echo "== terra-ci: OK =="
