#!/bin/bash

cd "$(dirname "$0")" || exit 1

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate

# 古いGPS部品を削除
python -m pip uninstall -y streamlit-geolocation >/dev/null 2>&1

# 必要なライブラリを更新
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# アプリ起動
python -m streamlit run app.py
