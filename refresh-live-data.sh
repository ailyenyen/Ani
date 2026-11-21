#!/bin/sh
# macOS/Linux counterpart of Refresh-LiveData.ps1. Options: --no-alerts, --monthly.
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python -X utf8 manage.py refresh_live "$@"
