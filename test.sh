#!/usr/bin/env bash
# for local testing

set -e

ENV_FOLDER="venv"
PY_CMD="python3"

clear

if [ ! -d "${ENV_FOLDER}" ]; then
    echo "Missing env folder: $ENV_FOLDER"
    echo "Re-building virtualenv"
    ./mkenv.sh
fi

echo "activating virtualenv so we can use those packages"
# shellcheck source=../venv/bin/activate
source "${ENV_FOLDER}/bin/activate" || {
    echo "failed to activate env ${ENV_FOLDER}, weird"
    exit 1
}

cd ./files/data/scripts/
rm -r __pycache__ || True

$PY_CMD kiosk.py -v "$@"
