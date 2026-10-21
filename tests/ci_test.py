"""GitHub 윈도우 환경에서 돌리는 점검 (실제 고객 서류 없이 가짜 서류로)."""
import io, os, sys, tempfile, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
ok = True
def check(name, fn):
    global ok
    try:
        r = fn()
        print(f"[OK] {name}: {r}")
    except Exception:
        ok = False
        print(f"[FAIL] {name}")
        traceback.print_exc()

for m in ["webview", "fitz", "pypdf", "numpy", "PIL",
          "winrt.windows.media.ocr", "winrt.windows.globalization",
          "winrt.windows.graphics.imaging", "winrt.windows.storage.streams", "winrt.windows.storage"]:
    check("import " + m, lambda m=m: __import__(m) and "ok")

from PIL import Image, ImageDraw, ImageFont
import ocr, core, pdfio

def font(size):
    for fp in (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()

def text_img(t):
    im = Image.new("RGB", (900, 160), "white")
    ImageDraw.Draw(im).text((30, 40), t, fill="black", font=font(56))
    return im

def winocr_en():
    e = ocr.WinOcr("en-US")
    return [w.text for w in e.words(text_img("Hello World 2026"))]
check("Windows OCR (English) pipeline", winocr_en)

def winocr_ko():
    e = ocr.WinOcr("ko")
    return ocr.text_of(e, text_img("계약자 홍길동 롯데손보"))
check("Windows OCR (Korean)", winocr_ko)

def pdf_roundtrip():
    d = tempfile.mkdtemp()
    src = os.path.join(d, "t.pdf")
    pages = [text_img(f"page {i}") .resize((1240, 1754)) for i in range(3)]
    pages[0].save(src, "PDF", save_all=True, append_images=pages[1:], resolution=150)
    doc = pdfio.Doc(src)
    img = doc.render(1, 75)
    out = os.path.join(d, "o.pdf")
    pdfio.save_pages(src, [(0, 0), (2, 180)], out)
    from pypdf import PdfReader
    r = PdfReader(out)
    return f"render {img.size}, saved {len(r.pages)} pages, rot={r.pages[1].get('/Rotate')}"
check("PDF render/save (PyMuPDF+pypdf)", pdf_roundtrip)

check("insurers", lambda: core.match_insurer("KB라이프생명", core.load_insurers()[1]))
print("RESULT:", "PASS" if ok else "FAIL (see above)")
# 한국어 OCR은 서버에 언어팩이 없을 수 있어 실패해도 빌드는 계속
