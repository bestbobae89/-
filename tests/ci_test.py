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
        traceback.print_exc(file=sys.stdout)

for m in ["webview", "fitz", "pypdf", "numpy", "PIL", "openpyxl",
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

def logo_test():
    import logos
    lm = logos.LogoMatcher([os.path.join(os.path.dirname(__file__), "..", "app", "logos")], core.load_insurers()[1])
    page = Image.new("RGB", (1654, 2339), "white")
    L = Image.open(os.path.join(os.path.dirname(__file__), "..", "app", "logos", "롯데손보.webp")).convert("RGBA")
    bg = Image.new("RGBA", L.size, "white"); bg.alpha_composite(L)
    page.paste(bg.convert("RGB").resize((L.width * 2, L.height * 2)), (100, 80))
    r = lm.find(page)
    assert r[0] == "롯데손보", r
    return f"{len(lm.tpls)} logos, {r}"
check("logo matching", logo_test)

def app_page_test():
    e = ocr.WinOcr("ko")
    page = Image.new("RGB", (1654, 2339), "white"); d = ImageDraw.Draw(page)
    for y, t in [(400, "계약자   홍길동      주민등록번호"), (470, "피보험자  김철수"), (1900, "모집인  이왕주  (서명)")]:
        d.text((120, y), t, fill="black", font=font(32))
    lines = ocr.group_lines(e.words(page))
    return (core.pick(core.names_next_to(lines, r"계\s*약\s*자")), core.pick(core.names_next_to(lines, r"피\s*보\s*험\s*자")),
            core.pick(core.names_next_to(lines, r"(모\s*집\s*인|설\s*계\s*사)")))
check("청약서 첫 장 이름 읽기 (Windows OCR)", app_page_test)
def auto_forms():
    import pdfio as P
    forms = {
     '삼성화재':[(100,80,'설계번호 : 2269193106000077 [스캔대상]',26),(100,140,'청약서  홍길동님을 위한 개인용 애니카',44),(100,300,'계약자  홍길동(72052****)',30),
       (100,2000,'충청.GA3센터 보험대리점 굿리치주식회사(신경균)',28),(100,2050,'Tel : 010-9758-1588 / 010-9758-1588',28),(100,2100,'E-mail : sf91931060@samsungfire.com',28)],
     'DB손보':[(100,80,'DB손해보험',40),(600,90,'프로미카개인용(프리미어형)',40),(100,300,'피보험자   정유미 / 서울 유성',30),(100,360,'계약자     김현용 / 대전 동구',30),
       (100,2100,'담당자   충청사업단 / 굿리치_둔산지점 / 김병규 010-5335-8007',28)],
     '메리츠':[(100,80,'[회사보관용] 청약서',30),(100,130,'Readycar개인용',44),(100,220,'전계약사 현대해상',26),(100,300,'피보험자   문우영 (27145)',30),(100,360,'계약자     문우영 (27145)',30),
       (100,2050,'영업담당자  충청GA-8지점(042-220-6809) 굿리치주식회사(굿리치보험대리점) 보험대리점(042-710-0841)',24),(330,2100,'김병규 (010-5335-8007)',24)],
     '현대해상':[(100,80,'Hicar개인용',30),(100,130,'자동차보험 청약서',44),(100,300,'보험',30),(400,300,'오동운 (59',30),(100,345,'계약자',30),(400,345,'(직장344',30),
       (100,420,'기명',30),(400,420,'오동운 (59',30),(100,465,'피보험자',30),(400,465,'(346601)',30),
       (100,2050,'대표AM지점 대리점명 : 굿리치주식회사 굿리치온라인지점(984369) 오흔이(4C5658)',24)],
     'KB손보':[(100,80,'KB금융그룹',30),(100,130,'자동차보험청약서   상품명 KB개인용',44),(100,300,'피보험자  김종숙 ( 32430',30),(100,360,'계 약 자  황재만 ( 32430',30),
       (100,2000,'영업담당자 굿리치주식회사(굿리치보험대리점)(대리점등록번호:2008)',24),(100,2050,'전화번호 010-9758-1588',24),
       (1100,2000,'완전 영업담당자  신경균  (인/서명)',24),(1100,2050,'판매 매니저        (인/서명)',24),(1100,2100,'확인 지점장  박미경  (인/서명)',24)],
     '한화손보':[(100,80,'자동차보험 청약서[회사보관용]',44),(100,160,'상품명 한화개인용 [일반]',30),(100,300,'계 약 자   김현익 (',30),(100,360,'피 보 험 자  김현익 (',30),
       (100,2050,'영업담당자  천안GA지점  [3404554](주)리치앤코.천안 [4733907]신경균',24)],
    }
    truth = {'삼성화재':('홍길동','','신경균'),'DB손보':('김현용','정유미','김병규'),'메리츠':('문우영','','김병규'),
             '현대해상':('오동운','','오흔이'),'KB손보':('황재만','김종숙','신경균'),'한화손보':('김현익','','신경균')}
    e = ocr.WinOcr("ko"); res = []
    d = tempfile.mkdtemp()
    for ins, items in forms.items():
        im = Image.new("RGB", (1654, 2339), "white"); dr = ImageDraw.Draw(im)
        for x, y, t, sz in items: dr.text((x, y), t, font=font(sz), fill="black")
        path = os.path.join(d, "a.pdf"); im.save(path, "PDF", resolution=200)
        _, its = core.Analyzer(P.Doc(path), core.MODE_APP, "자동차", e, roster=["이왕주"]).run()
        it = its[0]; got = (it["ins"], it["contractor"], it["insured"], it["agent"]); exp = (ins,) + truth[ins]
        res.append(("OK" if got == exp else "XX") + f" {ins}: {got}")
    print("\n".join("    " + r for r in res))
    return f"{sum(r.startswith('OK') for r in res)}/6"
check("자동차 청약서 6종 (Windows OCR)", auto_forms)
print("RESULT:", "PASS" if ok else "FAIL (see above)")
# 한국어 OCR은 서버에 언어팩이 없을 수 있어 실패해도 빌드는 계속
