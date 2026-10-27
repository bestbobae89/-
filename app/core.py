"""서류 나누기 / 종류 구분 / 이름 읽기 / 파일 이름 만들기."""
import difflib
import json
import logging
import os
import re

import numpy as np
from PIL import Image

from ocr import group_lines

log = logging.getLogger("core")
HERE = os.path.dirname(os.path.abspath(__file__))

MODE_3 = "3종"
MODE_APP = "청약서"
MODE_MIX = "청약서+3종"
MODE_AUTO = "자동"
CAT_LONG = "장기"
CAT_CAR = "자동차"
CAT_GEN = "일반"

KW = ["보험", "계약", "확인", "설명", "상품", "동의", "서명", "보장", "해지", "가입", "청약",
      "피보험자", "보험료", "고객", "내용", "금융", "소비자", "기간", "납입", "정보", "비교"]


# ------------------------------------------------------------------ 보험사 이름
def load_insurers(nonlife_only=False):
    import sys
    p = os.path.join(os.path.dirname(sys.executable), "insurers.json")  # exe 옆에 있으면 그걸 우선 사용
    if not (getattr(sys, "frozen", False) and os.path.exists(p)):
        p = os.path.join(HERE, "insurers.json")
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    canon, alias = [], {}
    for grp in (("손해보험",) if nonlife_only else ("생명보험", "손해보험")):
        for name, al in d[grp].items():
            canon.append(name)
            alias[_norm(name)] = name
            for a in al:
                alias[_norm(a)] = name
    return canon, alias


def _norm(s):
    s = re.sub(r"\b\d{3,}\b", "", s or "")  # 숫자 잡음 제거
    s = re.sub(r"[\s\(\)\[\]（）:：.,·ㆍ|'\"_\-]", "", s or "")
    s = s.replace("주식회사", "").replace("(주)", "")
    return s.upper()


_CONFUSE = str.maketrans({"0": "D", "8": "B", "응": "흥", "홍": "흥", "룻": "롯", "듯": "롯",
                          "6": "B", "|": "", "l": "", "성": "생", "뜨": "프", "네": "데"})


def match_insurer(raw, alias):
    """서류에서 읽은 글자 → 34곳 목록 이름. (이름, 점수)"""
    if not raw:
        return "", 0.0
    best, score = "", 0.0
    for cand in (_norm(raw), _norm(raw).translate(_CONFUSE)):
        if not cand:
            continue
        if cand in alias:
            return alias[cand], 1.0
        # 긴 별칭이 글자 안에 그대로 들어 있으면 그걸로
        for a in sorted(alias, key=len, reverse=True):
            if len(a) >= 3 and a in cand:
                return alias[a], 0.95
        for a, name in alias.items():
            r = difflib.SequenceMatcher(None, cand, a).ratio()
            if r > score:
                best, score = name, r
    return (best, score) if score >= 0.6 else ("", score)


def find_insurer_in_text(text, alias):
    t = _norm(text)
    for a in sorted(alias, key=len, reverse=True):
        if len(a) >= 3 and a in t:
            return alias[a]
    return ""


# ------------------------------------------------------------------ 이름 정리
def clean_name(s):
    s = (s or "").strip()
    s = re.sub(r"(?<=[가-힣]) (?=[가-힣])", "", s)  # '이 왕주' → '이왕주'
    s = re.sub(r"[^가-힣A-Za-z ()]", " ", s)
    s = re.sub(r"\(.*?\)|서명|성명|님", "", s)
    m = re.search(r"[A-Z][A-Z ]{2,25}[A-Z]", s.upper()) if re.search(r"[A-Za-z]{3,}", s) else None
    if m and not re.search(r"[가-힣]", s):
        return m.group(0).strip()
    hs = re.findall(r"[가-힣]{2,5}", s)
    return hs[0] if hs else ""


def valid_name(s):
    return bool(re.fullmatch(r"[가-힣]{2,5}", s or "") or re.fullmatch(r"[A-Z][A-Z ]{2,25}", s or ""))


STOP = {"정보", "확인", "서명", "본인", "주소", "연락처", "직업", "관계", "동일", "법정대리인", "대리인",
        "성명", "명의", "보험", "계약", "고객", "상품", "회사", "보험료", "친권자", "후견인", "위의"}


def regex_names(text, labels):
    """칸 제목 바로 뒤에 오는 이름 후보들 (뒤에 띄어쓰기/괄호/님 이 와야 이름으로 인정)."""
    out = []
    for lab in labels:
        pat = lab + r"\s*(?:명|성명|이름)?\s*[:：.;]?\s*([가-힣](?: ?[가-힣]){1,3})(?=\s*(?:\(|님|$|[^가-힣\s]))"
        for m in re.finditer(pat, text, re.M):
            n = m.group(1).replace(" ", "")
            if n in STOP or any(n.startswith(s) for s in STOP) or n[0] in "는의을를와과":
                continue
            out.append(n)
    return out


def regex_name(text, labels):
    c = regex_names(text, labels)
    return max(set(c), key=c.count) if c else ""


def short_product(s):
    s = (s or "").strip()
    s = re.sub(r"^[^:：]*[:：]", "", s) if re.match(r"^\s*상품", s) else s
    s = re.sub(r"\(무\)|무배당|\[.*?\]|【.*?】|\(.*?\)|（.*?）", " ", s)
    s = re.sub(r"\b\d{3,}\b", " ", s)
    toks = [t for t in re.split(r"\s+", s) if t and not re.fullmatch(r"[\W\d_]+", t)]
    toks = [t for t in toks if not re.match(r"^(KB|DB|NH|롯데|흥국|한화|삼성|현대|메리츠|교보|신한|하나|라이나|"
                                          r"동양|미래에셋|처브|농협|AIA|ABL|MG|KDB|iM|IBK|let|Good|굿)", t, re.I)
            or len(toks) == 1]
    out = "".join(toks[-2:]) if toks else ""
    out = re.sub(r'[\\/:*?"<>|]', "", out)
    return out[:15]


