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
CAT_LONG = "장기"

KW = ["보험", "계약", "확인", "설명", "상품", "동의", "서명", "보장", "해지", "가입", "청약",
      "피보험자", "보험료", "고객", "내용", "금융", "소비자", "기간", "납입", "정보", "비교"]


# ------------------------------------------------------------------ 보험사 이름
def load_insurers():
    import sys
    p = os.path.join(os.path.dirname(sys.executable), "insurers.json")  # exe 옆에 있으면 그걸 우선 사용
    if not (getattr(sys, "frozen", False) and os.path.exists(p)):
        p = os.path.join(HERE, "insurers.json")
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    canon, alias = [], {}
    for grp in ("생명보험", "손해보험"):
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
    if dens < 0.012:
        return "blank", 0, dens
    return "X", 0, dens


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


# ------------------------------------------------------------------ 칸 제목 옆 이름 찾기
_SKIP_TOK = re.compile(r"^[:：.;,()\[\]|·ㆍ\-]*(명|성명|이름|성 명|\(성명\)|\(인\))?[:：.;,()\[\]|·ㆍ\-]*$")
_LABEL_TOK = re.compile(r"(계약자|피보험자|보험자|설계사|모집인|모집자|취급자|판매자|담당자|수익자|성명|주민|생년|관계|연락처|주소|직업)")
_STOP2 = STOP | {"피보험자", "계약자", "설계사", "모집인", "모집자", "취급자", "판매자", "담당자", "수익자", "보험자"}


def _first_name_token(tokens):
    """칸 제목 뒤 단어들 → (이름, 상태). 상태: 'name' / 'label'(다른 칸 제목이 바로 옴) / 'none'(비어 있음) / 'other'"""
    for t in tokens[:4]:
        t = t.strip()
        if not t or _SKIP_TOK.match(t):
            continue
        t2 = re.sub(r"[\(:：].*$", "", t)  # '홍길동(서명)' → '홍길동'
        t2 = re.sub(r"[^가-힣A-Za-z]+$", "", t2)  # 끝의 점·따옴표 제거
        t2 = re.sub(r"^[^가-힣A-Za-z]+", "", t2)
        t2 = re.sub(r"(님|께|씨)$", "", t2)
        if _LABEL_TOK.search(t2):
            return "", "label"
        if re.fullmatch(r"[가-힣]{2,4}", t2) and t2 not in _STOP2 and not any(t2.startswith(s) for s in STOP) \
                and t2[0] not in "는의을를와과은":
            return t2, "name"
        if re.fullmatch(r"[A-Z][A-Z ]{2,25}", t2):
            return t2, "name"
        return "", "other"  # 칸 제목 바로 뒤가 이름이 아니면 포기 (엉뚱한 단어 방지)
    return "", "none"


def names_next_to(lines, label_pat, exclude_pat=None):
    """칸 제목(예: 계약자) 바로 오른쪽 → 오른쪽이 비었거나 다른 칸 제목이면 바로 아래 줄에서 이름 찾기."""
    out = []
    lab_re = re.compile(label_pat)
    for k, (text, words) in enumerate(lines):
        for m in lab_re.finditer(text):
            before = text[:m.start()]
            if exclude_pat and re.search(exclude_pat + r"\s*$", before):
                continue
            after = text[m.end():]
            if re.match(r"\s*(와|과|의|가|는|및|에|로)", after):
                continue  # '계약자와 피보험자의 관계' 같은 문장
            n, state = _first_name_token(after.split())
            if n:
                out.append(n)
                continue
            if state == "other":
                continue
            # 바로 아래 줄: 제목과 비슷한 가로 위치의 단어
            pos = len(before.replace(" ", ""))
            acc, x0, x1 = 0, None, None
            for w in words:
                if acc >= pos and x0 is None:
                    x0 = w.x0
                acc += len(w.text)
                if x0 is not None and acc >= pos + len(m.group(0).replace(" ", "")):
                    x1 = w.x1
                    break
            if x0 is None:
                continue
            x1 = x1 or x0 + 200
            h = max(w.h for w in words)
            for text2, words2 in lines[k + 1:k + 3]:
                if words2[0].cy - words[0].cy > 3.5 * h:
                    break
                near_w = [w for w in words2 if w.x1 > x0 - h and w.x0 < x1 + 2 * h]
                near = group_lines(near_w)[0][0].split() if near_w else []
                n, _ = _first_name_token(near)
                if n:
                    out.append(n)
                    break
    return out


