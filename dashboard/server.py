"""
Yuuki Bot Dashboard - Flask Backend Server
Serves the leaderboard HTML page and provides /api/data endpoint.
"""

import json
import os
from datetime import datetime
from flask import Flask, jsonify, send_from_directory, current_app

app = Flask(__name__)


def _get_data_dir():
    return current_app.config.get("DATA_DIR",
        os.environ.get('YUUKI_DATA_DIR',
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'yuuki_data')))


def _get_dashboard_dir():
    return current_app.config.get("DASHBOARD_DIR",
        os.path.dirname(os.path.abspath(__file__)))


def load_json(filename, default=None):
    """Load a JSON file safely, returning default if file not found or invalid."""
    filepath = os.path.join(_get_data_dir(), filename)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return default if default is not None else {}


@app.route('/')
def index():
    """Serve the main dashboard HTML page."""
    return send_from_directory(_get_dashboard_dir(), 'index.html')


@app.route('/api/data')
def api_data():
    """Return combined data from all JSON files."""
    checkin_records = load_json('checkin_records.json', {})
    user_points = load_json('user_points.json', {})
    user_profiles = load_json('user_profiles.json', {})

    return jsonify({
        'checkin_records': checkin_records,
        'user_points': user_points,
        'user_profiles': user_profiles,
        'server_time': datetime.now().isoformat()
    })


@app.route('/api/health')
def health():
    """Health check endpoint."""
    data_dir = _get_data_dir()
    return jsonify({
        'status': 'ok',
        'time': datetime.now().isoformat(),
        'data_dir': data_dir,
        'files': {
            'checkin_records.json': os.path.exists(os.path.join(data_dir, 'checkin_records.json')),
            'user_points.json': os.path.exists(os.path.join(data_dir, 'user_points.json')),
            'user_profiles.json': os.path.exists(os.path.join(data_dir, 'user_profiles.json')),
        }
    })
