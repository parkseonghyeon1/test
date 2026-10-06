"""창 크기/비율이 바뀌어도 Skip 을 찾는지 확인 (합성 화면 사용, OS 무관).

    python tests/test_detector_resize.py
"""
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from detector import SkipDetector, load_templates  # noqa: E402

REF_W, REF_H = 1244, 700


def background(w, h, seed):
    """게임 배경 비슷한 질감 (흐린 노이즈 + 밝은 글자 같은 선)."""
    rng = np.random.default_rng(seed)
    img = rng.integers(40, 200, (h // 8 + 1, w // 8 + 1), dtype=np.uint8)
    img = cv2.resize(img, (w, h), interpolation=cv2.INTER_CUBIC)
    img = cv2.GaussianBlur(img, (0, 0), 3)
    for _ in range(25):  # 다른 흰 글자/UI 처럼 보이는 방해 요소
        x, y = int(rng.integers(0, w - 80)), int(rng.integers(0, h - 20))
        cv2.putText(img, "Quest", (x, y + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 235, 1)
    return img


def make_frame(t, ui_scale, w, h, seed, right_margin, top):
    """UI 가 ui_scale 배로 그려진 w×h 화면에 템플릿 t 를 오른쪽에 붙여 넣는다."""
    img = background(w, h, seed)
    tpl = cv2.resize(t.gray, None, fx=ui_scale, fy=ui_scale,
                     interpolation=cv2.INTER_AREA if ui_scale < 1 else cv2.INTER_CUBIC)
    th, tw = tpl.shape
    x = w - int(right_margin * ui_scale) - tw
    y = int(top * ui_scale) if top >= 0 else h - int(-top * ui_scale) - th
    img[y:y + th, x:x + tw] = tpl
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), (x + tw // 2, y + int(th * 0.3))


def main():
    templates = load_templates(os.path.join(ROOT, "templates"))
    det = SkipDetector(templates)
    cases = []
    for sw, sh in ((1244, 700), (800, 450), (1920, 1080), (2560, 1440),  # 16:9
                   (2560, 1080), (1600, 600),                            # 가로로 넓은 창 (UI 는 높이 기준)
                   (1244, 1000)):                                        # 세로로 긴 창 (UI 는 폭 기준)
        ui = min(sw / REF_W, sh / REF_H)
        cases.append((sw, sh, ui))
    fails = 0
    for i, t in enumerate(templates):
        for j, (w, h, ui) in enumerate(cases):
            seed = i * 100 + j
            top = 30 if i % 2 == 0 else -20
            frame, (ex, ey) = make_frame(t, ui, w, h, seed, right_margin=20, top=top)
            m = det.find(frame)
            neg = det.find(cv2.cvtColor(background(w, h, seed), cv2.COLOR_GRAY2BGR))
            ok = (det.is_hit(m) and abs(m.x - ex) <= 6 * ui + 3 and abs(m.y - ey) <= 6 * ui + 3
                  and not det.is_hit(neg))
            fails += not ok
            print(f"{'PASS' if ok else 'FAIL'} {t.name:26} {w}x{h:<5} ui={ui:.2f} "
                  f"score={m.score:.2f} at=({m.x},{m.y}) expect=({ex},{ey}) neg={neg.score:.2f}")
    print(f"\n{fails} failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
