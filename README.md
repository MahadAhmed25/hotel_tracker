# 🏨 Manhattan Hotel Price Alert Bot

Watches Google Hotels prices for **one specific trip** and sends you a Discord
message when a hotel's **total price for the whole stay is under $2,000 USD**.

|                  |                                              |
| ---------------- | -------------------------------------------- |
| **Check-in**     | Friday, 4 September 2026                     |
| **Check-out**    | Tuesday, 8 September 2026                    |
| **Nights**       | 4                                            |
| **Alert when**   | total stay price is **less than $2,000 USD** |
| **Where**        | **Manhattan Island only**, south of Central Park's northern edge |
| **Runs**         | Automatically every 8 hours, free, on GitHub |

The dates are **hard-coded on purpose**. Nothing — not you, not GitHub, not an
environment variable — can make the bot search different dates.

> **$2,000 exactly does not count.** The total must be *under* $2,000.
> $1,999.99 alerts. $2,000.00 does not.

---

## Table of contents

1. [What you need before you start](#1-what-you-need-before-you-start)
2. [Step-by-step setup](#2-step-by-step-setup)
3. [Running it for the first time](#3-running-it-for-the-first-time)
4. [What the Discord alerts look like](#4-what-the-discord-alerts-look-like)
5. [How the total price is worked out](#5-how-the-total-price-is-worked-out)
6. [How the Manhattan-only filter works](#6-how-the-manhattan-only-filter-works)
7. [How it avoids spamming you](#7-how-it-avoids-spamming-you)
8. [Changing the settings](#8-changing-the-settings)
9. [What each file does](#9-what-each-file-does)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. What you need before you start

Three free accounts. No credit card, no coding.

- A **GitHub** account — <https://github.com/signup>
- A **SerpApi** account — <https://serpapi.com/users/sign_up> (free plan: 100 searches/month)
- A **Discord** account with a server you can manage — <https://discord.com>

Total setup time: about 15 minutes.

---

## 2. Step-by-step setup

### Step 1 — Create a GitHub repository

1. Go to <https://github.com/new>.
2. **Repository name:** `hotel-price-alert`
3. Choose **Private** (recommended — it is your trip, after all).
4. Leave every checkbox unticked.
5. Click **Create repository**.

### Step 2 — Upload the project

The easiest way, no command line needed:

1. On your new empty repository page, click **uploading an existing file**
   (it is in the grey "…or upload an existing file" line).
2. Drag in these files and folders from this project:
   - `hotel_tracker.py`
   - `requirements.txt`
   - `README.md`
   - `state.json`
   - `.gitignore`
   - the `tests` folder
   - the `.github` folder
3. Scroll down, click **Commit changes**.

> ⚠️ **The `.github` folder matters.** It contains the schedule. If your
> computer hides folders starting with a dot, upload it by dragging the whole
> project folder in at once. After uploading, check that GitHub shows a file at
> `.github/workflows/hotel-price-check.yml`.

### Step 3 — Create a SerpApi account and copy your key

1. Sign up at <https://serpapi.com/users/sign_up>.
2. Confirm your email address.
3. Go to <https://serpapi.com/manage-api-key>.
4. Click the copy button next to **Your Private API Key**.
5. Keep it on your clipboard for Step 5. It looks like a long string of
   letters and numbers.

> 🔒 Never paste this key into a file, a message, or anywhere public.

### Step 4 — Create a Discord webhook

A webhook is just a private URL that lets the bot post into one of your channels.

1. Open Discord and go to the server where you want the alerts.
   (If you don't have one: click the **+** in the left sidebar → **Create My Own**.)
2. Make a channel for this, e.g. `#hotel-alerts`.
3. Hover over that channel → click the **⚙️ gear** (Edit Channel).
4. In the left menu click **Integrations**.
5. Click **Webhooks** → **New Webhook**.
6. Name it `Hotel Bot` and click **Copy Webhook URL**.

The URL looks like `https://discord.com/api/webhooks/123456789/AbCdEf...`.

> 🔒 Anyone with this URL can post in your channel. Treat it like a password.

### Step 5 — Add your two secrets to GitHub

**This is the step people skip. Do not skip it.**

1. Go to your repository on GitHub.
2. Click **Settings** (the tab along the top of the repository, *not* your
   profile settings).
3. In the left sidebar: **Secrets and variables** → **Actions**.
4. Click the green **New repository secret** button.

Add the first secret:

| Field | Value |
| ----- | ----- |
| **Name** | `SERPAPI_KEY` |
| **Secret** | paste the key from Step 3 |

Click **Add secret**. Then click **New repository secret** again:

| Field | Value |
| ----- | ----- |
| **Name** | `DISCORD_WEBHOOK_URL` |
| **Secret** | paste the webhook URL from Step 4 |

Click **Add secret**.

You should now see exactly two secrets listed. GitHub will never show you their
values again, and the bot never prints them into the logs.

The names must match **exactly** — capital letters and underscores included.

### Step 6 — Turn on GitHub Actions

1. Click the **Actions** tab at the top of your repository.
2. If you see a green button saying **"I understand my workflows, go ahead and
   enable them"**, click it.
3. You should now see **Hotel Price Check** in the left sidebar.

Setup is done. 🎉

---

## 3. Running it for the first time

### First: test that Discord works

Do this before anything else — it proves your webhook is right.

1. **Actions** tab → click **Hotel Price Check** in the left sidebar.
2. Click the **Run workflow** dropdown button on the right.
3. Tick **"Send one sample alert to check the webhook works"**.
4. Click the green **Run workflow** button.
5. Wait about a minute, then check your Discord channel.

You should get a sample alert for "Example Hotel (test message)". If you do,
your webhook is correct.

### Then: a real run

1. **Actions** → **Hotel Price Check** → **Run workflow**.
2. Leave both boxes **unticked**.
3. Click **Run workflow**.

Click into the run to watch it. The log shows a line for every hotel and why it
was kept or dropped:

```
[ALERT]      The Beekman: $1,850.00 (ACTUAL) — first time under the threshold
[skip-geo]   Boro Hotel: outside the Manhattan Island boundary (40.7440, -73.9490)
[skip-geo]   Aloft Harlem: north of Central Park (lat 40.8116)
[skip-price] The Plaza: cheapest total $4,200.00 is not under $2,000

[summary] 40 results → 22 rejected on location, 16 rejected on price, 0 suppressed as duplicates, 2 alert(s) sent
```

**Getting no alerts is a normal, correct result.** Manhattan for 4 nights under
$2,000 is a genuine bargain. The bot will keep checking every 8 hours and tell
you the moment one appears.

### Want to see what it finds without any Discord messages?

Run the workflow with **"Find hotels but do NOT send Discord messages"** ticked.
It searches and prints everything, but stays silent and does not record anything.

---

## 4. What the Discord alerts look like

**When the API gave a real total for the whole stay:**

> 🏨 **HOTEL PRICE ALERT**
> **The Example Hotel**
> 📍 **Area** — Financial District, Manhattan
> 📅 **Dates** — September 4–8, 2026 · 4 nights
> 💰 **Total** — **$1,850.00** (threshold $2,000)
> **Nightly** — $462.50/night × 4 nights
> **Provider** — Booking.com
> **Price type** — ACTUAL TOTAL — reported by the API for the whole stay
> **Address** — 123 Example Street, New York, NY 10038
> **Other qualifying prices** — • Expedia: $1,975.00 (actual)
> 🔗 **Booking / Hotel Link** — Open the listing and confirm the final checkout price

**When only a nightly price was available and the bot did the multiplication:**

> 🏨 **HOTEL PRICE ALERT**
> **The Example Hotel**
> ⚠️ This total is **estimated** from the nightly rate ($450.00 × 4 nights).
> Final taxes and fees may differ — check the link before booking.
> 📍 **Area** — Upper East Side (Lenox Hill), Manhattan
> 📅 **Dates** — September 4–8, 2026 · 4 nights
> 💰 **Estimated total** — **$1,800.00** (threshold $2,000)
> **Nightly** — $450.00/night × 4 nights
> **Price type** — ESTIMATED TOTAL — calculated from the nightly price ($450.00 × 4 nights)
> 🔗 **Booking / Hotel Link** — Open the listing and confirm the final checkout price

Green border = real total. Orange border = estimated. Every alert says which
one it is, and every alert has a link so you can confirm the real checkout
price yourself.

---

## 5. How the total price is worked out

The bot uses the first of these it can find, in this order.

### Priority 1 — a real total from the API (preferred)

If Google Hotels reports a `total_rate` for the whole stay, **that number
wins**, even if it disagrees with the nightly rate. Real totals include the
discounts, taxes and fees that nightly rates hide.

> Nightly $550 × 4 = $2,200, but the API says the stay totals **$1,950**
> → **alerts at $1,950.** The real total is what matters.
>
> Nightly $450 × 4 = $1,800, but the API says the stay totals **$2,050**
> → **no alert.** Again, the real total is what matters.

Because of this, if a real total exists for a hotel, the bot throws away every
estimated price for that hotel. An estimate can never sneak a hotel past the
threshold when a real total says otherwise.

### Priority 2 — nightly rate × 4 nights

Only when no real total exists anywhere for that hotel:

```
$475/night × 4 nights = $1,900 estimated total
```

This is always labelled **ESTIMATED TOTAL** and carries a warning that taxes
and fees may change it. The bot never calls this a final checkout price.

### Priority 3 — checkout verification: deliberately not automated

The bot does **not** drive a browser through a checkout page. That kind of
automation breaks constantly and would need endless maintenance. Instead every
alert includes a **link**, so you make the final call in ten seconds.

### Taxes and fees

The API can report a price two ways, and the bot prefers the more complete one:

- `lowest` — the all-in figure → used first.
- `before_taxes_fees` — a pre-tax figure → used only as a fallback, and then
  the alert is explicitly labelled **"Total before taxes/fees"** with a warning.

### Occupancy

Google Hotels lists cheap **single-occupancy** rates next to double rates,
especially at budget hotels. Quoting the single would be misleading, so any
provider quote whose `num_guests` is lower than your `ADULTS` setting is
discarded. When a quote doesn't state its occupancy at all, the alert says so
and tells you to check the room sleeps 2.

### Why the alert links to Google Hotels, not the hotel's website

The price the bot quotes comes from Google's aggregation of booking providers.
A hotel's *own* website often charges a completely different direct rate, so
linking there would show you a number that doesn't match the alert. The primary
link therefore goes to the Google Hotels comparison **carrying your dates**, so
the quoted price is actually checkable. The hotel's own site is included as a
clearly-labelled second link.

### Currency

Everything is compared in **US dollars**. The bot asks SerpApi for USD, checks
that the response actually came back in USD, and additionally checks that each
price string is a plain US dollar amount. `CA$1,850`, `A$1,850`, `MX$1,850`,
`€1,850` and `HK$1,850` all fail that check and are **discarded rather than
guessed at** — a `$` sign on its own proves nothing.

---

## 6. How the Manhattan-only filter works

The rule is: **if the location is not certain, throw it away.** Missing a cheap
hotel is fine. An alert for Brooklyn is not.

Every hotel must pass all five checks in `is_valid_manhattan_hotel()`:

1. **It must have GPS coordinates.** Google Hotels search results do not
   include a street address, so the coordinates are the only trustworthy
   location signal. No coordinates → rejected.
2. **Hard latitude ceiling.** Anything above 40.8025°N is rejected outright.
3. **The Central Park north line.** 110th Street is not a straight
   east–west line — the Manhattan street grid is tilted about 29°, so the bot
   uses the actual sloped line through the real ends of West and East 110th
   Street. Anything north of it is rejected.
4. **It must be physically on Manhattan Island.** The coordinates are tested
   against a polygon traced around the shoreline, drawn very slightly *inside*
   the real coast. Roosevelt Island gets its own separate exclusion, because it
   sits in the East River and is not Manhattan. The rivers are 500–1000 m wide,
   so there is a wide safety margin on every side.
5. **A name/address blocklist**, as a second line of defence: Queens, Brooklyn,
   the Bronx, Staten Island, New Jersey, Jersey City, Hoboken, Newark, Long
   Island, Long Island City, Astoria, Flushing, Harlem, Washington Heights,
   Inwood, Morningside Heights, Roosevelt Island and more. If a hotel's own
   address contradicts its coordinates, that is ambiguity, so it is rejected.

**Accepted:** Financial District, Battery Park, Tribeca, SoHo, Nolita,
Chinatown, Lower East Side, Greenwich Village, West Village, Flatiron, Union
Square, Chelsea, Midtown, Upper East Side, Lenox Hill, Yorkville, Carnegie
Hill, and the Upper West Side south of Central Park's northern boundary.

**Never accepted:** anything north of Central Park, anything off Manhattan
Island, and anything on the blocklist.

One deliberate exception: a *landmark* name like "Brooklyn Bridge" does not get
a hotel rejected, because plenty of genuine Lower Manhattan hotels mention it.
The coordinates still have the final say, and they keep Brooklyn out.

When a hotel passes both the location and price checks, the bot makes one extra
API call to fetch its street address, then re-runs the location check against
that address before sending anything.

All of this is covered by the tests — including real coordinates for
Long Island City, Astoria, Brooklyn, DUMBO, Jersey City, Hoboken, Newark, the
Bronx, Harlem, Washington Heights, Inwood, Staten Island and Roosevelt Island,
every one of which must be rejected.

---

## 7. How it avoids spamming you

`state.json` remembers what you have already been told. After each run, GitHub
Actions commits the updated file back to your repository automatically.

You get a message when:

- a hotel drops under $2,000 **for the first time**, or
- a hotel you were already told about gets **at least $50 cheaper**, or
- a hotel went **back above** $2,000 and has now **fallen below again**.

You do **not** get a message for trivial wobbles:

```
Check 1   Hotel A  $2,300   → silent (over the threshold)
Check 2   Hotel A  $2,100   → silent (over the threshold)
Check 3   Hotel A  $1,950   → 🔔 ALERT
Check 4   Hotel A  $1,949   → silent (only $1 cheaper)
Check 5   Hotel A  $1,940   → silent
Check 6   Hotel A  $1,935   → silent
Check 7   Hotel A  $1,880   → 🔔 ALERT ($70 cheaper)
Check 8   Hotel A  $2,050   → silent (back over the threshold)
Check 9   Hotel A  $1,990   → 🔔 ALERT (dropped below again)
```

The $50 figure is the `MIN_DROP_USD` setting — see below.

---

## 8. Changing the settings

All settings live in one place:
**`.github/workflows/hotel-price-check.yml`**, under `env:`.

To edit it on GitHub: open the file → click the **✏️ pencil** icon → make your
change → **Commit changes**.

### Change the $2,000 threshold

```yaml
MAX_TOTAL_PRICE_USD: "2000"     # change to "2500", "1500", etc.
```

A hotel qualifies when its total is **strictly less than** this number.

### Change how often it runs

At the top of the same file:

```yaml
schedule:
  - cron: "0 */8 * * *"     # every 8 hours (3 runs a day) - the default
```

| You want          | Use                |
| ----------------- | ------------------ |
| Every 6 hours     | `"0 */6 * * *"`    |
| Every 8 hours     | `"0 */8 * * *"`    |
| Every 12 hours    | `"0 */12 * * *"`   |
| Once a day, 1pm UTC | `"0 13 * * *"`   |

⚠️ **Mind your SerpApi quota.** Each run uses `MAX_PAGES` searches (4 by
default = 80 hotels scanned), plus one extra credit per hotel it alerts on.

| Setting | Searches per month |
| ------- | ------------------ |
| Every 8h, 4 pages (current) | ~360 |
| Every 8h, 2 pages | ~180 |
| Every 12h, 2 pages | ~120 |
| Every 8h, 1 page | ~90 (fits the free plan) |

Because this bot only needs to run until the trip starts, what actually
matters is *searches until then*, not per month: at 4 pages every 8 hours it
uses about **12 searches a day**.

### Other settings

| Setting | Default | What it does |
| ------- | ------- | ------------ |
| `MAX_TOTAL_PRICE_USD` | `2000` | Total must be under this |
| `MIN_DROP_USD` | `50` | How much cheaper before you're told again |
| `ADULTS` | `2` | Number of guests |
| `MAX_PAGES` | `4` | SerpApi pages per search, 20 hotels each — **each page costs one credit** |
| `RENOTIFY_AFTER_HOURS` | `0` | `0` = never re-alert just because time passed |
| `MAX_ALERTS_PER_RUN` | `10` | Safety cap on messages per run |
| `FETCH_ADDRESS_DETAILS` | `true` | Set `false` to save one credit per alert (you lose the street address) |
| `SEARCH_QUERIES` | one query | Extra searches separated by `\|`. **Each one costs credits.** |

### Changing the dates

**You cannot, and that is intentional.** The trip is 4–8 September 2026. The
dates are constants at the top of `hotel_tracker.py`, are never read from the
environment, and a test enforces this.

If you genuinely need different dates later, edit `CHECK_IN_DATE` and
`CHECK_OUT_DATE` at the top of `hotel_tracker.py`. The night count recalculates
itself, but you should also update `STAY_LABEL` just below them so the Discord
messages read correctly.

---

## 9. What each file does

| File | What it is for |
| ---- | -------------- |
| `hotel_tracker.py` | The whole bot: search, Manhattan filter, total-price logic, duplicate suppression, Discord. One file, no framework. |
| `requirements.txt` | The two Python packages needed (`requests`, plus `pytest` for the tests). |
| `state.json` | The price history that stops repeat alerts. Committed automatically by GitHub Actions — do not edit it by hand. |
| `.github/workflows/hotel-price-check.yml` | The schedule, the **Run workflow** button, and all the settings. |
| `tests/test_hotel_tracker.py` | 126 tests covering the geography, price and anti-spam rules. They run automatically before every check. |
| `.gitignore` | Keeps junk out of the repository. Deliberately does **not** ignore `state.json`. |
| `README.md` | This file. |

### Running it on your own computer (optional)

```bash
pip install -r requirements.txt

python hotel_tracker.py --print-config     # show settings, no network calls
pytest -q                                  # run the tests

# PowerShell
$env:SERPAPI_KEY="your-key"
$env:DISCORD_WEBHOOK_URL="your-webhook"
python hotel_tracker.py --dry-run          # search, print, send nothing
python hotel_tracker.py --test-discord     # send one sample alert
python hotel_tracker.py                    # the real thing

# Investigate a price that looks wrong - dumps the raw API data for one hotel
# and shows exactly how the bot read it:
python hotel_tracker.py --debug-hotel "Pod 51"
```

---

## 10. Troubleshooting

**No Discord message from the test run**
Your `DISCORD_WEBHOOK_URL` secret is probably wrong. Check the name is spelled
exactly right, then re-copy the URL from Discord (Channel ⚙️ → Integrations →
Webhooks → Copy Webhook URL) and update the secret.

**`SERPAPI_KEY is not set`**
The secret name doesn't match. It must be `SERPAPI_KEY` — all capitals, with an
underscore, no spaces. Re-add it under Settings → Secrets and variables → Actions.

**`SerpApi rejected the API key (401)`**
The key is wrong or expired. Copy it again from <https://serpapi.com/manage-api-key>.

**`SerpApi rate limit / monthly quota reached (429)`**
You've used your 100 free searches for the month. Lower `MAX_PAGES` to `1`, run
less often, or upgrade your SerpApi plan. It resets monthly.

**Runs finish but never alert**
Almost certainly correct behaviour — 4 nights in Manhattan under $2,000 is rare.
Confirm by opening the run log and reading the `[summary]` line. To see what it
*is* finding, run it with the **dry run** box ticked.

**The schedule isn't firing**
GitHub disables scheduled workflows in repositories with no activity for 60
days — open the Actions tab and press **Run workflow** to wake it up. Scheduled
runs can also be delayed by 10–30 minutes when GitHub is busy; this is normal
and free.

**`Everything up-to-date` / push errors on the state step**
Harmless. It means no prices changed, so there was nothing to save.

**I want to reset the alert history**
Edit `state.json` in GitHub, replace the contents with `{"version": 1, "hotels": {}}`,
and commit. The next run will treat every hotel as new.
