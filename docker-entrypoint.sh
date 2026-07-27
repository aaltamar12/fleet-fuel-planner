#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py loaddata stations/fixtures/fuel_stations.json

exec "$@"
