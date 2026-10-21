"""글자인식(OCR) 엔진.

1순위: 윈도우 기본 글자인식(Windows.Media.Ocr, 한국어) — 설치 불필요
2순위: Tesseract (설치되어 있고 한국어 데이터가 있을 때만)
둘 다 없으면 None → 이름은 확인 화면에서 직접 입력
"""
import asyncio
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass

from PIL import Image, ImageOps

log = logging.getLogger("ocr")


@dataclass
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2

    @property
    def h(self):
        return self.y1 - self.y0


def group_lines(words):
    """단어들을 같은 줄끼리 묶어서 [(줄 글자, [단어들])] 로 돌려줌 (위→아래, 왼→오)."""
    ws = sorted(words, key=lambda w: w.cy)
    lines = []
    for w in ws:
        for ln in lines:
            ref = ln[-1]
            if abs(w.cy - ref.cy) < max(6, 0.6 * max(w.h, ref.h)):
                ln.append(w)
                break
        else:
            lines.append([w])
    out = []
    for ln in lines:
        ln.sort(key=lambda w: w.x0)
        txt = ln[0].text
        for a, b in zip(ln, ln[1:]):
            gap = b.x0 - a.x1
            h = max(4, (a.h + b.h) / 2)
            txt += ("" if gap < 0.35 * h else " ") + b.text
        out.append((txt, ln))
    out.sort(key=lambda t: t[1][0].cy)
    return out


def _pad(img, px=24):
    return ImageOps.expand(img.convert("RGB"), border=px, fill="white")


# ---------------------------------------------------------------- Windows OCR
class WinOcr:
    name = "윈도우 글자인식"
    fast = True

    def __init__(self, lang_code="ko"):
        try:  # 스레드 초기화 (버전에 따라 이름이 다름)
            import winrt.runtime as rt  # type: ignore
            if hasattr(rt, "init_apartment"):
                rt.init_apartment(getattr(rt, "MTA", 1))
        except Exception:
            pass
        from winrt.windows.media.ocr import OcrEngine  # type: ignore
        from winrt.windows.globalization import Language  # type: ignore
        lang = Language(lang_code)
        if not OcrEngine.is_language_supported(lang):
            raise RuntimeError(f"윈도우에 {lang_code} 글자인식이 설치되어 있지 않음")
        self.engine = OcrEngine.try_create_from_language(lang)
        if self.engine is None:
            raise RuntimeError("OcrEngine 생성 실패")
        try:
            self.maxdim = int(OcrEngine.max_image_dimension)
        except Exception:
            self.maxdim = 4000

    def _bitmap_from_buffer(self, img):
        from winrt.windows.graphics.imaging import (  # type: ignore
            SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode)
        from winrt.windows.storage.streams import DataWriter  # type: ignore
        rgba = img.convert("RGBA")
        data = rgba.tobytes("raw", "BGRA")
        dw = DataWriter()
        dw.write_bytes(data)
        buf = dw.detach_buffer()
        return SoftwareBitmap.create_copy_from_buffer(
            buf, BitmapPixelFormat.BGRA8, rgba.width, rgba.height, BitmapAlphaMode.PREMULTIPLIED)

    async def _bitmap_from_file(self, img):
        from winrt.windows.storage import StorageFile, FileAccessMode  # type: ignore
        from winrt.windows.graphics.imaging import BitmapDecoder  # type: ignore
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        img.convert("RGB").save(path)
        try:
            f = await StorageFile.get_file_from_path_async(path)
            stream = await f.open_async(FileAccessMode.READ)
            dec = await BitmapDecoder.create_async(stream)
            return await dec.get_software_bitmap_async()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    async def _run(self, img):
        try:
            bmp = self._bitmap_from_buffer(img)
        except Exception as e:  # 버전 차이 대비: 파일로 우회
            log.debug("buffer 방식 실패, 파일 방식 사용: %s", e)
            bmp = await self._bitmap_from_file(img)
        return await self.engine.recognize_async(bmp)

    def words(self, img):
        img = _pad(img)
        scale = 1.0
        if max(img.size) > self.maxdim:
            scale = self.maxdim / max(img.size)
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        res = asyncio.run(self._run(img))
        out = []
        for line in res.lines:
            for w in line.words:
                r = w.bounding_rect
                out.append(Word(w.text, (r.x) / scale - 24, (r.y) / scale - 24,
                                (r.x + r.width) / scale - 24, (r.y + r.height) / scale - 24))
        return out

    def line(self, img):
        return " ".join(t for t, _ in group_lines(self.words(img))).strip()


# ---------------------------------------------------------------- Tesseract
class TessOcr:
    name = "Tesseract"
    fast = False

    def __init__(self):
        import pytesseract  # type: ignore
        cmd = shutil.which("tesseract")
        if not cmd:
            for c in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                      r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
                if os.path.exists(c):
                    cmd = c
                    break
        if not cmd:
            raise RuntimeError("tesseract 없음")
        pytesseract.pytesseract.tesseract_cmd = cmd
        langs = pytesseract.get_languages(config="")
        if "kor" not in langs:
            raise RuntimeError("tesseract 한국어 데이터 없음")
        self.lang = "kor+eng" if "eng" in langs else "kor"
        self.pt = pytesseract

    def words(self, img):
        img = _pad(img)
        d = self.pt.image_to_data(img, lang=self.lang, config="--psm 6",
                                  output_type=self.pt.Output.DICT)
        out = []
        for i, t in enumerate(d["text"]):
            t = (t or "").strip()
            if not t or float(d["conf"][i]) < 0:
                continue
            x, y, w, h = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
            out.append(Word(t, x - 24, y - 24, x + w - 24, y + h - 24))
        return out

    def line(self, img):
        """한 줄짜리 칸 읽기 (Tesseract는 줄 모드가 더 정확)."""
        return self.pt.image_to_string(_pad(img), lang=self.lang, config="--psm 7").strip()


def get_engine():
    """쓸 수 있는 글자인식 엔진을 찾아서 돌려줌. 없으면 (None, 이유)."""
    reasons = []
    for cls in (WinOcr, TessOcr):
        try:
            eng = cls()
            log.info("글자인식 엔진: %s", eng.name)
            return eng, ""
        except Exception as e:  # noqa
            reasons.append(f"{cls.__name__}: {e}")
            log.info("%s 사용 불가: %s", cls.__name__, e)
    return None, " / ".join(reasons)


def text_of(engine, img):
    if engine is None:
        return ""
    return "\n".join(t for t, _ in group_lines(engine.words(img)))
