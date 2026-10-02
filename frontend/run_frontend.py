"""Runner script to launch the Streamlit frontend microservice."""

import os
import sys
import subprocess

def main():
    port = os.environ.get("STREAMLIT_PORT", "8501")
    host = os.environ.get("STREAMLIT_HOST", "0.0.0.0")
    app_path = os.path.join(os.path.dirname(__file__), "app.py")

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        app_path,
        "--server.port",
        str(port),
        "--server.address",
        host,
        "--server.headless",
        "true",
        "--theme.base",
        "light",
        "--theme.primaryColor",
        "#2563eb",
    ]

    print(f"Starting ZAMP Accounts Payable Frontend at http://localhost:{port}...")
    sys.exit(subprocess.call(cmd))

if __name__ == "__main__":
    main()
