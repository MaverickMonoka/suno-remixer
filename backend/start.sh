#!/bin/sh
set -eu
export FUSIONVOICE_CONVERTER="${FUSIONVOICE_CONVERTER:-/app/converters/http_converter.py}"
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
