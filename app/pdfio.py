"""PDF 열기 / 페이지 그림 만들기 / 나눠서 저장하기.

원본 PDF는 읽기만 하고 절대 수정하지 않음.
"""
import io
import os
import subprocess
import tempfile
import threading

from PIL import Image
from pypdf import PdfReader, PdfWriter

try:
    import fitz  # PyMuPDF
except Exception:  # 개발용(리눅스) 대체
    fitz = None


class Doc:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self._cache = {}
        if fitz is not None:
            self.fz = fitz.open(path)
            self.count = self.fz.page_count
        else:
            self.fz = None
            self.count = len(PdfReader(path).pages)

    def render(self, i, dpi):
        key = (i, dpi)
        if key in self._cache:
            return self._cache[key]
        with self.lock:
            if self.fz is not None:
                pg = self.fz[i]
                pix = pg.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            else:
                d = tempfile.mkdtemp()
                subprocess.run(["pdftoppm", "-r", str(dpi), "-png", "-f", str(i + 1), "-l", str(i + 1),
                                "-singlefile", self.path, os.path.join(d, "p")], check=True)
                img = Image.open(os.path.join(d, "p.png")).convert("RGB")
                img.load()
        if dpi <= 80:  # 작은 그림만 기억 (메모리 절약)
            self._cache[key] = img
        return img

    def close(self):
        if self.fz is not None:
            self.fz.close()


def save_pages(src_path, pages, out_path):
    """pages: [(페이지번호, 회전각)] → 새 PDF로 저장 (원본 화질 그대로)."""
    r = PdfReader(src_path)
    w = PdfWriter()
    for i, rot in pages:
        p = w.add_page(r.pages[i])
        if rot:
            p.rotate(rot)
    tmp = out_path + ".tmp"
    with open(tmp, "wb") as f:
        w.write(f)
    os.replace(tmp, out_path)


def to_jpeg_bytes(img, quality=82):
    b = io.BytesIO()
    img.convert("RGB").save(b, "JPEG", quality=quality)
    return b.getvalue()