def pick(c):
    return max(c, key=lambda n: (c.count(n), -c.index(n))) if c else ""


# ------------------------------------------------------------------ 본 처리
class Analyzer:
    def __init__(self, doc, mode, cat, engine, last_agent="", progress=None, logos=None):
        self.doc, self.mode, self.cat, self.eng = doc, mode, cat, engine
        self.last_agent = last_agent
        self.progress = progress or (lambda *a: None)
        self.canon, self.alias = load_insurers()
        self.logos = logos

    @property
    def is_long(self):
        return self.cat == CAT_LONG

    # 1) 페이지마다 종류/회전 (색깔 + 제목 글자 확인)
    def scan_pages(self):
        n = self.doc.count
        pages = []
        for i in range(n):
            self.progress(i, n * 2, f"{n}장 중 {i + 1}장 살펴보는 중")
            img = self.doc.render(i, 75)
            kind, r, dens = classify(img)
            info = {"i": i, "kind": kind, "rot": r, "dens": round(dens, 4)}
            if kind in ("G", "C") and self.mode != MODE_APP:
                info["kind"] = self._confirm_title(i, kind, r)
            pages.append(info)
        return pages

    def _confirm_title(self, i, kind, r):
        """색깔로 찾은 3종서류 후보의 맨 위 제목을 읽어서 한 번 더 확인."""
        if self.eng is None:
            return kind
        try:
            img = rot(self.doc.render(i, 110), r)
            W, H = img.size
            t = re.sub(r"\s", "", "".join(w.text for w in self.eng.words(img.crop((0, 0, W, int(H * .13))))))
            if len(re.findall(r"[가-힣]", t)) < 4:
                return kind  # 거의 못 읽었으면 색깔 판단을 믿음
            ok = (("고지" in t or "계약체결" in t or "금융소비자" in t) if kind == "G"
                  else ("신용" in t or "동의서" in t or "개인" in t))
            if not ok:
                log.info("p%d: 색은 %s 같지만 제목이 달라서 제외 (%s)", i + 1, kind, mask(t[:40]))
            return kind if ok else "X"
        except Exception as e:
            log.warning("제목 확인 실패 p%d: %s", i + 1, e)
            return kind

    def _is_long_b(self, p):
        """장기 비교설명서(가로로 누운 양식)인지: 옆으로 돌렸을 때 글자가 더 잘 읽히면 맞음."""
        if self.eng is None or p["kind"] != "X":
            return None
        try:
            g = self.doc.render(p["i"], 75).convert("L")
            s0 = kw_score(self.eng, g)
            s1 = max(kw_score(self.eng, g.rotate(-90, expand=True)), kw_score(self.eng, g.rotate(90, expand=True)))
            return s1 > s0 + 2
        except Exception as e:
            log.warning("비교설명서 판단 실패 p%d: %s", p["i"] + 1, e)
            return None

    # 2) 건별로 묶기
    def group(self, pages):
        if self.mode == MODE_APP:
            return [pages]
        groups, cur = [], []
        for p in pages:
            cur.append(p)
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
    def run(self):
        pages = self.scan_pages()
        groups = self.group(pages)
        items = []
        for k, grp in enumerate(groups):
            self.progress(self.doc.count + (k + 1) * self.doc.count // max(1, len(groups)), self.doc.count * 2,
                          f"{len(groups)}건 중 {k + 1}번째 건 이름 읽는 중")
            try:
                it = self.extract(grp)
            except Exception:
                log.exception("추출 실패")
                it = self.blank_item(grp)
                it["warns"].append("읽기 오류")
            it["no"] = k + 1
            items.append(it)
        agents = [it["agent"] for it in items if it["agent"]]
        common = max(set(agents), key=agents.count) if agents else self.last_agent
        for it in items:
            if not it["agent"] and common:
                it["agent"] = common
        for it in items:
            log.info("No.%d %s장 [%s] 버전=%s 보험사=%s 취급자=%s 계약자=%s 피보험자=%s 경고=%s",
                     it["no"], it["count"], "".join(p["kind"][0] for p in it["pages"]), it["ver"] or "-",
                     it["ins"] or "(못읽음)", "읽음" if it["agent"] else "(없음)",
                     "읽음" if it["contractor"] else "(못읽음)", "있음" if it["insured"] else "-",
                     ",".join(it["warns"]) or "-")
        return pages, items

    def blank_item(self, grp):
        return {"pages": [{"i": p["i"], "rot": p["rot"], "kind": p["kind"]} for p in grp],
                "ver": "", "ins": "", "agent": "", "contractor": "", "insured": "", "product": "",
                "count": len(grp), "warns": []}

    def extract(self, grp):
        it = self.blank_item(grp)
        kinds = [p["kind"] for p in grp]
        nblank = kinds.count("blank")
        if nblank:
            it["warns"].append(f"빈 장 같아요 ({nblank}장)")
        if self.mode == MODE_APP:
            self._extract_app(grp, it)
            return it

        G = next((p for p in grp if p["kind"] == "G"), None)
        C = next((p for p in reversed(grp) if p["kind"] == "C"), None)
        if G is None:
            it["warns"].append("고지의무확인서 빠짐")
        if C is None:
            it["warns"].append("동의서 빠짐")

        # --- 비교설명서 장수 / 버전
        before_c = []  # 동의서 바로 앞의 장들 (빈 장 제외, 가까운 순)
        if C is not None:
            j = grp.index(C) - 1
            while j >= 0 and len(before_c) < 3:
                if grp[j]["kind"] == "X":
                    before_c.append(grp[j])
                elif grp[j]["kind"] != "blank":
                    break
                j -= 1
        if self.mode == MODE_3:
            nb = kinds.count("X")
            if self.is_long:
                if nb == 2:
                    it["ver"] = "신"
                elif nb == 1:
                    it["ver"] = "구"
                elif nb == 0:
                    it["warns"].append("비교설명서 빠짐")
                else:
                    it["warns"].append(f"장수 확인 ({len(grp)}장)")
            else:
                if nb == 0:
                    it["warns"].append("비교설명서 빠짐")
                elif nb > 1:
                    it["warns"].append(f"장수 확인 ({len(grp)}장, 3장이어야 해요)")
        else:  # 청약서+3종
            if C is not None and not before_c:
                it["warns"].append("비교설명서 빠짐")
            if self.is_long and before_c:
                b1 = self._is_long_b(before_c[0])
                b2 = self._is_long_b(before_c[1]) if len(before_c) > 1 else False
                if b1 is None:
                    pass  # 판단 불가 → 확인 화면에서 '버전 확인'
                elif b1 and b2:
                    it["ver"] = "신"
                elif b1:
                    it["ver"] = "구"
                else:
                    it["warns"].append("비교설명서 확인")
            n3 = 3 if not self.is_long else (4 if it["ver"] == "신" else 3)
            if len(grp) - nblank <= n3:
                it["warns"].append("청약서 없음?")

        if self.eng is None:
            return it
        self._extract_3jong(G, C, it)
        return it

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
                log.info("고지의무확인서 맨 위 칸을 못 찾음 p%d", G["i"] + 1)
            body = rot(self.doc.render(G["i"], 200), G["rot"])
            W, H = body.size
            lines = "\n".join(t for t, _ in group_lines(self.eng.words(body.crop((0, int(H * .5), W, H)))))
            it["agent"] = regex_name(lines, ["보험설계사", "설계사"])
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
                elif "상품" in tt and not it["product"]:
                    it["product"] = short_product(re.split(r"[:：;]", t, 1)[-1])
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
            log.info("보험사 못 읽음: 고지='%s' 동의서='%s'", ins_raw, ins_raw2)
        if it["insured"] == it["contractor"]:
            it["insured"] = ""
        if it["insured"]:
            it["warns"].append("피보험자 확인")

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

    def _extract_app(self, grp, it):
        """청약서: 첫 장만 읽기. 계약자·피보험자 칸 바로 옆 이름, 보험사는 글자 → 로고 순서."""
        first = next((p for p in grp if p["kind"] != "blank"), grp[0])
        img = self.doc.render(first["i"], 200)
        if self.eng is not None:
            words = self.eng.words(img)
            if kw_score_words(words) < 4:  # 거꾸로 스캔됐는지 확인
                w2 = self.eng.words(img.rotate(180, expand=True))
                if kw_score_words(w2) > kw_score_words(words) + 3:
                    words, img = w2, img.rotate(180, expand=True)
                    for p in it["pages"]:
                        if p["i"] == first["i"]:
                            p["rot"] = 180
            lines = group_lines(words)
            log.info("청약서 첫 장 읽은 내용(이름 가림):\n" + "\n".join("    " + mask(t) for t, _ in lines))
            c = names_next_to(lines, r"계\s*약\s*자", exclude_pat=r"(피\s*보\s*험|대\s*리)")
            i_ = names_next_to(lines, r"피\s*보\s*험\s*자")
            a = names_next_to(lines, r"(설\s*계\s*사|모\s*집\s*인|모\s*집\s*자|취\s*급\s*자|판\s*매\s*자|담\s*당\s*자)")
            it["contractor"], it["insured"], it["agent"] = pick(c), pick(i_), pick(a)
            full = "\n".join(t for t, _ in lines)
            it["ins"] = find_insurer_in_text(full, self.alias)
            m = re.search(r"상\s*품\s*명\s*[:：]?\s*(.+)", full)
            if m:
                it["product"] = short_product(m.group(1))
            log.info("청약서 결과: 계약자후보 %d개, 피보험자후보 %d개, 취급자후보 %d개, 보험사(글자)=%s",
                     len(c), len(i_), len(a), it["ins"] or "-")
        if not it["ins"] and self.logos is not None and self.logos.ok:
            it["ins"], _ = self.logos.find(img)
        if it["insured"] == it["contractor"]:
            it["insured"] = ""


