"""Skip 버튼 탐지 (OpenCV 템플릿 매칭) - OS 독립 모듈."""
import os
import re
from dataclasses import dataclass

import cv2
import numpy as np

# 파일명에 "@1244" 처럼 템플릿을 잘라낸 당시의 게임 화면(클라이언트) 가로 폭을 적어둔다.
# 현재 창 크기와 비교해 템플릿을 자동으로 확대/축소한다.
_REF_RE = re.compile(r"@(\d+)\.png$", re.IGNORECASE)


@dataclass
class Template:
    name: str
    gray: np.ndarray
    ref_width: int | None  # None 이면 현재 창 크기 그대로 사용


@dataclass
class Match:
    name: str
    score: float
    x: int  # 클릭할 위치 = "Skip" 글자 부분 (클라이언트 좌표)
    y: int
    w: int
    h: int


def imread_unicode(path, flags=cv2.IMREAD_GRAYSCALE):
    """한글 경로에서도 동작하는 imread."""
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, flags)


def imwrite_unicode(path, img):
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(path)
    return ok


def load_templates(folder):
    templates = []
    for fn in sorted(os.listdir(folder)):
        if not fn.lower().endswith(".png"):
            continue
        img = imread_unicode(os.path.join(folder, fn))
        if img is None:
            continue
        m = _REF_RE.search(fn)
        templates.append(Template(fn, img, int(m.group(1)) if m else None))
    return templates


class SkipDetector:
    def __init__(self, templates, threshold=0.75, roi_right=0.35,
                 scale_steps=(0.9, 0.95, 1.0, 1.05, 1.1)):
        if not templates:
            raise ValueError("템플릿이 없습니다.")
        self.templates = templates
        self.threshold = threshold
        self.roi_right = roi_right  # 화면 오른쪽 몇 %만 검사할지 (Skip은 항상 오른쪽)
        self.scale_steps = scale_steps
        self._cache = {}  # (템플릿명, 창폭) -> 리사이즈된 템플릿 목록

    def _scaled(self, t, width):
        key = (t.name, width)
        if key not in self._cache:
            base = width / t.ref_width if t.ref_width else 1.0
            out = []
            for s in self.scale_steps:
                f = base * s
                interp = cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR
                img = cv2.resize(t.gray, None, fx=f, fy=f, interpolation=interp)
                if img.shape[0] >= 8 and img.shape[1] >= 8:
                    out.append(img)
            self._cache[key] = out
        return self._cache[key]

    def find(self, frame_bgr):
        """frame_bgr: 게임 클라이언트 영역 이미지. 가장 점수가 높은 Match 반환 (임계값 미만이면 best만 기록)."""
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY) if frame_bgr.ndim == 3 else frame_bgr
        h, w = gray.shape
        x0 = int(w * (1 - self.roi_right))
        roi = gray[:, x0:]
        best = None
        for t in self.templates:
            for timg in self._scaled(t, w):
                th, tw = timg.shape
                if th > roi.shape[0] or tw > roi.shape[1]:
                    continue
                r = cv2.matchTemplate(roi, timg, cv2.TM_CCOEFF_NORMED)
                r[~np.isfinite(r)] = 0  # 단색 영역에서 생기는 NaN/inf 제거
                r[r > 1.0001] = 0
                _, score, _, loc = cv2.minMaxLoc(r)
                if best is None or score > best.score:
                    best = Match(t.name, float(score), x0 + loc[0] + tw // 2,
                                 loc[1] + int(th * 0.3), tw, th)  # 템플릿 아래쪽은 "Space" 라벨
        return best

    def is_hit(self, match):
        return match is not None and match.score >= self.threshold
