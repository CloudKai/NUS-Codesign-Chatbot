#!/usr/bin/env sh
set -eu

python -m compileall -q backend streamlit_app.py
python -m pytest
python scripts/init_db.py
