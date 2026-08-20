#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# JobDibs — local job search.  Copyright (C) 2026 Shani Segev
# Licensed under the GNU AGPL-3.0. See LICENSE and NOTICE.
"""
JobDibs — אפליקציה מקומית.

הרצה:
    python3 app.py                  # פותח http://127.0.0.1:8765 בדפדפן
    python3 app.py --port 9000
    python3 app.py --no-browser

הכול רץ על המחשב שלך. שום קובץ ושום מידע לא נשלח לשום שרת חיצוני
מלבד לוחות המשרות עצמם, ורק כדי למשוך מהם משרות.
"""

import argparse
import base64
import json
import os
import threading
import traceback
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import engine

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "1.1.0"
DATA = engine.DATA_DIR
PROFILES = os.path.join(DATA, "profiles.json")
LAST = os.path.join(DATA, "last.json")
STATE = os.path.join(DATA, "state.json")

RUNS = {}          # run_id → {"lines": [...], "done": bool, "result": {...}}
RUNS_LOCK = threading.Lock()


# ── עזרי קבצים ──────────────────────────────────────────────────────

def jload(path, default):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            pass
    return default


def jdump(path, obj):
    tmp = path + ".tmp"
    json.dump(obj, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ── הרצת חיפוש ברקע ─────────────────────────────────────────────────

def run_search(run_id, body):
    def log(msg):
        with RUNS_LOCK:
            RUNS[run_id]["lines"].append(msg)

    try:
        cv_text = body.get("cv_text") or ""
        roles = [r for r in (body.get("roles") or []) if r.strip()]
        if not roles:
            raise ValueError("צריך לפחות כותרת תפקיד אחת.")

        log("בונה פרופיל התאמה מקורות החיים…")
        prof = engine.build_profile(
            cv_text, roles,
            market=body.get("market") or "israel",
            region=body.get("region") or "all",
            strict_location=body.get("strict_location", True),
            scope_prefs=body.get("scopes") or [],
            extra_terms=body.get("extra_terms") or [],
            exclude_terms=body.get("exclude_terms") or [])
        d = prof["_derived"]
        lvl = {"junior": "ג׳וניור", "mid": "מיד-לבל",
               "senior": "סניור", "leader": "הנהלה"}.get(d["level"], d["level"])
        log(f"פרופיל: רמה {lvl}, {d['years']} שנות ניסיון, "
            f"{len(prof['domains']['terms'])} תחומים, "
            f"{len(prof['title_must_match'])} ווריאנטים של כותרת תפקיד.")

        jobs, sources = engine.search(
            prof,
            min_score=int(body.get("min_score", 35) if body.get("min_score") is not None else 35),
            use_ats=body.get("use_ats", True),
            use_boards=body.get("use_boards", True),
            auto_discover=body.get("auto_discover", True),
            log=log)

        # מה חדש מאז הריצה הקודמת
        state = jload(STATE, {"seen": {}, "status": {}})
        today = datetime.now(timezone.utc).date().isoformat()
        for j in jobs:
            first = state["seen"].get(j["url"])
            if not first:
                state["seen"][j["url"]] = today
            j["is_new"] = state["seen"][j["url"]] == today
            j["status"] = state["status"].get(j["url"], "new")
        jdump(STATE, state)

        result = {
            "jobs": jobs,
            "meta": {
                "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "roles": roles,
                "market": prof["market"], "region": prof.get("region", "all"),
                "sources": sources,
                "total_shown": len(jobs),
                "profile": {
                    "level": d["level"], "years": d["years"],
                    "languages": d["languages"], "top_terms": d["top_terms"],
                    "titles": prof["title_must_match"][:40],
                    "domains": sorted(prof["domains"]["terms"].items(),
                                      key=lambda x: -x[1])[:30],
                    "cv_chars": d["cv_chars"],
                },
            },
        }
        jdump(LAST, result)
        with RUNS_LOCK:
            RUNS[run_id].update(done=True, result=result)
        log(f"סיימתי — {len(jobs)} משרות.")
    except Exception as e:
        traceback.print_exc()
        with RUNS_LOCK:
            RUNS[run_id]["lines"].append(f"שגיאה: {e}")
            RUNS[run_id].update(done=True, error=str(e))


# ── שרת ─────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    # ── GET ──
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "ui.html"), encoding="utf-8") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")

        if path == "/api/bootstrap":
            markets = engine._load_markets()
            cache = engine.load_cache()
            return self._send(200, {
                "markets": {k: {"label": v.get("label") or k,
                                "regions": {rk: rv.get("label", rk)
                                            for rk, rv in (v.get("regions") or {}).items()}}
                            for k, v in markets.items() if isinstance(v, dict)},
                "profiles": jload(PROFILES, {}),
                "last": jload(LAST, None),
                "discovered": len(cache.get("hits", {})),
                "roles_known": sorted(engine.ROLE_EXPANSIONS.keys()),
            })

        if path == "/api/progress":
            rid = self.path.split("id=")[-1]
            with RUNS_LOCK:
                r = RUNS.get(rid)
                if not r:
                    return self._send(404, {"error": "לא נמצא"})
                return self._send(200, {"lines": r["lines"], "done": r["done"],
                                        "error": r.get("error"),
                                        "result": r.get("result") if r["done"] else None})
        return self._send(404, {"error": "not found"})

    # ── POST ──
    def do_POST(self):
        try:
            body = self._read_json()
        except Exception as e:
            return self._send(400, {"error": f"JSON לא תקין: {e}"})
        path = self.path.split("?")[0]

        if path == "/api/parse-cv":
            raw = base64.b64decode(body.get("data_b64") or "")
            text, fmt, warn = engine.parse_cv(raw, body.get("filename", ""))
            return self._send(200, {"text": text, "format": fmt, "warning": warn,
                                    "chars": len(text)})

        if path == "/api/preview-profile":
            prof = engine.build_profile(
                body.get("cv_text") or "",
                [r for r in (body.get("roles") or []) if r.strip()] or ["product manager"],
                market=body.get("market") or "israel",
                region=body.get("region") or "all",
                strict_location=body.get("strict_location", True),
                scope_prefs=body.get("scopes") or [],
                extra_terms=body.get("extra_terms") or [],
            exclude_terms=body.get("exclude_terms") or [])
            d = prof["_derived"]
            return self._send(200, {
                "level": d["level"], "years": d["years"], "languages": d["languages"],
                "titles": prof["title_must_match"],
                "domains": sorted(prof["domains"]["terms"].items(), key=lambda x: -x[1])[:30],
                "companies_seed": len(prof["companies"]),
                "added": d["added"], "excluded": d["excluded"],
                "region_label": d.get("region_label", ""),
            })

        if path == "/api/search":
            rid = uuid.uuid4().hex[:12]
            with RUNS_LOCK:
                RUNS[rid] = {"lines": [], "done": False}
            threading.Thread(target=run_search, args=(rid, body), daemon=True).start()
            return self._send(200, {"run_id": rid})

        if path == "/api/learn-board":
            kind, entry = engine.learn_board((body.get("url") or "").strip(),
                                             (body.get("name") or "").strip() or None)
            if not kind:
                return self._send(200, {"ok": False,
                    "error": "לא זוהה לוח Workday או Comeet בכתובת הזו."})
            b = engine.load_boards()
            return self._send(200, {"ok": True, "kind": kind, "entry": entry,
                                    "counts": {k: len(v) for k, v in b.items()}})

        if path == "/api/save-profile":
            profs = jload(PROFILES, {})
            name = (body.get("name") or "").strip() or "ללא שם"
            profs[name] = {k: body.get(k) for k in
                           ("roles", "market", "region", "strict_location", "scopes",
                            "extra_terms", "exclude_terms",
                            "min_score", "cv_text", "cv_name")}
            jdump(PROFILES, profs)
            return self._send(200, {"ok": True, "profiles": profs})

        if path == "/api/delete-profile":
            profs = jload(PROFILES, {})
            profs.pop(body.get("name"), None)
            jdump(PROFILES, profs)
            return self._send(200, {"ok": True, "profiles": profs})

        if path == "/api/set-status":
            state = jload(STATE, {"seen": {}, "status": {}})
            url, st = body.get("url"), body.get("status")
            if st:
                state["status"][url] = st
            else:
                state["status"].pop(url, None)
            jdump(STATE, state)
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "not found"})


