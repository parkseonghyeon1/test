"""Windows 전용: 창 찾기 / 백그라운드 캡처 / 백그라운드 입력 (ctypes만 사용, pywin32 불필요)."""
import ctypes
import time
from ctypes import wintypes

import numpy as np

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

HWND = wintypes.HWND
HDC = wintypes.HDC

# ---- 함수 시그니처 (64bit 핸들 잘림 방지) ----
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.GetWindowTextLengthW.argtypes = [HWND]
user32.GetWindowTextW.argtypes = [HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [HWND]
user32.GetClassNameW.argtypes = [HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindow.argtypes = [HWND]
user32.IsIconic.argtypes = [HWND]
user32.GetClientRect.argtypes = [HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetDC.argtypes = [HWND]
user32.GetDC.restype = HDC
user32.ReleaseDC.argtypes = [HWND, HDC]
user32.PrintWindow.argtypes = [HWND, HDC, wintypes.UINT]
user32.PostMessageW.argtypes = [HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetForegroundWindow.restype = HWND
user32.SetForegroundWindow.argtypes = [HWND]
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(wintypes.DWORD)]
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p]

kernel32.GetConsoleWindow.restype = HWND
kernel32.SetConsoleTitleW.argtypes = [wintypes.LPCWSTR]

gdi32.CreateCompatibleDC.argtypes = [HDC]
gdi32.CreateCompatibleDC.restype = HDC
gdi32.CreateCompatibleBitmap.argtypes = [HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [HDC]

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
MK_LBUTTON = 0x0001
VK_SPACE = 0x20
VK_CONTROL = 0x11
VK_F10 = 0x79
KEYEVENTF_KEYUP = 0x0002
PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2  # DirectX/하드웨어 가속 창도 캡처 (Win 8.1+)
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


gdi32.GetDIBits.argtypes = [HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT]


def set_dpi_aware():
    """디스플레이 배율(125%, 150%...)에서도 좌표/크기가 실제 픽셀과 맞도록."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def _title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


# 게임 창이 아닌 것이 확실한 창 클래스 (탐색기, 콘솔, Windows Terminal, 메모장 등)
_EXCLUDED_CLASSES = {
    "CabinetWClass", "ExploreWClass", "ConsoleWindowClass",
    "CASCADIA_HOSTING_WINDOW_CLASS", "Notepad", "#32770",
}


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _is_own_or_console(hwnd):
    """이 프로그램 자신의 창(콘솔 포함)인지."""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == kernel32.GetCurrentProcessId():
        return True
    return bool(hwnd == kernel32.GetConsoleWindow())


def find_window(keyword):
    """제목에 keyword 가 포함된 게임 창 핸들 (없으면 None).

    콘솔/탐색기 창처럼 제목에 경로가 들어간 창은 제외한다.
    (exe 를 '이클립스' 폴더에 두면 콘솔 제목에도 '이클립스'가 들어가기 때문)
    """
    candidates = []

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _title(hwnd)
        if keyword not in title or _is_own_or_console(hwnd):
            return True
        if _class_name(hwnd) in _EXCLUDED_CLASSES:
            return True
        if "\\" in title or "/" in title or ".exe" in title.lower():
            return True
        # 실제 게임 창 제목('이클립스: 더 어웨이크닝')에 가까울수록 우선
        rank = 0 if "어웨이크닝" in title else 1 if title.startswith(keyword) else 2
        candidates.append((rank, hwnd))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return min(candidates)[1] if candidates else None


def set_console_title(title):
    kernel32.SetConsoleTitleW(title)


def window_title(hwnd):
    return _title(hwnd)


def window_class(hwnd):
    return _class_name(hwnd)


def is_valid(hwnd):
    return bool(hwnd) and bool(user32.IsWindow(hwnd))


def is_minimized(hwnd):
    return bool(user32.IsIconic(hwnd))


def client_size(hwnd):
    rc = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    return rc.right - rc.left, rc.bottom - rc.top


user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(wintypes.RECT)]

# 마지막 캡처 실패 원인 (진단 로그용)
last_capture = {"error": None}


def _read_bitmap(mdc, bmp, w, h):
    bih = BITMAPINFOHEADER()
    bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bih.biWidth, bih.biHeight = w, -h  # 음수 = top-down
    bih.biPlanes, bih.biBitCount, bih.biCompression = 1, 32, 0
    buf = np.empty((h, w, 4), dtype=np.uint8)
    if not gdi32.GetDIBits(mdc, bmp, 0, h, buf.ctypes.data, ctypes.byref(bih), DIB_RGB_COLORS):
        return None
    return buf[:, :, :3].copy()


def capture(hwnd):
    """PrintWindow 로 게임 클라이언트 영역 캡처 → BGR numpy 배열 (실패 시 None).

    다른 창에 가려져 있어도 동작한다. 최소화 상태는 게임이 화면을 그리지 않아 불가.
    """
    w, h = client_size(hwnd)
    if w <= 0 or h <= 0:
        return None
    hdc = user32.GetDC(None)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    try:
        ctypes.set_last_error(0)
        if not user32.PrintWindow(hwnd, mdc, PW_CLIENTONLY | PW_RENDERFULLCONTENT):
            last_capture["error"] = ctypes.get_last_error()
            return None
        img = _read_bitmap(mdc, bmp, w, h)
    finally:
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(None, hdc)
    if img is None or img.mean() < 1.0:  # 완전히 검은 화면은 실패로 간주
        last_capture["error"] = "검은 화면"
        return None
    last_capture["error"] = None
    return img


# ---- 창 숨기기 (화면 밖으로 이동) ----
SM_XVIRTUALSCREEN, SM_CXVIRTUALSCREEN = 76, 78
SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010
user32.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]


def window_pos(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top


def move_window(hwnd, x, y):
    user32.SetWindowPos(hwnd, None, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)


def move_offscreen(hwnd):
    """창을 모든 모니터 오른쪽 바깥으로 옮기고 원래 위치를 반환. (최소화와 달리 게임은 계속 그려진다)"""
    pos = window_pos(hwnd)
    right = user32.GetSystemMetrics(SM_XVIRTUALSCREEN) + user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    move_window(hwnd, right + 200, pos[1])
    return pos


# ---- 권한 ----
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenElevation = 20
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                         wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
shell32.ShellExecuteW.argtypes = [HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                  wintypes.LPCWSTR, ctypes.c_int]
shell32.ShellExecuteW.restype = ctypes.c_void_p


def is_admin():
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def game_elevation(hwnd):
    """게임 프로세스가 관리자 권한인지: True / False / None(확인 불가 = 보호된 프로세스일 가능성)."""
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    hp = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not hp:
        return None
    try:
        tok = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(hp, TOKEN_QUERY, ctypes.byref(tok)):
            return None
        try:
            val, ret = wintypes.DWORD(), wintypes.DWORD()
            if not advapi32.GetTokenInformation(tok, TokenElevation, ctypes.byref(val),
                                                ctypes.sizeof(val), ctypes.byref(ret)):
                return None
            return bool(val.value)
        finally:
            kernel32.CloseHandle(tok)
    finally:
        kernel32.CloseHandle(hp)


def relaunch_as_admin(exe, params):
    """UAC 창을 띄워 관리자 권한으로 다시 실행. 성공하면 True."""
    r = shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return (r or 0) > 32


class AccessDenied(Exception):
    """게임이 관리자 권한으로 실행 중이라 메시지가 차단됨 (UIPI)."""


def _post(hwnd, msg, wp, lp):
    if not user32.PostMessageW(hwnd, msg, wp, lp) and ctypes.get_last_error() == 5:
        raise AccessDenied()


def _lparam_xy(x, y):
    return (y & 0xFFFF) << 16 | (x & 0xFFFF)


def post_click(hwnd, x, y):
    """포커스를 뺏지 않고 창에 마우스 클릭 메시지 전송."""
    lp = _lparam_xy(x, y)
    _post(hwnd, WM_MOUSEMOVE, 0, lp)
    time.sleep(0.03)
    _post(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
    time.sleep(0.05)
    _post(hwnd, WM_LBUTTONUP, 0, lp)


def post_key(hwnd, vk=VK_SPACE):
    """포커스를 뺏지 않고 창에 키 입력 메시지 전송."""
    sc = user32.MapVirtualKeyW(vk, 0)
    _post(hwnd, WM_KEYDOWN, vk, 1 | (sc << 16))
    time.sleep(0.05)
    _post(hwnd, WM_KEYUP, vk, 1 | (sc << 16) | (1 << 30) | (1 << 31))


def foreground_key(hwnd, vk=VK_SPACE):
    """최후 수단: 게임 창을 잠깐(~0.1초) 앞으로 가져와 실제 키 입력 후 원래 창으로 복귀."""
    prev = user32.GetForegroundWindow()
    cur_tid = ctypes.windll.kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(prev, None) if prev else 0
    if fg_tid and fg_tid != cur_tid:
        user32.AttachThreadInput(cur_tid, fg_tid, True)
    try:
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        sc = user32.MapVirtualKeyW(vk, 0)
        user32.keybd_event(vk, sc, 0, None)
        time.sleep(0.04)
        user32.keybd_event(vk, sc, KEYEVENTF_KEYUP, None)
        time.sleep(0.03)
        if prev:
            user32.SetForegroundWindow(prev)
    finally:
        if fg_tid and fg_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, fg_tid, False)


VK_F11 = 0x7A


def snapshot_hotkey_pressed():
    """Ctrl+F11 (스냅샷 저장)."""
    ctrl = user32.GetAsyncKeyState(VK_CONTROL) & 0x8000
    return bool(ctrl and user32.GetAsyncKeyState(VK_F11) & 0x0001)


def hotkey_pressed():
    """Ctrl+F10 이 눌렸는지 (일시정지/재개 토글용)."""
    ctrl = user32.GetAsyncKeyState(VK_CONTROL) & 0x8000
    f10 = user32.GetAsyncKeyState(VK_F10) & 0x0001
    return bool(ctrl and f10)
