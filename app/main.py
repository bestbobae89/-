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
logging.basicConfig(filename=os.path.join(APPDIR, "log.txt"), level=logging.INFO, encoding="utf-8",
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

import core  # noqa: E402
import ocr  # noqa: E402
import pdfio  # noqa: E402

SETTINGS = os.path.join(APPDIR, "settings.json")


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
    def __init__(self, first_file=None):
        self._s = load_settings()
        self._doc = None
        self._path = first_file
        self._job = {"running": False, "done": 0, "total": 1, "msg": "", "finished": False, "error": ""}
        self._items, self._mode, self._cat = [], core.MODE_3, ""
        self._engine = None
        self._engine_note = ""
        self._engine_lock = threading.Lock()

    # ---------- 시작 화면
    def init(self):
        canon, _ = core.load_insurers()
        return {"out_dir": self._s.get("out_dir") or "", "first_file": self._path or "",
                "insurers": canon, "mode": self._s.get("mode") or core.MODE_3, "cat": self._s.get("cat") or ""}

    def choose_file(self):
        import webview
        kind = getattr(webview, "OPEN_DIALOG", 10)
        try:
            kind = webview.FileDialog.OPEN  # pywebview 5.1 이상
        except Exception:
            pass
        r = _window.create_file_dialog(kind, file_types=("PDF 파일 (*.pdf)",))
        if r:
            self._path = r[0] if isinstance(r, (list, tuple)) else r
            return self._path
        return ""

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

    def set_dropped(self, path):
        self._path = path
        return path

    # ---------- 처리
    def _get_engine(self):
        with self._engine_lock:
            if self._engine is None and not self._engine_note:
                self._engine, why = ocr.get_engine()
                if self._engine is None:
                    self._engine_note = why or "글자인식 없음"
            return self._engine

    def start(self, path, mode, cat):
        path = path or self._path
        if not path or not os.path.exists(path):
            return {"ok": False, "msg": "PDF 파일을 찾을 수 없어요."}
        if not path.lower().endswith(".pdf"):
            return {"ok": False, "msg": "PDF 파일만 넣을 수 있어요."}
        self._path, self._mode, self._cat = path, mode, cat
        self._s.update({"mode": mode, "cat": cat})
        save_settings(self._s)
        self._job = {"running": True, "done": 0, "total": 1, "msg": "준비 중", "finished": False, "error": ""}
        threading.Thread(target=self._work, daemon=True).start()
        return {"ok": True}

    def _work(self):
        try:
            self._job["msg"] = "글자인식 준비 중"
            eng = self._get_engine()
            if self._doc is not None:
                self._doc.close()
            self._doc = pdfio.Doc(self._path)

            def prog(d, n, m):
                self._job.update({"done": d, "total": max(1, n), "msg": m})

            an = core.Analyzer(self._doc, self._mode, self._cat, eng,
                               last_agent=self._s.get("last_agent", ""), progress=prog)
            _, items = an.run()
            self._items = items
            log.info("처리 완료: %s, %d건, 엔진=%s", self._path, len(items), eng and eng.name)
            self._job.update({"finished": True, "running": False, "done": 1, "total": 1})
        except Exception as e:
            log.exception("처리 실패")
            self._job.update({"finished": True, "running": False, "error": f"{e}"})

    def progress(self):
        return self._job

    def result(self):
        return {"items": self._items, "names": core.make_names(self._items, self._mode, self._cat),
                "mode": self._mode, "cat": self._cat, "file": os.path.basename(self._path or ""),
                "ocr": (self._engine.name if self._engine else ""), "ocr_note": self._engine_note}

    def names(self, items):
        return core.make_names(items, self._mode, self._cat)

    def page(self, i, rot, width):
        img = self._doc.render(int(i), 50 if width <= 160 else (110 if width <= 700 else 200))
        if rot:
            img = img.rotate(int(rot), expand=True)
        if img.width > width:
            img = img.resize((int(width), int(img.height * width / img.width)))
        return "data:image/jpeg;base64," + base64.b64encode(pdfio.to_jpeg_bytes(img)).decode()

    # ---------- 저장
    def save(self, items):
        out = self._s.get("out_dir") or ""
        if not out:
            return {"ok": False, "msg": "저장 위치를 먼저 정해주세요."}
        os.makedirs(out, exist_ok=True)
        names = core.make_names(items, self._mode, self._cat)
        saved, errors = [], []
        for it, nm in zip(items, names):
            try:
                p = core.unique_path(out, nm)
                pdfio.save_pages(self._path, [(pg["i"], pg.get("rot", 0)) for pg in it["pages"]], p)
                saved.append(os.path.basename(p))
            except PermissionError:
                errors.append(f"{nm}: 같은 이름의 파일이 열려 있어요")
            except Exception as e:
                log.exception("저장 실패")
                errors.append(f"{nm}: {e}")
        agents = [it.get("agent") for it in items if it.get("agent")]
        if agents:
            self._s["last_agent"] = max(set(agents), key=agents.count)
            save_settings(self._s)
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
    print("== 3종서류 자동 분할: 점검 ==")
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


def main():
    if "--selftest" in sys.argv:
        selftest()
        return
    import webview
    first = next((a for a in sys.argv[1:] if a.lower().endswith(".pdf")), None)
    api = Api(first)
    global _window
    _window = webview.create_window("3종서류 자동 분할", url=os.path.join(HERE, "ui", "index.html"),
                                    js_api=api, width=1320, height=860, min_size=(1100, 700))

    def on_loaded(*_):
        try:  # 끌어다 놓기 (pywebview 5 이상)
            from webview.dom import DOMEventHandler

            def on_drop(e):
                try:
                    files = e.get("dataTransfer", {}).get("files", [])
                    path = next((f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")), "")
                    if path:
                        api.set_dropped(path)
                        _window.evaluate_js(f"window.onPicked({json.dumps(path)})")
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
    except Exception:
        log.exception("프로그램 오류")
        raise