# ------------------------------------------------------------------ 그림 분석
def _orange(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (r > 200) & (g > 140) & (g < 225) & (b < 170) & (r - b > 60)


def _blue(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (b > 200) & (r < 190) & (b - r > 40)


def classify(img75):
    """페이지 종류 + 회전. 종류: G(고지의무확인서) C(동의서) X(그 외) blank(빈 장)"""
    im = img75.convert("RGB")
    sm = im.resize((300, int(300 * im.height / im.width)))
    a = np.asarray(sm).astype(int)
    H, W, _ = a.shape
    wo = np.where(_orange(a).sum(1) > W * .6)[0] / H
    wb = np.where(_blue(a).sum(1) > W * .6)[0] / H
    g = np.asarray(im.convert("L")).astype(int)
    m = int(g.shape[1] * .04)
    dens = float((g[m:-m, m:-m] < 200).mean())
    if len(wb):
        return "C", (0 if wb.mean() < .5 else 180), dens
    if len(wo):
        if wo.max() > .85:
            return "G", 0, dens
        if wo.min() < .15:
            return "G", 180, dens
    if dens < 0.0025:
        return "blank", 0, dens
    return "X", 0, dens


def is_gray(img75):
    """흑백 스캔인지 (색이 거의 없으면 True)."""
    a = np.asarray(img75.convert("RGB").resize((200, 280))).astype(int)
    sat = a.max(2) - a.min(2)
    return float((sat > 50).mean()) < 0.002


def is_g_title(t):
    """고지의무확인서 제목인지 (다른 서류의 '금융소비자' 문구에 속지 않도록 '고지'가 꼭 있어야 함)."""
    return "고지의무" in t or ("고지" in t and "확인서" in t)


def is_gr_c_title(t):
    """굿리치 동의서('고객 계약 관리를 위한 …')인지. 보험사 자체 동의서와 구분."""
    return "계약관리" in t or "고객계약" in t or "관리를위한" in t


def is_c_title(t):
    return "신용" in t or ("개인" in t and ("동의" in t or "정보" in t))


def kw_score(engine, img):
    t = re.sub(r"\s", "", "".join(w.text for w in engine.words(img)))
    return sum(t.count(k) for k in KW)


def header_cells(img):
    """고지의무확인서 맨 위 [계약자 명 | 이름 | 보험사명 | 보험사] 칸 위치 찾기 (주황색 칸 기준)."""
    a = np.asarray(img.convert("RGB")).astype(int)
    H, W, _ = a.shape
    m = _orange(a)
    top = m[:int(H * .3)]
    rows = np.where(top[:, :int(W * .2)].sum(1) > W * 0.03)[0]
    if len(rows) == 0:
        return None
    bands, y0, y1 = [], rows[0], rows[0]
    for y in rows[1:]:
        if y - y1 > 3:
            bands.append((y0, y1))
            y0 = y
        y1 = y
    bands.append((y0, y1))
    for y0, y1 in bands:
        if y1 - y0 < H * 0.012:
            continue
        band = m[y0:y1 + 1].sum(0) > (y1 - y0) * 0.5
        xs = np.where(band)[0]
        if len(xs) == 0:
            continue
        runs, s, p = [], xs[0], xs[0]
        for x in xs[1:]:
            if x - p > 5:
                runs.append((s, p))
                s = x
            p = x
        runs.append((s, p))
        runs = [r for r in runs if r[1] - r[0] > W * 0.03]
        if len(runs) >= 2:
            pad = max(8, int(W * 0.005))
            name_box = (runs[0][1] + pad, y0 + pad, runs[1][0] - pad, y1 - pad)
            ins_box = (runs[1][1] + pad, y0 + pad, min(W - 1, runs[1][1] + int(W * .45)), y1 - pad)
            return name_box, ins_box
    return None


def prep_cell(img, box, th=185):
    c = img.crop(box).convert("L")
    c = c.resize((c.width * 2, c.height * 2), Image.LANCZOS)
    return c.point(lambda v: 255 if v > th else 0) if th else c


def ocr_cell(engine, img, box, th=185):
    if engine is None:
        return ""
    return engine.line(prep_cell(img, box, th))


def rot(img, r):
    return img.rotate(r, expand=True) if r else img


# ------------------------------------------------------------------ 기록용 가리기
_KEEP = ["계약", "피보", "보험", "설계", "모집", "상품", "성명", "주소", "서명", "청약", "확인", "연락",
         "주민", "생년", "직업", "관계", "납입", "기간", "보장", "가입", "금액", "회사", "이름", "취급",
         "판매", "담당", "대리", "증권", "번호", "고지", "동의", "정보", "비교", "설명"]


def mask(t):
    """기록 파일용: 이름 같은 짧은 한글 단어와 숫자는 가림."""
    t = re.sub(r"\d", "#", t or "")
    t = re.sub(r"\b[A-Z]{5,}\b", lambda m: "○" * len(m.group(0)), t)
    return re.sub(r"[가-힣]+", lambda m: m.group(0) if (len(m.group(0)) > 4 or any(k in m.group(0) for k in _KEEP))
                  else "○" * len(m.group(0)), t)


# ------------------------------------------------------------------ 차량번호
_PLATE_CH = "가나다라마거너더러머버서어저고노도로모보소오조구누두루무부수우주아바사자배하허호육해공국합"
_PLATE = re.compile(r"(?<![\d가-힣])((?:[가-힣]{2}\s?)?\d{2,3}\s?[" + _PLATE_CH + r"]\s?\d{4})(?!\d)")


def plate_in_text(text):
    """차량번호 찾기: '차량번호' 칸 근처 우선. 예) 12가3456, 123가4567, 서울12가3456"""
    lines = (text or "").splitlines()
    cands = []
    for k, ln in enumerate(lines):
        near = any(re.search(r"차\s*량\s*번\s*호|차\s*번\s*호|차량\s*No", lines[j]) for j in range(max(0, k - 1), k + 1))
        for m in _PLATE.finditer(ln):
            v = re.sub(r"\s", "", m.group(1))
            cands.append((0 if near else 1, v))
    if not cands:
        return ""
    cands.sort(key=lambda c: c[0])
    return cands[0][1]


# ------------------------------------------------------------------ 칸 제목 옆 이름 찾기
_SKIP_TOK = re.compile(r"^[:：.;,()\[\]|·ㆍ\-/]*(명|성명|이름|성 명|\(성명\)|\(인\))?[:：.;,()\[\]|·ㆍ\-/]*$")
_LABEL_TOK = re.compile(r"(계약자|피보험자|보험자|설계사|모집인|모집자|취급자|판매자|담당자|수익자|성명|주민|생년|관계|연락처|주소|직업|매니저|지점장)")
_NOT_NAME = re.compile(r"(굿리치|리치앤코|지점|센터|사업단|대리점|보험|주식|회사|본부|영업|고객|개인|법인|서명|확인|번호|코드)")
_STOP2 = STOP | {"피보험자", "계약자", "설계사", "모집인", "모집자", "취급자", "판매자", "담당자", "수익자", "보험자",
                 "매니저", "지점장", "기명", "직장", "자택", "남자", "여자"}


def join_split(t):
    """'신경 균', '홍 길 동' 처럼 한 글자씩 떨어진 한글을 붙임 (칸 제목과 이름 사이 띄어쓰기는 그대로)."""
    prev = None
    while prev != t:
        prev = t
        t = re.sub(r"(?<![가-힣])([가-힣]) (?=[가-힣])", r"\1", t)
        t = re.sub(r"(?<![가-힣])([가-힣]{2}) ([가-힣])(?![가-힣])", r"\1\2", t)
    return t


def is_name(t):
    return bool(re.fullmatch(r"[가-힣]{2,4}", t)) and t not in _STOP2 and not any(t.startswith(s) for s in STOP) \
        and t[0] not in "는의을를와과은" and not _NOT_NAME.search(t) and not t.endswith(("점", "센터", "팀"))


def _first_name_token(tokens):
    """칸 제목 뒤 단어들 → (이름, 상태). 상태: 'name' / 'label'(다른 칸 제목이 바로 옴) / 'none'(비어 있음) / 'other'"""
    for t in tokens[:5]:
        t = t.strip()
        t = re.sub(r"^([\[\(][^\]\)]*[\]\)])+", "", t)  # '[4733907]신경균' → '신경균', '(직장)' → ''
        if not t or _SKIP_TOK.match(t) or t[0] in "([":
            continue
        t2 = re.sub(r"[\(\[:：/].*$", "", t)  # '홍길동(72052…' → '홍길동'
        t2 = re.sub(r"[^가-힣A-Za-z]+$", "", t2)
        t2 = re.sub(r"^[^가-힣A-Za-z]+", "", t2)
        t2 = re.sub(r"(님|께|씨)$", "", t2)
        if _LABEL_TOK.search(t2):
            return "", "label"
        if is_name(t2):
            return t2, "name"
        if re.fullmatch(r"[A-Z][A-Z ]{4,25}", t2):  # 영문 이름은 5글자 이상만
            return t2, "name"
        return "", "other"
    return "", "none"


def _label_span(words, before, label_text):
    pos = len(before.replace(" ", ""))
    acc, x0, x1, y = 0, None, None, None
    for w in words:
        if acc >= pos and x0 is None:
            x0, y = w.x0, w.cy
        acc += len(w.text)
        if x0 is not None and acc >= pos + len(label_text.replace(" ", "")):
            x1 = w.x1
            break
    return x0, x1, y


def names_next_to(lines, label_pat, exclude_pat=None, page_w=None):
    """칸 제목 바로 오른쪽 → 오른쪽 윗줄·아랫줄 → 바로 아래 칸 순서로 이름 찾기. 후보 목록."""
    out = []
    lab_re = re.compile(label_pat)
    for k, (text, words) in enumerate(lines):
        text = join_split(text)
        for m in lab_re.finditer(text):
            before = text[:m.start()]
            if exclude_pat and re.search(exclude_pat + r"\s*$", before):
                continue
            if re.search(r"(전\s*계\s*약|매\s*니\s*저|지\s*점\s*장)\s*$", before):
                continue
            after = text[m.end():]
            if re.match(r"\s*(와|과|의|가|는|및|에|로|를|을)\b", after) or re.match(r"(와|과|의|가|는|및|에|로|를|을)", after):
                continue  # '계약자와 피보험자의 관계' 같은 문장
            n, state = _first_name_token(after.split())
            if n:
                out.append(n)
                continue
            x0, x1, y = _label_span(words, before, m.group(0))
            if x0 is None:
                continue
            x1 = x1 or x0 + 200
            h = max(w.h for w in words)
            reach = (page_w or (x1 + 2000)) * 0.45

            def below():  # 제목 바로 아래 칸에 이름이 오는 표
                for text2, words2 in lines[k + 1:k + 3]:
                    if words2[0].cy - y > 3.5 * h:
                        break
                    near_w = [w for w in words2 if w.x1 > x0 - h and w.x0 < x1 + 2 * h]
                    near = join_split(group_lines(near_w)[0][0]).split() if near_w else []
                    n_, _ = _first_name_token(near)
                    if n_:
                        return n_
                return ""

            def beside():  # 칸 제목이 두 줄로 나뉘어 이름이 윗줄/아랫줄 오른쪽에 있는 표
                for kk in (k - 1, k + 1):
                    if 0 <= kk < len(lines):
                        t2, w2 = lines[kk]
                        if abs(w2[0].cy - y) > 2.2 * h:
                            continue
                        left = join_split(" ".join(w.text for w in w2 if w.x1 <= x1 + h))
                        if _LABEL_TOK.search(left.replace(" ", "")):
                            continue
                        right = [w for w in w2 if w.x0 > x1 - h * .3 and w.x0 < x1 + reach]
                        if right:
                            n_, _ = _first_name_token(join_split(group_lines(right)[0][0]).split())
                            if n_:
                                return n_
                return ""

            found = beside() if state == "other" else (below() or beside())
            if found:
                out.append(found)
    return out


def pick(c):
    return max(c, key=lambda n: (c.count(n), -c.index(n))) if c else ""


# ------------------------------------------------------------------ 청약서용 보험사 찾기
BRANDS = {  # 자동차보험 브랜드 등 (글자 그대로)
    "애니카": "삼성화재", "ANYCAR": "삼성화재", "하이카": "현대해상", "HICAR": "현대해상", "HI-CAR": "현대해상", "HLCAR": "현대해상", "H1CAR": "현대해상",
    "프로미": "DB손보", "PROMY": "DB손보", "READYCAR": "메리츠", "레디카": "메리츠", "매직카": "KB손보",
    "MAGICCAR": "KB손보", "LET:CLICK": "롯데손보", "LET:SMILE": "롯데손보",
}
EMAILS = {
    "samsungfire.com": "삼성화재", "hi.co.kr": "현대해상", "idbins.com": "DB손보", "dbins.co.kr": "DB손보",
    "meritzfire.com": "메리츠", "kbinsure.co.kr": "KB손보", "hwgeneralins.com": "한화손보", "lotteins.co.kr": "롯데손보",
    "heungkukfire.co.kr": "흥국화재", "nhfire.co.kr": "농협손보", "hanainsure.co.kr": "하나손보",
    "samsunglife.com": "삼성생명", "hanwhalife.com": "한화생명", "kyobo.com": "교보생명",
}
SHORT_NONLIFE = [("메리츠", "메리츠"), ("KB", "KB손보"), ("DB", "DB손보"), ("한화", "한화손보"), ("흥국", "흥국화재"),
                 ("삼성", "삼성화재"), ("현대", "현대해상"), ("롯데", "롯데손보"), ("농협", "농협손보"), ("NH", "농협손보"),
                 ("하나", "하나손보"), ("예별", "MG손보"), ("MG", "MG손보"), ("AIG", "AIG손해보험"), ("라이나", "라이나손보")]


def insurer_from_text(text, alias, nonlife_only):
    lines = [l for l in text.splitlines() if not re.search(r"전\s*계\s*약", l)]  # '전계약사'는 이전 보험사
    t = "\n".join(lines)
    up = re.sub(r"\s", "", t).upper()
    for k, v in BRANDS.items():
        if k in up:
            return v, "브랜드"
    low = t.lower()
    for k, v in EMAILS.items():
        if k in low:
            return v, "이메일"
    found = find_insurer_in_text(t, alias)
    if found:
        return found, "글자"
    if nonlife_only:
        for k, v in SHORT_NONLIFE:
            if k in up:
                return v, "짧은이름"
    return "", ""


# ------------------------------------------------------------------ 취급자 찾기
_AGENT_LINE = re.compile(r"(담\s*당\s*자|설\s*계\s*사|모\s*집\s*인|모\s*집\s*자|취\s*급\s*자|굿\s*리\s*치|리\s*치\s*앤\s*코|대\s*리\s*점|판\s*매\s*자)")
_PHONE = r"0\d{1,2}\s*[-)]?\s*\d{3,4}\s*-?\s*\d{4}"


def agents_in_lines(lines, page_w=None):
    """취급자 후보: 칸 제목 옆 / 굿리치(이름) / [번호]이름 / 이름(코드·전화번호)."""
    out = names_next_to(lines, r"(영\s*업\s*담\s*당\s*자|담\s*당\s*자|설\s*계\s*사|모\s*집\s*인|모\s*집\s*자|취\s*급\s*자|판\s*매\s*자)",
                        page_w=page_w)
    near_agent = 0
    for text, _ in lines:
        text = join_split(text)
        if _AGENT_LINE.search(text):
            near_agent = 3  # 담당자 줄과 그 아래 두 줄까지 봄
        if near_agent <= 0:
            continue
        near_agent -= 1
        t = re.sub(r"(매\s*니\s*저|지\s*점\s*장)\s*[가-힣]{2,4}", " ", text)  # 매니저·지점장 이름 제외
        for pat in (r"(?:굿\s*리\s*치|리\s*치\s*앤\s*코)[^()\n]{0,12}\(\s*([가-힣]{2,4})\s*\)",
                    r"\]\s*([가-힣]{2,4})(?![가-힣])",
                    r"\d\s*[\]\)]\s*([가-힣]{2,4})(?![가-힣])",
                    r"(?<![가-힣])([가-힣]{2,4})\s*\(\s*(?:고유번호|[A-Z0-9]{3,})",
                    r"(?<![가-힣])([가-힣]{2,4})\s*\(?\s*" + _PHONE):
            for m in re.finditer(pat, t):
                if is_name(m.group(1)):
                    out.append(m.group(1))
    return out


def _close(a, b):
    """한 글자만 다른 이름 (글자인식 실수 맞추기)."""
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) <= 1


def snap_agent(name, roster):
    if not name or not roster or name in roster:
        return name
    near = [r for r in roster if _close(name, r)]
    return near[0] if len(near) == 1 else name


def roster_in_text(text, roster):
    t = re.sub(r"\s", "", text)
    hits = [r for r in roster if r and r in t]
    return hits


# ------------------------------------------------------------------ 본 처리
class Analyzer:
    def __init__(self, doc, mode, cat, engine, last_agent="", progress=None, logos=None, roster=None):
        self.doc, self.mode, self.cat, self.eng = doc, mode, cat, engine
        self.last_agent = last_agent
        self.progress = progress or (lambda *a: None)
        self.canon, self.alias = load_insurers(nonlife_only=cat in ("자동차", "일반"))
        self.nonlife = set(load_insurers(nonlife_only=True)[0])
        self.logos = logos
        self.roster = [r.strip() for r in (roster or []) if r and r.strip()]

    @property
    def is_long(self):
        return self.cat == CAT_LONG

    # 1) 페이지마다 종류 (색깔 + 제목 글자 확인). rot 는 글자 읽을 때만 사용
    def scan_pages(self):
        n = self.doc.count
        pages = []
        for i in range(n):
            self.progress(i, n * 2, f"페이지 분석 중 ({i + 1}/{n})")
            img = self.doc.render(i, 75)
            kind, r, dens = classify(img)
            info = {"i": i, "kind": kind, "rot": r, "dens": round(dens, 4)}
            if kind in ("G", "C") and self.mode != MODE_APP:
                info["kind"], info["rot"] = self._confirm_title(i, kind, r)
                if info["kind"] == "C":
                    info["gr"] = self._gr
            elif kind == "X" and self.mode != MODE_APP and is_gray(img):
                self._gr = True
                info["kind"], info["rot"] = self._title_kind(i)
                info["bw"] = True
                if info["kind"] == "C":
                    info["gr"] = self._gr
            pages.append(info)
        return pages

    def _title_text(self, i, r, dpi=110, frac=.13):
        base = rot(self.doc.render(i, dpi), r)
        W, H = base.size
        return re.sub(r"\s", "", "".join(w.text for w in self.eng.words(base.crop((0, 0, W, int(H * frac))))))

    def _title_kind(self, i):
        """흑백 스캔: 색으로 못 찾으니 제목 글자로 고지의무확인서/동의서 찾기."""
        if self.eng is None:
            return "X", 0
        try:
            for r in (0, 180):
                t = self._title_text(i, r)
                if is_g_title(t):
                    return "G", r
                if is_c_title(t):
                    self._gr = is_gr_c_title(t)
                    return "C", r
                if len(re.findall(r"[가-힣]", t)) >= 6:
                    break
        except Exception as e:
            log.warning("흑백 제목 확인 실패 p%d: %s", i + 1, e)
        return "X", 0

    def _b_type(self, p, rotate_check=True):
        """비교설명서 종류: 장기(가로 양식) / 자동차 / 일반 / None(모름)."""
        if self.eng is None or p is None or p["kind"] != "X":
            return None
        try:
            g = self.doc.render(p["i"], 100).convert("L")
            t0 = re.sub(r"\s", "", "".join(w.text for w in self.eng.words(g)))
            if "자동차보험" in t0 and "비교" in t0:
                return "자동차"
            if "일반보험" in t0 and "비교" in t0:
                return "일반"
            if not rotate_check:
                return None
            s0 = sum(t0.count(k) for k in KW)
            if s0 >= 10:  # 바로 세운 상태로 잘 읽히면 가로 양식(장기)이 아님
                return None
            s1 = kw_score(self.eng, g.rotate(-90, expand=True))
            if s1 <= s0 + 2:
                s1 = max(s1, kw_score(self.eng, g.rotate(90, expand=True)))
            if s1 > s0 + 2:
                return "장기"
            return None
        except Exception as e:
            log.warning("비교설명서 판단 실패 p%d: %s", p["i"] + 1, e)
            return None

    def _confirm_title(self, i, kind, r):
        self._gr = True  # 제목을 못 읽으면 굿리치 동의서로 간주
        if self.eng is None:
            return kind, r
        try:
            base = self.doc.render(i, 110)
            W, H = base.size
            seen = False
            for rr in (r, 180 - r if r in (0, 180) else 0):
                img = rot(base, rr)
                t = re.sub(r"\s", "", "".join(w.text for w in self.eng.words(img.crop((0, 0, W, int(H * .13))))))
                if len(re.findall(r"[가-힣]", t)) >= 4:
                    seen = True
                if kind == "G":
                    # 제목에 '고지'가 없으면(글자인식 실수 대비) 맨 위 [계약자 명|보험사명] 칸 모양까지 맞아야 인정
                    ok = is_g_title(t) or (("금융소비자" in t or "계약체결" in t) and header_cells(img) is not None)
                else:
                    ok = is_c_title(t)
                if ok:
                    self._gr = kind == "C" and is_gr_c_title(t)
                    return kind, rr
            if not seen:
                return kind, r
            log.info("p%d: 색은 %s 같지만 제목이 달라서 제외", i + 1, kind)
            return "X", 0
        except Exception as e:
            log.warning("제목 확인 실패 p%d: %s", i + 1, e)
            return kind, r

    # 2) 건별로 묶기
    def group(self, pages):
        if self.mode == MODE_APP:
            return [pages]
        if self.mode == MODE_AUTO and not any(p["kind"] in ("G", "C") for p in pages):
            return [pages]  # 3종서류가 없는 파일 = 청약서 1건
        groups, cur = [], []
        close_at = None  # 순서가 바뀐 경우(고지의무확인서가 동의서보다 앞) 동의서까지 묶고 닫음
        for n, p in enumerate(pages):
            if p["kind"] == "G" and not any(q["kind"] == "C" for q in cur):
                ahead = [k for k in range(n + 1, min(n + 3, len(pages))) if pages[k]["kind"] == "C"]
                if ahead:
                    close_at = ahead[0]
                    p["swap"] = True
                    log.info("p%d: 고지의무확인서가 동의서(p%d)보다 앞에 있음 → 동의서까지 한 건으로 묶음",
                             p["i"] + 1, pages[close_at]["i"] + 1)
                else:
                    # 동의서 없이 나온 고지의무확인서로는 나누지 않음 (청약서 중간 장 오인 방지)
                    log.info("p%d: 동의서 없이 나온 고지의무확인서 → 나누지 않음", p["i"] + 1)
                    p["kind"], p["gx"] = "X", True
            cur.append(p)
            if close_at is not None:
                if n == close_at:
                    groups.append(cur)
                    cur, close_at = [], None
                continue
            if p["kind"] == "G":
                groups.append(cur)
                cur = []
        if cur:
            if groups and all(p["kind"] == "blank" for p in cur):
                groups[-1].extend(cur)
            else:
                groups.append(cur)
        return groups

    # 3) 건마다 정보 읽기
    def reread(self, pages):
        """확인 화면에서 순서를 바꾸거나 나누고 합친 건 다시 읽기. pages: 화면에서 정한 순서 (제외된 장 포함)."""
        use = [dict(p, gx=False) for p in pages if not p.get("off")] or [dict(p) for p in pages]
        try:
            it = self.extract(use)
        except Exception:
            log.exception("다시 읽기 실패")
            it = self.blank_item(use)
            it["warns"].append("읽기 오류")
        it["pages"] = pages
        it["count"] = len([p for p in pages if not p.get("off")])
        it["agent"] = snap_agent(it["agent"], self.roster)
        log.info("다시 읽기: 원본 %s쪽 [%s] 보험사=%s 취급자=%s 계약자=%s 경고=%s",
                 ",".join(str(p["i"] + 1) for p in pages), "".join(p["kind"][0] for p in use),
                 it["ins"] or "(못읽음)", "읽음" if it["agent"] else "(없음)", "읽음" if it["contractor"] else "(못읽음)",
                 ",".join(it["warns"]) or "-")
        return it

    def run(self):
        pages = self.scan_pages()
        groups = self.group(pages)
        items = []
        for k, grp in enumerate(groups):
            self.progress(self.doc.count + (k + 1) * self.doc.count // max(1, len(groups)), self.doc.count * 2,
                          f"정보 인식 중 ({k + 1}/{len(groups)}건)")
            try:
                it = self.extract(grp)
            except Exception:
                log.exception("추출 실패")
                it = self.blank_item(grp)
                it["warns"].append("읽기 오류")
            it["no"] = k + 1
            items.append(it)
        if self.mode != MODE_APP and not (self.mode == MODE_AUTO and len(items) == 1 and items[0].get("mode") == MODE_APP):
            agents = [it["agent"] for it in items if it["agent"]]
            common = max(set(agents), key=agents.count) if agents else ""
            for it in items:
                if not it["agent"] and common:
                    it["agent"] = common
        keys = [(it["contractor"], it["insured"], it["ins"]) for it in items]
        for it, k in zip(items, keys):
            if k[0] and k[2] and keys.count(k) > 1:
                it["warns"].append("동일상품 확인")
        for it in items:
            it["agent"] = snap_agent(it["agent"], self.roster)
            log.info("No.%d 원본 %s쪽 %s장 [%s] 보험사=%s 취급자=%s 계약자=%s 피보험자=%s 경고=%s",
                     it["no"], ",".join(str(p["i"] + 1) for p in it["pages"][:1] + it["pages"][-1:]), it["count"],
                     "".join(p["kind"][0] for p in it["pages"]),
                     it["ins"] or "(못읽음)", "읽음" if it["agent"] else "(없음)",
                     "읽음" if it["contractor"] else "(못읽음)", "있음" if it["insured"] else "-",
                     ",".join(it["warns"]) or "-")
        return pages, items

    def blank_item(self, grp):
        return {"pages": [{k: p[k] for k in ("i", "rot", "kind", "gr", "gx") if k in p} for p in grp],
                "ver": "", "ins": "", "agent": "", "contractor": "", "insured": "",
                "product": "", "plate": "", "count": len(grp), "warns": []}

    def extract(self, grp):
        it = self.blank_item(grp)
        kinds = [p["kind"] for p in grp]
        nblank = kinds.count("blank")
        if nblank:
            it["warns"].append("빈 페이지 포함")
        if self.mode == MODE_APP or (self.mode == MODE_AUTO and not any(k in ("G", "C") for k in kinds)):
            if self.mode == MODE_AUTO:
                it["mode"] = MODE_APP
            self._extract_app(grp, it)
            return it
        if self.mode == MODE_AUTO:
            return self._extract_auto(grp, it, kinds, nblank)

        G = next((p for p in grp if p["kind"] == "G"), None)
        C = next((p for p in reversed(grp) if p["kind"] == "C"), None)
        if G is None:
            it["warns"].append("고지의무확인서 누락")
        if C is None:
            it["warns"].append("개인정보동의서 누락")
        self._merge_check(grp, it)
        if C is not None:
            ci = grp.index(C)
            before = [p for p in grp[:ci] if p["kind"] == "X"]
        else:
            before = [p for p in grp if p["kind"] == "X"]
        b_near = before[::-1]  # 동의서 바로 앞부터
        btype = self._b_type(b_near[0], rotate_check=not (self.mode == MODE_3 and self.is_long)) if b_near else None
        if btype and btype != self.cat:
            it["warns"].append("상품구분 불일치(확인필요)")
            log.info("상품구분 불일치: 선택=%s 비교설명서=%s", self.cat, btype)
        if self.mode == MODE_3:
            nb = len(before) if C is not None else kinds.count("X")
            if nb == 0:
                it["warns"].append("비교설명서 누락")
            elif self.is_long:
                if nb == 2:
                    it["ver"] = "신"
                elif nb == 1:
                    it["ver"] = "구"
                else:
                    it["warns"].append("2건 병합 의심" if nb > 2 else "버전 판별 불가")
            elif nb > 1:
                it["warns"].append("2건 병합 의심")
        else:  # 청약서+3종
            if not b_near:
                it["warns"].append("비교설명서 누락")
            elif self.is_long:
                b1 = btype == "장기"
                b2 = self._b_type(b_near[1]) == "장기" if len(b_near) > 1 else False
                if btype is None:
                    it["warns"].append("버전 판별 불가")
                elif b1 and b2:
                    it["ver"] = "신"
                elif b1:
                    it["ver"] = "구"
            n3 = 4 if (self.is_long and it["ver"] != "구") else 3
            if len(grp) - nblank <= n3:
                it["warns"].append("청약서 누락")
        if it["ver"] == "구" and self.is_long:
            it["warns"].append("구버전 적용")
        if self.is_long and not it["ver"] and "버전 판별 불가" not in it["warns"] and self.mode != MODE_APP \
                and "비교설명서 누락" not in it["warns"]:
            it["warns"].append("버전 판별 불가")
        if self.eng is None:
            return it
        self._extract_3jong(G, C, it)
        if not it["agent"]:
            self._agent_from_pages(grp, it)
        if self.mode == MODE_MIX:
            self._app_info_for_mix(grp, it, exclude=b_near[:(2 if self.is_long else 1)], car=self.cat == CAT_CAR)
        return it

    def _merge_check(self, grp, it):
        """2건 병합 의심 + 이유."""
        why = []
        cs = [(k, p) for k, p in enumerate(grp) if p["kind"] == "C" and p.get("gr", True)]
        if len(cs) > 1:
            why.append("이 건 안에 굿리치 개인정보동의서가 %d장 있습니다 (%s). 2건이 하나로 묶였을 수 있습니다."
                       % (len(cs), ", ".join("%d번째 장(원본 %d쪽)" % (k + 1, p["i"] + 1) for k, p in cs)))
        for k, p in enumerate(grp):
            if p.get("gx"):
                why.append("%d번째 장(원본 %d쪽)이 고지의무확인서로 보이지만 앞에 동의서가 없어 여기서 나누지 않았습니다."
                           % (k + 1, p["i"] + 1))
        if why:
            it["warns"].append("2건 병합 의심")
            it.setdefault("why", {})["2건 병합 의심"] = " ".join(why)
            log.info("2건 병합 의심: %s", " / ".join(why))

    def _agent_from_pages(self, grp, it):
        """고지의무확인서에서 취급자를 못 찾으면 다른 장의 '담당자' 칸 등에서 찾기."""
        if self.eng is None or it["agent"]:
            return
        cand = [p for p in grp if p["kind"] == "X"][:5]
        for p in cand:
            try:
                words, img = self._read_page(p)
            except Exception as e:
                log.warning("취급자 보완 읽기 실패 p%d: %s", p["i"] + 1, e)
                continue
            lines = group_lines(words)
            full = "\n".join(join_split(t) for t, _ in lines)
            hits = [h for h in roster_in_text(full, self.roster) if h not in (it["contractor"], it["insured"])]
            a = [x for x in agents_in_lines(lines, page_w=img.width) if x not in (it["contractor"], it["insured"])]
            ag = hits[0] if len(hits) == 1 else (next((h for h in hits if h in a), "") or pick(a))
            if ag:
                it["agent"] = ag
                log.info("취급자: 원본 %d쪽의 담당자 칸에서 찾음", p["i"] + 1)
                return

    def _cat_from_text(self, t):
        t = re.sub(r"\s", "", t)
        up = t.upper()
        if any(k in t for k in ("자동차", "대인배상", "대물배상", "자기신체", "자기차량", "차량번호", "운전자범위",
                                "애니카", "프로미카", "하이카", "매직카", "레디카")) or \
                any(k in up for k in ("ANYCAR", "HICAR", "READYCAR", "MAGICCAR", "PROMY")):
            return CAT_CAR, True
        if "일반보험" in t or "화재보험" in t or "배상책임" in t:
            return CAT_GEN, True
        if "장기" in t or "생명" in t or "건강보험" in t or "종신" in t:
            return CAT_LONG, True
        return CAT_LONG, False

    def _extract_auto(self, grp, it, kinds, nblank):
        """자동 판별: 비교설명서 양식으로 상품 구분, 장수로 3종/청약서+3종·신/구버전."""
        G = next((p for p in grp if p["kind"] == "G"), None)
        C = next((p for p in reversed(grp) if p["kind"] == "C"), None)
        if G is None:
            it["warns"].append("고지의무확인서 누락")
        if C is None:
            it["warns"].append("개인정보동의서 누락")
        self._merge_check(grp, it)
        end = grp.index(C) if C is not None else (grp.index(G) if G is not None else len(grp))
        before = [p for p in grp[:end] if p["kind"] == "X"]
        near = before[::-1]
        types = []
        for p in near[:2]:
            t = self._b_type(p)
            types.append(t)
            if t in (CAT_CAR, CAT_GEN) or t is None:
                break
        cat, nb, sure = None, 0, False
        if types and types[0] in (CAT_CAR, CAT_GEN):
            cat, nb, sure = types[0], 1, True
        elif types and types[0] == CAT_LONG:
            cat, sure = CAT_LONG, True
            nb = 2 if len(types) > 1 and types[1] == CAT_LONG else 1
            it["ver"] = "신" if nb == 2 else "구"
        if not near:
            it["warns"].append("비교설명서 누락")
        if cat is None and self.eng is not None and grp[0]["kind"] == "X" and len(near) > 2:
            try:  # 비교설명서로 모르면 청약서 첫 장 글자로
                cat, sure = self._cat_from_text("".join(w.text for w in self.eng.words(self.doc.render(grp[0]["i"], 100))))
            except Exception as e:
                log.warning("구분 판별 실패: %s", e)
        if cat is None:
            cat = CAT_LONG
        if not sure:
            it["warns"].append("구분 확인")
        if nb == 0:
            nb = min(len(near), 2 if cat == CAT_LONG else 1)
        extra = len(near) - nb
        it["cat"] = cat
        it["mode"] = MODE_MIX if extra > 0 else MODE_3
        if cat == CAT_LONG:
            if it["ver"] == "구":
                it["warns"].append("구버전 적용")
            elif not it["ver"] and near:
                it["warns"].append("버전 판별 불가")
        log.info("자동 판별: %s %s 비교설명서=%s 청약서=%d장 버전=%s", cat, it["mode"], types, max(0, extra), it["ver"] or "-")
        if self.eng is None:
            return it
        self._extract_3jong(G, C, it)
        if not it["agent"]:
            self._agent_from_pages(grp, it)
        if it["mode"] == MODE_MIX:
            self._app_info_for_mix(grp, it, exclude=near[:nb], car=cat == CAT_CAR)
        return it

    def _app_info_for_mix(self, grp, it, exclude=(), car=False):
        """청약서+3종: 청약서 앞 장에서 계약자·피보험자(·차량번호)를 읽고, 고지의무확인서 값과 비교."""
        if self.eng is None:
            return
        ex = {p["i"] for p in exclude}
        pages = [q for q in grp if q["kind"] == "X" and q["i"] not in ex][:2]
        app_c, app_i, plate = "", "", ""
        for p in pages:
            try:
                words, img = self._read_page(p)
            except Exception as e:
                log.warning("청약서 읽기 실패 p%d: %s", p["i"] + 1, e)
                continue
            lines = group_lines(words)
            full = "\n".join(join_split(t) for t, _ in lines)
            W = img.width
            if not app_c:
                c = [m.group(1) for m in re.finditer(r"([가-힣]{2,4})\s*님\s*을\s*위\s*한", full) if is_name(m.group(1))]
                c += names_next_to(lines, r"계\s*약\s*자", exclude_pat=r"(피\s*보\s*[험혐]|대\s*리|전)", page_w=W)
                app_c = pick(c)
            if not app_i:
                app_i = pick(names_next_to(lines, r"피\s*보\s*[험혐]\s*자", page_w=W))
            if car and not plate:
                plate = plate_in_text(full)
            if app_c and (app_i or not car) and (plate or not car):
                break
        g_c = it["contractor"]
        if app_c:
            if g_c and valid_name(g_c) and g_c != app_c:
                it["warns"].append("계약자 확인")
                it.setdefault("why", {})["계약자 확인"] = (
                    "청약서의 계약자는 '%s', 고지의무확인서의 계약자는 '%s'로 읽혔습니다. 청약서 값을 넣었으니 원본을 보고 맞는지 확인하십시오."
                    % (app_c, g_c))
                log.info("계약자 불일치: 청약서와 고지의무확인서가 다름")
            it["contractor"] = app_c
            log.info("계약자: 청약서에서 읽음")
        if app_i and app_i != it["contractor"]:
            it["insured"] = app_i
            if "피보험자 칸 확인" in it["warns"]:
                it["warns"].remove("피보험자 칸 확인")
            log.info("피보험자: 청약서에서 읽음")
        if plate:
            it["plate"] = plate

    def _plate_from_pages(self, grp, it, exclude=()):
        """자동차 청약서 장에서 차량번호 찾기 (앞에서부터 최대 3장)."""
        ex = {p["i"] for p in exclude}
        for p in [q for q in grp if q["kind"] == "X" and q["i"] not in ex][:3]:
            try:
                words, _ = self._read_page(p)
            except Exception as e:
                log.warning("차량번호 읽기 실패 p%d: %s", p["i"] + 1, e)
                continue
            v = plate_in_text("\n".join(join_split(t) for t, _ in group_lines(words)))
            if v:
                it["plate"] = v
                log.info("차량번호: 원본 %d쪽에서 찾음", p["i"] + 1)
                return

    def _extract_3jong(self, G, C, it):
        ins_raw = ""
        if G is not None:
            img = rot(self.doc.render(G["i"], 250), G["rot"])
            cells = header_cells(img)
            if cells:
                it["contractor"] = clean_name(ocr_cell(self.eng, img, cells[0]))
                if not valid_name(it["contractor"]):
                    it["contractor"] = clean_name(ocr_cell(self.eng, img, cells[0], 0)) or it["contractor"]
                for th in (185, 0, 150, 215):
                    raw = ocr_cell(self.eng, img, cells[1], th)
                    if match_insurer(raw, self.alias)[1] >= 0.8:
                        ins_raw = raw
                        break
                    ins_raw = ins_raw or raw
            else:
                log.info("고지의무확인서 맨 위 칸을 못 찾음 p%d — 글자로 읽기", G["i"] + 1)
                W0, H0 = img.size
                lines0 = group_lines(self.eng.words(img.crop((0, 0, W0, int(H0 * .25)))))
                c0 = names_next_to(lines0, r"계\s*약\s*자", exclude_pat=r"피\s*보", page_w=W0)
                if c0:
                    it["contractor"] = pick(c0)
                for t0, _ in lines0:
                    m0 = re.search(r"보\s*험\s*사\s*명?\s*[:：]?\s*(.+)", t0)
                    if m0:
                        ins_raw = m0.group(1)
                        break
            body = rot(self.doc.render(G["i"], 200), G["rot"])
            W, H = body.size
            lines = "\n".join(t for t, _ in group_lines(self.eng.words(body.crop((0, int(H * .5), W, H)))))
            hits = roster_in_text(lines, self.roster)
            it["agent"] = hits[0] if len(hits) == 1 else regex_name(lines, ["보험설계사", "설계사"])
            if not valid_name(it["contractor"]):
                it["contractor"] = regex_name(lines, ["보험계약자", "계약자"]) or it["contractor"]
        ins_raw2 = ""
        if C is not None:
            img = rot(self.doc.render(C["i"], 250), C["rot"])
            W, H = img.size
            top = img.crop((0, int(H * .045), W, int(H * .14))).convert("L").point(lambda v: 255 if v > 200 else 0)
            for t, _ in group_lines(self.eng.words(top)):
                tt = t.replace(" ", "")
                if "회사" in tt and not ins_raw2:
                    ins_raw2 = re.split(r"[:：;]", t, 1)[-1]
                elif "상품" in tt and not it.get("product_hint"):
                    it["product_hint"] = short_product(re.split(r"[:：;]", t, 1)[-1])
            ins_d = self._insured(img)
            if ins_d is None:
                pass
            elif ins_d == "?" or not re.fullmatch(r"[가-힣]{3}|[A-Z][A-Z ]{3,25}", ins_d):
                it["warns"].append("피보험자 칸 확인")
            elif len(set(ins_d) & set(it["contractor"] or "")) >= 2:
                pass
            else:
                it["insured"] = ins_d
            if not valid_name(it["contractor"]):
                bot = img.crop((0, int(H * .78), W, int(H * .95)))
                txt = "\n".join(t for t, _ in group_lines(self.eng.words(bot)))
                it["contractor"] = regex_name(txt, [r"계\s*약\s*자"]) or it["contractor"]
        n1, s1 = match_insurer(ins_raw, self.alias)
        n2, s2 = match_insurer(ins_raw2, self.alias)
        it["ins"] = n1 if s1 >= s2 else n2
        if not it["ins"]:
            log.info("보험사 못 읽음: 고지='%s' 동의서='%s'", mask(ins_raw), mask(ins_raw2))
        if it["insured"] == it["contractor"]:
            it["insured"] = ""

    def _insured(self, img):
        """동의서 아래 표 '피보험자' 칸: 비어 있으면 None, 글씨가 있는데 못 읽으면 '?', 읽으면 이름."""
        W, H = img.size
        y0 = int(H * .78)
        words = self.eng.words(img.crop((0, y0, W, int(H * .95))))
        for t, ws in group_lines(words):
            lab = next((w for w in ws if "피보" in w.text and len(w.text) <= 6), None)
            if lab is None:
                continue
            sig = next((w for w in ws if w.x0 > lab.x1 and "서" in w.text), None)
            x1 = sig.x0 - 8 if sig else lab.x1 + W * .25
            box = (int(lab.x1 + 12), int(y0 + lab.y0 - 6), int(x1), int(y0 + lab.y1 + 6))
            if box[2] - box[0] < 20:
                return None
            g = np.asarray(img.crop(box).convert("L"))
            if (g < 150).mean() < 0.04:
                return None
            between = [w.text for w in ws if w.x0 > lab.x1 and (sig is None or w.x1 < sig.x0)]
            nm = clean_name(" ".join(between))
            return nm if valid_name(nm) else "?"
        return None

    def _read_page(self, p):
        cache = self.__dict__.setdefault("_rp_cache", {})
        if p["i"] in cache:
            return cache[p["i"]]
        r = self._read_page_raw(p)
        if len(cache) >= 4:
            cache.pop(next(iter(cache)))
        cache[p["i"]] = r
        return r

    def _read_page_raw(self, p):
        img = self.doc.render(p["i"], 200)
        words = self.eng.words(img)
        if kw_score_words(words) < 4:  # 거꾸로 스캔된 장은 돌려서 읽기만 함 (파일은 그대로)
            w2 = self.eng.words(img.rotate(180, expand=True))
            if kw_score_words(w2) > kw_score_words(words) + 3:
                return w2, img.rotate(180, expand=True)
        return words, img

    def _extract_app(self, grp, it):
        """청약서: 첫 장에서 읽고, 못 찾은 것만 두 번째 장에서 한 번 더."""
        pages = [p for p in grp if p["kind"] != "blank"][:2] or grp[:1]
        first_img = None
        all_lines = []
        if self.eng is not None:
            for n, p in enumerate(pages):
                words, img = self._read_page(p)
                first_img = first_img or img
                lines = group_lines(words)
                all_lines += lines
                log.info("청약서 %d쪽 읽은 내용(이름 가림):\n" % (n + 1) + "\n".join("    " + mask(t) for t, _ in lines))
                W = img.width
                full = "\n".join(join_split(t) for t, _ in lines)
                if self.mode == MODE_AUTO and not it.get("cat"):
                    it["cat"], sure = self._cat_from_text(full)
                    if not sure:
                        it["warns"].append("구분 확인")
                if not it["contractor"]:
                    c = [m.group(1) for m in re.finditer(r"([가-힣]{2,4})\s*님\s*을\s*위\s*한", full) if is_name(m.group(1))]
                    c += names_next_to(lines, r"계\s*약\s*자", exclude_pat=r"(피\s*보\s*[험혐]|대\s*리|전)", page_w=W)
                    it["contractor"] = pick(c)
                if not it["insured"]:
                    it["insured"] = pick(names_next_to(lines, r"피\s*보\s*[험혐]\s*자", page_w=W))
                if not it["agent"]:
                    hits = roster_in_text(full, self.roster)
                    hits = [h for h in hits if h not in (it["contractor"], it["insured"])]
                    a = agents_in_lines(lines, page_w=W)
                    a = [x for x in a if x not in (it["contractor"], it["insured"])]
                    it["agent"] = (hits[0] if len(hits) == 1 else
                                   next((h for h in hits if h in a), "") or snap_agent(pick(a), self.roster))
                if not it["ins"]:
                    nl = (it.get("cat") or self.cat) in ("자동차", "일반")
                    it["ins"], how = insurer_from_text(full, self.alias, nl)
                    if nl and it["ins"] and it["ins"] not in self.nonlife:
                        log.info("자동차·일반인데 생명보험사(%s)로 읽혀 버림", it["ins"])
                        it["ins"] = ""
                    if it["ins"]:
                        log.info("보험사: %s (%s)", it["ins"], how)
                        if how == "브랜드" and self.mode == MODE_AUTO and "구분 확인" in it["warns"]:
                            it["cat"] = CAT_CAR  # 자동차보험 브랜드(애니카·하이카 등)가 보이면 자동차
                            it["warns"].remove("구분 확인")
                            it["plate"] = it.get("plate") or plate_in_text(full)
                if not it.get("plate") and (it.get("cat") or self.cat) == CAT_CAR:
                    it["plate"] = plate_in_text(full)
                if not it.get("product_hint"):
                    m = re.search(r"상\s*품\s*명\s*[:：]?\s*(.+)", full)
                    if m:
                        it["product_hint"] = short_product(m.group(1))
                if it["contractor"] and it["agent"] and it["ins"] and (it.get("plate") or (it.get("cat") or self.cat) != CAT_CAR):
                    break
        if first_img is None:
            first_img = self.doc.render(pages[0]["i"], 200)
        if not it["ins"] and self.logos is not None and self.logos.ok:
            it["ins"], _ = self.logos.find(first_img)
            if it["ins"] and it["ins"] not in self.canon:
                it["ins"] = ""
        if it["insured"] == it["contractor"]:
            it["insured"] = ""


def kw_score_words(words):
    t = re.sub(r"\s", "", "".join(w.text for w in words))
    return sum(t.count(k) for k in KW)


# ------------------------------------------------------------------ 파일 이름
BAD = re.compile(r'[\\/:*?"<>|\r\n\t]')


def _safe(s):
    return BAD.sub("", (s or "").strip())


def item_prefix(it, mode, cat):
    """접두어: 3종 → 3종 / 청약서 → 장기·자동차·일반 / 청약서+3종 → 장기3종·자동차3종·일반3종"""
    if it.get("kind"):
        return it["kind"]
    m = it.get("mode") or mode
    c = it.get("cat") or cat or CAT_LONG
    return "3종" if m == MODE_3 else (c if m == MODE_APP else c + "3종")


def make_names(items, mode, cat):
    """파일 이름: 접두어_보험사_취급자_계약자[_피보험자][_차량번호][_상품명][_구][_장수]"""
    names, used = [], {}
    for it in items:
        pre = item_prefix(it, mode, cat)
        parts = [pre, it.get("ins") or "보험사", it.get("agent") or "취급자", it.get("contractor") or "계약자"]
        ins_d = (it.get("insured") or "").strip()
        if ins_d and ins_d != it.get("contractor"):
            parts.append(ins_d)
        if pre.startswith("자동차") and (it.get("plate") or "").strip():
            parts.append(it["plate"].strip())
        if (it.get("product") or "").strip():
            parts.append(it["product"])
        if it.get("ver") == "구" and pre in ("3종", "장기3종"):
            parts.append("구")
        if pre.endswith("3종") and pre != "3종":
            parts.append(str(it.get("count") or len(it.get("pages", []))))
        nm = "_".join(p for p in (_safe(x) for x in parts) if p)
        n = used.get(nm, 0) + 1
        used[nm] = n
        names.append(nm + (f"({n})" if n > 1 else "") + ".pdf")
    return names


def unique_path(folder, name):
    p = os.path.join(folder, name)
    if not os.path.exists(p):
        return p
    stem, ext = os.path.splitext(name)
    k = 2
    while os.path.exists(os.path.join(folder, f"{stem}({k}){ext}")):
        k += 1
    return os.path.join(folder, f"{stem}({k}){ext}")
