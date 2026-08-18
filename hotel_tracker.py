#!/usr/bin/env python3
"""
Manhattan Hotel Price Alert Bot
===============================

Searches Google Hotels (via SerpApi) for the FIXED stay

    check-in  : 2026-09-04
    check-out : 2026-09-08   ->  4 nights

and sends a Discord webhook alert when a hotel's TOTAL price for the whole
stay is under $2,000 USD.

Design rules (deliberate, do not "optimise" away):

  * Geography is judged from GPS coordinates, not from the search query text.
    Google Hotels search results do NOT contain a street address, so the
    coordinates are the only trustworthy location signal in the search
    payload. No coordinates -> the hotel is REJECTED.
  * An ACTUAL total returned by the API always beats a total we calculate
    ourselves. We never present a calculated number as a final checkout price.
  * Anything ambiguous (currency, price, location) is REJECTED. A missed
    bargain is cheap; a false alert for Brooklyn is not.

Run:
    python hotel_tracker.py                # normal run
    python hotel_tracker.py --dry-run      # search + filter, but send nothing
    python hotel_tracker.py --test-discord # send one sample alert and exit
    python hotel_tracker.py --print-config # show settings, no network calls
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter

try:  # urllib3 v2 and v1 keep Retry in different places
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover
    from requests.packages.urllib3.util.retry import Retry  # type: ignore


# ---------------------------------------------------------------------------
# 1. FIXED CONFIGURATION
# ---------------------------------------------------------------------------

# These dates are intentionally hard-coded. They are NOT configurable and are
# NOT read from the environment or from GitHub Actions.
CHECK_IN_DATE = "2026-09-04"
CHECK_OUT_DATE = "2026-09-08"

# 4 Sep -> 5 Sep (night 1), 5 -> 6 (2), 6 -> 7 (3), 7 -> 8 (4). Checkout day is
# not a night, which is exactly what a date subtraction gives us.
NIGHTS = (date.fromisoformat(CHECK_OUT_DATE) - date.fromisoformat(CHECK_IN_DATE)).days

STAY_LABEL = "September 4–8, 2026 · 4 nights"

# Everything below can be tuned with environment variables.
DEFAULT_MAX_TOTAL_PRICE_USD = 2000.0  # strict: total must be < this
DEFAULT_MIN_DROP_USD = 50.0           # re-alert only after a drop this big
DEFAULT_RENOTIFY_AFTER_HOURS = 0.0    # 0 = never re-alert just because of time
DEFAULT_ADULTS = 2
DEFAULT_MAX_PAGES = 2                 # SerpApi pages per query (API budget!)
DEFAULT_MAX_ALERTS_PER_RUN = 10

# One query is usually enough because we sort by price and filter by
# coordinates afterwards. Each query costs one SerpApi search credit per page.
DEFAULT_SEARCH_QUERIES = ["hotels in Manhattan, New York"]

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
REQUEST_TIMEOUT = 45  # seconds


# ---------------------------------------------------------------------------
# 2. GEOGRAPHY  --  Manhattan Island only, nothing north of Central Park
# ---------------------------------------------------------------------------
#
# The polygon traces the Manhattan shoreline from the Battery up to the 110th
# Street line. It is drawn very slightly INSIDE the real shoreline: erring
# inward can only ever cost us a waterfront hotel, while erring outward could
# let Long Island City or DUMBO through. The rivers are 500-1000 m wide, so
# there is a comfortable margin on every side.
#
# Vertices are (latitude, longitude), traced counter-clockwise: up the Hudson
# side, across the top, back down the East River side.

MANHATTAN_POLYGON: list[tuple[float, float]] = [
    # --- Hudson River (west) shoreline, heading north ---
    (40.7009, -74.0177),  # Battery / southern tip
    (40.7085, -74.0193),  # Battery Park City
    (40.7195, -74.0165),  # Tribeca waterfront
    (40.7305, -74.0122),  # Hudson Square / Canal St
    (40.7430, -74.0100),  # West Village / W 14th St
    (40.7550, -74.0060),  # Chelsea Piers
    (40.7650, -74.0000),  # Hell's Kitchen / W 42nd St
    (40.7750, -73.9930),  # Riverside South / W 72nd St
    (40.7850, -73.9860),  # W 79th-86th St
    (40.7950, -73.9760),  # W 96th-106th St
    (40.8025, -73.9690),  # W 110th St & Riverside Dr  (north-west corner)
    # --- across the 110th Street line ---
    (40.7935, -73.9330),  # E 110th St & FDR Dr        (north-east corner)
    # --- East River shoreline, heading south ---
    (40.7845, -73.9375),  # E 96th St
    (40.7770, -73.9420),  # E 86th St
    (40.7670, -73.9495),  # E 72nd St
    (40.7590, -73.9580),  # E 59th St
    (40.7500, -73.9640),  # E 42nd St / United Nations
    (40.7420, -73.9690),  # E 23rd-34th St
    (40.7300, -73.9720),  # E 14th St
    (40.7185, -73.9730),  # East River Park / Williamsburg Bridge
    (40.7115, -73.9740),  # Corlears Hook
    (40.7095, -73.9900),  # Manhattan Bridge landing
    (40.7060, -74.0015),  # South Street Seaport
    (40.7010, -74.0120),  # Battery Maritime Building
]

# Roosevelt Island sits in the East River. It is NOT Manhattan Island, and it
# has hotels on it, so it gets its own explicit cut-out.
ROOSEVELT_ISLAND_POLYGON: list[tuple[float, float]] = [
    (40.7485, -73.9570),
    (40.7495, -73.9590),
    (40.7560, -73.9560),
    (40.7640, -73.9505),
    (40.7715, -73.9435),
    (40.7695, -73.9415),
    (40.7620, -73.9480),
    (40.7540, -73.9535),
]

# The northern limit is the Central Park north boundary (110th Street). The
# Manhattan grid is rotated ~29 degrees, so 110th Street is a sloped line, not
# a constant latitude. Fitted through the two real ends of W/E 110th Street:
#   W 110th & Riverside Dr : 40.8022, -73.9700
#   E 110th & FDR Dr       : 40.7930, -73.9345
_CP_NORTH_REF_LAT = 40.7930
_CP_NORTH_REF_LON = -73.9345
_CP_NORTH_SLOPE = (40.8022 - 40.7930) / (-73.9700 - -73.9345)  # d(lat)/d(lon)

# Hard ceiling so that extrapolating the line off the edge of the island can
# never accidentally allow Morningside Heights / Harlem.
ABSOLUTE_MAX_LATITUDE = 40.8025

# Text that disqualifies a hotel outright, checked against the name and (when
# we have one) the address. This is a second line of defence behind the
# coordinates, not a replacement for them.
EXCLUDED_LOCATION_KEYWORDS = [
    "queens", "brooklyn", "bronx", "staten island",
    "new jersey", "jersey city", "hoboken", "newark", "weehawken",
    "secaucus", "north bergen", "union city, nj", "fort lee", "edgewater",
    "long island", "long island city", "astoria", "flushing", "jamaica, ny",
    "sunnyside", "woodside", "greenpoint", "williamsburg", "bushwick",
    "dumbo", "bay ridge", "coney island", "jfk", "laguardia", "newark airport",
    "harlem", "east harlem", "west harlem", "spanish harlem",
    "washington heights", "inwood", "hamilton heights", "manhattanville",
    "morningside heights", "sugar hill", "marble hill",
    "roosevelt island", "randalls island", "wards island", "governors island",
    "yonkers", "mount vernon", "new rochelle", "westchester",
]

# "nj", "bklyn" style tokens are matched separately with word boundaries so
# that we do not trip over substrings inside ordinary words ("public" != LIC).
EXCLUDED_LOCATION_TOKENS = ["nj", "n.j.", "qns", "bklyn", "lic"]

# Landmarks that borrow an excluded borough's name. Plenty of perfectly good
# Lower Manhattan hotels sit next to the Brooklyn Bridge, so these phrases are
# removed before the blocklist runs. The coordinates already keep the actual
# outer boroughs out, so this costs us nothing.
NEUTRAL_LANDMARK_PHRASES = [
    "brooklyn bridge", "manhattan bridge", "williamsburg bridge",
    "queensboro bridge", "ed koch queensboro bridge", "59th street bridge",
    "queens midtown tunnel", "brooklyn battery tunnel", "hugh l. carey tunnel",
    "queens midtown expressway", "long island expressway",
    "brooklyn bridge park", "harlem meer", "harlem line",
]


# Shared accommodation is priced per BED, not per room, so its "total" is a
# per-person figure that cannot be compared to a room-for-two budget.
EXCLUDED_ACCOMMODATION_KEYWORDS = [
    "hostel", "hostal", "dormitory", "dorm bed", "shared room",
    "shared dorm", "bunk bed", "capsule hotel", "backpacker",
]

# How far below the cheapest named provider quote a headline "from" price may
# sit before we stop believing it refers to the same room. Google's headline
# figure is a teaser for the cheapest available bed/room and often is not the
# price for the occupancy we asked for.
HEADLINE_CORROBORATION_RATIO = 0.9


def point_in_polygon(lat: float, lon: float, polygon: list[tuple[float, float]]) -> bool:
    """Standard ray-casting test. `polygon` is a list of (lat, lon) vertices."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        lat_i, lon_i = polygon[i]
        lat_j, lon_j = polygon[j]
        # Does the horizontal ray at `lat` cross the edge i-j?
        if (lat_i > lat) != (lat_j > lat):
            lon_at_lat = lon_i + (lat - lat_i) * (lon_j - lon_i) / (lat_j - lat_i)
            if lon < lon_at_lat:
                inside = not inside
        j = i
    return inside


