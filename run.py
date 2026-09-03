#!/usr/bin/env python3
"""Uygulamayı başlatır: python run.py  ->  http://127.0.0.1:8777"""
import webbrowser
import threading
import os

from app.main import run

if __name__ == "__main__":
    port = os.getenv("PORT", "8777")
    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    run()
