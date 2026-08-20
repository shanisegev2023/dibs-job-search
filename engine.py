#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# JobDibs — local job search.  Copyright (C) 2026 Shani Segev
# Licensed under the GNU AGPL-3.0. See LICENSE and NOTICE.
"""
JobDibs engine — גנרי: קו"ח פנימה, משרות מדורגות החוצה.

אין תלויות חיצוניות. הכול ספרייה סטנדרטית של פייתון.

  parse_cv(path|bytes)        → טקסט גולמי מ-PDF / DOCX / TXT
  build_profile(text, roles)  → פרופיל התאמה מלא, אוטומטית
  search(profile, opts)       → משרות מכל המקורות, מסוננות ומדורגות
  discover(names)             → מגלה slugs פעילים של לוחות גיוס
"""

import concurrent.futures as futures
import html as html_mod
import io
import json
import os
import re
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
import zlib
from collections import Counter
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
os.makedirs(DATA_DIR, exist_ok=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")
TIMEOUT = 18

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE


# ════════════════════════════════════════════════════════════════════
# 1 · קריאת קורות חיים
# ════════════════════════════════════════════════════════════════════

import pdftext


def _docx_text(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        parts = [n for n in z.namelist()
                 if n.startswith("word/") and n.endswith(".xml")
                 and ("document" in n or "header" in n or "footer" in n)]
        out = []
        for n in sorted(parts):
            xml = z.read(n).decode("utf-8", "replace")
            xml = re.sub(r"</w:p>", "\n", xml)
            xml = re.sub(r"<w:tab[^>]*/>", " ", xml)
            out.append(html_mod.unescape(re.sub(r"<[^>]+>", "", xml)))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def parse_cv(src, filename=""):
    """src = נתיב לקובץ או bytes. מחזיר (text, format, warning)."""
    if isinstance(src, (bytes, bytearray)):
        raw, name = bytes(src), (filename or "")
    else:
        name = src
        with open(src, "rb") as f:
            raw = f.read()
    ext = os.path.splitext(name.lower())[1]

    if raw[:4] == b"%PDF" or ext == ".pdf":
        txt, method, warn = pdftext.extract(raw)
        return txt, f"pdf/{method}", warn
    if raw[:2] == b"PK" or ext in (".docx", ".dotx"):
        try:
            return _docx_text(raw), "docx", ""
        except Exception as e:
            return "", "docx", f"קובץ ה-DOCX לא נקרא ({e}). נסי להדביק את הטקסט."
    for enc in ("utf-8", "utf-16", "cp1255", "latin-1"):
        try:
            return raw.decode(enc).strip(), "text", ""
        except Exception:
            continue
    return "", "unknown", "פורמט קובץ לא מזוהה. נתמכים: PDF, DOCX, TXT, MD."


# ════════════════════════════════════════════════════════════════════
# 2 · בניית פרופיל מהקו"ח
# ════════════════════════════════════════════════════════════════════

# לקסיקון תחומים — מה שמופיע בקו"ח נכנס לפרופיל עם משקל לפי תדירות.
LEXICON = {
 "product": ["roadmap","prd","product strategy","product discovery","backlog","user story",
   "product-led","go-to-market","gtm","pricing","positioning","product launch","mvp",
   "design partner","pilot program","product analytics","north star","okr","jira","confluence",
   "linear","productboard","amplitude","mixpanel","stakeholder"],
 "growth": ["growth","retention","churn","activation","acquisition","conversion rate","cro",
   "a/b test","experimentation","funnel","lifecycle","ltv","cac","seo","paid media",
   "email marketing","crm","segmentation","personalization","ga4","google analytics","looker"],
 "ecommerce": ["e-commerce","ecommerce","dtc","direct-to-consumer","shopify","magento",
   "woocommerce","checkout","cart","merchandising","catalog","subscription","marketplace",
   "merchant","payments","fulfillment","retail","omnichannel","pim"],
 "ai_data": ["machine learning","artificial intelligence","computer vision","nlp","llm","genai",
   "synthetic data","data platform","data pipeline","etl","annotation","model training",
   "mlops","recommendation","deep learning","data science","bigquery","snowflake","databricks"],
 "design": ["ux","ui","user research","usability","wireframe","prototype","figma","adobe xd",
   "sketch","design system","information architecture","accessibility","user journey","persona"],
 "engineering": ["api","microservices","cloud","aws","gcp","azure","kubernetes","docker",
   "ci/cd","devops","sql","python","javascript","react","node","terraform","architecture",
   "sdk","integration","rest","graphql"],
 "quality": ["qa","quality assurance","test plan","automation testing","regression","bug",
   "release management","test case","selenium","cypress"],
 "delivery": ["agile","scrum","kanban","sprint","waterfall","program management","pmo",
   "gantt","risk management","budget","vendor management","stakeholder management",
   "cross-functional","raci","milestone","governance"],
 "domain_verticals": ["fintech","insurtech","healthtech","medtech","biotech","cybersecurity",
   "adtech","martech","proptech","logistics","supply chain","manufacturing","automotive",
   "gaming","edtech","legaltech","hr tech","3d","cad","simulation","fashion","apparel",
   "telecom","energy","aviation","defense","travel","real estate","b2b saas","saas","b2b","b2c"],
 "business": ["p&l","revenue","forecast","pricing strategy","business development",
   "partnerships","market research","competitive analysis","customer interviews",
   "voice of customer","nps","churn analysis","unit economics"],

 # תחומים מחוץ להייטק — כדי שקורות חיים שאינם טכנולוגיים יקבלו פרופיל אמיתי
 "finance_acc": ["bookkeeping","accounts payable","accounts receivable","reconciliation",
   "general ledger","ifrs","gaap","audit","payroll","budgeting","tax return",
   "financial statements","sap","priority","hashavshevet","excel","הנהלת חשבונות",
   "שכר","מאזן","תמחיר","גבייה"],
 "healthcare_dom": ["patient care","clinical trials","triage","emergency room","icu",
   "surgery","pediatrics","geriatrics","rehabilitation","medical records","hmo",
   "pharmacy","diagnosis","טיפול","מרפאה","אשפוז","קופת חולים","סיעוד"],
 "education_dom": ["lesson planning","classroom management","curriculum development",
   "pedagogy","special education","assessment","e-learning","moodle","student progress",
   "חינוך מיוחד","תכנית לימודים","הוראה","כיתה","הערכה"],
 "legal_dom": ["contracts","litigation","due diligence","regulatory","gdpr","compliance",
   "intellectual property","corporate law","labor law","חוזים","ליטיגציה","רגולציה",
   "דיני עבודה","קניין רוחני"],
 "hospitality_dom": ["food safety","haccp","menu","inventory count","pos","kashrut",
   "customer experience","reservations","housekeeping","shift scheduling","barista",
   "כשרות","מלאי","קופה","סידור עבודה","שירות"],
 "trades_dom": ["preventive maintenance","troubleshooting","blueprints","hydraulics",
   "pneumatics","plc","cnc","calibration","forklift licence","safety regulations",
   "אחזקה מונעת","תקלות","שרטוטים","רישיון מלגזה","תקני בטיחות"],
 "hr_dom": ["onboarding","sourcing","employer branding","performance review",
   "employee engagement","ats","interviewing","retention plan","קליטה","גיוס",
   "הערכת עובדים","רווחת עובדים"],
}
ALL_TERMS = sorted({t for v in LEXICON.values() for t in v}, key=len, reverse=True)

# מונחים קצרים כמו rest, cad, ai נתפסים בטעות בתוך מילים ארוכות
# (restaurant, academy). לכן קצרים נבדקים עם גבולות מילה.
_SHORT = 4


def term_count(text, term):
    if len(term) <= _SHORT and " " not in term:
        return len(re.findall(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text))
    return text.count(term)


def term_in(text, term):
    if len(term) <= _SHORT and " " not in term:
        return re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) is not None
    return term in text


SENIORITY_WORDS = ["chief","vp","vice president","head of","director","principal","staff",
                   "lead","senior","sr.","manager","mid-level","junior","jr.","associate",
                   "intern","entry"]

# הרחבת כותרת תפקיד לווריאנטים שבאמת מופיעים במודעות
ROLE_EXPANSIONS = {
 "product manager": ["product manager","product management","product owner","product lead",
   "head of product","director of product","vp of product","vp product","group product manager",
   "principal product manager","technical product manager","growth product manager",
   "מנהל מוצר","מנהלת מוצר","מנהל/ת מוצר"],
 "project manager": ["project manager","projects manager","project management","program manager",
   "technical program manager","technical project manager","delivery manager","delivery lead",
   "pmo","scrum master","מנהל פרויקט","מנהלת פרויקטים","מנהל/ת פרויקט","מנהל/ת פרוייקט"],
 "program manager": ["program manager","technical program manager","program management","pmo",
   "portfolio manager","מנהל תוכנית","מנהל/ת תוכנית"],
 "data analyst": ["data analyst","business analyst","analytics","bi analyst","insights analyst",
   "product analyst","אנליסט","אנליסטית"],
 "ux designer": ["ux designer","product designer","ui/ux","ux/ui","user experience designer",
   "interaction designer","ux researcher","מעצב חוויית משתמש","מעצבת ux"],
 "marketing manager": ["marketing manager","growth marketing","demand generation","brand manager",
   "product marketing manager","pmm","מנהל שיווק","מנהלת שיווק"],
 "qa": ["qa engineer","qa manager","quality assurance","test engineer","automation engineer",
   "qa lead","בודק תוכנה","מנהל qa"],
 "software engineer": ["software engineer","developer","backend engineer","frontend engineer",
   "full stack","full-stack","engineering manager","מפתח","מפתחת"],
 "customer success": ["customer success","account manager","customer success manager","csm",
   "technical account manager","implementation manager","onboarding manager"],
 "operations": ["operations manager","business operations","bizops","chief of staff",
   "operations lead","process manager","מנהל תפעול","מנהלת תפעול"],

 # מחוץ להייטק
 "finance": ["accountant","bookkeeper","financial analyst","controller","cfo",
   "auditor","payroll","tax","treasury","רואה חשבון","מנהל חשבונות","חשב",
   "כלכלן","בקר תקציב","גזבר"],
 "hr": ["hr manager","human resources","recruiter","talent acquisition","hr business partner",
   "hrbp","people operations","training manager","compensation","משאבי אנוש",
   "מגייס","מגייסת","רכזת גיוס","מנהל הדרכה"],
 "sales": ["sales manager","account executive","business development","sales representative",
   "key account","inside sales","channel manager","מנהל מכירות","איש מכירות",
   "מנהל לקוחות","פיתוח עסקי"],
 "healthcare": ["nurse","physician","doctor","medical","clinical","pharmacist",
   "physiotherapist","caregiver","lab technician","dietitian","psychologist",
   "אח","אחות","רופא","רופאה","פיזיותרפיסט","פסיכולוג","דיאטנית","מרפא בעיסוק",
   "טכנאי מעבדה","סייעת רפואית"],
 "education": ["teacher","lecturer","instructor","tutor","principal","educator",
   "curriculum","teaching assistant","מורה","מרצה","מדריך","מדריכה","גננת",
   "רכז חינוך","מנהל בית ספר","מתרגל"],
 "legal": ["lawyer","attorney","legal counsel","paralegal","compliance officer",
   "contract manager","עורך דין","עורכת דין","יועץ משפטי","מתמחה משפטי","פרליגל"],
 "logistics": ["logistics manager","supply chain manager","warehouse manager","procurement",
   "buyer","dispatcher","fleet manager","inventory manager","מנהל לוגיסטיקה",
   "מנהל מחסן","רכש","קניין","מנהל שרשרת אספקה"],
 "hospitality_retail": ["store manager","shift manager","barista","waiter","waitress",
   "chef","cook","bartender","host","housekeeping","front desk","receptionist",
   "cashier","sales associate","מלצר","מלצרית","ברמן","טבח","שף","קופאי","קופאית",
   "מנהל סניף","מנהל משמרת","פקיד קבלה","מוכר","מוכרת"],
 "skilled_trades": ["electrician","technician","mechanic","plumber","welder","machinist",
   "maintenance technician","field service","installer","driver","forklift",
   "חשמלאי","טכנאי","מכונאי","אינסטלטור","רתך","נהג","מפעיל","מתקין",
   "טכנאי שירות","אחזקה"],
 "admin": ["administrative assistant","executive assistant","office manager",
   "personal assistant","secretary","data entry","scheduler","עוזרת אישית",
   "מזכירה","מזכיר","אחראית משרד","הזנת נתונים","פקיד","פקידה"],
 "customer_service": ["customer service","call center","support representative",
   "help desk","service desk","נציג שירות","מוקדן","מוקדנית","תמיכה טכנית",
   "שירות לקוחות"],
 "security_safety": ["security guard","safety officer","security officer","guard",
   "מאבטח","מאבטחת","קצין בטיחות","ממונה בטיחות","שומר","סייר"],
}

SENIORITY_PREFIXES = ["senior","sr","lead","principal","staff","head of","director of",
                      "vp of","chief","group","associate","junior"]

# סוגי העסקה. המשתמש בוחר אילו מהם רלוונטיים לו, וזה מה שקובע את הניקוד.
SCOPE_FAMILIES = {
  "fractional": {
    "he": "פרקשנל",
    "terms": {"fractional": 40, "פרקשנל": 40, "retainer": 26, "hours per week": 22,
              "hrs/week": 22, "hrs per week": 22, "advisory": 18},
  },
  "part-time": {
    "he": "משרה חלקית",
    "terms": {"part-time": 38, "part time": 38, "parttime": 38, "משרה חלקית": 38,
              "חצי משרה": 38, "50%": 30, "60%": 30, "70%": 28, "80%": 24,
              "reduced scope": 20, "flexible hours": 18, "flexible schedule": 18},
  },
  "freelance": {
    "he": "פרילנס / ייעוץ",
    "terms": {"freelance": 32, "פרילנס": 32, "consultant": 26, "consulting": 24,
              "self-employed": 24, "עצמאי": 24, "עוסק מורשה": 24},
  },
  "contract": {
    "he": "חוזה / קבלנות",
    "terms": {"contractor": 28, "contract role": 28, "fixed-term": 28, "fixed term": 28,
              "temporary": 26, "temp position": 26, "זמני": 24, "לתקופה קצובה": 26},
  },
  "interim": {
    "he": "אינטרים",
    "terms": {"interim": 30, "stand-in": 22, "stopgap": 20, "bridge role": 20},
  },
  "maternity-cover": {
    "he": "החלפה לחל\"ד",
    "terms": {"maternity": 34, "maternity cover": 34, "maternity leave replacement": 34,
              "parental leave cover": 34, "חל\"ד": 34, "חופשת לידה": 34,
              "החלפה לחל\"ד": 34, "החלפה לחופשת לידה": 34},
  },
  "full-time": {
    "he": "משרה מלאה",
    "terms": {"full-time": 34, "full time": 34, "fulltime": 34, "משרה מלאה": 34,
              "permanent position": 30, "permanent role": 30, "משרה קבועה": 30,
              "salaried": 24, "שכיר": 24},
  },
  "student": {
    "he": "סטודנטים / התמחות",
    "terms": {"student": 38, "students": 38, "סטודנט": 38, "סטודנטית": 38,
              "לסטודנטים": 38, "intern": 36, "internship": 36, "מתמחה": 36,
              "התמחות": 36, "working student": 34, "werkstudent": 34,
              "co-op": 30, "apprentice": 28, "חונכות": 24},
  },
  "entry-level": {
    "he": "משרת כניסה / ג׳וניור",
    "terms": {"entry level": 36, "entry-level": 36, "junior": 34, "ג׳וניור": 34,
              "ג'וניור": 34, "graduate": 30, "new grad": 32, "no experience required": 34,
              "ללא ניסיון": 34, "trainee": 30, "מתחילים": 28},
  },
  "shift": {
    "he": "משמרות / שעתי",
    "terms": {"shift work": 32, "shifts": 28, "משמרות": 32, "hourly rate": 24,
              "שעתי": 26, "per hour": 22, "evening shift": 26, "weekend shift": 26},
  },
}

# משפחות שנחשבות "היקף גמיש" בתצוגה
FLEXIBLE_FAMILIES = {"fractional", "part-time", "freelance", "contract",
                     "interim", "maternity-cover", "student", "shift"}

# ברירת מחדל כשהמשתמש לא בחר כלום — חיפוש כללי, בלי הטיה
DEFAULT_FAMILIES = list(SCOPE_FAMILIES)

# אין כותרות שנחסמות תמיד. הסינון נעשה ממילא לפי title_must_match,
# וכל רשימת חסימה קבועה רק מונעת ממישהו למצוא את העבודה שהוא באמת מחפש.
ALWAYS_EXCLUDE = []

# נחסמות רק כשהמשתמש לא מחפש משרות סטודנטים/התמחות
STUDENT_TITLES = ["intern", "internship", "student", "מתמחה", "סטודנט"]


def resolve_scope_tag(blob):
    """מזהה את סוג ההעסקה של המשרה. הספציפי מנצח את הכללי."""
    for name, fam in SCOPE_FAMILIES.items():
        if any(term_in(blob, t) for t in fam["terms"]):
            return name
    return "hybrid" if "hybrid" in blob else "unknown"


def build_scope_terms(prefs):
    """
    מחזיר (מונחים חיוביים, המשפחות שנבחרו, האם הייתה בחירה מפורשת).
    הקנס על סוג העסקה לא נכון מחושב ב-score() לפי התגית של המשרה,
    ולא לפי מונחים בודדים — כי freelance/contract/fractional חופפים
    זה לזה, ומילה בודדת בתיאור לא אומרת שזה סוג ההעסקה בפועל.
    """
    prefs = [p for p in (prefs or []) if p in SCOPE_FAMILIES]
    if not prefs:                                   # חיפוש כללי — הכול נספר שווה
        terms = {}
        for fam in SCOPE_FAMILIES.values():
            for t, w in fam["terms"].items():
                terms[t] = max(terms.get(t, 0), int(w * 0.6))
        return terms, DEFAULT_FAMILIES, False
    terms = {}
    for name in prefs:
        for t, w in SCOPE_FAMILIES[name]["terms"].items():
            terms[t] = max(terms.get(t, 0), w)
    return terms, prefs, True


MARKETS = {}   # נטען מ-markets.json


def _load_markets():
    global MARKETS
    if MARKETS:
        return MARKETS
    p = os.path.join(HERE, "markets.json")
    raw = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    MARKETS = {k: v for k, v in raw.items() if isinstance(v, dict)}
    return MARKETS


def expand_roles(roles):
    """['Product Manager', 'PMO'] → כל הווריאנטים שכדאי לחפש בכותרות."""
    out = set()
    for r in roles:
        r = (r or "").strip().lower()
        if not r:
            continue
        out.add(r)
        matched = False
        for key, variants in ROLE_EXPANSIONS.items():
            if key in r or r in key or any(r == v for v in variants):
                out.update(variants); matched = True
        if not matched:
            for v in ROLE_EXPANSIONS.values():
                if any(r in v2 or v2 in r for v2 in v):
                    out.update(v); matched = True; break
        if not matched:                       # תפקיד לא מוכר — נייצר ווריאנטים בעצמנו
            out.update(f"{p} {r}" for p in SENIORITY_PREFIXES[:6])
            base = re.sub(r"\b(senior|junior|lead|principal|staff)\b\s*", "", r).strip()
            if base:
                out.add(base)
    return sorted(out)


def build_profile(cv_text, roles, market="israel", scope_prefs=None,
                  extra_terms=None, exclude_terms=None, region="all",
                  strict_location=True):
    """בונה פרופיל התאמה מלא מקו"ח + כותרות תפקיד. מחזיר dict."""
    text = (cv_text or "").lower()
    mk = _load_markets().get(market, {})

    # --- תחומים: מה שבאמת מופיע בקו"ח, במשקל לפי תדירות ---
    freq = Counter()
    for term in ALL_TERMS:
        n = term_count(text, term)
        if n:
            freq[term] = n
    domains = {}
    if freq:
        top = freq.most_common(45)
        hi = top[0][1]
        for term, n in top:
            domains[term] = int(round(8 + 22 * (n / hi) ** 0.5))   # 8..30
    # מילות מפתח שהמשתמש הוסיף ידנית — מקבלות את המשקל המרבי
    for t in (extra_terms or []):
        t = t.strip().lower()
        if t:
            domains[t] = 30
    excludes = sorted({t.strip().lower() for t in (exclude_terms or []) if t.strip()})

    # --- סניוריטי: מה שמופיע בכותרות בקו"ח ---
    years = 0
    for m in re.finditer(r"(\d{1,2})\s*\+?\s*(?:years|yrs|שנות|שנים)", text):
        years = max(years, int(m.group(1)))
    if not years:
        yrs = [int(y) for y in re.findall(r"\b(19[89]\d|20[0-4]\d)\b", text)]
        if len(yrs) >= 2:
            years = max(0, min(40, datetime.now().year - min(yrs)))
    level = ("junior" if years < 3 else "mid" if years < 6
             else "senior" if years < 12 else "leader")
    seniority = {"junior": {"junior": 15, "associate": 10, "senior": -8, "principal": -18,
                            "director": -25, "vp ": -30, "head of": -20},
                 "mid":    {"senior": 6, "junior": -5, "intern": -40, "vp ": -18, "chief": -25},
                 "senior": {"senior": 12, "lead": 10, "principal": 10, "staff": 8, "head of": 8,
                            "junior": -25, "associate": -12, "intern": -40, "entry level": -30},
                 "leader": {"head of": 14, "director": 14, "vp ": 12, "chief": 12, "principal": 10,
                            "senior": 8, "lead": 8, "junior": -30, "associate": -20,
                            "intern": -45, "entry level": -35}}[level]

    # --- שפות ---
    langs = [l for l in ("hebrew","english","russian","french","spanish","german","italian",
                         "arabic","עברית","אנגלית") if l in text]

    scope, chosen_families, explicit_scope = build_scope_terms(scope_prefs)

    # מיקום: המשקלים של השוק, ומעליהם האזור שנבחר בתוכו
    loc_pos = dict(mk.get("positive") or {"remote": 16, "worldwide": 20})
    loc_neg = dict(mk.get("negative") or {})
    reg = (mk.get("regions") or {}).get(region or "all") or {}
    for t, w in (reg.get("positive") or {}).items():
        loc_pos[t] = max(loc_pos.get(t, 0), w)
    for t, w in (reg.get("negative") or {}).items():
        loc_neg[t] = min(loc_neg.get(t, 0), w)

    # כותרות חסומות — משרות סטודנטים/התמחות נחסמות רק אם לא ביקשו אותן
    hard_exclude = list(ALWAYS_EXCLUDE)
    if "student" not in chosen_families and "entry-level" not in chosen_families:
        hard_exclude += STUDENT_TITLES

    # מי שמחפש התמחות או משרת כניסה — לא נעניש אותו על "junior"
    if "student" in chosen_families or "entry-level" in chosen_families:
        seniority = {k: v for k, v in seniority.items()
                     if k not in ("junior", "intern", "entry level", "associate")}
        seniority.update({"junior": 10, "intern": 8, "entry level": 10, "graduate": 8})

    return {
        "roles": roles,
        "title_must_match": expand_roles(roles),
        "title_hard_exclude": hard_exclude,
        "exclude_terms": excludes,
        "market": market,
        "region": region or "all",
        "scope_signals": {"weight": 40 if explicit_scope else 24, "terms": scope,
                          "families": chosen_families,
                     "region_label": reg.get("label", ""), "explicit": explicit_scope},
        "domains": {"weight": 30, "terms": domains},
        "location_rules": {"weight": 20, "positive": loc_pos,
                           "negative": loc_neg, "strict": bool(strict_location),
                           "market": market, "region": region or "all",
                           "allowed_codes": MARKET_GEO.get(market, set())},
        "seniority": {"weight": 10, "terms": seniority},
        "freshness": {"weight": 10, "days_full_score": 7, "days_zero_score": 45,
                      "stale_penalty": -12},
        "companies": mk.get("companies", []),
        "search_terms": (roles or ["product manager"])[:6],
        "_derived": {"years": years, "level": level, "languages": langs,
                     "families": chosen_families,
                     "region_label": reg.get("label", ""),
                     "top_terms": [t for t, _ in freq.most_common(18)],
                     "added": [t.strip().lower() for t in (extra_terms or []) if t.strip()],
                     "excluded": excludes,
                     "cv_chars": len(cv_text or "")},
    }


# ════════════════════════════════════════════════════════════════════
# 3 · מקורות
# ════════════════════════════════════════════════════════════════════

def fetch(url, as_json=True):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json, text/xml, */*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_SSL) as r:
            raw = r.read()
    except Exception:
        return None
    if not raw:
        return None
    try:
        text = raw.decode("utf-8", "replace")
    except Exception:
        return None
    if not as_json:
        return text
    try:
        return json.loads(text)
    except Exception:
        return None


def post_json(url, payload, extra_headers=None):
    """POST JSON. נדרש ל-Workday, שלא חושף GET."""
    body = json.dumps(payload).encode("utf-8")
    hdr = {"User-Agent": UA, "Content-Type": "application/json",
           "Accept": "application/json", "Accept-Language": "en-US,en;q=0.9"}
    hdr.update(extra_headers or {})
    try:
        req = urllib.request.Request(url, data=body, headers=hdr, method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_SSL) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def strip_html(s):
    if not s:
        return ""
    s = re.sub(r"<(script|style).*?</\1>", " ", s, flags=re.S | re.I)
    s = html_mod.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"\s+", " ", s).strip()


def parse_date(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            ts = float(v)
            return datetime.fromtimestamp(ts / 1000 if ts > 1e11 else ts, tz=timezone.utc)
        except Exception:
            return None
    s = str(v).strip().replace("Z", "+00:00")
    if not s:
        return None
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z",
                "%d %b %Y", "%Y/%m/%d"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def mk_job(title, company, location, url, source, desc="", posted=None,
           employment_type="", rate=""):
    if not title or not url:
        return None
    return {"title": strip_html(str(title))[:200],
            "company": strip_html(str(company or ""))[:120],
            "location": strip_html(str(location or ""))[:160],
            "url": str(url), "source": source,
            "employment_type": strip_html(str(employment_type or ""))[:90],
            "rate": str(rate or "")[:90], "desc": strip_html(desc)[:5000],
            "posted": posted.isoformat() if isinstance(posted, datetime) else (posted or "")}


def src_greenhouse(slug):
    d = fetch(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    if not isinstance(d, dict):
        return []
    return [x for x in (mk_job(j.get("title"), slug, (j.get("location") or {}).get("name", ""),
            j.get("absolute_url"), f"Greenhouse:{slug}", j.get("content", ""),
            parse_date(j.get("updated_at"))) for j in d.get("jobs") or []) if x]


def src_lever(slug):
    d = fetch(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not isinstance(d, list):
        return []
    out = []
    for j in d:
        c = j.get("categories") or {}
        out.append(mk_job(j.get("text"), slug, c.get("location", ""),
                          j.get("hostedUrl") or j.get("applyUrl"), f"Lever:{slug}",
                          (j.get("descriptionPlain") or "") + " " + (j.get("additionalPlain") or ""),
                          parse_date(j.get("createdAt")), c.get("commitment", "")))
    return [x for x in out if x]


def src_ashby(slug):
    d = fetch(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if not isinstance(d, dict):
        return []
    out = []
    for j in d.get("jobs") or []:
        if j.get("isListed") is False:
            continue
        out.append(mk_job(j.get("title"), slug, j.get("location", ""),
                          j.get("jobUrl") or j.get("applyUrl"), f"Ashby:{slug}",
                          j.get("descriptionPlain", ""), parse_date(j.get("publishedAt")),
                          j.get("employmentType", "")))
    return [x for x in out if x]


def src_recruitee(slug):
    d = fetch(f"https://{slug}.recruitee.com/api/offers/")
    if not isinstance(d, dict):
        return []
    out = []
    for j in d.get("offers") or []:
        out.append(mk_job(j.get("title"), slug, j.get("location", ""),
                          j.get("careers_url") or j.get("careers_apply_url"), f"Recruitee:{slug}",
                          j.get("description", ""), parse_date(j.get("published_at")),
                          j.get("employment_type_code", "")))
    return [x for x in out if x]


def src_workable(slug):
    d = fetch(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
    if not isinstance(d, dict):
        return []
    out = []
    for j in d.get("jobs") or []:
        out.append(mk_job(j.get("title"), slug,
                          ", ".join(filter(None, [j.get("city"), j.get("country")])),
                          j.get("url") or j.get("application_url"), f"Workable:{slug}",
                          j.get("description", ""), parse_date(j.get("published_on")),
                          j.get("employment_type", "")))
    return [x for x in out if x]



# ── מערכות גיוס נוספות (GET ציבורי, בלי מפתח) ─────────────────────

def src_personio(slug):
    for host in ("de", "com"):
        txt = fetch(f"https://{slug}.jobs.personio.{host}/xml", as_json=False)
        if not txt or "<position" not in txt:
            continue
        try:
            root = ET.fromstring(txt)
        except Exception:
            continue
        out = []
        for p in root.iter("position"):
            g = lambda t: (p.find(t).text or "") if p.find(t) is not None else ""
            desc = " ".join((d.text or "") for d in p.iter("value"))
            jid = g("id")
            out.append(mk_job(g("name"), slug, g("office"),
                              f"https://{slug}.jobs.personio.{host}/job/{jid}",
                              f"Personio:{slug}", desc, parse_date(g("createdAt")),
                              " ".join(filter(None, [g("employmentType"), g("schedule")]))))
        return [x for x in out if x]
    return []


def src_bamboo(slug):
    d = fetch(f"https://{slug}.bamboohr.com/careers/list")
    if not isinstance(d, dict):
        return []
    out = []
    for j in (d.get("result") or []):
        loc = j.get("location") or {}
        parts = [loc.get("city"), loc.get("state")] if isinstance(loc, dict) else [str(loc)]
        remote = {1: "Remote", 2: "Hybrid"}.get(j.get("locationType"))
        out.append(mk_job(j.get("jobOpeningName"), slug,
                          ", ".join([p for p in parts if p] + ([remote] if remote else []))
                          or j.get("atsLocation", ""),
                          f"https://{slug}.bamboohr.com/careers/{j.get('id')}",
                          f"BambooHR:{slug}",
                          " ".join(filter(None, [j.get("departmentLabel"),
                                                 j.get("employmentStatusLabel"), remote])),
                          None,
                          j.get("employmentStatusLabel") or j.get("employmentType", "")))
    return [x for x in out if x]


def src_breezy(slug):
    d = fetch(f"https://{slug}.breezy.hr/json")
    if not isinstance(d, list):
        return []
    out = []
    for j in d:
        loc = j.get("location") or {}
        if isinstance(loc, dict):
            c = (loc.get("city") or "") + (", " + loc.get("country", {}).get("name", "")
                                           if isinstance(loc.get("country"), dict) else "")
            loc = c or loc.get("name", "")
        out.append(mk_job(j.get("name"), j.get("company") or slug, loc, j.get("url"),
                          f"Breezy:{slug}",
                          " ".join(filter(None, [str(j.get("department") or ""),
                                                 str(j.get("type") or ""),
                                                 str(j.get("experience") or "")])),
                          parse_date(j.get("published_date")),
                          (j.get("type") or {}).get("name", "") if isinstance(j.get("type"), dict)
                          else str(j.get("type") or "")))
    return [x for x in out if x]


def src_rippling(slug):
    d = fetch(f"https://api.rippling.com/platform/api/ats/v1/board/{slug}/jobs")
    if not isinstance(d, list):
        return []
    return [x for x in (mk_job(j.get("name"), slug, j.get("workLocation", {}).get("label", "")
            if isinstance(j.get("workLocation"), dict) else str(j.get("workLocation") or ""),
            j.get("url"), f"Rippling:{slug}", str(j.get("department") or ""))
            for j in d) if x]


def src_smartrecruiters(slug):
    d = fetch(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100")
    if not isinstance(d, dict):
        return []
    out = []
    for j in (d.get("content") or []):
        loc = j.get("location") or {}
        out.append(mk_job(j.get("name"), (j.get("company") or {}).get("name") or slug,
                          ", ".join(filter(None, [loc.get("city"), loc.get("country")])),
                          j.get("ref") or f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}",
                          f"SmartRecruiters:{slug}",
                          " ".join(filter(None, [(j.get("department") or {}).get("label", ""),
                                                 (j.get("typeOfEmployment") or {}).get("label", ""),
                                                 (j.get("experienceLevel") or {}).get("label", "")])),
                          parse_date(j.get("releasedDate")),
                          (j.get("typeOfEmployment") or {}).get("label", "")))
    return [x for x in out if x]


def src_jazzhr(slug):
    txt = fetch(f"https://{slug}.applytojob.com/apply/jobs/feed", as_json=False)
    if not txt or "<item" not in txt:
        return []
    try:
        root = ET.fromstring(txt)
    except Exception:
        return []
    out = []
    for item in root.iter("item"):
        g = lambda t: (item.find(t).text or "") if item.find(t) is not None else ""
        out.append(mk_job(g("title"), slug, "", g("link"), f"JazzHR:{slug}",
                          g("description"), parse_date(g("pubDate"))))
    return [x for x in out if x]


def src_pinpoint(slug):
    d = fetch(f"https://{slug}.pinpointhq.com/postings.json")
    if not isinstance(d, dict):
        return []
    out = []
    for j in (d.get("data") or []):
        a = j.get("attributes") or j
        out.append(mk_job(a.get("title"), slug, a.get("location", ""),
                          a.get("url") or a.get("apply_url"), f"Pinpoint:{slug}",
                          a.get("description", ""), parse_date(a.get("published_at")),
                          a.get("employment_type", "")))
    return [x for x in out if x]


ATS = [src_greenhouse, src_lever, src_ashby, src_recruitee, src_workable,
       src_personio, src_bamboo, src_breezy, src_rippling, src_smartrecruiters,
       src_jazzhr, src_pinpoint]
ATS_NAMES = ["greenhouse", "lever", "ashby", "recruitee", "workable",
             "personio", "bamboohr", "breezy", "rippling", "smartrecruiters",
             "jazzhr", "pinpoint"]


# ── Workday ו-Comeet: דורשים מזהה ייעודי, לא ניתן לניחוש משם החברה ──

BOARDS_PATH = os.path.join(HERE, "boards.json")


def load_boards():
    if os.path.exists(BOARDS_PATH):
        try:
            b = json.load(open(BOARDS_PATH, encoding="utf-8"))
            return {k: v for k, v in b.items() if isinstance(v, list)}
        except Exception:
            pass
    return {"workday": [], "comeet": []}


def save_boards(b):
    json.dump(b, open(BOARDS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


WD_RE = re.compile(r"https://(?P<tenant>[^./]+)\.(?P<shard>wd\d+)\.myworkdayjobs\.com"
                   r"/(?:[a-z]{2}-[A-Z]{2}/)?(?P<site>[^/?#]+)")


def src_workday(entry, max_pages=5):
    """
    Workday חושפת POST בלבד, ודורשת tenant + shard + site.
    רשימת המשרות מחזירה תקציר בלבד; התיאור המלא הוא קריאה נוספת לכל משרה,
    ולכן אנחנו מסתפקים בתקציר, בכותרת ובסוג המשרה.
    """
    t, sh, site = entry.get("tenant"), entry.get("shard"), entry.get("site")
    name = entry.get("name") or t
    if not (t and sh and site):
        return []
    base = "https://%s.%s.myworkdayjobs.com" % (t, sh)
    api = "%s/wday/cxs/%s/%s/jobs" % (base, t, site)
    out, offset = [], 0
    for _ in range(max_pages):
        d = post_json(api, {"appliedFacets": {}, "limit": 20, "offset": offset,
                            "searchText": ""}, {"Referer": "%s/%s" % (base, site)})
        posts = (d or {}).get("jobPostings") or []
        if not posts:
            break
        for j in posts:
            path = j.get("externalPath") or ""
            out.append(mk_job(j.get("title"), name, j.get("locationsText", ""),
                              "%s/%s%s" % (base, site, path), "Workday:%s" % t,
                              " ".join(str(x) for x in (j.get("bulletFields") or [])),
                              parse_date(j.get("startDate")), j.get("timeType", "")))
        offset += 20
        if offset >= int((d or {}).get("total") or 0):
            break
    return [x for x in out if x]


COMEET_RE = re.compile(r"COMPANY_DATA\s*=\s*(\{.*?\})\s*[;<]", re.S)


def src_comeet(entry):
    """
    Comeet נפוצה מאוד בישראל. ה-token מתחלף מדי פעם, ולכן שולפים אותו
    מדף הקריירה עצמו בכל ריצה במקום לשמור אותו בקובץ.
    """
    uid, token = entry.get("uid"), entry.get("token")
    name = entry.get("name") or uid
    page = entry.get("careers_url")
    if page and not (uid and token):
        html = fetch(page, as_json=False)
        m = COMEET_RE.search(html or "")
        if m:
            try:
                data = json.loads(m.group(1))
                uid = data.get("uid") or data.get("company_uid") or uid
                token = data.get("token") or uid
            except Exception:
                pass
    if not uid:
        return []
    d = fetch("https://www.comeet.co/careers-api/2.0/company/"
              "%s/positions?token=%s&details=true" % (uid, token or uid))
    if not isinstance(d, list):
        return []
    out = []
    for j in d:
        loc = j.get("location") or {}
        locname = loc.get("name") if isinstance(loc, dict) else str(loc)
        out.append(mk_job(j.get("name"), j.get("company_name") or name, locname,
                          j.get("url_comeet_hosted_page") or j.get("url_active_page"),
                          "Comeet:%s" % uid,
                          " ".join(str(x.get("value", "")) for x in (j.get("details") or [])),
                          parse_date(j.get("time_updated")),
                          j.get("employment_type", "")))
    return [x for x in out if x]


def learn_board(url, name=None):
    """
    מקבל כתובת של דף קריירה ומזהה אם היא Workday או Comeet,
    ומוסיף אותה ל-boards.json כדי שהריצות הבאות יכללו אותה.
    """
    b = load_boards()
    m = WD_RE.search(url or "")
    if m:
        e = {"name": name or m.group("tenant"), "tenant": m.group("tenant"),
             "shard": m.group("shard"), "site": m.group("site")}
        if e not in b.setdefault("workday", []):
            b["workday"].append(e)
            save_boards(b)
        return ("workday", e)
    if "comeet.co" in (url or ""):
        e = {"name": name or "comeet", "careers_url": url}
        if e not in b.setdefault("comeet", []):
            b["comeet"].append(e)
            save_boards(b)
        return ("comeet", e)
    return (None, None)


def collect_named_boards(log=None, workers=8):
    """מושך מכל לוחות ה-Workday וה-Comeet הרשומים ב-boards.json."""
    b = load_boards()
    tasks = ([(src_workday, e, "Workday:%s" % e.get("tenant")) for e in b.get("workday", [])] +
             [(src_comeet, e, "Comeet:%s" % e.get("name")) for e in b.get("comeet", [])])
    if not tasks:
        return [], []
    if log:
        log("בודקת %d לוחות Workday/Comeet מוגדרים…" % len(tasks))
    jobs, hits = [], []
    with futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn, e): label for fn, e, label in tasks}
        for f in futures.as_completed(futs):
            try:
                res = f.result() or []
            except Exception:
                res = []
            if res:
                hits.append("%s (%d)" % (futs[f], len(res)))
                jobs.extend(res)
    return jobs, hits


# ── לוחות משרות מרחוק ─────────────────────────────────────────────────────

def src_remoteok():
    d = fetch("https://remoteok.com/api")
    if not isinstance(d, list):
        return []
    out = []
    for j in d:
        if isinstance(j, dict) and j.get("position"):
            out.append(mk_job(j["position"], j.get("company"), j.get("location") or "Remote",
                              j.get("url") or j.get("apply_url"), "RemoteOK",
                              j.get("description", ""), parse_date(j.get("date")),
                              rate=(f"${j.get('salary_min')}–${j.get('salary_max')}"
                                    if j.get("salary_min") else "")))
    return [x for x in out if x]


def src_remotive(term):
    d = fetch("https://remotive.com/api/remote-jobs?limit=100&search=" + urllib.parse.quote(term))
    if not isinstance(d, dict):
        return []
    return [x for x in (mk_job(j.get("title"), j.get("company_name"),
            j.get("candidate_required_location"), j.get("url"), "Remotive",
            j.get("description", ""), parse_date(j.get("publication_date")),
            j.get("job_type", ""), j.get("salary", "")) for j in d.get("jobs") or []) if x]


def src_himalayas():
    d = fetch("https://himalayas.app/jobs/api?limit=200")
    if not isinstance(d, dict):
        return []
    out = []
    for j in d.get("jobs") or []:
        locs = j.get("locationRestrictions") or []
        out.append(mk_job(j.get("title"), j.get("companyName"),
                          ", ".join(locs) if locs else "Remote",
                          j.get("applicationLink") or j.get("guid"), "Himalayas",
                          j.get("description", ""), parse_date(j.get("pubDate")),
                          j.get("employmentType", "")))
    return [x for x in out if x]


def src_jobicy(term):
    d = fetch("https://jobicy.com/api/v2/remote-jobs?count=50&tag=" +
              urllib.parse.quote(term.replace(" ", "-")))
    if not isinstance(d, dict):
        return []
    return [x for x in (mk_job(j.get("jobTitle"), j.get("companyName"), j.get("jobGeo"),
            j.get("url"), "Jobicy", j.get("jobExcerpt", ""), parse_date(j.get("pubDate")),
            ", ".join(j.get("jobType") or [])) for j in d.get("jobs") or []) if x]


def src_arbeitnow():
    d = fetch("https://www.arbeitnow.com/api/job-board-api")
    if not isinstance(d, dict):
        return []
    return [x for x in (mk_job(j.get("title"), j.get("company_name"), j.get("location"),
            j.get("url"), "Arbeitnow", j.get("description", ""), parse_date(j.get("created_at")),
            ", ".join(j.get("job_types") or [])) for j in d.get("data") or []) if x]


def src_workingnomads():
    d = fetch("https://www.workingnomads.com/api/exposed_jobs/")
    if not isinstance(d, list):
        return []
    return [x for x in (mk_job(j.get("title"), j.get("company_name"),
            j.get("location") or "Remote", j.get("url"), "WorkingNomads",
            j.get("description", ""), parse_date(j.get("pub_date"))) for j in d) if x]


def src_wwr():
    out = []
    for feed in ("https://weworkremotely.com/categories/remote-product-jobs.rss",
                 "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
                 "https://weworkremotely.com/categories/remote-programming-jobs.rss",
                 "https://weworkremotely.com/categories/remote-design-jobs.rss",
                 "https://weworkremotely.com/categories/remote-customer-support-jobs.rss",
                 "https://weworkremotely.com/categories/remote-sales-and-marketing-jobs.rss",
                 "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
                 "https://weworkremotely.com/categories/all-other-remote-jobs.rss"):
        txt = fetch(feed, as_json=False)
        if not txt:
            continue
        try:
            root = ET.fromstring(txt)
        except Exception:
            continue
        for item in root.iter("item"):
            g = lambda t: (item.find(t).text if item.find(t) is not None else "")
            raw = g("title") or ""
            company, _, title = raw.partition(":")
            out.append(mk_job(title.strip() or raw, company.strip(), g("region") or "Remote",
                              g("link"), "WeWorkRemotely", g("description"), parse_date(g("pubDate"))))
    return [x for x in out if x]


# ════════════════════════════════════════════════════════════════════
# 4 · גילוי חברות
# ════════════════════════════════════════════════════════════════════

CACHE_PATH = os.path.join(DATA_DIR, "discovered.json")


def slugify(name):
    n = re.sub(r"\b(inc|ltd|llc|gmbh|corp|co|the|company|technologies|technology|labs|group|"
               r"solutions|systems|software|holdings|sa|bv|ag|plc)\b", "", (name or "").lower())
    n = re.sub(r"[^a-z0-9]+", "", n)
    return n if 2 < len(n) < 30 else ""


def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            return json.load(open(CACHE_PATH, encoding="utf-8"))
        except Exception:
            pass
    return {"hits": {}, "misses": []}


def save_cache(c):
    c["misses"] = c["misses"][-4000:]
    json.dump(c, open(CACHE_PATH, "w", encoding="utf-8"), ensure_ascii=False)


def discover(names, log=None, workers=16, budget=40):
    """
    מקבל שמות חברות, מנסה כל אחד מול חמש מערכות הגיוס, ומחזיר את מה שנמצא.
    התוצאות נשמרות ב-data/discovered.json כדי שריצות הבאות יהיו מהירות.
    """
    cache = load_cache()
    known, misses = cache["hits"], set(cache["misses"])
    slugs, seen = [], set()
    for n in names:
        s = slugify(n)
        if s and s not in seen:
            seen.add(s); slugs.append(s)

    fresh = [s for s in slugs if s not in known and s not in misses][:budget]
    todo = [(s, a) for s in fresh for a in range(len(ATS))]
    if log and todo:
        log(f"בודקת {len(fresh)} חברות חדשות מול {len(ATS)} מערכות גיוס…")

    found = 0
    if todo:
        with futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(ATS[a], s): (s, a) for s, a in todo}
            for f in futures.as_completed(futs):
                s, a = futs[f]
                try:
                    res = f.result() or []
                except Exception:
                    res = []
                if res:
                    known.setdefault(s, [])
                    if ATS_NAMES[a] not in known[s]:
                        known[s].append(ATS_NAMES[a]); found += 1
        for s, _ in todo:
            if s not in known:
                misses.add(s)
    cache["hits"], cache["misses"] = known, sorted(misses)
    save_cache(cache)
    if log and found:
        log(f"התגלו {found} לוחות גיוס פעילים חדשים.")
    return known


def collect_ats(known, log=None, workers=14):
    jobs, hits = [], []
    tasks = [(ATS[ATS_NAMES.index(a)], s) for s, ats in known.items()
             for a in ats if a in ATS_NAMES]
    if not tasks:
        return jobs, hits
    if log:
        log(f"מושכת משרות מ-{len(tasks)} לוחות גיוס פעילים…")
    with futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn, s): s for fn, s in tasks}
        for f in futures.as_completed(futs):
            try:
                res = f.result() or []
            except Exception:
                res = []
            if res:
                hits.append(f"{futs[f]} ({len(res)})")
                jobs.extend(res)
    return jobs, hits


def collect_boards(terms, log=None):
    jobs, hits = [], []
    tasks = [("RemoteOK", src_remoteok), ("Himalayas", src_himalayas),
             ("Arbeitnow", src_arbeitnow), ("WorkingNomads", src_workingnomads),
             ("WeWorkRemotely", src_wwr)]
    tasks += [(f"Remotive:{t}", (lambda t=t: src_remotive(t))) for t in terms[:4]]
    tasks += [(f"Jobicy:{t}", (lambda t=t: src_jobicy(t))) for t in terms[:3]]
    if log:
        log(f"סורקת {len(tasks)} לוחות משרות ציבוריים…")
    with futures.ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(fn): n for n, fn in tasks}
        for f in futures.as_completed(futs):
            try:
                res = f.result() or []
            except Exception:
                res = []
            if res:
                hits.append(f"{futs[f]} ({len(res)})")
                jobs.extend(res)
    return jobs, hits


# ════════════════════════════════════════════════════════════════════
# 5 · סינון וניקוד
# ════════════════════════════════════════════════════════════════════

def title_ok(job, prof):
    t = job["title"].lower()
    if any(x in t for x in prof.get("title_hard_exclude", [])):
        return False
    return any(x in t for x in prof["title_must_match"])


# ── גיאוגרפיה: לאיזו מדינה שייכת המשרה ─────────────────────────────
# הכלל: "remote"/"hybrid" הן צורת עבודה, לא מיקום. משרה שכתוב עליה
# "Remote — Berlin" היא משרה בגרמניה, ומי שביקש ישראל לא אמור לקבל אותה.

GEO_COUNTRIES = {
 "IL": ("israel", "ישראל", "tel aviv", "tel-aviv", "telaviv", "תל אביב", "תל־אביב",
        "jerusalem", "ירושלים", "haifa", "חיפה", "herzliya", "herzeliya", "הרצליה",
        "raanana", "ra'anana", "רעננה", "netanya", "נתניה", "petah tikva", "פתח תקווה",
        "ramat gan", "רמת גן", "rehovot", "רחובות", "beer sheva", "be'er sheva",
        "באר שבע", "yokneam", "יקנעם", "kfar saba", "כפר סבא", "holon", "חולון",
        "rishon", "ראשון לציון", "ashdod", "אשדוד", "modiin", "מודיעין",
        "hod hasharon", "הוד השרון", "givatayim", "גבעתיים", "ness ziona", "נס ציונה",
        "airport city", "caesarea", "קיסריה", "eilat", "אילת"),
 "US": ("united states", "u.s.", "u.s.a", "usa", "us", "new york", "nyc", "brooklyn",
        "san francisco", "bay area", "silicon valley", "palo alto", "mountain view",
        "san jose", "sunnyvale", "santa clara", "seattle", "bellevue", "boston",
        "austin", "dallas", "houston", "denver", "boulder", "chicago", "atlanta",
        "miami", "orlando", "tampa", "phoenix", "portland", "los angeles",
        "san diego", "las vegas", "minneapolis", "detroit", "philadelphia",
        "pittsburgh", "washington dc", "arlington va", "raleigh", "charlotte",
        "nashville", "salt lake city", "kansas city", "st. louis", "columbus ohio",
        "california", "texas", "florida", "colorado", "massachusetts", "illinois",
        "new jersey", "virginia", "arizona", "utah", "oregon", "michigan",
        "north carolina", "pennsylvania", "washington state"),
 "CA": ("canada", "toronto", "vancouver", "montreal", "ottawa", "calgary",
        "edmonton", "waterloo", "ontario", "quebec", "british columbia"),
 "UK": ("united kingdom", "u.k.", "england", "scotland", "wales",
        "northern ireland", "london", "manchester", "birmingham uk", "leeds",
        "glasgow", "edinburgh", "bristol", "sheffield", "liverpool", "newcastle",
        "nottingham", "brighton", "oxford", "milton keynes", "belfast", "cardiff"),
 "IE": ("ireland", "dublin", "galway", "limerick"),
 "DE": ("germany", "deutschland", "berlin", "munich", "münchen", "muenchen",
        "hamburg", "frankfurt", "cologne", "köln", "stuttgart", "düsseldorf",
        "dusseldorf", "leipzig", "dresden", "nuremberg", "nürnberg", "karlsruhe",
        "hannover", "bremen", "essen", "dortmund", "bavaria", "bayern"),
 "AT": ("austria", "österreich", "vienna", "wien", "graz", "salzburg", "linz"),
 "CH": ("switzerland", "schweiz", "suisse", "zurich", "zürich", "geneva", "genève",
        "basel", "bern", "lausanne", "lugano", "zug"),
 "NL": ("netherlands", "holland", "amsterdam", "rotterdam", "utrecht", "eindhoven",
        "the hague", "den haag", "delft", "groningen"),
 "BE": ("belgium", "brussels", "bruxelles", "antwerp", "antwerpen", "ghent", "leuven"),
 "LU": ("luxembourg", "luxemburg"),
 "FR": ("france", "paris", "lyon", "marseille", "toulouse", "bordeaux", "lille",
        "nantes", "montpellier", "strasbourg", "grenoble", "sophia antipolis"),
 "ES": ("spain", "españa", "espana", "madrid", "barcelona", "valencia", "seville",
        "sevilla", "malaga", "málaga", "bilbao", "zaragoza", "canary islands"),
 "PT": ("portugal", "lisbon", "lisboa", "porto", "braga", "coimbra", "madeira"),
 "IT": ("italy", "italia", "milan", "milano", "rome", "roma", "turin", "torino",
        "bologna", "florence", "firenze", "naples", "napoli", "venice"),
 "GR": ("greece", "athens", "thessaloniki", "crete"),
 "CY": ("cyprus", "nicosia", "limassol", "larnaca"),
 "MT": ("malta", "valletta"),
 "SE": ("sweden", "sverige", "stockholm", "gothenburg", "göteborg", "malmö", "malmo",
        "uppsala", "lund"),
 "NO": ("norway", "norge", "oslo", "bergen", "trondheim", "stavanger"),
 "DK": ("denmark", "danmark", "copenhagen", "københavn", "aarhus", "odense"),
 "FI": ("finland", "suomi", "helsinki", "espoo", "tampere", "oulu"),
 "IS": ("iceland", "reykjavik", "reykjavík"),
 "PL": ("poland", "polska", "warsaw", "warszawa", "krakow", "kraków", "cracow",
        "wroclaw", "wrocław", "gdansk", "gdańsk", "poznan", "poznań", "lodz", "katowice"),
 "CZ": ("czech republic", "czechia", "prague", "praha", "brno", "ostrava"),
 "SK": ("slovakia", "bratislava", "kosice", "košice"),
 "HU": ("hungary", "budapest", "debrecen", "szeged"),
 "RO": ("romania", "bucharest", "bucurești", "cluj", "cluj-napoca", "timisoara",
        "timișoara", "iasi", "iași", "brasov", "brașov"),
 "BG": ("bulgaria", "sofia", "plovdiv", "varna", "burgas"),
 "HR": ("croatia", "zagreb", "split", "rijeka"),
 "SI": ("slovenia", "ljubljana", "maribor"),
 "RS": ("serbia", "belgrade", "beograd", "novi sad", "nis", "niš"),
 "BA": ("bosnia", "sarajevo", "banja luka"),
 "MK": ("north macedonia", "skopje"),
 "AL": ("albania", "tirana"),
 "EE": ("estonia", "tallinn", "tartu"),
 "LV": ("latvia", "riga", "rīga"),
 "LT": ("lithuania", "vilnius", "kaunas"),
 "UA": ("ukraine", "kyiv", "kiev", "lviv", "kharkiv", "odesa", "odessa", "dnipro"),
 "BY": ("belarus", "minsk"),
 "MD": ("moldova", "chisinau", "chișinău"),
 "RU": ("russia", "moscow", "st petersburg", "saint petersburg", "novosibirsk",
        "yekaterinburg", "kazan"),
 "TR": ("turkey", "türkiye", "turkiye", "istanbul", "ankara", "izmir", "antalya"),
 "GE": ("tbilisi", "batumi"),
 "AM": ("armenia", "yerevan"),
 "AZ": ("azerbaijan", "baku"),
 "AE": ("united arab emirates", "u.a.e", "uae", "dubai", "abu dhabi", "sharjah"),
 "SA": ("saudi arabia", "riyadh", "jeddah", "dammam", "neom"),
 "QA": ("qatar", "doha"),
 "KW": ("kuwait",),
 "BH": ("bahrain", "manama"),
 "OM": ("oman", "muscat"),
 "JO": ("jordan", "amman"),
 "LB": ("lebanon", "beirut"),
 "EG": ("egypt", "cairo", "alexandria", "giza"),
 "MA": ("morocco", "casablanca", "rabat", "marrakech", "tangier"),
 "TN": ("tunisia", "tunis"),
 "DZ": ("algeria", "algiers"),
 "ZA": ("south africa", "johannesburg", "cape town", "durban", "pretoria"),
 "NG": ("nigeria", "lagos", "abuja"),
 "KE": ("kenya", "nairobi", "mombasa"),
 "GH": ("ghana", "accra"),
 "ET": ("ethiopia", "addis ababa"),
 "IN": ("india", "bangalore", "bengaluru", "hyderabad", "mumbai", "bombay", "pune",
        "chennai", "delhi", "gurgaon", "gurugram", "noida", "kolkata", "ahmedabad",
        "kochi", "jaipur", "indore", "coimbatore"),
 "PK": ("pakistan", "karachi", "lahore", "islamabad"),
 "BD": ("bangladesh", "dhaka"),
 "LK": ("sri lanka", "colombo"),
 "NP": ("nepal", "kathmandu"),
 "CN": ("china", "beijing", "shanghai", "shenzhen", "guangzhou", "hangzhou",
        "chengdu", "suzhou", "wuhan", "xi'an"),
 "HK": ("hong kong", "hongkong"),
 "TW": ("taiwan", "taipei", "hsinchu", "kaohsiung"),
 "JP": ("japan", "tokyo", "osaka", "kyoto", "yokohama", "nagoya", "fukuoka"),
 "KR": ("south korea", "seoul", "busan", "incheon"),
 "SG": ("singapore",),
 "MY": ("malaysia", "kuala lumpur", "penang", "johor"),
 "TH": ("thailand", "bangkok", "chiang mai", "phuket"),
 "VN": ("vietnam", "viet nam", "ho chi minh", "hanoi", "da nang"),
 "ID": ("indonesia", "jakarta", "bandung", "surabaya", "bali"),
 "PH": ("philippines", "manila", "makati", "cebu", "taguig", "pasig", "quezon city"),
 "AU": ("australia", "sydney", "melbourne", "brisbane", "perth", "adelaide",
        "canberra", "gold coast"),
 "NZ": ("new zealand", "auckland", "wellington", "christchurch"),
 "BR": ("brazil", "brasil", "sao paulo", "são paulo", "rio de janeiro",
        "belo horizonte", "porto alegre", "curitiba", "recife", "florianopolis",
        "florianópolis", "brasilia", "brasília"),
 "AR": ("argentina", "buenos aires", "cordoba argentina", "rosario", "mendoza"),
 "CL": ("chile", "santiago de chile"),
 "CO": ("colombia", "bogota", "bogotá", "medellin", "medellín", "cali"),
 "PE": ("peru", "lima"),
 "UY": ("uruguay", "montevideo"),
 "EC": ("ecuador", "quito", "guayaquil"),
 "MX": ("mexico", "méxico", "mexico city", "ciudad de méxico", "guadalajara",
        "monterrey", "queretaro", "querétaro", "tijuana", "puebla", "merida"),
 "CR": ("costa rica", "san jose costa rica"),
 "PA": ("panama", "panamá"),
 "GT": ("guatemala",),
 "DO": ("dominican republic", "santo domingo"),
 "JM": ("jamaica", "kingston jamaica"),
}

# גושים אזוריים — קיצור שנפוץ במודעות. כל גוש מתורגם לקבוצת מדינות.
_EU = {"IE","DE","AT","CH","NL","BE","LU","FR","ES","PT","IT","GR","CY","MT","SE",
       "NO","DK","FI","IS","PL","CZ","SK","HU","RO","BG","HR","SI","RS","BA","MK",
       "AL","EE","LV","LT","UK"}
_MEA = {"IL","AE","SA","QA","KW","BH","OM","JO","LB","EG","MA","TN","DZ","ZA",
        "NG","KE","GH","ET","TR"}
_APAC = {"IN","CN","HK","TW","JP","KR","SG","MY","TH","VN","ID","PH","AU","NZ",
         "PK","BD","LK","NP"}
_LATAM = {"BR","AR","CL","CO","PE","UY","EC","MX","CR","PA","GT","DO","JM"}
_NA = {"US","CA"}

GEO_BLOCS = {
    "emea": _EU | _MEA,
    "europe": _EU,
    "european union": _EU,
    "eea": _EU,
    "dach": {"DE", "AT", "CH"},
    "benelux": {"NL", "BE", "LU"},
    "nordics": {"SE", "NO", "DK", "FI", "IS"},
    "iberia": {"ES", "PT"},
    "baltics": {"EE", "LV", "LT"},
    "middle east": _MEA,
    "mena": {"AE","SA","QA","KW","BH","OM","JO","LB","EG","MA","TN","DZ","IL"},
    "apac": _APAC,
    "asia pacific": _APAC,
    "asia-pacific": _APAC,
    "southeast asia": {"SG","MY","TH","VN","ID","PH"},
    "latam": _LATAM,
    "latin america": _LATAM,
    "south america": {"BR","AR","CL","CO","PE","UY","EC"},
    "north america": _NA,
    "americas": _NA | _LATAM,
    "namer": _NA,
}

# אילו מדינות נחשבות "בתוך השוק" לכל שוק שאפשר לבחור בממשק
MARKET_GEO = {
    "israel": {"IL"},
    "europe": _EU,
    "usa": {"US"},
    "remote_global": None,          # None = אין הגבלה גיאוגרפית
}

# ביטויים שמוציאים משרה החוצה גם אם המיקום נראה תמים
GEO_HARD_BLOCK = {
    "IL": (),
    "US": ("us only", "usa only", "united states only", "u.s. only",
           "must be located in the us", "must reside in the united states",
           "us work authorization", "authorized to work in the united states",
           "must be authorized to work in the u.s", "us citizens only",
           "green card", "w2 only", "must be based in the us"),
    "CA": ("canada only", "must be located in canada"),
    "UK": ("uk only", "united kingdom only", "right to work in the uk",
           "must be based in the uk"),
    "IN": ("india only", "must be based in india"),
    "AU": ("australia only",),
    "BR": ("brazil only",),
    "PH": ("philippines only",),
    "_EU": ("eu only", "european union only", "must be based in the eu",
            "eu work authorization", "must reside in the eu", "europe only",
            "must be located in europe"),
}

_GEO_INDEX = [(code, term) for code, terms in GEO_COUNTRIES.items() for term in terms]
_GEO_INDEX.sort(key=lambda x: -len(x[1]))        # ביטויים ארוכים קודם


def geo_codes(text):
    """אילו מדינות/גושים מוזכרים בטקסט. מחזיר set של קודי מדינה."""
    t = (text or "").lower()
    if not t.strip():
        return set()
    found = set()
    for bloc, codes in GEO_BLOCS.items():
        if term_in(t, bloc):
            found |= codes
    for code, term in _GEO_INDEX:
        if term_in(t, term):
            found.add(code)
    return found


def _hard_blocked(blob, allowed):
    """ביטויי 'רק בארץ X' — חוסמים אם X אינו בשוק שנבחר."""
    for key, phrases in GEO_HARD_BLOCK.items():
        codes = _EU if key == "_EU" else {key}
        if allowed & codes:
            continue
        for p in phrases:
            if p in blob:
                return p
    return False


def region_of(text, market):
    """לאילו אזורים בתוך המדינה שייך המיקום. set ריק = לא זוהה."""
    mk = _load_markets().get(market, {})
    hit = set()
    t = (text or "").lower()
    for name, reg in (mk.get("regions") or {}).items():
        if name == "all":
            continue
        for term in (reg.get("positive") or {}):
            if term_in(t, term):
                hit.add(name)
                break
    return hit


def location_ok(job, prof):
    """
    סינון קשיח לפי מיקום.
    "remote" ו-"hybrid" הן צורת עבודה ולא מיקום — הן לבדן לא מכשירות משרה.
    מה שקובע הוא איזו מדינה מוזכרת בשדה המיקום ובכותרת:
      • לא זוהתה מדינה           → נשארת (משרה גלובלית אמיתית)
      • זוהתה מדינה שבשוק שנבחר  → נשארת
      • זוהתה רק מדינה אחרת      → יוצאת
    """
    lr = prof["location_rules"]
    if not lr.get("strict"):
        return True
    allowed = lr.get("allowed_codes")
    if not allowed:                      # remote_global — אין משמעות לסינון מדינה
        return True

    where = " ".join([job.get("location", ""), job.get("title", "")])
    found = geo_codes(where)

    if found and not (found & allowed):
        job["_loc_reason"] = "מדינה אחרת"
        return False

    blob = " ".join([job.get("location", ""), job.get("title", ""),
                     job.get("employment_type", ""), job.get("desc", "")]).lower()
    hb = _hard_blocked(blob, allowed)
    if hb:
        job["_loc_reason"] = f"מוגבל ל\"{hb}\""
        return False

    # אזור בתוך המדינה — נאכף רק אם המשתמש בחר אזור מסוים והעיר זוהתה
    reg = lr.get("region")
    if reg and reg != "all" and (found & allowed):
        hit = region_of(job.get("location", ""), lr.get("market", ""))
        if hit and reg not in hit:
            job["_loc_reason"] = "אזור אחר בארץ"
            return False
    return True


def job_allowed(job, prof):
    """מילים שהמשתמש ביקש לסנן החוצה — מוציאות את המשרה לגמרי."""
    ex = prof.get("exclude_terms") or []
    if not ex:
        return True
    blob = " ".join([job["title"], job["company"], job["location"],
                     job["employment_type"], job["desc"]]).lower()
    return not any(term_in(blob, t) for t in ex)


def _hits(text, terms):
    return {k: v for k, v in terms.items() if term_in(text, k.lower())}


def score(job, prof, now=None):
    now = now or datetime.now(timezone.utc)
    blob = " ".join([job["title"], job["company"], job["location"],
                     job["employment_type"], job["desc"]]).lower()
    head = (job["title"] + " " + job["location"] + " " + job["employment_type"]).lower()
    bd, why = {}, []

    sc = prof["scope_signals"]
    tag = resolve_scope_tag(blob)
    job["scope_tag"] = tag
    h = _hits(blob, sc["terms"])
    raw = (max(h.values()) if h else 0) + (min(8, 2 * (len(h) - 1)) if len(h) > 1 else 0)
    mismatch = (sc.get("explicit") and tag not in sc["families"]
                and tag not in ("hybrid", "unknown"))
    if mismatch:
        raw = min(raw, 6) - 26                       # סוג העסקה לא מה שביקשת
    bd["scope"] = max(-sc["weight"], min(sc["weight"], raw * sc["weight"] / 40.0))
    if h and not mismatch:
        why.append("היקף: " + ", ".join(sorted(h, key=h.get, reverse=True)[:3]))
    if mismatch:
        why.append("⚠ סוג העסקה: " + (SCOPE_FAMILIES[tag]["he"] if tag in SCOPE_FAMILIES else tag))

    dm = prof["domains"]
    h = _hits(blob, dm["terms"])
    bd["domain"] = min(dm["weight"], sum(sorted(h.values(), reverse=True)[:5]) * dm["weight"] / 95.0)
    if h:
        why.append("תחום: " + ", ".join(sorted(h, key=h.get, reverse=True)[:4]))

    lr = prof["location_rules"]
    p, n = _hits(head + " " + blob[:1500], lr["positive"]), _hits(blob, lr["negative"])
    raw = (max(p.values()) if p else 0) + sum(n.values())
    # מדינה: גם כשהסינון הקשיח כבוי, משרה במדינה אחרת יורדת בדירוג ומסומנת
    allowed, foreign = lr.get("allowed_codes"), False
    if allowed:
        codes = geo_codes(job["location"] + " " + job["title"])
        if codes and not (codes & allowed):
            foreign, raw = True, raw - 30
        elif codes:
            raw = max(raw, 18) + 2       # עיר בארץ שנבחרה שווה לפחות כמו "israel"
    job["off_market"] = foreign
    bd["location"] = max(-lr["weight"], min(lr["weight"], raw * lr["weight"] / 25.0))
    if foreign:
        why.append("⚠ מדינה אחרת: " + (job["location"] or job["title"])[:40])
    elif p:
        why.append("מיקום: " + max(p, key=p.get))
    if n:
        why.append("⚠ " + ", ".join(list(n)[:2]))

    sn = prof["seniority"]
    raw = sum(_hits(job["title"].lower(), sn["terms"]).values())
    bd["seniority"] = max(-sn["weight"] * 2, min(sn["weight"], raw * sn["weight"] / 12.0))

    fr = prof["freshness"]
    dt = parse_date(job.get("posted"))
    if dt:
        age = (now - dt).days
        job["age_days"] = age
        bd["freshness"] = (fr["weight"] if age <= fr["days_full_score"] else
                           fr["stale_penalty"] if age >= fr["days_zero_score"] else
                           fr["weight"] * (1 - (age - fr["days_full_score"]) /
                                           (fr["days_zero_score"] - fr["days_full_score"])))
    else:
        job["age_days"] = None
        bd["freshness"] = fr["weight"] * 0.4

    job["score"] = int(max(0, min(100, round(sum(bd.values())))))
    job["breakdown"] = {k: round(v, 1) for k, v in bd.items()}
    job["reasons"] = why
    return job


def dedupe(jobs):
    seen, out = set(), []
    for j in sorted(jobs, key=lambda x: -x.get("score", 0)):
        k = re.sub(r"[^a-z0-9֐-׿]", "", (j["title"] + j["company"]).lower())
        if k not in seen:
            seen.add(k); out.append(j)
    return out


# ════════════════════════════════════════════════════════════════════
# 6 · חיפוש מלא
# ════════════════════════════════════════════════════════════════════

def search(prof, min_score=35, limit=300, use_ats=True, use_boards=True,
           auto_discover=True, log=None):
    log = log or (lambda *_: None)
    raw, sources = [], []

    if use_boards:
        j, h = collect_boards(prof["search_terms"], log)
        raw += j; sources += h
        log(f"{len(j)} משרות מלוחות ציבוריים.")

    if use_ats:
        names = list(prof.get("companies") or [])
        if auto_discover:
            # גילוי: שמות החברות שראינו בלוחות הציבוריים הם מועמדים ל-ATS
            names += [j["company"] for j in raw if j.get("company")]
        known = discover(names, log)
        j, h = collect_ats(known, log)
        raw += j; sources += h
        j2, h2 = collect_named_boards(log)
        raw += j2; sources += h2
        log(f"{len(j) + len(j2)} משרות מלוחות גיוס של חברות.")

    # משרות שנאספו ידנית (seed_jobs.json) — נכנסות לכל ריצה
    seed_path = os.path.join(HERE, "seed_jobs.json")
    if os.path.exists(seed_path):
        try:
            seed = json.load(open(seed_path, encoding="utf-8"))
            for s in seed:
                s.setdefault("desc", ""); s.setdefault("employment_type", "")
                s.setdefault("rate", ""); s.setdefault("posted", "")
            raw += seed
            log(f"{len(seed)} משרות מקובץ האיסוף הידני.")
        except Exception:
            pass

    log(f"מסננת {len(raw)} משרות לפי כותרת ומדרגת…")
    now = datetime.now(timezone.utc)
    kept = [j for j in raw if title_ok(j, prof) and job_allowed(j, prof)]
    if prof["location_rules"].get("strict"):
        passed, dropped = [], Counter()
        for j in kept:
            if location_ok(j, prof):
                passed.append(j)
            else:
                dropped[j.get("_loc_reason", "מחוץ לאזור")] += 1
        if dropped:
            why = ", ".join(f"{k}: {v}" for k, v in dropped.most_common())
            log(f"סוננו {sum(dropped.values())} משרות מחוץ לאזור שנבחר ({why}).")
        kept = passed
    out = [score(j, prof, now) for j in kept]
    out = dedupe([j for j in out if j["score"] >= min_score])[:limit]
    log(f"נשארו {len(out)} משרות רלוונטיות.")
    return out, sorted(set(sources))