def central_park_north_boundary_lat(lon: float) -> float:
    """Latitude of the 110th Street / Central Park North line at `lon`."""
    return _CP_NORTH_REF_LAT + _CP_NORTH_SLOPE * (lon - _CP_NORTH_REF_LON)


def _contains_excluded_place(text: str) -> Optional[str]:
    """Return the offending phrase if `text` mentions an excluded place."""
    if not text:
        return None
    low = " " + text.lower().replace(",", " , ") + " "
    for landmark in NEUTRAL_LANDMARK_PHRASES:
        low = low.replace(landmark, " ")
    for phrase in EXCLUDED_LOCATION_KEYWORDS:
        if phrase in low:
            return phrase
    for token in EXCLUDED_LOCATION_TOKENS:
        if re.search(r"(?<![a-z])" + re.escape(token) + r"(?![a-z])", low):
            return token
    return None


def is_valid_manhattan_hotel(hotel: dict[str, Any]) -> tuple[bool, str]:
    """
    Decide whether `hotel` is on Manhattan Island, south of Central Park North.

    Returns (accepted, reason). Ambiguous input is always rejected.
    """
    if not isinstance(hotel, dict):
        return False, "malformed hotel record"

    name = str(hotel.get("name") or "").strip()
    if not name:
        return False, "hotel has no name"

    # --- 1. coordinates are mandatory ------------------------------------
    coords = hotel.get("gps_coordinates")
    if not isinstance(coords, dict):
        return False, "no gps_coordinates (location cannot be verified)"

    lat = coords.get("latitude")
    lon = coords.get("longitude")
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False, "gps_coordinates are not numeric"

    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return False, "gps_coordinates out of range"

    # --- 2. hard latitude ceiling ----------------------------------------
    if lat > ABSOLUTE_MAX_LATITUDE:
        return False, f"north of Central Park (lat {lat:.4f})"

    # --- 3. the sloped 110th Street line ---------------------------------
    boundary = central_park_north_boundary_lat(lon)
    if lat > boundary:
        return False, f"north of the Central Park north boundary (lat {lat:.4f} > {boundary:.4f})"

    # --- 4. physically on Manhattan Island --------------------------------
    if not point_in_polygon(lat, lon, MANHATTAN_POLYGON):
        return False, f"outside the Manhattan Island boundary ({lat:.4f}, {lon:.4f})"

    if point_in_polygon(lat, lon, ROOSEVELT_ISLAND_POLYGON):
        return False, "Roosevelt Island is not Manhattan Island"

    # --- 4b. shared accommodation prices per bed, not per room -------------
    lowered = f" {name.lower()} "
    for word in EXCLUDED_ACCOMMODATION_KEYWORDS:
        if word in lowered:
            return False, f"shared accommodation ({word}) is priced per bed, not per room"

    if str(hotel.get("type") or "").strip().lower() == "vacation rental":
        return False, "vacation rental, not a hotel"

    # --- 5. text blocklist on whatever location text we have ---------------
    # `description` is deliberately excluded: it is marketing copy about
    # nearby attractions ("moments from Brooklyn Bridge"), not a location.
    haystack = " ".join(
        str(hotel.get(key) or "")
        for key in ("name", "address", "city", "state", "neighborhood")
    )
    offender = _contains_excluded_place(haystack)
    if offender:
        return False, f"name/address mentions excluded location: {offender!r}"

    return True, f"Manhattan ({lat:.4f}, {lon:.4f})"