def kw_score_words(words):
    t = re.sub(r"\s", "", "".join(w.text for w in words))
    return sum(t.count(k) for k in KW)


# ------------------------------------------------------------------ 파일 이름
BAD = re.compile(r'[\\/:*?"<>|\r\n\t]')


def _safe(s):
    return BAD.sub("", (s or "").strip())


def make_names(items, mode, cat):
    prefix = [cat or "장기"] if mode == MODE_APP else ["3종", cat or "장기"]
    base = []
    for it in items:
        parts = prefix + [it.get("ins") or "보험사", it.get("agent") or "취급자", it.get("contractor") or "계약자"]
        ins_d = (it.get("insured") or "").strip()
        if ins_d and ins_d != it.get("contractor"):
            parts.append(ins_d)
        base.append([_safe(p) for p in parts])
    keys = ["_".join(b) for b in base]
    names, used = [], {}
    for it, b, k in zip(items, base, keys):
        parts = list(b)
        if keys.count(k) > 1 and it.get("product"):
            parts.append(_safe(it["product"]))
        if it.get("ver") == "구" and cat == CAT_LONG:
            parts.append("구")
        if mode == MODE_MIX:
            parts.append(str(it.get("count") or len(it.get("pages", []))))
        nm = "_".join(p for p in parts if p)
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
