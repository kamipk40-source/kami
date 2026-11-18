#!/usr/bin/env python3
"""
Hazri Hisab camera program (Windows / Linux).

Reads one or more IP cameras (RTSP) or a USB webcam, recognises registered faces
and sends the FIRST sighting of each person per day to the Hazri Hisab database.

Commands
  python hr_camera.py folders          create faces\\<ID Name> folders from employees.csv
  python hr_camera.py enroll           learn faces from the photos in faces\\
  python hr_camera.py identify a.jpg   test one photo against the learned faces
  python hr_camera.py check            test models, sign-in and every camera (saves a snapshot)
  python hr_camera.py run [--show]     start recognising (--show opens a window with boxes)
"""
import os, sys, re, csv, json, time, pickle, queue, argparse, threading, configparser
import urllib.request, urllib.error
from datetime import datetime

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
import numpy as np
import cv2

BASE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(BASE, "models")
FACES_DIR = os.path.join(BASE, "faces")
DB_FILE = os.path.join(BASE, "faces.pkl")
UNSENT = os.path.join(BASE, "unsent.jsonl")
LOG_FILE = os.path.join(BASE, "camera.log")
YUNET = ("face_detection_yunet_2023mar.onnx",
         "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx")
SFACE = ("face_recognition_sface_2021dec.onnx",
         "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx")
ID_RE = re.compile(r"^([EN]\d{2,4})\b", re.I)
IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp")


# ---------------------------------------------------------------- small helpers
def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_config():
    path = os.path.join(BASE, "config.ini")
    if not os.path.exists(path):
        sys.exit("config.ini not found. Copy config.example.ini to config.ini and fill it in.")
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.optionxform = str  # keep camera names as typed
    cfg.read(path, encoding="utf-8")
    return cfg


def ensure_models():
    os.makedirs(MODELS, exist_ok=True)
    paths = []
    for name, url in (YUNET, SFACE):
        p = os.path.join(MODELS, name)
        if not os.path.exists(p) or os.path.getsize(p) < 100000:
            log("Downloading model %s ..." % name)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=120) as r, open(p, "wb") as f:
                    f.write(r.read())
            except Exception as e:
                if os.path.exists(p):
                    os.remove(p)
                sys.exit("Could not download %s (%s).\nDownload it by hand from\n  %s\nand put it in the folder:\n  %s" % (name, e, url, MODELS))
            if os.path.getsize(p) < 100000:
                os.remove(p)
                sys.exit("The downloaded %s is not a real model file. Download it by hand from\n  %s\ninto %s" % (name, url, MODELS))
        paths.append(p)
    return paths


class Engine:
    """One detector + one recogniser (OpenCV objects are not shared between threads)."""
    def __init__(self, yunet_path, sface_path):
        self.det = cv2.FaceDetectorYN_create(yunet_path, "", (320, 320), 0.85, 0.3, 5000)
        self.rec = cv2.FaceRecognizerSF_create(sface_path, "")

    def faces(self, frame):
        h, w = frame.shape[:2]
        self.det.setInputSize((w, h))
        _, found = self.det.detect(frame)
        return [] if found is None else list(found)

    def feature(self, frame, face):
        aligned = self.rec.alignCrop(frame, face)
        f = self.rec.feature(aligned).flatten().astype(np.float32)
        n = np.linalg.norm(f)
        return f / n if n else f


def imread(path):
    data = np.fromfile(path, dtype=np.uint8)  # works with any Windows path
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


# ---------------------------------------------------------------- matching
class Gallery:
    def __init__(self, owners, feats):
        self.owners = list(owners)
        self.feats = np.asarray(feats, dtype=np.float32).reshape(-1, 128) if len(owners) else np.zeros((0, 128), np.float32)

    @classmethod
    def load(cls):
        if not os.path.exists(DB_FILE):
            sys.exit("No learned faces yet. Run:  python hr_camera.py enroll")
        with open(DB_FILE, "rb") as f:
            d = pickle.load(f)
        return cls(d["owners"], d["feats"])

    def match(self, q, threshold, margin):
        """Return (id, score) or (None, best_score)."""
        if not len(self.owners):
            return None, 0.0
        sims = self.feats @ q
        best = {}
        for o, s in zip(self.owners, sims):
            if s > best.get(o, -1):
                best[o] = float(s)
        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        top_id, top = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else -1.0
        if top >= threshold and (top - second) >= margin:
            return top_id, top
        return None, top


