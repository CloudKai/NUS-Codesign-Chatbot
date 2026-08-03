#!/usr/bin/env sh
set -eu

exec python -m streamlit run streamlit_app.py --server.port 8501
