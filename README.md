# JobDibs

**Call dibs on the job before anyone else.**
Your CV never leaves your computer.

A local job-search tool. Drop in a CV, type a job title, and it pulls open roles
from public company job boards and remote job boards, scores each one 0–100
against a profile it derives from your CV, and shows you a ranked dashboard.

Works for any kind of job — **full-time, part-time, fractional, contract,
student and internship** roles are all first-class choices. It's especially good
at the ones keyword filters miss, where the signal (part-time, interim,
parental-leave cover) is buried in the description rather than the title.

*[עברית](README.he.md)*

![screenshot](docs/screenshot.png)

---

## Run it

```bash
python3 app.py
```

Your browser opens at `http://127.0.0.1:8765`. That's it.

**No dependencies. No account. No server.** Python 3.8+ only — on macOS it
comes with the Command Line Tools macOS offers to install on first use; on
Windows, install it from python.org.

Not comfortable with a terminal? Don't use one:

- **macOS** — double-click **`Start JobDibs.command`** (blocked once by Gatekeeper — [how to allow it](HOW-TO-USE.md))
- **Windows** — double-click **`Start JobDibs.bat`**

**→ [Step-by-step guide for Windows and macOS](HOW-TO-USE.md)** ·
**[מדריך מלא בעברית](HOW-TO-USE.he.md)**

| Flag | |
|---|---|
| `--port 9000` | use a different port |
| `--no-browser` | don't open a browser |

---

## How it works

**1. It reads your CV.** `pdftext.py` extracts text from PDF using nothing but
the Python standard library — including CID/Identity-H fonts, the kind Word,
Pages and Google Docs produce, by parsing the embedded ToUnicode maps. DOCX is
read straight out of the zip. If `pypdf` or `pdftotext` happen to be installed
they're used when they give a better result. Scanned PDFs have no text to
extract; paste the text instead.

**2. It builds a matching profile.** Seniority is inferred from years of
experience found in the text, which then sets the title weights — a leadership
profile gets a bonus on "Head of" and a penalty on "Junior"; a junior profile
gets the reverse. Domain terms are matched against a lexicon of ~250 skills
across seventeen groups — product, growth, e-commerce, AI/data, design,
engineering, QA, delivery, finance, healthcare, education, legal, HR, sales,
hospitality, trades and admin — each weighted by how often it appears in your
CV. Short terms like `cad` or `rest` are matched on word boundaries so
"academy" and "restaurant" don't count.

**3. It finds companies by itself.** Every company name seen on the public
boards is normalised to a slug and probed against five ATS APIs. Hits are cached
in `data/discovered.json` and reused. The list grows on its own with each run —
the seed is ~76 Israeli companies in `markets.json`, but it doesn't stay that way.

**4. It scores.**

| Component | Weight | Measures |
|---|---|---|
| Employment type | 24 or 40 | the types you selected score; other types are penalised |
| Domain | 30 | the five strongest profile terms in the posting, including keywords you added by hand |
| Location | ±20 | per selected market **and region**; "US only" or a work-authorisation requirement is a heavy penalty |
| Seniority | ±10 | against the level derived from your CV |
| Freshness | ±10 | full score under a week, penalty over 45 days |

Reasons are shown under each result, so you can see why it scored what it did.

---

## Sources

**Company job boards (ATS), discovered automatically from a company name:**
Greenhouse · Lever · Ashby · Recruitee · Workable · Personio · BambooHR ·
Breezy · Rippling · SmartRecruiters · JazzHR · Pinpoint

**Workday and Comeet** need a tenant identifier that cannot be guessed from a
company name, so you add them once by pasting a careers URL — in the app, or:

```bash
python3 app.py --learn https://acme.wd3.myworkdayjobs.com/en-US/AcmeCareers --name Acme
python3 app.py --learn https://www.comeet.co/jobs/acme/12.345 --name Acme
```

They're saved to `boards.json` and included in every run from then on. Workday
is POST-only and paginates 20 at a time; Comeet's token rotates, so it's
re-read from the careers page on each run. Comeet is worth the effort in
Israel — a large share of Israeli tech companies use it.

**Job boards:** [RemoteOK](https://remoteok.com) ·
[Remotive](https://remotive.com) · [Himalayas](https://himalayas.app) ·
[Jobicy](https://jobicy.com) · [We Work Remotely](https://weworkremotely.com) ·
[Arbeitnow](https://www.arbeitnow.com) ·
[Working Nomads](https://www.workingnomads.com)

Some sites have no API — LinkedIn and most national job boards block automated
access entirely. For those, `seed_jobs.json` lets you paste listings in by hand
and have them scored alongside everything else. It ships empty.

All the sources above are public, unauthenticated endpoints. Requests go out from your own machine
at your own pace — there is no shared server and no shared IP.

---

## Privacy

There is no backend. The app binds to `127.0.0.1` and nothing is exposed to your
network. Your CV is parsed in your own Python process; the extracted text is
written only to `data/profiles.json` on your disk, and only if you press "save
search". No analytics, no telemetry, no crash reporting, no account.

The only outbound requests are to the job boards listed above, to fetch job
listings.

---

## Configuring

**A different market or region.** Add a block to `markets.json` with `label`,
`positive`, `negative`, `companies` and optionally `regions`. Both dropdowns are
built from that file, so anything you add appears automatically.

**A different role.** Unrecognised titles get variants generated automatically
(Senior / Lead / Head of / …). For precise control, add an entry to
`ROLE_EXPANSIONS` in `engine.py`.

**Scoring.** All weights live in `engine.py` — `SCOPE_FAMILIES`, `LEXICON`, and
the per-market location dictionaries in `markets.json`.

---

## Files

```
app.py           local server + API (standard library only)
engine.py        sources, profile building, company discovery, scoring
pdftext.py       standalone PDF extractor, CID/ToUnicode aware
ui.html          the entire interface
markets.json     markets: location dictionaries + seed company lists
seed_jobs.json   optional: listings you add by hand, injected into every run
data/            created on first run: discovered · profiles · state · last
```

---

## Status

Built for one person's job search and released because it might help someone
else. It is maintained on a best-effort basis by one person who has a startup to
run — issues and pull requests are welcome, but a reply is not guaranteed.

Job board endpoints change without notice. If a source stops returning results,
the app skips it silently and the dashboard footer shows which sources actually
responded.

Licensed under the **GNU AGPL-3.0**. You are free to use, study, change and
share it. If you distribute a modified version — or run one as a service that
other people use — you must publish your source under the same licence.

The name "JobDibs" is not covered by the licence. Fork freely; rename if you
publish. See [NOTICE](NOTICE).


---

## A note on the name

"Dibs" is a common English word and a number of unrelated products use it.
JobDibs is not affiliated with, endorsed by, or connected to any of them.