def _heal_launchers():
    """
    מחזיר את הרשאת ההרצה לקובצי ההפעלה.
    קובץ zip שיורד מגיטהאב, או העלאה דרך הדפדפן, עלולים לאבד את הרשאת
    ההרצה — ואז לחיצה כפולה נותנת "you do not have appropriate access
    privileges". אחרי הרצה אחת מהטרמינל, הלחיצה הכפולה תעבוד מכאן והלאה.
    """
    for name in ("Start JobDibs.command",):   # רק במק/לינוקס יש משמעות
        p = os.path.join(HERE, name)
        try:
            if os.path.exists(p) and not os.access(p, os.X_OK):
                os.chmod(p, os.stat(p).st_mode | 0o111)
                print(f"  ✓ תוקנה הרשאת ההרצה של \"{name}\" "
                      f"(restored the executable bit)")
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--learn", metavar="URL",
                    help="הוספת לוח Workday/Comeet מכתובת דף קריירה")
    ap.add_argument("--name", help="שם החברה עבור --learn")
    a = ap.parse_args()

    if a.learn:
        kind, entry = engine.learn_board(a.learn, a.name)
        print(f"  ✓ נוסף {kind}: {entry}" if kind else
              "  ✗ לא זוהה לוח Workday או Comeet בכתובת הזו.")
        return

    _heal_launchers()

    # אם הפורט תפוס — כנראה שיש חלון קודם שעדיין רץ. מנסים את הבא בתור
    # במקום ליפול. זו הסיבה הנפוצה ל"בפעם הראשונה עבד ובשנייה לא".
    srv, port = None, a.port
    for p in range(a.port, a.port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if srv is None:
        print("\n  לא הצלחתי לתפוס פורט פנוי בטווח "
              f"{a.port}–{a.port + 19}.")
        print("  כנראה שכבר רצים כמה עותקים של JobDibs. סגרי את חלונות")
        print("  הטרמינל הפתוחים ונסי שוב.\n")
        return
    if port != a.port:
        print(f"\n  הפורט {a.port} היה תפוס (כנראה חלון קודם שעדיין פתוח),")
        print(f"  אז עברתי לפורט {port}.")

    url = f"http://127.0.0.1:{port}"
    print(f"\n  JobDibs {VERSION}")
    print(f"  תיקייה: {HERE}")
    print(f"  רץ על  {url}")
    print("  לעצירה: Ctrl+C\n")
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  ביי 👋\n")


if __name__ == "__main__":
    main()
