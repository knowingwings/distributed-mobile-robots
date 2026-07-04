#!/bin/bash
# One-command heavy-CI loop from odin: push the current branch, then build
# and test everything (core tests in container + colcon build/test) on
# terra's Docker. Heavy compute belongs on terra; this keeps the loop tight.
#
# Usage: scripts/terra-ci.sh
set -euo pipefail

TERRA="tom@100.126.116.33"
KEY="$HOME/.ssh/id_ed25519"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
REPO_ROOT="$(git rev-parse --show-toplevel)"

git push -q origin "$BRANCH"

# Ship the remote script from the working tree (not the terra clone) so the
# first run on a new branch bootstraps correctly.
scp -q -o BatchMode=yes -i "$KEY" \
    "$REPO_ROOT/scripts/terra-remote-ci.sh" "$TERRA:C:/Users/Tom/terra-remote-ci.sh"

ssh -o BatchMode=yes -i "$KEY" "$TERRA" \
    "wsl -e bash -lc \"cp /mnt/c/Users/Tom/terra-remote-ci.sh ~/terra-remote-ci.sh && bash ~/terra-remote-ci.sh $BRANCH\""
