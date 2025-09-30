#!/usr/bin/env bash
# Create virtualenv with correct python version and install requirements
#   this is only for development testing

set -e

ENV_FOLDER="venv"
PY_CMD="python3"


command -v "$PY_CMD" || {
    echo "$PY_CMD is required, but was not found"
    exit 1
}

$PY_CMD --version


if [ -d "${ENV_FOLDER}" ]; then
    echo "removing previous instance of ${ENV_FOLDER}"
    rm -rf "${ENV_FOLDER}" || {
        echo "failed to remove previous env ${ENV_FOLDER}/ please do so manually"
        exit 1
  }
fi

echo "setting up ${ENV_FOLDER}/"
"$PY_CMD" -m virtualenv "${ENV_FOLDER}" || {
    echo "failed to create env ${ENV_FOLDER}, probably missing $PY_CMD virtualenv module"
    echo "going to try installing that now"
    "$PY_CMD" -m pip install virtualenv || {
        echo "ugh, that failed"
        exit 1
    }
    echo "trying again to set up ${ENV_FOLDER}/"
    "$PY_CMD" -m virtualenv "${ENV_FOLDER}" || {
        echo "failed to create env ${ENV_FOLDER}, probably missing $PY_CMD virtualenv module"
        echo "we already tried to install it for you, so there may be something else wrong"
        exit 1
    }
}

# shellcheck disable=SC1091
source "${ENV_FOLDER}/bin/activate" || {
    echo "failed to activate env ${ENV_FOLDER}, weird"
    exit 1
}

echo "making sure venv has latest pip"
pip install --upgrade pip || {
    echo "failed to upgrade pip? huh..."
    exit 1
}

echo "installing ./files/data/scripts/requirements.txt"
pip install -r ./files/data/scripts/requirements.txt || {
    echo "failed to install packages from requirements.txt"
    deactivate
    exit 1
}

echo "installing ./files/host/kiosk-updater/requirements.txt"
pip install -r ./files/host/kiosk-updater/requirements.txt || {
    echo "failed to install packages from requirements.txt"
    deactivate
    exit 1
}

deactivate

echo "done"
