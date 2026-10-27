"""3종서류 자동 분할 — 프로그램 시작 파일."""
import base64
import json
import logging
import os
import sys
import threading
import traceback

FROZEN = getattr(sys, "frozen", False)
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
EXE_DIR = os.path.dirname(sys.executable) if FROZEN else HERE
sys.path.insert(0, HERE)

APPDIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "3종서류자동분할")
os.makedirs(APPDIR, exist_ok=True)
LOGFILE = os.path.join(APPDIR, "log.txt")
try:  # 기록이 너무 커지면 예전 기록으로 돌림
    if os.path.getsize(LOGFILE) > 5 * 1024 * 1024:
        os.replace(LOGFILE, os.path.join(APPDIR, "log_old.txt"))
except OSError:
    pass
APP_VERSION = "v1.4"
APP_DATE = "2026.10.27"
logging.basicConfig(filename=os.path.join(APPDIR, "log.txt"), level=logging.INFO, encoding="utf-8",
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

import core  # noqa: E402
import ocr  # noqa: E402
import pdfio  # noqa: E402
import logos  # noqa: E402

SETTINGS = os.path.join(APPDIR, "settings.json")


def _desktop_dir():
    """바탕화면 경로 (OneDrive 바탕화면 포함)."""
    try:
        import ctypes
        from ctypes import wintypes
        import uuid
        fid = uuid.UUID("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")  # FOLDERID_Desktop

        class GUID(ctypes.Structure):
            _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]
        g = GUID(fid.fields[0], fid.fields[1], fid.fields[2], (ctypes.c_ubyte * 8)(*fid.bytes[8:]))
        p = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) == 0:
            d = p.value
            ctypes.windll.ole32.CoTaskMemFree(p)
            if d and os.path.isdir(d):
                return d
    except Exception:
        pass
    for d in (os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop"), os.path.join(os.path.expanduser("~"), "Desktop")):
        if os.path.isdir(d):
            return d
    return os.path.expanduser("~")


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(s):
    try:
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
    except Exception:
        log.exception("설정 저장 실패")


_window = None  # pywebview 창 (Api 속성으로 두면 화면 쪽에 노출되므로 따로 보관)


class Api:
    def __init__(self, first_files=None):
        self._s = load_settings()
        self._docs = []
        self._ans = []
        self._paths = list(first_files or [])
        self._job = {"running": False, "done": 0, "total": 1, "msg": "", "finished": False, "error": ""}
        self._items, self._mode, self._cat = [], core.MODE_3, ""
        self._engine = None
        self._engine_note = ""
        self._engine_lock = threading.Lock()

    # ---------- 시작 화면
    def init(self):
        canon, _ = core.load_insurers()
        return {"version": APP_VERSION + " · " + APP_DATE, "out_dir": self._s.get("out_dir") or "", "first_files": self._paths,
                "insurers": canon, "mode": self._s.get("mode") or "", "cat": self._s.get("cat") or "",
                "pv_width": self._s.get("pv_width") or "", "zoom": self._s.get("zoom") or "w",
                "agents": self._s.get("agents") or []}

    def set_pref(self, key, value):
        if key in ("pv_width", "zoom"):
            self._s[key] = value
            save_settings(self._s)
        return True

    def set_agents(self, names):
        clean = []
        for n in names or []:
            n = (n or "").strip()
            if n and n not in clean:
                clean.append(n)
        self._s["agents"] = clean
        save_settings(self._s)
        return clean

    def page_count(self, path):
        try:
            return pdfio.Doc(path).count
        except Exception:
            return 0

    def export_log(self):
        """기록 파일을 바탕화면에 '오류기록_날짜시간.txt'로 저장."""
        import datetime
        try:
            desk = _desktop_dir()
            name = "오류기록_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".txt"
            out = os.path.join(desk, name)
            data = b""
            if os.path.exists(LOGFILE):
                with open(LOGFILE, "rb") as f:
                    f.seek(0, 2)
                    size = f.tell()
                    f.seek(max(0, size - 3 * 1024 * 1024))  # 최근 3MB
                    data = f.read()
            head = ("PDF 분할·파일명 작성기 오류 기록\n버전: %s (%s)\n저장 시각: %s\n(고객 이름은 가려져 있습니다)\n\n"
                    % (APP_VERSION, APP_DATE, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))).encode("utf-8")
            with open(out, "wb") as f:
                f.write(head + data)
            log.info("오류 기록 저장: %s", name)
            return {"ok": True, "name": name, "folder": desk}
        except Exception as e:
            log.exception("오류 기록 저장 실패")
            return {"ok": False, "msg": str(e)}

    def reread(self, items):
        """화면에서 순서 변경·나누기·합치기 한 건 다시 읽기."""
        out = []
        for it in items:
            src = int(it.get("src", 0))
            an = self._ans[src]
            new = an.reread(it["pages"])
            new["src"], new["file"] = src, it.get("file", "")
            new["product"] = it.get("product", "")
            new["skip"] = it.get("skip", False)
            new["warns"] = [w for w in new["warns"] if w != "동일상품 확인"]
            out.append(new)
        return out

    def open_log(self):
        try:
            os.startfile(APPDIR)  # noqa (윈도우 전용)
        except Exception:
            log.exception("기록 폴더 열기 실패")

    def _logos(self):
        if getattr(self, "_lm", None) is None:
            _, alias = core.load_insurers()
            self._lm = logos.LogoMatcher([os.path.join(HERE, "logos"), os.path.join(EXE_DIR, "로고")], alias)
        return self._lm

    def choose_file(self):
        import webview
        kind = getattr(webview, "OPEN_DIALOG", 10)
        try:
            kind = webview.FileDialog.OPEN  # pywebview 5.1 이상
        except Exception:
            pass
        r = _window.create_file_dialog(kind, allow_multiple=True, file_types=("PDF 파일 (*.pdf)",))
        if r:
            self._paths = list(r) if isinstance(r, (list, tuple)) else [r]
            return self._paths
        return []

    def choose_folder(self):
        import webview
        kind = getattr(webview, "FOLDER_DIALOG", 20)
        try:
            kind = webview.FileDialog.FOLDER
        except Exception:
            pass
        r = _window.create_file_dialog(kind, directory=self._s.get("out_dir") or "")
        if r:
            d = r[0] if isinstance(r, (list, tuple)) else r
            self._s["out_dir"] = d
            save_settings(self._s)
            return d
        return ""

    def set_dropped(self, paths):
        self._paths = list(paths)
        return self._paths

    # ---------- 처리
    def _get_engine(self):
        with self._engine_lock:
            if self._engine is None and not self._engine_note:
                self._engine, why = ocr.get_engine()
                if self._engine is None:
                    self._engine_note = why or "글자인식 없음"
            return self._engine

    def start(self, paths, mode, cat):
        if isinstance(paths, str):
            paths = [paths]
        paths = [p for p in (paths or self._paths) if p]
        if not paths:
            return {"ok": False, "msg": "PDF 파일을 추가하십시오."}
        bad = [os.path.basename(p) for p in paths if not p.lower().endswith(".pdf")]
        if bad:
            return {"ok": False, "msg": "PDF 파일만 추가할 수 있습니다: " + ", ".join(bad)}
        miss = [os.path.basename(p) for p in paths if not os.path.exists(p)]
        if miss:
            return {"ok": False, "msg": "파일을 찾을 수 없습니다: " + ", ".join(miss)}
        if mode == core.MODE_AUTO:
            cat = ""
        elif mode not in (core.MODE_3, core.MODE_APP, core.MODE_MIX) or not cat:
            return {"ok": False, "msg": "상품 구분과 서류 종류를 선택하십시오."}
        self._paths, self._mode, self._cat = paths, mode, cat
        log.info("시작: 상품구분=%s 서류종류=%s 파일 %d개", cat, mode, len(paths))
        self._s.update({"mode": mode, "cat": cat})
        save_settings(self._s)
        self._job = {"running": True, "done": 0, "total": 1, "msg": "준비 중", "finished": False, "error": ""}
        threading.Thread(target=self._work, daemon=True).start()
        return {"ok": True}

    def _work(self):
        try:
            self._job["msg"] = "문서 분석 중…"
            eng = self._get_engine()
            for d in self._docs:
                d.close()
            self._docs = []
            self._ans = []
            items = []
            nf = len(self._paths)
            lm = self._logos() if self._mode in (core.MODE_APP, core.MODE_AUTO) else None
            for k, path in enumerate(self._paths):
                doc = pdfio.Doc(path)
                self._docs.append(doc)

                def prog(d, n, m, k=k):
                    pre = f"[파일 {k + 1}/{nf}] " if nf > 1 else ""
                    self._job.update({"done": k * 1000 + int(1000 * d / max(1, n)), "total": nf * 1000,
                                      "msg": pre + m})

                log.info("파일 %d/%d: %s (%d장)", k + 1, nf, core.mask(os.path.basename(path)), doc.count)
                an = core.Analyzer(doc, self._mode, self._cat, eng, progress=prog, logos=lm,
                                   roster=self._s.get("agents") or [])
                _, its = an.run()
                self._ans.append(an)
                for it in its:
                    it["src"] = k
                    it["file"] = os.path.basename(path)
                items.extend(its)
            for n, it in enumerate(items, 1):
                it["no"] = n
            keys = [(it["contractor"], it["insured"], it["ins"]) for it in items]
            for it, kk in zip(items, keys):
                w = [x for x in it["warns"] if x != "동일상품 확인"]
                if kk[0] and kk[2] and keys.count(kk) > 1:
                    w.append("동일상품 확인")
                it["warns"] = w
            self._items = items
            log.info("처리 완료: 파일 %d개, %d건, 엔진=%s", nf, len(items), eng and eng.name)
            self._job.update({"finished": True, "running": False, "done": 1, "total": 1})
        except Exception as e:
            log.exception("처리 실패")
            self._job.update({"finished": True, "running": False, "error": f"{e}"})

    def progress(self):
        return self._job

    def result(self):
        return {"items": self._items, "names": self.names(self._items), 
                "mode": self._mode, "cat": self._cat, "files": [os.path.basename(p) for p in self._paths],
                "ocr": (self._engine.name if self._engine else ""), "ocr_note": self._engine_note}

    def names(self, items):
        """뺀 건은 겹침 계산에서 제외하고, 줄마다 저장될 이름을 돌려줌."""
        active = [k for k, it in enumerate(items) if not it.get("skip")]
        nm = core.make_names([items[k] for k in active], self._mode, self._cat)
        out = [core.make_names([it], self._mode, self._cat)[0] for it in items]
        for k, n in zip(active, nm):
            out[k] = n
        return out

    def page(self, src, i, width):
        """미리보기: 스캔한 방향 그대로 (자동 회전 없음)."""
        img = self._docs[int(src)].render(int(i), 50 if width <= 160 else (110 if width <= 700 else 200))
        if img.width > width:
            img = img.resize((int(width), int(img.height * width / img.width)))
        return "data:image/jpeg;base64," + base64.b64encode(pdfio.to_jpeg_bytes(img)).decode()

    # ---------- 저장
    def save(self, items):
        out = self._s.get("out_dir") or ""
        if not out:
            return {"ok": False, "msg": "저장 경로를 먼저 지정하십시오."}
        os.makedirs(out, exist_ok=True)
        items = [it for it in items if not it.get("skip") and any(not pg.get("off") for pg in it["pages"])]
        names = core.make_names(items, self._mode, self._cat)
        saved, errors = [], []
        for it, nm in zip(items, names):
            try:
                p = core.unique_path(out, nm)
                pdfio.save_pages(self._paths[it.get("src", 0)], [(pg["i"], 0) for pg in it["pages"] if not pg.get("off")], p)
                saved.append(os.path.basename(p))
            except PermissionError:
                errors.append(f"{nm}: 같은 이름의 파일이 다른 프로그램에서 열려 있습니다")
            except Exception as e:
                log.exception("저장 실패")
                errors.append(f"{nm}: {e}")
        return {"ok": not errors, "saved": saved, "errors": errors, "folder": out}

    def open_folder(self):
        d = self._s.get("out_dir")
        if d and os.path.isdir(d):
            os.startfile(d)  # noqa (윈도우 전용)


