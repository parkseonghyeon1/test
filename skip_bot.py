"""이클립스: 더 어웨이크닝 - Skip 버튼 자동 클릭기.

게임 창이 다른 창 뒤에 있어도 화면을 캡처해서 Skip 버튼을 찾고,
포커스를 뺏지 않는 방식(PostMessage)으로 Space 키 / 클릭을 보낸다.

사용법:
    python skip_bot.py                  # 실행 (Ctrl+F10 일시정지/재개, Ctrl+C 종료)
    python skip_bot.py --capture        # Skip 이 떠 있을 때 실행 → 드래그로 새 템플릿 저장
    python skip_bot.py --debug          # 매 프레임 점수 출력 + 감지 화면 저장
"""
import argparse
import datetime
import os
import sys
import time

import cv2

from detector import SkipDetector, imwrite_unicode, load_templates

# 출력이 파일/파이프로 리다이렉트되거나 영문 Windows 에서도 한글 출력 때문에 죽지 않도록
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if sys.platform != "win32":
    sys.exit("Windows 에서만 동작합니다.")

import win32_utils as w32  # noqa: E402

FROZEN = getattr(sys, "frozen", False)  # PyInstaller exe 로 실행 중인지
BASE_DIR = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
# exe 안에 포함된 기본 템플릿 + exe 옆 templates 폴더(--capture 로 추가한 것)를 함께 사용
BUNDLED_TEMPLATE_DIR = os.path.join(getattr(sys, "_MEIPASS", BASE_DIR), "templates")
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
DEBUG_DIR = os.path.join(BASE_DIR, "debug")

# auto 모드에서 시도하는 순서. 앞의 방식이 안 먹히면 다음 방식으로 넘어간다.
AUTO_ORDER = ["key", "click"]


def log(msg):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


def parse_args():
    p = argparse.ArgumentParser(description="이클립스 Skip 자동 클릭기")
    p.add_argument("--title", default="이클립스", help="게임 창 제목에 포함된 글자 (기본: 이클립스)")
    p.add_argument("--method", default="auto", choices=["auto", "key", "click", "foreground"],
                   help="auto=자동선택, key=Space 메시지, click=클릭 메시지, foreground=잠깐 앞으로 가져와 입력")
    p.add_argument("--allow-foreground", action="store_true",
                   help="auto 모드에서 key/click 이 모두 안 먹히면 foreground 방식까지 시도")
    p.add_argument("--threshold", type=float, default=0.75, help="매칭 임계값 0~1 (기본 0.75)")
    p.add_argument("--interval", type=float, default=0.4, help="화면 검사 주기(초)")
    p.add_argument("--cooldown", type=float, default=1.2, help="입력 후 다음 검사까지 대기(초)")
    p.add_argument("--debug", action="store_true", help="점수 출력 + 감지 시 화면을 debug/ 폴더에 저장")
    p.add_argument("--capture", action="store_true", help="현재 게임 화면에서 템플릿을 잘라 저장")
    return p.parse_args()


def wait_window(keyword):
    hwnd = w32.find_window(keyword)
    if not hwnd:
        log(f"'{keyword}' 창을 찾는 중... (게임을 창 모드로 실행해 주세요)")
        while not hwnd:
            time.sleep(2)
            hwnd = w32.find_window(keyword)
    log(f"게임 창 발견: {w32.window_title(hwnd)}  (클라이언트 {w32.client_size(hwnd)})")
    return hwnd


def capture_template(keyword):
    hwnd = wait_window(keyword)
    frame = w32.capture(hwnd)
    if frame is None:
        sys.exit("캡처 실패. 게임 창이 최소화되어 있지 않은지 확인하세요.")
    w = frame.shape[1]
    log("창이 뜨면 Skip 버튼(+아래 Space 라벨)을 드래그로 감싸고 Enter, 취소는 c")
    x, y, rw, rh = cv2.selectROI("Select Skip (Enter=save, c=cancel)", frame, showCrosshair=False)
    cv2.destroyAllWindows()
    if rw == 0 or rh == 0:
        log("취소됨")
        return
    crop = cv2.cvtColor(frame[y:y + rh, x:x + rw], cv2.COLOR_BGR2GRAY)
    name = f"custom_{datetime.datetime.now():%Y%m%d_%H%M%S}@{w}.png"
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    imwrite_unicode(os.path.join(TEMPLATE_DIR, name), crop)
    log(f"저장 완료: templates/{name}")


