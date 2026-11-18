#!/usr/bin/env python3
"""炼金炉独立窗口模式。

启动本地服务后，把页面套进原生窗口（pywebview / WKWebView），
关闭窗口即退出整个程序。三级降级：
  1. pywebview（原生窗口，推荐，需 pip install pywebview）
  2. Chrome/Edge --app 模式（无地址栏的独立窗口，不改浏览器主窗口）
  3. 系统默认浏览器（旧行为）
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import app  # noqa: E402

APP_URL = "http://127.0.0.1:8765"
HEALTH_URL = f"{APP_URL}/api/health"


def wait_server(seconds: float = 8.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=1):
                return True
        except Exception:
            time.sleep(0.15)
    return False


def find_chromium_app() -> str | None:
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def open_in_default_browser() -> None:
    if sys.platform == "win32":
        os.startfile(APP_URL)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", APP_URL], check=False)
    else:
        subprocess.run(["xdg-open", APP_URL], check=False)


def open_in_chromium_app_mode() -> None:
    browser = None
    if sys.platform == "darwin":
        browser = find_chromium_app()
    elif sys.platform == "win32":
        for path in (
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        ):
            if os.path.exists(path):
                browser = path
                break
    profile = os.path.join(BASE_DIR, ".chromeprofile")
    if browser:
        subprocess.run(
            [
                browser,
                f"--app={APP_URL}",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1440,900",
            ],
            check=False,
        )
    else:
        open_in_default_browser()


class NativeBridge:
    """暴露给前端的原生能力（目前只有目录选择）。

    前端通过 window.pywebview.api.pick_directory() 调用；浏览器模式下不存在
    这个桥，前端会自动降级为 <input webkitdirectory>。
    """

    def pick_directory(self, initial: str = "") -> str:
        import webview

        window = webview.windows[0] if webview.windows else None
        if window is None:
            return ""
        directory = initial if isinstance(initial, str) and initial and os.path.isdir(initial) else ""
        try:
            result = window.create_file_dialog(webview.FOLDER_DIALOG, directory=directory)
        except Exception:
            return ""
        if not result:
            return ""
        if isinstance(result, (list, tuple)):
            return str(result[0]) if result else ""
        return str(result)


def run_native_window() -> None:
    import webview  # pywebview

    # 每次启动都换一个查询串，绕开 WKWebView 对旧页面的磁盘缓存
    bust = f"{APP_URL}/?_launch={int(time.time())}"
    webview.create_window(
        "炼金炉",
        bust,
        width=1440,
        height=900,
        min_size=(1080, 680),
        js_api=NativeBridge(),
    )
    webview.start()
    # 用户关闭窗口后返回，退出整个程序（含后台服务线程）
    os._exit(0)


def server_already_running() -> bool:
    """检测是否已有炼金炉服务在监听（端口被占用时复用它，而不是崩掉）。

    只有 /api/health 响应正常才视为"我们的"服务；被其他程序占端口时
    仍尝试自行启动，失败会在日志里留下 traceback。
    """
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1):
            return True
    except Exception:
        return False


def main() -> None:
    if server_already_running():
        print("检测到已有炼金炉服务在运行，直接复用，不重复启动。")
    else:
        server = app.create_server()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        if not wait_server():
            print("警告：本地服务未在预期时间内就绪，仍尝试打开窗口。")

    try:
        run_native_window()
    except ImportError:
        open_in_chromium_app_mode()
        os._exit(0)


if __name__ == "__main__":
    main()
