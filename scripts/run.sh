#!/usr/bin/env sh
set -eu

if [ -x ".venv/bin/python" ]; then
  exec .venv/bin/python -m streamlit run streamlit_app.py --server.port 8501
fi

exec python -m streamlit run streamlit_app.py --server.port 8501
