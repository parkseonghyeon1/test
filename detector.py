"""Skip 버튼 탐지 (OpenCV 템플릿 매칭) - OS 독립 모듈."""
import os
import re
from dataclasses import dataclass

import cv2
import numpy as np

# 파일명에 "@1244x700"(또는 "@1244") 처럼 템플릿을 잘라낸 당시의 게임 화면(클라이언트) 크기를 적어둔다.
# 현재 창 크기와 비교해 템플릿을 자동으로 확대/축소한다. 높이가 없으면 16:9 로 가정.
_REF_RE = re.compile(r"@(\d+)(?:x(\d+))?\.png$", re.IGNORECASE)


@dataclass
class Template:
    name: str
    gray: np.ndarray
    ref_width: int | None  # None 이면 현재 창 크기 그대로 사용
    ref_height: int | None = None


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
        rw = int(m.group(1)) if m else None
        rh = int(m.group(2)) if m and m.group(2) else (round(rw * 9 / 16) if rw else None)
        templates.append(Template(fn, img, rw, rh))
    return templates


class SkipDetector:
    """창 크기가 바뀌어도 동작하는 Skip 탐지기.

    게임마다 UI 가 창의 폭 또는 높이에 맞춰 커지므로, 두 비율을 모두 후보 배율로 시도한다.
    큰 창은 작업 해상도(높이 WORK_HEIGHT)로 줄여서 검사하므로 창 크기와 관계없이 속도가 일정하다.
    마지막으로 찾은 배율을 기억해 다음엔 그 배율부터 시도한다.
    """

    WORK_HEIGHT = 720
    STEPS = (0.9, 0.95, 1.0, 1.05, 1.1)

    def __init__(self, templates, threshold=0.75, roi_right=0.35):
        if not templates:
            raise ValueError("템플릿이 없습니다.")
        self.templates = templates
        self.threshold = threshold
        self.roi_right = roi_right  # 화면 오른쪽 몇 %만 검사할지 (Skip은 항상 오른쪽)
        self._cache = {}  # (템플릿명, 창크기) -> [(배율, 리사이즈된 템플릿)]
        self._last_good = {}  # 창크기 -> (템플릿명, 배율)
        self._misses = 0  # 배율을 좁혀서 못 찾은 연속 횟수

    def _candidates(self, t, w, h, k):
        """템플릿 t 를 창 w×h (작업 배율 k) 에 맞출 배율 후보와 리사이즈 결과."""
        key = (t.name, w, h)
        if key not in self._cache:
            bases = [1.0] if not t.ref_width else [w / t.ref_width, h / t.ref_height]
            scales = sorted({round(b * st, 3) for b in bases for st in self.STEPS})
            dedup = []
            for sc in scales:  # 2% 이내로 겹치는 배율은 하나만
                if not dedup or sc / dedup[-1] > 1.02:
                    dedup.append(sc)
            out = []
            for sc in dedup:
                f = sc * k
                img = cv2.resize(t.gray, None, fx=f, fy=f,
                                 interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR)
                if img.shape[0] >= 8 and img.shape[1] >= 12:
                    out.append((sc, img))
            self._cache[key] = out
            if len(self._cache) > 64:  # 창 크기를 자주 바꿔도 메모리가 늘지 않게
                self._cache.pop(next(iter(self._cache)))
        return self._cache[key]

    def find(self, frame_bgr):
        """frame_bgr: 게임 클라이언트 영역 이미지. 가장 점수가 높은 Match 반환."""
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY) if frame_bgr.ndim == 3 else frame_bgr
        h, w = gray.shape
        x0 = int(w * (1 - self.roi_right))
        k = min(1.0, self.WORK_HEIGHT / h)  # 작업 해상도 배율
        roi = gray[:, x0:]
        if k < 1.0:
            roi = cv2.resize(roi, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)

        jobs = [(t, sc, img) for t in self.templates for sc, img in self._candidates(t, w, h, k)]
        last = self._last_good.get((w, h))
        if last:
            # 이 창 크기에서 맞았던 배율 근처만 검사 (모든 템플릿이 같은 기준 크기라 배율이 공통).
            # 8번에 1번은 전체 배율을 다시 검사해서 혹시 모를 변화에 대비.
            if self._misses % 8 != 7:
                near = [j for j in jobs if abs(j[1] / last[1] - 1) <= 0.06]
                if near:
                    jobs = near
            jobs.sort(key=lambda j: (j[0].name, j[1]) != last)  # 지난번 템플릿·배율부터

        best = None
        for t, sc, timg in jobs:
            th, tw = timg.shape
            if th > roi.shape[0] or tw > roi.shape[1]:
                continue
            r = cv2.matchTemplate(roi, timg, cv2.TM_CCOEFF_NORMED)
            r[~np.isfinite(r)] = 0  # 단색 영역에서 생기는 NaN/inf 제거
            r[r > 1.0001] = 0
            _, score, _, loc = cv2.minMaxLoc(r)
            if best is None or score > best[0]:
                best = (float(score), t, sc, loc, tw, th)
                if score >= self.threshold + 0.1:  # 확실하면 나머지는 생략
                    break
        if best is None:
            return None
        score, t, sc, loc, tw, th = best
        if score >= self.threshold:
            self._last_good[(w, h)] = (t.name, sc)
            self._misses = 0
        elif last:
            self._misses += 1
        # 작업 해상도 좌표 → 원래 창 좌표
        tw_o, th_o = round(tw / k), round(th / k)
        left, top = x0 + loc[0] / k, loc[1] / k
        return Match(t.name, score, int(left + tw_o // 2), int(top + th_o * 0.3), tw_o, th_o)

    def is_hit(self, match):
        return match is not None and match.score >= self.threshold