def approximate_neighborhood(lat: float, lon: float) -> str:
    """A human-friendly area label. Cosmetic only - filtering never uses it."""
    if lat < 40.7075:
        return "Battery Park / Financial District"
    if lat < 40.7145:
        return "Financial District"
    if lat < 40.7200:
        return "Tribeca" if lon < -74.0050 else "Chinatown / Two Bridges"
    if lat < 40.7250:
        if lon < -74.0030:
            return "Tribeca"
        return "Chinatown" if lon < -73.9950 else "Lower East Side"
    if lat < 40.7300:
        if lon < -74.0000:
            return "SoHo"
        return "Nolita / Little Italy" if lon < -73.9920 else "Lower East Side"
    if lat < 40.7360:
        if lon < -74.0000:
            return "West Village"
        return "Greenwich Village / NoHo" if lon < -73.9900 else "East Village"
    if lat < 40.7420:
        return "West Village / Meatpacking" if lon < -74.0000 else "Greenwich Village / Union Square"
    if lat < 40.7480:
        if lon < -73.9980:
            return "Chelsea"
        return "Flatiron / Union Square" if lon < -73.9850 else "Gramercy / Kips Bay"
    if lat < 40.7530:
        return "Chelsea / Hudson Yards" if lon < -73.9950 else "Murray Hill / Kips Bay"
    if lat < 40.7600:
        return "Midtown West / Times Square" if lon < -73.9900 else "Midtown East / Turtle Bay"
    if lat < 40.7680:
        return "Midtown West / Hell's Kitchen" if lon < -73.9850 else "Midtown East / Sutton Place"
    if lat < 40.7750:
        return "Upper West Side" if lon < -73.9700 else "Upper East Side (Lenox Hill)"
    if lat < 40.7830:
        return "Upper West Side" if lon < -73.9680 else "Upper East Side (Lenox Hill / Yorkville)"
    return "Upper West Side" if lon < -73.9650 else "Upper East Side (Carnegie Hill / Yorkville)"


# ---------------------------------------------------------------------------
# 3. CURRENCY  --  USD or nothing
# ---------------------------------------------------------------------------

# A bare US dollar amount and nothing else: "$1,850", "$1,850.00", "$499".
# "CA$120", "A$120", "MX$1,200", "HK$900", "€120" and friends all fail this,
# which is the point: the "$" glyph on its own proves nothing.
_USD_AMOUNT_RE = re.compile(r"^\$\s?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?$")


def is_usd_price_string(text: Any) -> bool:
    """True only when `text` is unambiguously a plain US dollar amount."""
    if not isinstance(text, str):
        return False
    return bool(_USD_AMOUNT_RE.match(text.strip()))


# ---------------------------------------------------------------------------
# 4. PRICING
# ---------------------------------------------------------------------------

ACTUAL = "ACTUAL"
ESTIMATED = "ESTIMATED"


@dataclass
class Offer:
    """One purchasable price for one hotel, normalised to a stay total."""

    provider: str
    total: float
    kind: str                    # ACTUAL or ESTIMATED
    includes_taxes_fees: bool    # False -> the number is a pre-tax figure
    nightly: Optional[float] = None
    link: Optional[str] = None
    is_headline: bool = False   # the property-level "lowest listed" figure
    num_guests: Optional[int] = None  # None = the API did not say

    @property
    def nightly_display(self) -> float:
        if self.nightly is not None:
            return self.nightly
        return self.total / NIGHTS if NIGHTS else self.total

    def price_type_label(self) -> str:
        if self.kind == ACTUAL:
            base = "ACTUAL TOTAL — reported by the API for the whole stay"
        else:
            base = (
                f"ESTIMATED TOTAL — calculated from the nightly price "
                f"(${self.nightly_display:,.2f} × {NIGHTS} nights)"
            )
        if not self.includes_taxes_fees:
            base += "\n⚠️ This figure is BEFORE taxes & fees."
        return base

    def total_label(self) -> str:
        if self.kind == ACTUAL:
            if self.includes_taxes_fees:
                return "Total"
            return "Total before taxes/fees"
        if self.includes_taxes_fees:
            return "Estimated total"
        return "Estimated total before taxes/fees"


def _extract_rate(rate: Any) -> tuple[Optional[float], bool]:
    """
    Pull a numeric USD amount out of a SerpApi rate object.

    Returns (amount, includes_taxes_fees). Prefers the all-in figure
    (`extracted_lowest`) and falls back to `extracted_before_taxes_fees`,
    which is then flagged as pre-tax. Returns (None, False) if the value is
    missing, non-numeric, or not verifiably in USD.
    """
    if not isinstance(rate, dict):
        return None, False

    for value_key, text_key, all_in in (
        ("extracted_lowest", "lowest", True),
        ("extracted_before_taxes_fees", "before_taxes_fees", False),
    ):
        raw = rate.get(value_key)
        if raw is None:
            continue
        try:
            amount = float(raw)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        # The paired display string must look like plain USD. If SerpApi ever
        # hands back another currency, this is what catches it.
        text = rate.get(text_key)
        if text is not None and not is_usd_price_string(text):
            continue
        return amount, all_in

    return None, False


def _offer_from_rates(
    provider: str,
    total_rate: Any,
    rate_per_night: Any,
    link: Optional[str],
    is_headline: bool = False,
    num_guests: Optional[int] = None,
) -> Optional[Offer]:
    """Build one Offer, preferring a real stay total over a nightly figure."""
    total, all_in = _extract_rate(total_rate)
    if total is not None:
        nightly, _ = _extract_rate(rate_per_night)
        return Offer(
            provider=provider,
            total=total,
            kind=ACTUAL,
            includes_taxes_fees=all_in,
            nightly=nightly,
            link=link,
            is_headline=is_headline,
            num_guests=num_guests,
        )

    nightly, nightly_all_in = _extract_rate(rate_per_night)
    if nightly is not None and NIGHTS > 0:
        return Offer(
            provider=provider,
            total=round(nightly * NIGHTS, 2),
            kind=ESTIMATED,
            includes_taxes_fees=nightly_all_in,
            nightly=nightly,
            link=link,
            is_headline=is_headline,
            num_guests=num_guests,
        )

    return None


