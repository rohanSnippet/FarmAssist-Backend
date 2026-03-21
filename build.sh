#!/usr/bin/env bash
# Exit on error
set -o errexit

pip install -r requirements.txt

32.
python manage.py collectstatic --no-input
python manage.py migrate