_out = []


def _p(*a):
    s = " ".join(str(x) for x in a)
    _out.append(s)
    try:
        print(s)
    except Exception:
        pass


def selftest():
    print = _p  # noqa
    print("== PDF 분할·파일명 작성기: 점검 ==")
    print("파이썬:", sys.version.split()[0])
    for m in ("webview", "fitz", "pypdf", "PIL", "numpy"):
        try:
            __import__(m)
            print(f"[OK] {m}")
        except Exception as e:
            print(f"[실패] {m}: {e}")
    eng, why = ocr.get_engine()
    if eng is None:
        print("[주의] 글자인식을 쓸 수 없어요 → 이름은 직접 입력해야 해요.", why)
    else:
        print("[OK] 글자인식:", eng.name)
        try:
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new("RGB", (600, 120), "white")
            d = ImageDraw.Draw(img)
            f = None
            for fp in (r"C:\Windows\Fonts\malgun.ttf",):
                if os.path.exists(fp):
                    f = ImageFont.truetype(fp, 48)
            d.text((20, 30), "계약자 홍길동", fill="black", font=f)
            print("   시험 글자 읽기 결과:", ocr.text_of(eng, img))
        except Exception:
            traceback.print_exc()
    print("기록 파일:", os.path.join(APPDIR, "log.txt"))
    try:
        with open(os.path.join(EXE_DIR, "selftest.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(_out))
    except Exception:
        pass


def _close_splash():
    try:
        import pyi_splash  # exe로 실행할 때만 있음
        pyi_splash.close()
    except Exception:
        pass


def main():
    log.info("프로그램 시작 (exe=%s, 버전=%s)", FROZEN, APP_VERSION)
    if "--selftest" in sys.argv:
        _close_splash()
        selftest()
        return
    import webview
    first = [a for a in sys.argv[1:] if a.lower().endswith(".pdf")]
    api = Api(first)
    global _window
    _window = webview.create_window("PDF 분할·파일명 작성기", url=os.path.join(HERE, "ui", "index.html"),
                                    js_api=api, width=1320, height=860, min_size=(1100, 700),
                                    maximized=True)

    def on_loaded(*_):
        _close_splash()
        log.info("화면 열림")
        try:  # 끌어다 놓기 (pywebview 5 이상)
            from webview.dom import DOMEventHandler

            def on_drop(e):
                try:
                    files = e.get("dataTransfer", {}).get("files", [])
                    paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
                    if paths:
                        api.set_dropped(paths)
                        _window.evaluate_js(f"window.onPicked({json.dumps(paths)})")
                except Exception:
                    log.exception("drop 처리 실패")

            _window.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, True)
            _window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
        except Exception:
            log.exception("끌어다 놓기 연결 실패 — 파일 선택 버튼은 사용 가능")
        threading.Thread(target=api._get_engine, daemon=True).start()  # 미리 준비

    _window.events.loaded += on_loaded
    webview.start(debug="--debug" in sys.argv)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("프로그램 오류")
        _close_splash()
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"프로그램 실행 중 오류가 발생했습니다.\n\n{e}\n\n기록 파일: {APPDIR}\\log.txt",
                                             "3종서류 자동 분할", 0x10)
        except Exception:
            pass
        raise
