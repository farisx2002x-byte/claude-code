"""نقاط الدخول: transport-hub (الواجهة) وtransport-hub-api (الخدمة)."""

import argparse
import subprocess
import sys
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser(prog="transport-hub", description="تشغيل واجهة منصة النقل")
    ap.add_argument("--port", type=int, default=8501)
    ap.add_argument("--headless", action="store_true")
    a = ap.parse_args(argv)
    app = Path(__file__).resolve().parent / "app.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(app), "--server.port", str(a.port)]
    if a.headless:
        cmd += ["--server.headless", "true"]
    return subprocess.call(cmd)


def api(argv=None):
    ap = argparse.ArgumentParser(prog="transport-hub-api", description="تشغيل واجهة REST")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)
    import uvicorn

    uvicorn.run("transport_hub.api:app", host=a.host, port=a.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