class Skipper:
    def __init__(self, args):
        self.args = args
        if args.method == "auto":
            self.order = AUTO_ORDER + (["foreground"] if args.allow_foreground else [])
        else:
            self.order = [args.method]
        self.idx = 0
        self.fails = 0
        self.last_sent = None  # (시각, 위치)

    @property
    def method(self):
        return self.order[self.idx]

    def send(self, hwnd, match):
        m = self.method
        if m == "key":
            w32.post_key(hwnd)
        elif m == "click":
            w32.post_click(hwnd, match.x, match.y)
        else:
            w32.foreground_key(hwnd)
        self.last_sent = (time.time(), (match.x, match.y))
        log(f"Skip 감지 ({match.name}, {match.score:.2f}) → {m} 전송")

    def check_result(self, still_there, match):
        """입력 후에도 같은 자리에 Skip 이 남아 있으면 실패로 보고, 2번 연속 실패 시 다음 방식으로."""
        if not self.last_sent:
            return
        _, (px, py) = self.last_sent
        same_spot = still_there and abs(match.x - px) < 20 and abs(match.y - py) < 20
        self.last_sent = None
        if not same_spot:
            if self.fails:
                log(f"'{self.method}' 방식 동작 확인")
            self.fails = 0
            return
        self.fails += 1
        if self.fails >= 2 and self.idx + 1 < len(self.order):
            self.idx += 1
            self.fails = 0
            log(f"입력이 먹히지 않는 것 같아 '{self.method}' 방식으로 전환합니다.")
        elif self.fails >= 3 and self.idx + 1 >= len(self.order):
            hint = "" if "foreground" in self.order else " (--allow-foreground 옵션을 시도해 보세요)"
            log(f"모든 입력 방식이 실패했습니다.{hint}")
            self.fails = 0


def run(args):
    templates = {}
    for folder in (BUNDLED_TEMPLATE_DIR, TEMPLATE_DIR):
        if os.path.isdir(folder):
            templates.update({t.name: t for t in load_templates(folder)})
    templates = list(templates.values())
    if not templates:
        sys.exit(f"템플릿이 없습니다: {TEMPLATE_DIR}")
    log(f"템플릿 {len(templates)}개 로드: {', '.join(t.name for t in templates)}")
    det = SkipDetector(templates, threshold=args.threshold)
    skipper = Skipper(args)
    hwnd = wait_window(args.title)
    log(f"동작 시작 (입력 방식: {args.method}) - Ctrl+F10 일시정지/재개, Ctrl+C 종료")

    paused = False
    warned = set()
    while True:
        if w32.hotkey_pressed():
            paused = not paused
            log("일시정지" if paused else "재개")
        if paused:
            time.sleep(0.2)
            continue

        if not w32.is_valid(hwnd):
            log("게임 창이 닫혔습니다.")
            hwnd = wait_window(args.title)
            continue
        if w32.is_minimized(hwnd):
            if "min" not in warned:
                log("게임 창이 최소화되어 있으면 감지할 수 없습니다. (다른 창 뒤에 두는 건 괜찮아요)")
                warned.add("min")
            time.sleep(1)
            continue
        warned.discard("min")

        frame = w32.capture(hwnd)
        if frame is None:
            time.sleep(args.interval)
            continue
        if frame.mean() < 1.0:
            if "black" not in warned:
                log("캡처 화면이 검은색입니다. 게임 그래픽 설정에서 '창 모드'인지 확인해 주세요.")
                warned.add("black")
            time.sleep(1)
            continue
        warned.discard("black")

        match = det.find(frame)
        hit = det.is_hit(match)
        if args.debug and match:
            log(f"  best={match.score:.3f} ({match.name}) at {match.x},{match.y}")

        skipper.check_result(hit, match)
        if hit:
            if args.debug:
                os.makedirs(DEBUG_DIR, exist_ok=True)
                dbg = frame.copy()
                cv2.rectangle(dbg, (match.x - match.w // 2, match.y - int(match.h * 0.3)),
                              (match.x + match.w // 2, match.y + int(match.h * 0.7)), (0, 0, 255), 2)
                imwrite_unicode(os.path.join(DEBUG_DIR, f"{time.time():.0f}_{match.score:.2f}.png"), dbg)
            try:
                skipper.send(hwnd, match)
            except w32.AccessDenied:
                sys.exit("게임이 관리자 권한으로 실행 중이라 입력을 보낼 수 없습니다.\n"
                         "이 프로그램을 마우스 오른쪽 클릭 → '관리자 권한으로 실행' 해 주세요.")
            time.sleep(args.cooldown)
        else:
            time.sleep(args.interval)


def main():
    w32.set_dpi_aware()
    args = parse_args()
    try:
        if args.capture:
            capture_template(args.title)
        else:
            run(args)
    except KeyboardInterrupt:
        log("종료")
    except SystemExit as e:
        if e.code not in (None, 0):
            log(str(e.code))
            if FROZEN:  # exe 를 더블클릭했을 때 오류 메시지를 보고 닫을 수 있게
                input("Enter 키를 누르면 종료합니다...")
        raise


if __name__ == "__main__":
    main()
