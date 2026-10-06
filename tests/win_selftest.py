"""Windows CI 자가 테스트: 메모장을 띄워 캡처 함수들이 실제로 동작하는지 확인."""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import win32_utils as w32  # noqa: E402
from detector import SkipDetector, load_templates  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
w32.set_dpi_aware()
proc = subprocess.Popen(["notepad.exe"])
try:
    hwnd = None
    for _ in range(40):
        time.sleep(0.5)
        found = []

        def cb(h, _):
            if w32.user32.IsWindowVisible(h) and "Notepad" in w32.window_title(h):
                found.append(h)
            return True

        w32.user32.EnumWindows(w32.WNDENUMPROC(cb), 0)
        if found:
            hwnd = found[0]
            break
    assert hwnd, "notepad window not found"
    print("window:", w32.window_title(hwnd), w32.window_class(hwnd), w32.client_size(hwnd))

    w, h = w32.client_size(hwnd)
    img = w32.capture(hwnd)
    assert img is not None and img.shape[:2] == (h, w), f"capture failed: {w32.last_capture['error']}"
    print("PrintWindow capture ok:", img.shape, round(float(img.mean()), 1))

    print("is_admin:", w32.is_admin(), "notepad elevated:", w32.game_elevation(hwnd))
    # 메모장 클래스는 제외 목록에 있으므로 게임 창으로 잡히면 안 됨
    assert w32.find_window("Notepad") is None, "excluded window class was selected"
    # 입력 메시지 전송이 예외 없이 되는지
    w32.post_key(hwnd)
    w32.post_click(hwnd, 10, 10)

    det = SkipDetector(load_templates("templates"))
    m = det.find(img)
    print("detector on notepad (should be low):", round(m.score, 3) if m else None)
    assert m is None or m.score < det.threshold
    print("SELFTEST OK")
finally:
    proc.kill()
