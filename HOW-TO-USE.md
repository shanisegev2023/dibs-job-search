# How to use JobDibs

No technical knowledge assumed. Part 1 is done **once**. After that, starting the
app is a double-click.

*[עברית — מדריך מלא](HOW-TO-USE.he.md)*

---

# Part 1 · One-time setup

## Windows

### 1. Install Python

1. Go to **https://www.python.org/downloads/**
2. Click the big yellow **Download Python** button
3. Run the file you downloaded

**⚠️ The single most important step:** on the installer's first screen, at the
bottom, tick

> ☐ **Add python.exe to PATH**

Tick it **before** clicking *Install Now*. If you skip it, nothing will work —
this is the number one cause of failure. Already installed without it? Run the
installer again, choose *Modify*, and tick the box.

4. Click **Install Now**, wait, then **Close**.

### 2. Unzip properly

Double-clicking a `.zip` in Windows only *previews* it — the app will not run
from there.

1. **Right-click** `jobdibs.zip`
2. **Extract All…** → **Extract**

Move the resulting `jobdibs` folder somewhere permanent, e.g. Documents.

### 3. First run

Double-click **`Start JobDibs.bat`**.

> If a security warning appears, Windows shows one of two, depending on
> version and settings:
> - blue **"Windows protected your PC"** → **More info** → **Run anyway**
> - **"Open File – Security Warning"** → **Run**
>
> Both appear because the file came from the internet. Both are one-time.

A black window opens, and your browser opens on the app a few seconds later.

> If the window closes instantly or says Python was not found, the PATH box in
> step 1 wasn't ticked. Reinstall with it ticked.

---

## macOS

### 1. Unzip and Python

Double-click the zip. Move the resulting folder somewhere permanent.

**Python is not preinstalled on macOS.** The first time something runs
`python3`, macOS offers to install the Xcode Command Line Tools — click
**Install** and wait a few minutes. That one-time install brings Python 3.9,
which is more than enough (JobDibs needs 3.8+).

### 2. First run — start from Terminal, not the double-click

The folder contains `Start JobDibs.command` for double-clicking, **but don't
use it for the first run.** Starting from Terminal clears both of macOS's
blocks at once, and repairs the launcher so double-clicking works from then on.

1. Command + Space, type `Terminal`, Enter
2. Type `cd ` — with a trailing space — then **drag the folder from Finder onto
   the Terminal window**. The path fills itself in. Press Enter
3. Type `python3 app.py` and press Enter

You'll see this line on that run:

```
✓ תוקנה הרשאת ההרצה של "Start JobDibs.command" (restored the executable bit)
```

Zip files downloaded from the internet routinely lose the executable bit;
JobDibs puts it back. **From here on, double-clicking works.**

> If macOS offers to install developer command line tools, click **Install**,
> wait, and try again. That's Apple's one-time Python setup.

Your browser opens on the app a few seconds later.

### If you double-clicked anyway

macOS shows one of two dialogs, and they are completely different problems:

**1. "could not be executed because you do not have appropriate access
privileges"** — the executable bit is missing. There is no GUI fix; run
`python3 app.py` from Terminal once as above and it repairs itself.

**2. "Apple could not verify that it is free of malware"** — two buttons,
*Move to Trash* and *Done*. **Click Done, not Move to Trash.** Then, once:

1. **System Settings** → **Privacy & Security**
2. Scroll to **Security**. You'll see
   *"Start JobDibs.command" was blocked to protect your Mac*
3. Click **Open Anyway**, authenticate, then **Open**

> On macOS Sequoia and later this is the only route — the old Control-click →
> Open bypass no longer works.

**Why this happens, and how to end it permanently.** Every file downloaded
through a browser is tagged `com.apple.quarantine`, and the tag propagates to
everything extracted from the zip. Gatekeeper blocks a tagged script that isn't
signed by Apple. Strip the tag from the whole folder once and double-clicking
works with no dialog at all:

```
xattr -dr com.apple.quarantine ~/Downloads/JobDibs
```

(Use the real path — you can drag the folder onto Terminal instead of typing.)

> **If you have GitHub Desktop:** cloning the repo doesn't go through a browser,
> so its files are never tagged and nothing is ever blocked. It's the smoothest
> way to run this on a Mac.

---

## Linux

```bash
unzip jobdibs.zip && cd jobdibs && python3 app.py
```

---

# Part 2 · Using it

Everything happens in the browser at `http://127.0.0.1:8765`.

**1 · Job titles.** Type a title, press **Enter**. Add as many as you like. You
don't need every variation — type "Product Manager" and it also searches Senior
Product Manager, Product Owner, Head of Product, and the Hebrew equivalents.

**2 · Your CV.** Drag a **PDF**, **DOCX** or **TXT** onto the dashed box. A line
appears telling you how many characters were read. If you see a red message
saying text couldn't be extracted, your CV is a scanned image — open it, select
all, copy, then click *"paste text manually"* and paste. Works the same.

A **"what was detected"** panel appears with your seniority level, years of
experience and domain terms. Glance at it — if something looks wrong, that's the
moment to fix your CV or add missing words.

**2b · Your own keywords.** Two optional fields.

