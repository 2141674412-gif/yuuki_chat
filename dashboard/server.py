"""
Yuuki Bot Dashboard - 内置HTTP服务（无外部依赖）
"""

import json
import os
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

DATA_DIR = ""
DASHBOARD_DIR = ""


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DASHBOARD_DIR, **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            self._serve_html()
        elif path == "/api/data":
            self._serve_data()
        elif path == "/api/health":
            self._serve_health()
        else:
            super().do_GET()

    def _serve_html(self):
        filepath = os.path.join(DASHBOARD_DIR, "index.html")
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            self._send_response(200, "text/html; charset=utf-8", content)
        except FileNotFoundError:
            self._send_response(404, "text/plain", "index.html not found")

    def _serve_data(self):
        checkin_records = self._load_json("checkin_records.json", {})
        user_points = self._load_json("user_points.json", {})
        user_profiles = self._load_json("user_profiles.json", {})

        data = {
            "checkin_records": checkin_records,
            "user_points": user_points,
            "user_profiles": user_profiles,
            "data_dir": DATA_DIR,
            "files_exist": {
                "checkin_records.json": os.path.exists(os.path.join(DATA_DIR, "checkin_records.json")),
                "user_points.json": os.path.exists(os.path.join(DATA_DIR, "user_points.json")),
                "user_profiles.json": os.path.exists(os.path.join(DATA_DIR, "user_profiles.json")),
            },
            "server_time": datetime.now().isoformat()
        }
        self._send_response(200, "application/json; charset=utf-8", json.dumps(data, ensure_ascii=False))

    def _serve_health(self):
        data = {
            "status": "ok",
            "time": datetime.now().isoformat(),
            "data_dir": DATA_DIR,
            "cwd": os.getcwd(),
            "files": {
                "checkin_records.json": os.path.exists(os.path.join(DATA_DIR, "checkin_records.json")),
                "user_points.json": os.path.exists(os.path.join(DATA_DIR, "user_points.json")),
                "user_profiles.json": os.path.exists(os.path.join(DATA_DIR, "user_profiles.json")),
            }
        }
        self._send_response(200, "application/json; charset=utf-8", json.dumps(data, ensure_ascii=False))

    def _load_json(self, filename, default=None):
        filepath = os.path.join(DATA_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
            print(f"[Dashboard] 加载 {filename} 失败: {e} (路径: {filepath})")
            return default if default is not None else {}

    def _send_response(self, code, content_type, body):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format, *args):
        """静默HTTP请求日志"""
        pass


def start_server(data_dir, dashboard_dir, port=8080):
    global DATA_DIR, DASHBOARD_DIR
    DATA_DIR = data_dir
    DASHBOARD_DIR = dashboard_dir
    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"[排行榜] Dashboard 已启动: http://0.0.0.0:{port} (数据目录: {data_dir})")
    server.serve_forever()