def extract_offers(hotel: dict[str, Any], required_guests: Optional[int] = None) -> list[Offer]:
    """
    Every price we can read for this hotel: the headline one plus each provider.

    `required_guests` drops provider quotes that are for fewer people than you
    are travelling with. Budget hotels list a cheap single-occupancy rate
    alongside the double, and quoting the single would be flatly misleading.
    """
    offers: list[Offer] = []
    link = hotel.get("link") if isinstance(hotel.get("link"), str) else None

    headline = _offer_from_rates(
        provider="Google Hotels (lowest listed)",
        total_rate=hotel.get("total_rate"),
        rate_per_night=hotel.get("rate_per_night"),
        link=link,
        is_headline=True,
    )
    if headline:
        offers.append(headline)

    prices = hotel.get("prices")
    if isinstance(prices, list):
        for entry in prices:
            if not isinstance(entry, dict):
                continue
            provider = str(entry.get("source") or "").strip() or "Unknown provider"
            entry_link = entry.get("link") if isinstance(entry.get("link"), str) else link

            guests: Optional[int] = None
            raw_guests = entry.get("num_guests")
            if isinstance(raw_guests, (int, float)) and not isinstance(raw_guests, bool):
                guests = int(raw_guests)

            # A quote for fewer people than are travelling is not a usable
            # price - this is how a $262 single-occupancy rate masquerades as
            # the price of a room for two.
            if required_guests and guests is not None and guests < required_guests:
                continue

            offer = _offer_from_rates(
                provider=provider,
                total_rate=entry.get("total_rate"),
                rate_per_night=entry.get("rate_per_night"),
                link=entry_link,
                num_guests=guests,
            )
            if offer:
                offers.append(offer)

    return offers


