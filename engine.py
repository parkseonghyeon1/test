"""Skip 자동 클릭 엔진: 백그라운드 스레드에서 캡처 → 감지 → 입력, UI 에는 이벤트 큐로 알린다."""
import json
import os
import queue
import sys
import threading
import time
from dataclasses import asdict, dataclass, fields

import cv2

from detector import SkipDetector, load_templates

FROZEN = getattr(sys, "frozen", False)  # PyInstaller exe 로 실행 중인지
BASE_DIR = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
# exe 안에 포함된 기본 템플릿 + exe 옆 templates 폴더(사용자가 추가한 것)
BUNDLED_TEMPLATE_DIR = os.path.join(getattr(sys, "_MEIPASS", BASE_DIR), "templates")
USER_TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
SETTINGS_PATH = os.path.join(BASE_DIR, "settings.json")

METHODS = {
    "auto": "자동 (Space → 클릭)",
    "key": "Space 키 메시지",
    "click": "클릭 메시지",
    "foreground": "잠깐 앞으로 가져와 Space",
}


@dataclass
class Settings:
    title: str = "이클립스"
    method: str = "auto"
    allow_foreground: bool = False
    threshold: float = 0.75
    interval: float = 0.4
    cooldown: float = 1.2
    preview: bool = True
    always_on_top: bool = False

    @classmethod
    def load(cls):
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            names = {f.name for f in fields(cls)}
            return cls(**{k: v for k, v in data.items() if k in names})
        except Exception:
            return cls()

    def save(self):
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        except OSError:
            pass


def all_templates():
    """(Template, 사용자 추가 여부) 목록. 사용자가 추가한 템플릿은 이름이 custom_ 으로 시작."""
    out = {}
    for folder in (BUNDLED_TEMPLATE_DIR, USER_TEMPLATE_DIR):
        if os.path.isdir(folder):
            for t in load_templates(folder):
                out[t.name] = (t, t.name.startswith("custom_"))
    return list(out.values())


class Skipper:
    """입력 방식 선택. auto 면 입력 후에도 Skip 이 그대로일 때 다음 방식으로 넘어간다."""

    def __init__(self, w32, settings, emit):
        self.w32, self.emit = w32, emit
        self.configure(settings)

    def configure(self, s):
        if s.method == "auto":
            self.order = ["key", "click"] + (["foreground"] if s.allow_foreground else [])
        else:
            self.order = [s.method]
        self.idx, self.fails, self.last_sent = 0, 0, None

    @property
    def method(self):
        return self.order[self.idx]

    def send(self, hwnd, m):
        if self.method == "key":
            self.w32.post_key(hwnd)
        elif self.method == "click":
            self.w32.post_click(hwnd, m.x, m.y)
        else:
            self.w32.foreground_key(hwnd)
        self.last_sent = (m.x, m.y)

    def check_result(self, hit, m):
        if not self.last_sent:
            return
        px, py = self.last_sent
        self.last_sent = None
        if not (hit and abs(m.x - px) < 20 and abs(m.y - py) < 20):
            self.fails = 0
            return
        self.fails += 1
        if self.fails >= 2 and self.idx + 1 < len(self.order):
            self.idx, self.fails = self.idx + 1, 0
            self.emit("log", f"입력이 먹히지 않아 '{METHODS.get(self.method, self.method)}' 방식으로 전환합니다.")
            self.emit("method", self.method)
        elif self.fails >= 3:
            self.fails = 0
            self.emit("log", "모든 입력 방식이 실패했습니다. 설정에서 '앞으로 가져와 Space' 허용을 켜 보세요.")