class Confirmer:
    """A person must be matched in `need` frames within `window` seconds before an event is sent."""
    def __init__(self, need=2, window=4.0):
        self.need, self.window, self.hits = need, window, {}

    def add(self, emp_id, now):
        lst = [t for t in self.hits.get(emp_id, []) if now - t <= self.window] + [now]
        self.hits[emp_id] = lst
        return len(lst) >= self.need


# ---------------------------------------------------------------- cloud
class Cloud:
    def __init__(self, url, key, email, password):
        self.url, self.key, self.email, self.password = url.rstrip("/"), key, email, password
        self.tok, self.ref, self.exp = "", "", 0.0
        self.lock = threading.Lock()

    def _call(self, method, path, body=None, headers=None, auth=True):
        h = {"apikey": self.key, "Content-Type": "application/json"}
        if auth:
            h["Authorization"] = "Bearer " + self.token()
        h.update(headers or {})
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=h)
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)

    def _set(self, j):
        self.tok, self.ref = j["access_token"], j.get("refresh_token", "")
        self.exp = time.time() + float(j.get("expires_in", 3600))

    def login(self):
        _, j = self._call("POST", "/auth/v1/token?grant_type=password", {"email": self.email, "password": self.password}, auth=False)
        self._set(j)

    def token(self):
        with self.lock:
            if self.tok and time.time() < self.exp - 60:
                return self.tok
            if self.ref:
                try:
                    _, j = self._call("POST", "/auth/v1/token?grant_type=refresh_token", {"refresh_token": self.ref}, auth=False)
                    self._set(j)
                    return self.tok
                except Exception:
                    pass
            self.login()
            return self.tok

    def send_event(self, ev):
        s, _ = self._call("POST", "/rest/v1/hr_events?on_conflict=day,emp_id", ev,
                          {"Prefer": "resolution=ignore-duplicates,return=minimal"})
        return s in (200, 201, 204)

    def heartbeat(self, camera):
        s, _ = self._call("POST", "/rest/v1/hr_cameras?on_conflict=name",
                          {"name": camera, "last_seen": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")},
                          {"Prefer": "resolution=merge-duplicates,return=minimal"})
        return s in (200, 201, 204)


class Sender(threading.Thread):
    """Sends events in the background and retries until they get through.
    Events still waiting when the program stops are saved in unsent.jsonl and sent on the next start."""
    def __init__(self, cloud):
        super().__init__(daemon=True)
        self.cloud, self.q, self.current = cloud, queue.Queue(), None
        if os.path.exists(UNSENT):
            with open(UNSENT, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self.q.put(json.loads(line))
            os.remove(UNSENT)

    def put(self, ev):
        self.q.put(ev)

    def dump(self):
        left = ([self.current] if self.current else []) + list(self.q.queue)
        if left:
            with open(UNSENT, "w", encoding="utf-8") as f:
                for ev in left:
                    f.write(json.dumps(ev) + "\n")
            log("%d unsent event(s) saved for the next start" % len(left))

    def run(self):
        while True:
            ev = self.current = self.q.get()
            while True:
                try:
                    self.cloud.send_event(ev)
                    log("sent %s %s %s (%s)" % (ev["emp_id"], ev["day"], ev["t"], ev["camera"]))
                    break
                except urllib.error.HTTPError as e:
                    if e.code in (400, 409, 422):  # a bad row: do not retry forever
                        log("event rejected (%s): %s" % (e.code, ev))
                        break
                    log("send failed (%s), retrying in 20 s" % e.code)
                except Exception as e:
                    log("send failed (%s), retrying in 20 s" % e)
                time.sleep(20)
            self.current = None


# ---------------------------------------------------------------- commands
def cmd_folders(args):
    path = os.path.join(BASE, "employees.csv")
    if not os.path.exists(path):
        sys.exit("employees.csv not found next to this program.")
    os.makedirs(FACES_DIR, exist_ok=True)
    n = 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            emp_id, name = row["ID"].strip(), row["Name"].strip()
            safe = re.sub(r'[\\/:*?"<>|]', "", name)
            d = os.path.join(FACES_DIR, "%s %s" % (emp_id, safe))
            if not os.path.isdir(d):
                os.makedirs(d)
                n += 1
    print("Created %d folders in %s. Put 3 to 5 clear photos of each person inside their folder." % (n, FACES_DIR))


def cmd_enroll(args):
    y, s = ensure_models()
    eng = Engine(y, s)
    owners, feats, report = [], [], []
    if not os.path.isdir(FACES_DIR):
        sys.exit("faces folder not found. Run:  python hr_camera.py folders")
    for entry in sorted(os.listdir(FACES_DIR)):
        d = os.path.join(FACES_DIR, entry)
        m = ID_RE.match(entry)
        if not os.path.isdir(d) or not m:
            continue
        emp_id = m.group(1).upper()
        ok = bad = 0
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith(IMG_EXT):
                continue
            img = imread(os.path.join(d, fn))
            faces = eng.faces(img) if img is not None else []
            faces = [f for f in faces if f[2] >= 60]
            if not faces:
                bad += 1
                print("  no usable face in %s\\%s" % (entry, fn))
                continue
            face = max(faces, key=lambda f: f[2] * f[3])
            owners.append(emp_id)
            feats.append(eng.feature(img, face))
            ok += 1
        report.append((entry, ok, bad))
    with open(DB_FILE, "wb") as f:
        pickle.dump({"owners": owners, "feats": np.array(feats, dtype=np.float32)}, f)
    people = len({o for o in owners})
    print("\nLearned %d photos of %d people." % (len(owners), people))
    for entry, ok, bad in report:
        if ok == 0:
            print("  NO FACE LEARNED: %s" % entry)
        elif ok < 3:
            print("  only %d photo(s): %s (3 to 5 is better)" % (ok, entry))


def cmd_identify(args):
    cfg = load_config()
    th = float(cfg.get("recognition", "threshold", fallback="0.45"))
    mg = float(cfg.get("recognition", "margin", fallback="0.05"))
    y, s = ensure_models()
    eng, gal = Engine(y, s), Gallery.load()
    img = imread(args.photo)
    if img is None:
        sys.exit("Cannot read " + args.photo)
    faces = eng.faces(img)
    if not faces:
        print("No face found in the photo.")
    for f in faces:
        emp_id, score = gal.match(eng.feature(img, f), th, mg)
        print("face width %d px -> %s (best score %.2f, needs %.2f)" % (f[2], emp_id or "not recognised", score, th))


def open_cap(src):
    return cv2.VideoCapture(int(src) if str(src).isdigit() else src)


def cmd_check(args):
    cfg = load_config()
    ensure_models()
    print("Models OK.")
    s = cfg["supabase"]
    cloud = Cloud(s["url"], s["anon_key"], s["email"], s["password"])
    try:
        cloud.login()
        print("Database sign-in OK (%s)." % s["email"])
    except Exception as e:
        print("Database sign-in FAILED: %s" % e)
    for name, src in cfg["cameras"].items():
        cap = open_cap(src)
        ok, frame = cap.read() if cap.isOpened() else (False, None)
        cap.release()
        if ok:
            out = os.path.join(BASE, "snapshot_%s.jpg" % re.sub(r"\W+", "_", name))
            cv2.imwrite(out, frame)
            print("Camera '%s' OK, picture %dx%d saved to %s" % (name, frame.shape[1], frame.shape[0], out))
        else:
            print("Camera '%s' FAILED to open. Check the address, user, password and that the PC can reach the camera." % name)


def camera_loop(name, src, gal, state, show):
    th, mg = state["th"], state["mg"]
    every, min_face = state["every"], state["min_face"]
    eng = Engine(*state["models"])
    conf = Confirmer(need=state["confirm"])
    n = 0
    while not state["stop"]:
        cap = open_cap(src)
        if not cap.isOpened():
            log("%s: cannot open camera, retrying in 10 s" % name)
            time.sleep(10)
            continue
        log("%s: camera connected" % name)
        while not state["stop"]:
            ok, frame = cap.read()
            if not ok:
                log("%s: lost the picture, reconnecting" % name)
                break
            state["last_frame"][name] = time.time()
            n += 1
            if n % every:
                if show:
                    cv2.imshow(name, frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        state["stop"] = True
                continue
            now_dt = datetime.now()
            for f in eng.faces(frame):
                if f[2] < min_face:
                    continue
                emp_id, score = gal.match(eng.feature(frame, f), th, mg)
                if show:
                    x, y, w, h = [int(v) for v in f[:4]]
                    col = (0, 200, 0) if emp_id else (0, 0, 220)
                    cv2.rectangle(frame, (x, y), (x + w, y + h), col, 2)
                    cv2.putText(frame, "%s %.2f" % (emp_id or "?", score), (x, max(y - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
                if not emp_id or not conf.add(emp_id, time.time()):
                    continue
                day = now_dt.strftime("%Y-%m-%d")
                with state["lock"]:
                    if state["day"] != day:
                        state["day"], state["sent"] = day, set()
                    if emp_id in state["sent"]:
                        continue
                    state["sent"].add(emp_id)
                state["sender"].put({"day": day, "emp_id": emp_id, "t": now_dt.strftime("%H:%M"), "camera": name, "score": round(score, 3)})
                log("%s: %s recognised (score %.2f)" % (name, emp_id, score))
            if show:
                cv2.imshow(name, frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    state["stop"] = True
        cap.release()
        time.sleep(3)


def cmd_run(args):
    cfg = load_config()
    models = ensure_models()
    gal = Gallery.load()
    s = cfg["supabase"]
    cloud = Cloud(s["url"], s["anon_key"], s["email"], s["password"])
    r = cfg["recognition"] if cfg.has_section("recognition") else {}
    state = {
        "stop": False, "lock": threading.Lock(), "day": "", "sent": set(), "last_frame": {},
        "models": models, "sender": Sender(cloud),
        "th": float(r.get("threshold", 0.45)), "mg": float(r.get("margin", 0.05)),
        "every": int(r.get("process_every", 5)), "min_face": int(r.get("min_face", 80)),
        "confirm": int(r.get("confirm", 2)),
    }
    state["sender"].start()
    cams = dict(cfg["cameras"])
    log("Started. %d people learned, %d camera(s): %s" % (len(set(gal.owners)), len(cams), ", ".join(cams)))
    threads = [threading.Thread(target=camera_loop, args=(n, src, gal, state, args.show), daemon=True) for n, src in cams.items()]
    for t in threads:
        t.start()
    try:
        while not state["stop"]:
            time.sleep(30)
            for name in cams:  # tell the app each camera is alive
                if time.time() - state["last_frame"].get(name, 0) < 60:
                    try:
                        cloud.heartbeat(name)
                    except Exception as e:
                        log("heartbeat failed: %s" % e)
    except KeyboardInterrupt:
        state["stop"] = True
    time.sleep(1)
    state["sender"].dump()
    log("Stopped.")


def main():
    ap = argparse.ArgumentParser(description="Hazri Hisab camera program")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("folders").set_defaults(fn=cmd_folders)
    sub.add_parser("enroll").set_defaults(fn=cmd_enroll)
    p = sub.add_parser("identify"); p.add_argument("photo"); p.set_defaults(fn=cmd_identify)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    p = sub.add_parser("run"); p.add_argument("--show", action="store_true"); p.set_defaults(fn=cmd_run)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