def _coerce_guests(raw: Any) -> Optional[int]:
    """`num_guests` arrives as an int in some places and a string in others."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        match = re.search(r"\d+", raw)
        if match:
            return int(match.group())
    return None


def offers_from_details(
    details: dict[str, Any], required_guests: Optional[int] = None
) -> list[Offer]:
    """
    Real, bookable offers from a Property Details payload.

    Unlike the search response, every offer here can be attributed to a named
    provider and (usually) a stated occupancy, so these are the numbers we are
    willing to put in an alert.
    """
    offers: list[Offer] = []
    if not isinstance(details, dict):
        return offers

    for key in ("featured_prices", "prices"):
        entries = details.get(key)
        if not isinstance(entries, list):
            continue

        for entry in entries:
            if not isinstance(entry, dict):
                continue

            source = str(entry.get("source") or "").strip() or "Unknown provider"
            entry_link = entry.get("link") if isinstance(entry.get("link"), str) else None
            entry_guests = _coerce_guests(entry.get("num_guests"))

            # Room-level offers are the most precise thing the API gives us.
            room_offers: list[Offer] = []
            rooms = entry.get("rooms")
            if isinstance(rooms, list):
                for room in rooms:
                    if not isinstance(room, dict):
                        continue
                    guests = _coerce_guests(room.get("num_guests"))
                    if guests is None:
                        guests = entry_guests
                    if required_guests and guests is not None and guests < required_guests:
                        continue
                    room_name = str(room.get("name") or "").strip()
                    offer = _offer_from_rates(
                        provider=f"{source} — {room_name}" if room_name else source,
                        total_rate=room.get("total_rate"),
                        rate_per_night=room.get("rate_per_night"),
                        link=room.get("link") if isinstance(room.get("link"), str) else entry_link,
                        num_guests=guests,
                    )
                    if offer:
                        room_offers.append(offer)

            if room_offers:
                offers.extend(room_offers)
                continue

            if required_guests and entry_guests is not None and entry_guests < required_guests:
                continue
            offer = _offer_from_rates(
                provider=source,
                total_rate=entry.get("total_rate"),
                rate_per_night=entry.get("rate_per_night"),
                link=entry_link,
                num_guests=entry_guests,
            )
            if offer:
                offers.append(offer)

    return offers


def pick_best_offer(offers: list[Offer], threshold: float) -> tuple[Optional[Offer], list[Offer]]:
    """
    Choose the cheapest qualifying offer for a hotel.

    An actual total always wins over a calculated one: if ANY offer for this
    hotel carries a real stay total, the calculated ones are discarded
    entirely. That is what stops a $600/night estimate ($2,400) from being
    undercut by - or, worse, hiding - a real $2,050 total.

    Returns (best, other_qualifying_offers).
    """
    if not offers:
        return None, []

    # Google's property-level "from" price advertises the cheapest bed or room
    # it can find, which is frequently a single-occupancy or dorm rate rather
    # than the room we searched for. Believe it only when a named provider
    # quotes something comparable; otherwise it is not a price for our stay.
    named = [o for o in offers if not o.is_headline]
    if named:
        cheapest_named = min(o.total for o in named)
        offers = [
            o
            for o in offers
            if not o.is_headline or o.total >= cheapest_named * HEADLINE_CORROBORATION_RATIO
        ]

    actuals = [o for o in offers if o.kind == ACTUAL]
    considered = actuals if actuals else offers

    # Cheapest first; then prefer an all-in figure over a pre-tax one; then
    # prefer a named booking provider over the generic "lowest listed" entry,
    # because a named provider is what you actually click through to.
    considered = sorted(
        considered, key=lambda o: (o.total, not o.includes_taxes_fees, o.is_headline)
    )

    qualifying = [o for o in considered if o.total < threshold]
    if not qualifying:
        return None, []

    best = qualifying[0]

    # Mention other genuinely different providers, one line each, no repeats.
    others: list[Offer] = []
    seen = {best.provider}
    for offer in qualifying[1:]:
        if offer.is_headline or offer.provider in seen:
            continue
        seen.add(offer.provider)
        others.append(offer)
    return best, others


def cheapest_observed_total(offers: list[Offer]) -> Optional[float]:
    """Cheapest total we can see, qualifying or not - used for price history."""
    if not offers:
        return None
    actuals = [o for o in offers if o.kind == ACTUAL]
    considered = actuals if actuals else offers
    return min(o.total for o in considered)


# ---------------------------------------------------------------------------
# 5. SETTINGS
# ---------------------------------------------------------------------------


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"[warn] {name}={raw!r} is not a number; using {default}")
        return default


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, float(default)))


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    serpapi_key: str = ""
    discord_webhook_url: str = ""
    max_total_price_usd: float = DEFAULT_MAX_TOTAL_PRICE_USD
    min_drop_usd: float = DEFAULT_MIN_DROP_USD
    renotify_after_hours: float = DEFAULT_RENOTIFY_AFTER_HOURS
    adults: int = DEFAULT_ADULTS
    max_pages: int = DEFAULT_MAX_PAGES
    max_alerts_per_run: int = DEFAULT_MAX_ALERTS_PER_RUN
    fetch_details: bool = True
    require_verified_price: bool = True
    queries: list[str] = field(default_factory=lambda: list(DEFAULT_SEARCH_QUERIES))

    @classmethod
    def from_env(cls) -> "Settings":
        raw_queries = os.environ.get("SEARCH_QUERIES", "").strip()
        queries = [q.strip() for q in raw_queries.split("|") if q.strip()] or list(
            DEFAULT_SEARCH_QUERIES
        )
        return cls(
            serpapi_key=os.environ.get("SERPAPI_KEY", "").strip(),
            discord_webhook_url=os.environ.get("DISCORD_WEBHOOK_URL", "").strip(),
            max_total_price_usd=_env_float("MAX_TOTAL_PRICE_USD", DEFAULT_MAX_TOTAL_PRICE_USD),
            min_drop_usd=_env_float("MIN_DROP_USD", DEFAULT_MIN_DROP_USD),
            renotify_after_hours=_env_float(
                "RENOTIFY_AFTER_HOURS", DEFAULT_RENOTIFY_AFTER_HOURS
            ),
            adults=_env_int("ADULTS", DEFAULT_ADULTS),
            max_pages=max(1, _env_int("MAX_PAGES", DEFAULT_MAX_PAGES)),
            max_alerts_per_run=_env_int("MAX_ALERTS_PER_RUN", DEFAULT_MAX_ALERTS_PER_RUN),
            fetch_details=_env_bool("FETCH_ADDRESS_DETAILS", True),
            require_verified_price=_env_bool("REQUIRE_VERIFIED_PRICE", True),
            queries=queries,
        )


# ---------------------------------------------------------------------------
# 6. SERPAPI CLIENT
# ---------------------------------------------------------------------------


class SerpApiError(RuntimeError):
    """Raised when SerpApi cannot give us usable data."""


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=2.0,               # 0s, 2s, 4s
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "manhattan-hotel-price-alert/1.0"})
    return session


def _serpapi_get(session: requests.Session, params: dict[str, Any]) -> dict[str, Any]:
    try:
        response = session.get(SERPAPI_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise SerpApiError(f"network error talking to SerpApi: {exc}") from exc

    if response.status_code == 401:
        raise SerpApiError("SerpApi rejected the API key (401). Check the SERPAPI_KEY secret.")
    if response.status_code == 429:
        raise SerpApiError("SerpApi rate limit / monthly quota reached (429).")
    if response.status_code >= 400:
        raise SerpApiError(f"SerpApi returned HTTP {response.status_code}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise SerpApiError("SerpApi returned a response that is not JSON") from exc

    if not isinstance(payload, dict):
        raise SerpApiError("SerpApi returned an unexpected JSON shape")

    if payload.get("error"):
        raise SerpApiError(f"SerpApi error: {payload['error']}")

    return payload


def search_hotels(session: requests.Session, settings: Settings) -> list[dict[str, Any]]:
    """Run every configured query and return the raw, de-duplicated properties."""
    collected: dict[str, dict[str, Any]] = {}

    for query in settings.queries:
        next_page_token: Optional[str] = None
        for page in range(settings.max_pages):
            params: dict[str, Any] = {
                "engine": "google_hotels",
                "q": query,
                "check_in_date": CHECK_IN_DATE,
                "check_out_date": CHECK_OUT_DATE,
                "adults": settings.adults,
                "currency": "USD",
                "gl": "us",
                "hl": "en",
                "sort_by": 3,  # lowest price first
                "api_key": settings.serpapi_key,
            }
            if next_page_token:
                params["next_page_token"] = next_page_token

            try:
                payload = _serpapi_get(session, params)
            except SerpApiError as exc:
                print(f"[error] query {query!r} page {page + 1}: {exc}")
                break

            # Never trust the "$" glyph alone - confirm the API honoured USD.
            requested = payload.get("search_parameters")
            if isinstance(requested, dict):
                currency = str(requested.get("currency") or "USD").upper()
                if currency != "USD":
                    print(f"[error] SerpApi returned currency {currency}, not USD. Skipping query.")
                    break

            properties = payload.get("properties")
            if not isinstance(properties, list):
                print(f"[warn] query {query!r} page {page + 1}: no 'properties' array in response")
                break

            for prop in properties:
                if isinstance(prop, dict):
                    collected.setdefault(hotel_key(prop), prop)

            print(f"[info] {query!r} page {page + 1}: {len(properties)} properties")

            pagination = payload.get("serpapi_pagination")
            next_page_token = (
                pagination.get("next_page_token") if isinstance(pagination, dict) else None
            )
            if not next_page_token:
                break

    return list(collected.values())


def fetch_property_details(
    session: requests.Session, settings: Settings, hotel: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """
    Fetch the Property Details payload for one hotel.

    This is where the truth lives. Search results carry only Google's headline
    "from" price - a teaser for the cheapest bed or room, with no occupancy
    attached. Property Details carries the actual bookable offers
    (`featured_prices[].rooms[]`, `prices[]`) complete with `num_guests`, plus
    the street address.

    Costs one SerpApi credit, so it only runs for hotels that already passed
    geography and the preliminary price screen.
    """
    token = hotel.get("property_token")
    if not settings.fetch_details or not isinstance(token, str) or not token:
        return None

    params = {
        "engine": "google_hotels",
        "q": hotel.get("name") or "hotel",
        "property_token": token,
        "check_in_date": CHECK_IN_DATE,
        "check_out_date": CHECK_OUT_DATE,
        "adults": settings.adults,
        "currency": "USD",
        "gl": "us",
        "hl": "en",
        "api_key": settings.serpapi_key,
    }
    try:
        return _serpapi_get(session, params)
    except SerpApiError as exc:
        print(f"[warn] could not fetch property details: {exc}")
        return None


# ---------------------------------------------------------------------------
# 7. STATE  --  keeps the bot from spamming
# ---------------------------------------------------------------------------


def hotel_key(hotel: dict[str, Any]) -> str:
    """A stable id for a hotel across runs."""
    token = hotel.get("property_token")
    if isinstance(token, str) and token:
        return f"token:{token}"
    name = re.sub(r"\s+", " ", str(hotel.get("name") or "unknown")).strip().lower()
    coords = hotel.get("gps_coordinates") or {}
    try:
        lat = round(float(coords.get("latitude")), 4)
        lon = round(float(coords.get("longitude")), 4)
        return f"geo:{name}|{lat}|{lon}"
    except (TypeError, ValueError):
        return f"name:{name}"


def load_state(path: str = STATE_FILE) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {"version": 1, "hotels": {}}
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[warn] state file unreadable ({exc}); starting fresh")
        return {"version": 1, "hotels": {}}

    if not isinstance(data, dict) or not isinstance(data.get("hotels"), dict):
        print("[warn] state file has an unexpected shape; starting fresh")
        return {"version": 1, "hotels": {}}
    data.setdefault("version", 1)
    return data


def save_state(state: dict[str, Any], path: str = STATE_FILE) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except OSError as exc:
        print(f"[warn] could not write state file: {exc}")


def _hours_since(iso_timestamp: Any) -> Optional[float]:
    if not isinstance(iso_timestamp, str):
        return None
    try:
        stamp = datetime.fromisoformat(iso_timestamp)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 3600.0


def should_alert(previous: Optional[dict[str, Any]], total: float, settings: Settings) -> tuple[bool, str]:
    """
    Decide whether a qualifying hotel is worth another Discord message.

    Alert when: we have never alerted, or the hotel climbed back over the
    threshold and has now dropped under it again, or the price fell by at
    least MIN_DROP_USD since the last alert.
    """
    if not previous:
        return True, "first time under the threshold"

    if not previous.get("below_threshold", False):
        return True, "back under the threshold after being above it"

    last_alert_total = previous.get("last_alert_total")
    if not isinstance(last_alert_total, (int, float)):
        return True, "no recorded price from the last alert"

    drop = float(last_alert_total) - total
    if drop >= settings.min_drop_usd:
        return True, f"price dropped ${drop:,.2f} since the last alert"

    if settings.renotify_after_hours > 0:
        elapsed = _hours_since(previous.get("last_alert_at"))
        if elapsed is not None and elapsed >= settings.renotify_after_hours:
            return True, f"{elapsed:.0f}h since the last alert"

    return False, f"already alerted at ${last_alert_total:,.2f} (only ${drop:,.2f} cheaper)"


# ---------------------------------------------------------------------------
# 8. DISCORD
# ---------------------------------------------------------------------------

COLOR_ACTUAL = 0x2ECC71    # green
COLOR_ESTIMATED = 0xE67E22  # orange


def google_hotels_link(hotel: dict[str, Any]) -> str:
    """
    A Google Hotels link carrying OUR dates and guest count.

    This matters: `hotel["link"]` is the property's own website, whose direct
    rack rate is often nothing like the aggregated price we quoted. Linking to
    the dated Google Hotels comparison is what lets you actually check the
    number in the alert.
    """
    name = str(hotel.get("name") or "hotel")
    query = urllib.parse.quote_plus(f"{name} New York")
    return (
        f"https://www.google.com/travel/search?q={query}"
        f"&checkin={CHECK_IN_DATE}&checkout={CHECK_OUT_DATE}"
    )


def build_discord_payload(
    hotel: dict[str, Any],
    best: Offer,
    others: list[Offer],
    address: Optional[str],
    settings: Settings,
) -> dict[str, Any]:
    coords = hotel.get("gps_coordinates") or {}
    try:
        lat = float(coords.get("latitude"))
        lon = float(coords.get("longitude"))
        area = f"{approximate_neighborhood(lat, lon)}, Manhattan"
        maps_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
    except (TypeError, ValueError):
        area = "Manhattan"
        maps_url = None

    # Primary link = the dated Google Hotels comparison, because that is where
    # the quoted price came from and therefore the only place it can be
    # checked. The property's own website is offered separately.
    compare_link = google_hotels_link(hotel)
    own_site = hotel.get("link") if isinstance(hotel.get("link"), str) else None
    link = compare_link

    fields: list[dict[str, Any]] = [
        {"name": "\U0001f4cd Area", "value": area, "inline": True},
        {"name": "\U0001f4c5 Dates", "value": STAY_LABEL, "inline": True},
        {
            "name": f"\U0001f4b0 {best.total_label()}",
            "value": f"**${best.total:,.2f}**  (threshold ${settings.max_total_price_usd:,.0f})",
            "inline": False,
        },
        {
            "name": "Nightly",
            "value": f"${best.nightly_display:,.2f}/night × {NIGHTS} nights",
            "inline": True,
        },
        {"name": "Provider", "value": best.provider, "inline": True},
        {
            "name": "Guests",
            "value": (
                f"{best.num_guests} guest(s) — matches your search"
                if best.num_guests is not None
                else "⚠️ Not stated by the API — confirm the room sleeps "
                     f"{settings.adults}"
            ),
            "inline": True,
        },
        {"name": "Price type", "value": best.price_type_label(), "inline": False},
    ]

    if address:
        fields.append({"name": "Address", "value": address, "inline": False})
    elif maps_url:
        fields.append(
            {
                "name": "Address",
                "value": f"Not supplied by the API — [open in Google Maps]({maps_url})",
                "inline": False,
            }
        )

    if others:
        lines = [
            f"• {o.provider}: ${o.total:,.2f} "
            f"({'actual' if o.kind == ACTUAL else 'estimated'})"
            for o in others[:3]
        ]
        fields.append(
            {"name": "Other qualifying prices", "value": "\n".join(lines), "inline": False}
        )

    link_lines = [f"[Compare prices on Google Hotels for these dates]({compare_link})"]
    if own_site:
        link_lines.append(f"[The hotel's own website]({own_site}) (direct rate may differ)")
    fields.append(
        {
            "name": "\U0001f517 Booking / Hotel Link",
            "value": "\n".join(link_lines) + "\n**Always confirm the final checkout price.**",
            "inline": False,
        }
    )

    description = None
    if best.kind == ESTIMATED:
        description = (
            f"⚠️ This total is **estimated** from the nightly rate "
            f"(${best.nightly_display:,.2f} × {NIGHTS} nights). "
            "Final taxes and fees may differ — check the link before booking."
        )
    elif not best.includes_taxes_fees:
        description = (
            "⚠️ This is a real stay total, but the API flagged it as "
            "**before taxes & fees**. The checkout price will be higher."
        )

    embed: dict[str, Any] = {
        "title": str(hotel.get("name") or "Hotel"),
        "url": link,
        "color": COLOR_ACTUAL if best.kind == ACTUAL else COLOR_ESTIMATED,
        "fields": fields,
        "footer": {"text": "Manhattan only · total stay under threshold · verify before booking"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if description:
        embed["description"] = description

    images = hotel.get("images")
    if isinstance(images, list) and images and isinstance(images[0], dict):
        thumb = images[0].get("thumbnail")
        if isinstance(thumb, str) and thumb.startswith("http"):
            embed["thumbnail"] = {"url": thumb}

    return {"content": "\U0001f3e8 **HOTEL PRICE ALERT**", "embeds": [embed]}


def send_discord(session: requests.Session, webhook_url: str, payload: dict[str, Any]) -> bool:
    """Post to Discord. Returns True on success; never raises, never logs the URL."""
    if not webhook_url:
        print("[error] DISCORD_WEBHOOK_URL is not set; cannot send alert")
        return False
    try:
        response = session.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        print(f"[error] Discord request failed: {exc}")
        return False

    if response.status_code in (200, 204):
        return True
    if response.status_code == 429:
        print("[error] Discord rate limited this alert (429)")
    else:
        print(f"[error] Discord returned HTTP {response.status_code}")
    return False


def sample_payload(settings: Settings) -> dict[str, Any]:
    """A realistic-looking alert used by --test-discord."""
    hotel = {
        "name": "Example Hotel (test message)",
        "gps_coordinates": {"latitude": 40.7075, "longitude": -74.0100},
        "link": "https://www.google.com/travel/search?q=example+hotel+new+york",
    }
    best = Offer(
        provider="Booking.com",
        total=1850.00,
        kind=ACTUAL,
        includes_taxes_fees=True,
        nightly=462.50,
        link=hotel["link"],
    )
    others = [Offer("Expedia", 1975.00, ACTUAL, True, 493.75, hotel["link"])]
    return build_discord_payload(hotel, best, others, "123 Example Street, New York, NY 10004", settings)


# ---------------------------------------------------------------------------
# 9. MAIN
# ---------------------------------------------------------------------------


def process_hotels(
    hotels: list[dict[str, Any]],
    state: dict[str, Any],
    settings: Settings,
    session: requests.Session,
    dry_run: bool,
) -> int:
    """Filter, price, de-duplicate and alert. Returns the number of alerts sent."""
    threshold = settings.max_total_price_usd
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    hotels_state: dict[str, Any] = state["hotels"]

    rejected_geo = 0
    rejected_price = 0
    suppressed = 0
    alerts_sent = 0

    for hotel in hotels:
        try:
            name = str(hotel.get("name") or "(unnamed)")

            accepted, reason = is_valid_manhattan_hotel(hotel)
            if not accepted:
                rejected_geo += 1
                print(f"[skip-geo]   {name}: {reason}")
                continue

            offers = extract_offers(hotel, required_guests=settings.adults)
            if not offers:
                rejected_price += 1
                print(f"[skip-price] {name}: no usable USD price")
                continue

            observed = cheapest_observed_total(offers)
            key = hotel_key(hotel)
            previous = hotels_state.get(key) if isinstance(hotels_state.get(key), dict) else None

            best, others = pick_best_offer(offers, threshold)

            if best is None:
                rejected_price += 1
                cheapest = f"${observed:,.2f}" if observed is not None else "unknown"
                print(f"[skip-price] {name}: cheapest total {cheapest} is not under ${threshold:,.0f}")
                record = dict(previous or {})
                record.update(
                    {
                        "name": name,
                        "last_seen_total": observed,
                        "last_seen_at": now_iso,
                        "below_threshold": False,
                    }
                )
                hotels_state[key] = record
                continue

            alert, why = should_alert(previous, best.total, settings)
            if not alert:
                suppressed += 1
                print(f"[quiet]      {name}: ${best.total:,.2f} — {why}")
                record = dict(previous or {})
                record.update(
                    {
                        "name": name,
                        "last_seen_total": best.total,
                        "last_seen_at": now_iso,
                        "below_threshold": True,
                    }
                )
                hotels_state[key] = record
                continue

            if alerts_sent >= settings.max_alerts_per_run:
                print(f"[quiet]      {name}: hit MAX_ALERTS_PER_RUN, will retry next run")
                continue

            if dry_run:
                print(
                    f"[dry-run]    ALERT {name}: ${best.total:,.2f} ({best.kind}) — {why} "
                    "(unverified: dry runs skip the details lookup)"
                )
                continue

            # The search price is only a screen. Before telling anyone about
            # it, confirm it against the real bookable offers.
            address = None
            details = fetch_property_details(session, settings, hotel)
            if details:
                raw_address = details.get("address")
                if isinstance(raw_address, str) and raw_address.strip():
                    address = raw_address.strip()
                    # Last geography check, now that we finally have street text.
                    enriched = dict(hotel)
                    enriched["address"] = address
                    accepted, reason = is_valid_manhattan_hotel(enriched)
                    if not accepted:
                        rejected_geo += 1
                        print(f"[skip-geo]   {name}: address check failed — {reason}")
                        continue

                verified = offers_from_details(details, required_guests=settings.adults)
                if verified:
                    v_best, v_others = pick_best_offer(verified, threshold)
                    if v_best is None:
                        cheapest = min(o.total for o in verified)
                        rejected_price += 1
                        print(
                            f"[skip-price] {name}: screened at ${best.total:,.2f} but the real "
                            f"bookable price is ${cheapest:,.2f} — not under ${threshold:,.0f}"
                        )
                        record = dict(previous or {})
                        record.update({
                            "name": name,
                            "last_seen_total": cheapest,
                            "last_seen_at": now_iso,
                            "below_threshold": False,
                        })
                        hotels_state[key] = record
                        continue

                    if abs(v_best.total - best.total) >= 1.0:
                        print(
                            f"[verify]     {name}: search said ${best.total:,.2f}, "
                            f"real offer is ${v_best.total:,.2f} ({v_best.provider})"
                        )
                    best, others = v_best, v_others

                    # The suppression decision must use the verified price.
                    alert, why = should_alert(previous, best.total, settings)
                    if not alert:
                        suppressed += 1
                        print(f"[quiet]      {name}: ${best.total:,.2f} — {why}")
                        record = dict(previous or {})
                        record.update({
                            "name": name,
                            "last_seen_total": best.total,
                            "last_seen_at": now_iso,
                            "below_threshold": True,
                        })
                        hotels_state[key] = record
                        continue
                elif settings.require_verified_price:
                    print(
                        f"[skip-price] {name}: ${best.total:,.2f} is an unverified Google "
                        "'from' price with no bookable offer behind it"
                    )
                    continue
            elif settings.require_verified_price:
                print(f"[skip-price] {name}: could not verify the price; not alerting")
                continue

            payload = build_discord_payload(hotel, best, others, address, settings)

            if send_discord(session, settings.discord_webhook_url, payload):
                alerts_sent += 1
                print(f"[ALERT]      {name}: ${best.total:,.2f} ({best.kind}) — {why}")
                hotels_state[key] = {
                    "name": name,
                    "last_alert_total": best.total,
                    "last_alert_at": now_iso,
                    "last_alert_kind": best.kind,
                    "last_seen_total": best.total,
                    "last_seen_at": now_iso,
                    "below_threshold": True,
                }
            else:
                print(f"[warn]       Discord send failed for {name}; state not updated")

        except Exception as exc:  # one bad record must not kill the run
            print(f"[warn] skipped a malformed result: {exc}")

    print(
        f"\n[summary] {len(hotels)} results → "
        f"{rejected_geo} rejected on location, "
        f"{rejected_price} rejected on price, "
        f"{suppressed} suppressed as duplicates, "
        f"{alerts_sent} alert(s) sent"
    )
    return alerts_sent


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Manhattan hotel price alert bot")
    parser.add_argument("--dry-run", action="store_true", help="search and filter, but send nothing")
    parser.add_argument("--test-discord", action="store_true", help="send one sample alert and exit")
    parser.add_argument("--print-config", action="store_true", help="show settings, make no calls")
    parser.add_argument(
        "--debug-hotel",
        metavar="NAME",
        help="dump the raw SerpApi data for hotels whose name contains NAME",
    )
    args = parser.parse_args(argv)

    settings = Settings.from_env()

    if args.print_config:
        print(f"Check-in            : {CHECK_IN_DATE}  (fixed)")
        print(f"Check-out           : {CHECK_OUT_DATE}  (fixed)")
        print(f"Nights              : {NIGHTS}")
        print(f"Threshold           : total < ${settings.max_total_price_usd:,.2f} USD")
        print(f"Adults              : {settings.adults}")
        print(f"Queries             : {settings.queries}")
        print(f"Pages per query     : {settings.max_pages}")
        print(f"Min re-alert drop   : ${settings.min_drop_usd:,.2f}")
        print(f"Renotify after      : {settings.renotify_after_hours} h (0 = never)")
        print(f"SERPAPI_KEY set     : {bool(settings.serpapi_key)}")
        print(f"DISCORD_WEBHOOK set : {bool(settings.discord_webhook_url)}")
        return 0

    session = build_session()

    if args.test_discord:
        if not settings.discord_webhook_url:
            print("[error] DISCORD_WEBHOOK_URL is not set.")
            return 1
        ok = send_discord(session, settings.discord_webhook_url, sample_payload(settings))
        print("Test message sent." if ok else "Test message FAILED.")
        return 0 if ok else 1

    if not settings.serpapi_key:
        print("[error] SERPAPI_KEY is not set. Add it as a GitHub Actions secret.")
        return 1
    # --dry-run and --debug-hotel never post anything, so they do not need a
    # webhook. Only a real run does.
    if not settings.discord_webhook_url and not args.dry_run and not args.debug_hotel:
        print(
            "[error] DISCORD_WEBHOOK_URL is not set. Set it in your shell to run "
            "locally, or add it as a GitHub Actions secret."
        )
        return 1

    print(f"Searching {CHECK_IN_DATE} → {CHECK_OUT_DATE} ({NIGHTS} nights), "
          f"total under ${settings.max_total_price_usd:,.0f} USD, Manhattan only.\n")

    try:
        hotels = search_hotels(session, settings)
    except SerpApiError as exc:
        print(f"[error] {exc}")
        return 1

    if not hotels:
        print("[info] no results returned this run; nothing to do")
        return 0

    if args.debug_hotel:
        needle = args.debug_hotel.strip().lower()
        matches = [h for h in hotels if needle in str(h.get("name") or "").lower()]
        if not matches:
            print(f"No hotel matching {args.debug_hotel!r} in {len(hotels)} results.")
            print("Names returned:")
            for h in hotels:
                print(f"  - {h.get('name')}")
            return 0

        for match in matches:
            print("=" * 70)
            print(f"RAW SERPAPI DATA — {match.get('name')}")
            print("=" * 70)
            print(json.dumps(
                {
                    key: match.get(key)
                    for key in (
                        "name", "type", "link", "property_token", "gps_coordinates",
                        "rate_per_night", "total_rate", "prices", "deal",
                        "deal_description", "hotel_class",
                    )
                    if match.get(key) is not None
                },
                indent=2,
            ))
            print("\nHOW THE BOT READS THAT:")
            for offer in extract_offers(match, required_guests=settings.adults):
                guests = offer.num_guests if offer.num_guests is not None else "not stated"
                print(
                    f"  {offer.provider:<32} ${offer.total:>9,.2f} {offer.kind:<9} "
                    f"guests={guests} taxes_included={offer.includes_taxes_fees}"
                )
            best, _ = pick_best_offer(
                extract_offers(match, required_guests=settings.adults),
                settings.max_total_price_usd,
            )
            print(f"  -> screened as: {best.provider} ${best.total:,.2f}" if best
                  else "  -> nothing qualifies from search data")

            print("\nVERIFIED BOOKABLE OFFERS (Property Details API, 1 credit):")
            details = fetch_property_details(session, settings, match)
            if not details:
                print("  (details lookup failed)")
                continue

            address = details.get("address")
            if isinstance(address, str):
                print(f"  address: {address}")

            verified = offers_from_details(details, required_guests=settings.adults)
            if not verified:
                print("  none — no bookable offer backs the headline price.")
                print(f"  raw keys returned: {sorted(details.keys())}")
                continue

            for offer in sorted(verified, key=lambda o: o.total):
                guests = offer.num_guests if offer.num_guests is not None else "not stated"
                print(
                    f"  {offer.provider[:44]:<44} ${offer.total:>9,.2f} "
                    f"{offer.kind:<9} guests={guests}"
                )
            v_best, _ = pick_best_offer(verified, settings.max_total_price_usd)
            print(
                f"  -> WOULD ALERT: {v_best.provider} ${v_best.total:,.2f}"
                if v_best
                else f"  -> no alert: nothing under ${settings.max_total_price_usd:,.0f}"
            )
        return 0

    state = load_state()
    process_hotels(hotels, state, settings, session, dry_run=args.dry_run)
    if not args.dry_run:
        save_state(state)
    return 0


if __name__ == "__main__":
    # Emoji in the logs must not crash a Windows console.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    sys.exit(main())