*Keywords to add* — terms that matter to you but aren't necessarily in your CV.
Changing field, or your CV uses different vocabulary than the postings? Add
`Klaviyo`, `headless commerce`, `FinOps`. Each gets the **maximum weight** in
domain scoring, equal to the strongest term found in your CV.

*Keywords to exclude* — any job containing one of these is **not shown at all**.
Not scored low, not shown. Useful for a sector you won't work in (`crypto`,
`gambling`, `defense`), a specific company, or a city.

Both lists are saved with the search and shown in the "what was detected" panel
— green for added, red for excluded.

**3 · Market and region.** Market is Israel · Remote worldwide · Europe · USA.
The second dropdown lists that market's regions and changes with it — for
Israel: Gush Dan, Sharon, Jerusalem, Haifa & the north, Shfela, the south, or
the whole country.

The region you pick lifts roles inside it and pushes down distant ones.
**"Whole country" prefers nowhere** — every location scores the same. For the
remote market the regions are time zones rather than cities, since that's what
actually decides whether a remote role works for you.

**Location filter** — the button next to the region menu, on by default. With
it on, jobs outside the selected market are **not shown at all**. With it off,
location only affects the score: a Berlin role ranks lower but still appears.

The filter reads the job's **location field only**, not the description — a
Berlin posting that mentions "Europe" in its text is still a Berlin job.
Anything marked remote, hybrid or worldwide always passes, and so does a job
with no location field, since missing data shouldn't disqualify a role.

> Especially relevant if you added a Workday or Comeet board: those return
> *every* job the company has worldwide.

Add your own under `regions` in `markets.json` and it appears in the menu.

**4 · Employment type.** The field that matters most. Pick the types you
actually want:

| | |
|---|---|
| Full-time | permanent, 100% |
| Part-time | 50%, 60%, 80%, flexible hours |
| Fractional | 5–20 hrs/week, usually a monthly retainer |
| Freelance / consulting | self-employed, project work |
| Contract | fixed-term, contractor |
| Parental-leave cover | time-boxed by definition |
| Interim | holding a seat until a permanent hire |
| Student / internship | student jobs, internships, working-student roles |
| Entry level / junior | no experience required, new grads |
| Shift / hourly | shift work, hourly pay |

Pick as many as apply. The choice works **both ways**: matching types are pushed
up, and other types are pushed down and flagged **⚠ not the type you asked for** —
still visible, but no longer flooding the list.

Select nothing and every type counts equally, which behaves like an ordinary job
search.

> **Looking for student work?** You must tick **Student / internship**. Without
> it, roles with Intern, Internship or Student in the title are filtered out —
> for most users they're noise. With it, they're exactly what you get.

**4b · Adding a specific company (Workday / Comeet).** Most ATS platforms are
detected automatically from a company name. These two aren't — they need an
internal identifier that can't be guessed. Find the company's careers page; if
the URL looks like `xxx.wd3.myworkdayjobs.com/...` or `comeet.co/jobs/...`,
paste it into **Add a specific company's board** and click Add. It's included in
every run from then on. Worth doing in Israel especially — a large share of
Israeli tech companies use Comeet.

**5 · Minimum score.** Default 35. Too much noise → raise to 50. Too few results
→ lower to 25.

**6 · Search.** The **first run takes 1–4 minutes** — it's discovering company
job boards and building a cache. Later runs are faster.

**7 · Results.** Every job gets 0–100, with the reasons shown underneath.

| | |
|---|---|
| ★ dibs | call dibs on a role to come back to |
| ✓ applied | track your applications |
| ✕ not relevant | dims the row |
| ↗ open | the original posting, new tab |

Marks persist between runs, on your machine. Roles that weren't in the previous
run are tagged **✦ new**. Filter by scope, source or free text; sort by score or
date.

**8 · Save search.** Stores all settings under a name, so you can keep e.g.
"part-time PM in Israel" and "remote PMO in Europe" side by side and switch
between them.

---

# Part 3 · FAQ

**How do I stop it?** Close the black window. That's all.

**How do I start it tomorrow?** Double-click the same launcher. On macOS you no
longer need to right-click.

**Did my results disappear?** No — the last run reloads automatically every time
you open the app.

**Does it cost anything?** No. No account, no subscription, no server.

**What happens to my CV?** It stays with you. The app runs only on your machine,
on an internal address (`127.0.0.1`) that isn't reachable from outside. The only
outbound requests are to job boards, to fetch listings. Your CV is never sent
anywhere.

**"Active sources: 0" and no results.** Almost always no internet connection, or
a firewall blocking it.

**It worked once, then stopped.** Two causes, both handled from v1.1 on:

1. **A previous window is still running** and holding the port. JobDibs now
   moves to the next free port and says so; before, it just crashed. To force
   a specific port: `python3 app.py --port 8899` (macOS/Linux) or
   `py app.py --port 8899` (Windows).
2. **You're launching a different copy.** It's easy to accumulate several — one
   in Downloads from an old zip, one somewhere else. If one works and another
   doesn't, they're different copies. Delete the stale ones.

**No LinkedIn / Indeed results.** They block automated access and there's no way
around it. You can paste listings from those sites into `seed_jobs.json` by hand
and they'll be scored alongside everything else.

**Found a bug, or want to change the scoring?** It's AGPL-3.0 licensed. The weights
live in `engine.py`; the market definitions in `markets.json`. Both are readable
and meant to be edited.