class SkipEngine(threading.Thread):
    """이벤트 (종류, 값) 를 events 큐에 넣는다.

    window(dict|None), capture(str), state(str), score(Match|None), frame(ndarray, Match|None),
    skip(Match), log(str), capture_fail(dict), method(str)
    """

    def __init__(self, w32, settings):
        super().__init__(daemon=True)
        self.w32 = w32
        self.settings = settings
        self.events = queue.Queue()
        self.running = threading.Event()
        self.running.set()
        self._stop_evt = threading.Event()
        self._lock = threading.Lock()
        self._reload = True
        self._snapshot = None  # 스냅샷 요청 콜백
        self.hwnd = None
        self.skip_count = 0
        self.detector = None
        self.skipper = Skipper(w32, settings, self.emit)

    # ---- UI 에서 호출 ----
    def emit(self, kind, *value):
        self.events.put((kind, value[0] if len(value) == 1 else value))

    def stop(self):
        self._stop_evt.set()

    def set_running(self, on):
        (self.running.set if on else self.running.clear)()
        self.emit("state", "running" if on else "paused")

    def apply_settings(self, s):
        with self._lock:
            title_changed = s.title != self.settings.title
            self.settings = s
            self.skipper.configure(s)
            if self.detector:
                self.detector.threshold = s.threshold
            if title_changed:
                self.hwnd = None

    def reload_templates(self):
        self._reload = True

    def request_frame(self, callback):
        """다음 캡처 화면을 callback(frame) 으로 전달 (템플릿 추가용)."""
        self._snapshot = callback

    # ---- 스레드 ----
    def run(self):
        last_find, last_frame_emit = 0.0, 0.0
        cap_fails, cap_ok, min_warned = 0, False, False
        self.emit("state", "running")
        while not self._stop_evt.is_set():
            if self.w32.hotkey_pressed():
                self.set_running(not self.running.is_set())

            if self._reload:
                self._reload = False
                tpls = [t for t, _ in all_templates()]
                self.detector = SkipDetector(tpls, threshold=self.settings.threshold) if tpls else None
                self.emit("log", f"템플릿 {len(tpls)}개 사용")

            s = self.settings
            # 게임 창 찾기
            if not self.hwnd or not self.w32.is_valid(self.hwnd):
                if self.hwnd:
                    self.emit("log", "게임 창이 닫혔습니다.")
                    self.hwnd = None
                    self.emit("window", None)
                if time.time() - last_find > 1.5:
                    last_find = time.time()
                    self.hwnd = self.w32.find_window(s.title)
                    if self.hwnd:
                        info = {"title": self.w32.window_title(self.hwnd),
                                "size": self.w32.client_size(self.hwnd),
                                "elevated": self.w32.game_elevation(self.hwnd)}
                        self.emit("window", info)
                        self.emit("log", f"게임 창 발견: {info['title']} {info['size'][0]}×{info['size'][1]}")
                        cap_fails, cap_ok = 0, False
                self._sleep(0.3)
                continue

            if self.w32.is_minimized(self.hwnd):
                if not min_warned:
                    min_warned = True
                    self.emit("capture", "minimized")
                    self.emit("log", "게임 창이 최소화되어 감지를 멈췄습니다. 최소화 대신 다른 창 뒤에 두세요.")
                self._sleep(0.5)
                continue
            if min_warned:
                min_warned = False
                cap_ok = False

            frame = self.w32.capture(self.hwnd)
            if frame is None:
                cap_fails += 1
                if cap_fails == 3:
                    cap_ok = False
                    self.emit("capture", "failed")
                    self.emit("capture_fail", {
                        "error": self.w32.last_capture["error"],
                        "admin": self.w32.is_admin(),
                        "game_elevated": self.w32.game_elevation(self.hwnd),
                    })
                self._sleep(s.interval)
                continue
            cap_fails = 0
            if not cap_ok:
                cap_ok = True
                self.emit("capture", "ok")

            if self._snapshot:
                cb, self._snapshot = self._snapshot, None
                cb(frame)

            if not self.running.is_set() or not self.detector:
                if s.preview and time.time() - last_frame_emit > 0.5:
                    last_frame_emit = time.time()
                    self.emit("frame", (frame, None))
                self._sleep(0.3)
                continue

            with self._lock:
                m = self.detector.find(frame)
                hit = self.detector.is_hit(m)
                self.skipper.check_result(hit, m)
            self.emit("score", m)
            if s.preview and (hit or time.time() - last_frame_emit > 0.5):
                last_frame_emit = time.time()
                self.emit("frame", (frame, m if hit else None))

            if hit:
                try:
                    self.skipper.send(self.hwnd, m)
                except self.w32.AccessDenied:
                    self.emit("capture_fail", {"error": 5, "admin": self.w32.is_admin(),
                                               "game_elevated": True, "input": True})
                    self.set_running(False)
                    continue
                self.skip_count += 1
                self.emit("skip", m)
                self._sleep(s.cooldown)
            else:
                self._sleep(s.interval)

    def _sleep(self, sec):
        self._stop_evt.wait(sec)


def save_custom_template(frame, box):
    """frame 의 box(x0,y0,x1,y1) 영역을 사용자 템플릿으로 저장하고 파일명을 반환."""
    from detector import imwrite_unicode
    x0, y0, x1, y1 = box
    crop = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    os.makedirs(USER_TEMPLATE_DIR, exist_ok=True)
    name = f"custom_{time.strftime('%Y%m%d_%H%M%S')}@{frame.shape[1]}.png"
    imwrite_unicode(os.path.join(USER_TEMPLATE_DIR, name), crop)
    return name
