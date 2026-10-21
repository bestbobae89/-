"""보험사 로고로 보험사 알아보기 (청약서 첫 장용).

로고 그림 파일 이름 = 34곳 목록 이름 (예: 롯데손보.webp, 롯데손보_자동차.png)
프로그램 안에 기본 로고가 들어 있고, exe 옆 '로고' 폴더에 넣은 파일이 추가/우선됩니다.
"""
import glob
import logging
import os

import numpy as np
from PIL import Image

log = logging.getLogger("logos")
try:
    import cv2
except Exception:  # 없으면 로고 기능만 꺼짐
    cv2 = None

EXTS = ("*.png", "*.webp", "*.jpg", "*.jpeg", "*.bmp")


def _load(path):
    im = Image.open(path)
    im.load()
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, "white")
        bg.alpha_composite(im)
        im = bg
    g = np.asarray(im.convert("L"))
    ys, xs = np.where(g < 235)  # 여백 잘라내기
    if len(xs) == 0:
        return None
    return g[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


class LogoMatcher:
    def __init__(self, dirs, alias):
        self.tpls = {}
        for d in dirs:
            if not d or not os.path.isdir(d):
                continue
            for ext in EXTS:
                for f in glob.glob(os.path.join(d, ext)):
                    stem = os.path.splitext(os.path.basename(f))[0]
                    key = stem.split("_")[0]
                    name = alias.get(key.upper().replace(" ", ""), key)
                    try:
                        t = _load(f)
                    except Exception as e:
                        log.warning("로고 읽기 실패 %s: %s", f, e)
                        continue
                    if t is not None and min(t.shape) >= 8:
                        self.tpls[stem] = (name, t)
        log.info("로고 %d개 불러옴", len(self.tpls))

    @property
    def ok(self):
        return cv2 is not None and bool(self.tpls)

    def find(self, page_img, min_score=0.7):
        """페이지 그림에서 가장 잘 맞는 로고 → (보험사 이름, 점수)."""
        if not self.ok:
            return "", 0.0
        g = np.asarray(page_img.convert("L"))
        W = 900
        h = int(g.shape[0] * W / g.shape[1])
        g = cv2.resize(g, (W, h), interpolation=cv2.INTER_AREA)
        regions = [g[: int(h * .28)], g[int(h * .82):]]
        best, bscore = "", 0.0
        for name, t in self.tpls.values():
            for frac in np.geomspace(0.06, 0.34, 12):
                tw = int(W * frac)
                th = max(6, int(t.shape[0] * tw / t.shape[1]))
                tt = cv2.resize(t, (tw, th), interpolation=cv2.INTER_AREA)
                for r in regions:
                    if r.shape[0] <= th or r.shape[1] <= tw:
                        continue
                    s = float(cv2.matchTemplate(r, tt, cv2.TM_CCOEFF_NORMED).max())
                    if s > bscore:
                        best, bscore = name, s
        log.info("로고 판정: %s (%.2f)", best, bscore)
        return (best, bscore) if bscore >= min_score else ("", bscore)
