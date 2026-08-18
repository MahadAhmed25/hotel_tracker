"""
Tests for the Manhattan hotel price alert bot.

Run them with:   pytest -q
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hotel_tracker as ht  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def hotel(name, lat=None, lon=None, **extra):
    """Build a minimal SerpApi-shaped property record."""
    record = {"name": name}
    if lat is not None and lon is not None:
        record["gps_coordinates"] = {"latitude": lat, "longitude": lon}
    record.update(extra)
    return record


def accepted(record):
    return ht.is_valid_manhattan_hotel(record)[0]


def rate(lowest=None, before=None):
    """Build a SerpApi rate object the way the real API returns it."""
    out = {}
    if lowest is not None:
        out["lowest"] = f"${lowest:,.0f}" if float(lowest).is_integer() else f"${lowest:,.2f}"
        out["extracted_lowest"] = lowest
    if before is not None:
        out["before_taxes_fees"] = f"${before:,.0f}"
        out["extracted_before_taxes_fees"] = before
    return out


# ---------------------------------------------------------------------------
# fixed dates
# ---------------------------------------------------------------------------


def test_dates_are_fixed_and_four_nights():
    assert ht.CHECK_IN_DATE == "2026-09-04"
    assert ht.CHECK_OUT_DATE == "2026-09-08"
    assert ht.NIGHTS == 4, "checkout day must not be counted as a night"


def test_dates_are_not_configurable_from_the_environment():
    source = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hotel_tracker.py"),
        encoding="utf-8",
    ).read()
    assert "CHECK_IN_DATE" in source
    assert 'environ.get("CHECK_IN_DATE"' not in source
    assert 'environ.get("CHECK_OUT_DATE"' not in source


# ---------------------------------------------------------------------------
# geography - ACCEPT
# ---------------------------------------------------------------------------

MANHATTAN_HOTELS = [
    ("Financial District", 40.7075, -74.0113),
    ("Lower Manhattan / Battery Park", 40.7033, -74.0155),
    ("Tribeca", 40.7195, -74.0090),
    ("SoHo", 40.7233, -74.0030),
    ("Nolita", 40.7220, -73.9955),
    ("Chinatown", 40.7158, -73.9970),
    ("Lower East Side", 40.7180, -73.9880),
    ("Greenwich Village", 40.7336, -74.0027),
    ("West Village", 40.7358, -74.0036),
    ("Flatiron", 40.7411, -73.9897),
    ("Union Square", 40.7359, -73.9911),
    ("Chelsea", 40.7465, -74.0014),
    ("Midtown / Times Square", 40.7580, -73.9855),
    ("Midtown East", 40.7549, -73.9748),
    ("Upper East Side", 40.7736, -73.9566),
    ("Lenox Hill", 40.7660, -73.9620),
    ("Yorkville", 40.7760, -73.9490),
    ("Carnegie Hill", 40.7840, -73.9540),
    ("Upper West Side south of 110th", 40.7870, -73.9754),
]


@pytest.mark.parametrize("label,lat,lon", MANHATTAN_HOTELS)
def test_accepts_manhattan_neighborhoods(label, lat, lon):
    ok, reason = ht.is_valid_manhattan_hotel(hotel(f"{label} Hotel", lat, lon))
    assert ok, f"{label} should be accepted, got: {reason}"


# ---------------------------------------------------------------------------
# geography - REJECT
# ---------------------------------------------------------------------------

EXCLUDED_HOTELS = [
    ("Long Island City", 40.7440, -73.9490),
    ("Astoria", 40.7644, -73.9235),
    ("Flushing", 40.7590, -73.8300),
    ("Brooklyn (Downtown)", 40.6928, -73.9903),
    ("Williamsburg Brooklyn", 40.7145, -73.9613),
    ("DUMBO Brooklyn", 40.7033, -73.9881),
    ("Jersey City", 40.7178, -74.0431),
    ("Hoboken", 40.7440, -74.0324),
    ("Newark", 40.7357, -74.1724),
    ("The Bronx", 40.8448, -73.8648),
    ("Harlem", 40.8116, -73.9465),
    ("East Harlem", 40.7957, -73.9389),
    ("Washington Heights", 40.8417, -73.9394),
    ("Inwood", 40.8677, -73.9212),
    ("Staten Island", 40.5795, -74.1502),
    ("Roosevelt Island", 40.7614, -73.9506),
    ("Long Island / Nassau", 40.7259, -73.5143),
    ("Morningside Heights", 40.8075, -73.9626),
]


@pytest.mark.parametrize("label,lat,lon", EXCLUDED_HOTELS)
def test_rejects_excluded_locations(label, lat, lon):
    ok, _ = ht.is_valid_manhattan_hotel(hotel(f"{label} Hotel", lat, lon))
    assert not ok, f"{label} must never be accepted"


def test_rejects_anything_north_of_central_park():
    # 110th Street is the line. Just south passes, just north does not.
    assert accepted(hotel("Just south of 110th on CPW", 40.7985, -73.9580))
    assert not accepted(hotel("Just north of 110th on CPW", 40.8060, -73.9580))


def test_upper_west_side_is_only_ok_south_of_the_park_boundary():
    assert accepted(hotel("UWS 79th St", 40.7830, -73.9790))
    assert not accepted(hotel("UWS 116th St", 40.8070, -73.9660))


# ---------------------------------------------------------------------------
# geography - ambiguity is always rejected
# ---------------------------------------------------------------------------


def test_rejects_hotel_without_coordinates():
    ok, reason = ht.is_valid_manhattan_hotel({"name": "Mystery Hotel"})
    assert not ok
    assert "gps" in reason.lower()


def test_rejects_non_numeric_coordinates():
    assert not accepted(hotel("Bad Coords", "not-a-number", "nope"))
    assert not accepted({"name": "Null Coords", "gps_coordinates": {"latitude": None, "longitude": None}})


def test_rejects_out_of_range_coordinates():
    assert not accepted(hotel("Impossible", 999.0, 999.0))


def test_rejects_empty_or_malformed_records():
    assert not accepted({})
    assert not ht.is_valid_manhattan_hotel(None)[0]
    assert not ht.is_valid_manhattan_hotel("a string")[0]


def test_rejects_excluded_place_named_in_the_address_even_with_manhattan_coords():
    # Contradictory data is ambiguous data - throw it away.
    record = hotel("Some Hotel", 40.7580, -73.9855, address="123 Main St, Brooklyn, NY 11201")
    assert not accepted(record)

    record = hotel("Some Hotel", 40.7580, -73.9855, address="1 Plaza, Jersey City, NJ 07302")
    assert not accepted(record)


def test_rejects_excluded_place_named_in_the_hotel_name():
    assert not accepted(hotel("Comfort Inn Long Island City", 40.7580, -73.9855))
    assert not accepted(hotel("Aloft Harlem", 40.7580, -73.9855))


def test_nearby_landmarks_do_not_reject_a_valid_manhattan_hotel():
    # "Brooklyn Bridge" appears constantly in Lower Manhattan listings.
    record = hotel(
        "Hotel Near Brooklyn Bridge",
        40.7105,
        -74.0040,
        address="123 Nassau St, New York, NY 10038",
    )
    assert accepted(record), "a Manhattan hotel must not be rejected for a landmark name"


def test_description_marketing_copy_does_not_reject():
    record = hotel(
        "Seaport Hotel",
        40.7075,
        -74.0030,
        description="Stylish rooms with views of Brooklyn and the harbour.",
    )
    assert accepted(record)


def test_word_boundaries_do_not_cause_false_rejections():
    assert ht._contains_excluded_place("The Public Hotel, 215 Chrystie St") is None
    assert ht._contains_excluded_place("Delicious Suites New York") is None
    assert ht._contains_excluded_place("Hotel in Astoria, Queens") is not None


# ---------------------------------------------------------------------------
# price threshold - strict "<", never "<="
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "total,expected",
    [
        (1500.00, True),
        (1800.00, True),
        (1900.00, True),
        (1996.00, True),
        (1999.00, True),
        (1999.99, True),
        (2000.00, False),   # exactly the threshold does NOT qualify
        (2000.01, False),
        (2001.00, False),
        (2300.00, False),
    ],
)
def test_threshold_is_strictly_less_than(total, expected):
    offers = [ht.Offer("Booking.com", total, ht.ACTUAL, True)]
    best, _ = ht.pick_best_offer(offers, 2000.0)
    assert (best is not None) is expected


@pytest.mark.parametrize(
    "nightly,expected",
    [
        (450.0, True),    # 1800
        (475.0, True),    # 1900
        (499.0, True),    # 1996
        (499.99, True),   # 1999.96
        (500.0, False),   # exactly 2000
        (501.0, False),   # 2004
    ],
)
def test_nightly_rate_times_four_nights(nightly, expected):
    record = hotel("X", 40.7580, -73.9855, rate_per_night=rate(nightly))
    offers = ht.extract_offers(record)
    assert offers[0].kind == ht.ESTIMATED
    assert offers[0].total == pytest.approx(nightly * 4, abs=0.01)
    best, _ = ht.pick_best_offer(offers, 2000.0)
    assert (best is not None) is expected


def test_calculated_totals_at_other_night_counts(monkeypatch):
    # The stay is fixed at 4 nights, but the arithmetic itself must be right.
    monkeypatch.setattr(ht, "NIGHTS", 3)

    record = hotel("Three Nights", 40.7580, -73.9855, rate_per_night=rate(500.0))
    offers = ht.extract_offers(record)
    assert offers[0].total == pytest.approx(1500.00)
    assert ht.pick_best_offer(offers, 2000.0)[0] is not None

    record = hotel("Three Nights", 40.7580, -73.9855, rate_per_night=rate(666.67))
    offers = ht.extract_offers(record)
    assert offers[0].total == pytest.approx(2000.01, abs=0.01)
    assert ht.pick_best_offer(offers, 2000.0)[0] is None, "$2,000.01 must be rejected"


# ---------------------------------------------------------------------------
# actual total always beats a calculated one
# ---------------------------------------------------------------------------


def test_actual_total_takes_priority_over_nightly_calculation(monkeypatch):
    """Nightly $600 x 3 = $1,800 calculated, but the real total is $2,050 -> REJECT."""
    monkeypatch.setattr(ht, "NIGHTS", 3)

    record = hotel(
        "Priority Hotel",
        40.7580,
        -73.9855,
        rate_per_night=rate(600.0),
        total_rate=rate(2050.0),
    )
    offers = ht.extract_offers(record)
    assert offers[0].kind == ht.ACTUAL
    assert offers[0].total == pytest.approx(2050.0)

    best, _ = ht.pick_best_offer(offers, 2000.0)
    assert best is None, "the actual total is what matters, not the nightly rate"


def test_actual_total_wins_at_four_nights():
    record = hotel(
        "Four Night Hotel",
        40.7580,
        -73.9855,
        rate_per_night=rate(450.0),      # would calculate to $1,800
        total_rate=rate(2100.0),         # but the real total is $2,100
    )
    best, _ = ht.pick_best_offer(ht.extract_offers(record), 2000.0)
    assert best is None


def test_actual_total_below_threshold_alerts_even_when_nightly_is_high():
    # $550/night would calculate to $2,200, but the API says the stay is $1,950.
    record = hotel(
        "Discounted Hotel",
        40.7580,
        -73.9855,
        rate_per_night=rate(550.0),
        total_rate=rate(1950.0),
    )
    best, _ = ht.pick_best_offer(ht.extract_offers(record), 2000.0)
    assert best is not None
    assert best.kind == ht.ACTUAL
    assert best.total == pytest.approx(1950.0)


def test_an_estimate_can_never_undercut_a_real_total():
    """A provider quoting only a nightly rate must not mask a real total."""
    record = hotel(
        "Mixed Signals",
        40.7580,
        -73.9855,
        total_rate=rate(2050.0),
        prices=[{"source": "Expedia", "rate_per_night": rate(400.0)}],  # would be $1,600
    )
    best, _ = ht.pick_best_offer(ht.extract_offers(record), 2000.0)
    assert best is None


# ---------------------------------------------------------------------------
# provider selection
# ---------------------------------------------------------------------------


def test_picks_the_cheapest_qualifying_provider():
    record = hotel(
        "Multi Provider Hotel",
        40.7075,
        -74.0113,
        prices=[
            {"source": "Expedia", "total_rate": rate(2100.0)},
            {"source": "Booking.com", "total_rate": rate(1950.0)},
            {"source": "Hotels.com", "total_rate": rate(1990.0)},
        ],
    )
    best, others = ht.pick_best_offer(ht.extract_offers(record), 2000.0)
    assert best.provider == "Booking.com"
    assert best.total == pytest.approx(1950.0)
    assert [o.provider for o in others] == ["Hotels.com"], "only qualifying extras are mentioned"


def test_one_hotel_yields_one_alert_not_one_per_provider():
    record = hotel(
        "Many Rooms Hotel",
        40.7075,
        -74.0113,
        prices=[{"source": f"Provider {i}", "total_rate": rate(1500.0 + i)} for i in range(10)],
    )
    best, others = ht.pick_best_offer(ht.extract_offers(record), 2000.0)
    assert best is not None
    assert len(ht.build_discord_payload(record, best, others, None, ht.Settings())["embeds"]) == 1


def test_named_provider_beats_the_generic_headline_at_the_same_price():
    record = hotel(
        "Tie Hotel",
        40.7075,
        -74.0113,
        total_rate=rate(1850.0),
        prices=[
            {"source": "Booking.com", "total_rate": rate(1850.0)},
            {"source": "Expedia", "total_rate": rate(1975.0)},
        ],
    )
    best, others = ht.pick_best_offer(ht.extract_offers(record), 2000.0)
    assert best.provider == "Booking.com", "you should be told who to book with"
    assert [o.provider for o in others] == ["Expedia"], "no duplicate headline line"


def test_all_in_price_preferred_over_pre_tax_at_the_same_number():
    offers = [
        ht.Offer("Pre-tax Co", 1800.0, ht.ACTUAL, includes_taxes_fees=False),
        ht.Offer("All-in Co", 1800.0, ht.ACTUAL, includes_taxes_fees=True),
    ]
    best, _ = ht.pick_best_offer(offers, 2000.0)
    assert best.provider == "All-in Co"


# ---------------------------------------------------------------------------
# missing / malformed price data
# ---------------------------------------------------------------------------


def test_no_price_information_means_no_offer():
    assert ht.extract_offers(hotel("No Prices", 40.7580, -73.9855)) == []


def test_malformed_price_values_are_ignored():
    record = hotel(
        "Broken Prices",
        40.7580,
        -73.9855,
        rate_per_night={"lowest": "$abc", "extracted_lowest": "not a number"},
    )
    assert ht.extract_offers(record) == []


def test_zero_and_negative_prices_are_ignored():
    record = hotel("Free?", 40.7580, -73.9855, rate_per_night={"lowest": "$0", "extracted_lowest": 0})
    assert ht.extract_offers(record) == []


def test_pre_tax_only_price_is_labelled_as_such():
    record = hotel("Pre Tax Hotel", 40.7580, -73.9855, total_rate=rate(before=1750.0))
    offer = ht.extract_offers(record)[0]
    assert offer.kind == ht.ACTUAL
    assert offer.includes_taxes_fees is False
    assert offer.total == pytest.approx(1750.0)
    assert "before taxes" in offer.total_label().lower()
    assert "BEFORE TAXES" in offer.price_type_label().upper()


# ---------------------------------------------------------------------------
# currency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["$1,850", "$1,850.00", "$499", "$1850", "$1,999.99"])
def test_accepts_plain_usd_strings(text):
    assert ht.is_usd_price_string(text)


@pytest.mark.parametrize(
    "text",
    ["CA$1,850", "A$1850", "MX$1,850", "HK$900", "S$900", "R$900", "NZ$900", "US$900",
     "€1,850", "£1,850", "¥185000", "₹185000", "1850", "1,850 USD", "", None, 1850],
)
def test_rejects_anything_not_plainly_usd(text):
    assert not ht.is_usd_price_string(text)


def test_price_in_a_foreign_currency_is_discarded():
    record = hotel(
        "Euro Hotel",
        40.7580,
        -73.9855,
        total_rate={"lowest": "€1,500", "extracted_lowest": 1500},
    )
    assert ht.extract_offers(record) == [], "a non-USD total must never be compared to $2,000"


def test_a_numeric_price_with_no_display_string_is_still_accepted():
    # SerpApi was asked for USD and echoed USD; a missing display string is
    # not, by itself, a reason to throw the number away.
    record = hotel("Sparse Hotel", 40.7580, -73.9855, total_rate={"extracted_lowest": 1800})
    offers = ht.extract_offers(record)
    assert len(offers) == 1
    assert offers[0].total == pytest.approx(1800.0)


# ---------------------------------------------------------------------------
# duplicate suppression
# ---------------------------------------------------------------------------


def settings(**kw):
    s = ht.Settings()
    for key, value in kw.items():
        setattr(s, key, value)
    return s


def test_alerts_the_first_time_a_hotel_drops_below():
    ok, why = ht.should_alert(None, 1950.0, settings())
    assert ok and "first time" in why


def test_does_not_repeat_an_alert_for_a_trivial_drop():
    """The scenario from the brief: 1950 -> 1949 -> 1940 -> 1935 stays quiet."""
    prev = {"last_alert_total": 1950.0, "below_threshold": True}
    for price in (1949.0, 1940.0, 1935.0):
        ok, _ = ht.should_alert(prev, price, settings(min_drop_usd=50.0))
        assert not ok, f"${price} is not a meaningful drop from $1,950"


def test_alerts_again_on_a_meaningful_drop():
    prev = {"last_alert_total": 1950.0, "below_threshold": True}
    ok, why = ht.should_alert(prev, 1899.0, settings(min_drop_usd=50.0))
    assert ok and "dropped" in why


def test_alerts_again_after_going_back_over_the_threshold():
    """2300 -> 2100 -> 1950 alerts; then back over 2000; then under again alerts."""
    prev = {"last_alert_total": 1950.0, "below_threshold": False}
    ok, why = ht.should_alert(prev, 1980.0, settings())
    assert ok and "back under" in why


def test_min_drop_is_configurable():
    prev = {"last_alert_total": 1950.0, "below_threshold": True}
    assert not ht.should_alert(prev, 1930.0, settings(min_drop_usd=50.0))[0]
    assert ht.should_alert(prev, 1930.0, settings(min_drop_usd=10.0))[0]


def test_time_based_renotify_is_off_by_default():
    prev = {
        "last_alert_total": 1950.0,
        "below_threshold": True,
        "last_alert_at": "2000-01-01T00:00:00+00:00",
    }
    assert not ht.should_alert(prev, 1949.0, settings())[0]
    assert ht.should_alert(prev, 1949.0, settings(renotify_after_hours=1.0))[0]


def test_hotel_key_is_stable_and_distinct():
    a = hotel("Hotel A", 40.7075, -74.0113, property_token="TOKEN123")
    b = hotel("Hotel A", 40.7075, -74.0113, property_token="TOKEN123")
    c = hotel("Hotel B", 40.7075, -74.0113, property_token="TOKEN999")
    assert ht.hotel_key(a) == ht.hotel_key(b)
    assert ht.hotel_key(a) != ht.hotel_key(c)


def test_hotel_key_falls_back_to_name_and_coordinates():
    record = hotel("No Token Hotel", 40.7075, -74.0113)
    assert ht.hotel_key(record).startswith("geo:")
    assert ht.hotel_key({"name": "Nothing"}).startswith("name:")


# ---------------------------------------------------------------------------
# Discord payload
# ---------------------------------------------------------------------------


def test_alert_states_the_fixed_dates_and_night_count():
    record = hotel("Test Hotel", 40.7075, -74.0113)
    best = ht.Offer("Booking.com", 1850.0, ht.ACTUAL, True, 462.50)
    payload = ht.build_discord_payload(record, best, [], None, ht.Settings())
    blob = str(payload)
    assert "September 4–8, 2026 · 4 nights" in blob


def test_actual_total_is_labelled_actual():
    record = hotel("Test Hotel", 40.7075, -74.0113)
    best = ht.Offer("Booking.com", 1850.0, ht.ACTUAL, True, 462.50)
    blob = str(ht.build_discord_payload(record, best, [], None, ht.Settings()))
    assert "ACTUAL TOTAL" in blob
    assert "ESTIMATED" not in blob


def test_estimated_total_is_labelled_estimated_and_carries_a_warning():
    record = hotel("Test Hotel", 40.7075, -74.0113)
    best = ht.Offer("Expedia", 1800.0, ht.ESTIMATED, True, 450.0)
    payload = ht.build_discord_payload(record, best, [], None, ht.Settings())
    blob = str(payload)
    assert "ESTIMATED TOTAL" in blob
    assert "estimated" in payload["embeds"][0]["description"].lower()
    assert "taxes and fees may differ" in payload["embeds"][0]["description"].lower()


def test_alert_always_contains_a_clickable_link():
    record = hotel("No Link Hotel", 40.7075, -74.0113)
    best = ht.Offer("Booking.com", 1850.0, ht.ACTUAL, True)
    payload = ht.build_discord_payload(record, best, [], None, ht.Settings())
    assert payload["embeds"][0]["url"].startswith("http")


def test_alert_shows_the_area_and_the_address_when_known():
    record = hotel("FiDi Hotel", 40.7075, -74.0113)
    best = ht.Offer("Booking.com", 1850.0, ht.ACTUAL, True)
    blob = str(ht.build_discord_payload(record, best, [], "123 Example St, New York, NY", ht.Settings()))
    assert "Manhattan" in blob
    assert "123 Example St" in blob


def test_nightly_figure_is_derived_from_the_total_when_absent():
    offer = ht.Offer("Booking.com", 1800.0, ht.ACTUAL, True, nightly=None)
    assert offer.nightly_display == pytest.approx(450.0)


def test_sample_payload_builds():
    assert ht.sample_payload(ht.Settings())["embeds"][0]["title"].startswith("Example Hotel")


# ---------------------------------------------------------------------------
# state file
# ---------------------------------------------------------------------------


def test_missing_state_file_starts_clean(tmp_path):
    assert ht.load_state(str(tmp_path / "nope.json")) == {"version": 1, "hotels": {}}


def test_corrupt_state_file_starts_clean(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{ this is not json", encoding="utf-8")
    assert ht.load_state(str(path)) == {"version": 1, "hotels": {}}


def test_state_round_trips(tmp_path):
    path = str(tmp_path / "state.json")
    ht.save_state({"version": 1, "hotels": {"token:abc": {"last_alert_total": 1950.0}}}, path)
    assert ht.load_state(path)["hotels"]["token:abc"]["last_alert_total"] == 1950.0


# ---------------------------------------------------------------------------
# end-to-end filtering
# ---------------------------------------------------------------------------


def test_full_pipeline_only_alerts_on_cheap_manhattan_hotels():
    results = [
        hotel("FiDi Bargain", 40.7075, -74.0113, total_rate=rate(1850.0)),          # alert
        hotel("LIC Bargain", 40.7440, -73.9490, total_rate=rate(900.0)),            # wrong borough
        hotel("Midtown Pricey", 40.7580, -73.9855, total_rate=rate(2400.0)),        # too expensive
        hotel("Harlem Bargain", 40.8116, -73.9465, total_rate=rate(700.0)),         # north of park
        hotel("Nowhere Hotel", total_rate=rate(500.0)),                             # no coordinates
        hotel("UES Estimate", 40.7736, -73.9566, rate_per_night=rate(475.0)),       # alert ($1,900)
    ]

    alerted = []
    for record in results:
        if not ht.is_valid_manhattan_hotel(record)[0]:
            continue
        best, _ = ht.pick_best_offer(ht.extract_offers(record), 2000.0)
        if best:
            alerted.append((record["name"], best.total, best.kind))

    assert alerted == [
        ("FiDi Bargain", 1850.0, ht.ACTUAL),
        ("UES Estimate", 1900.0, ht.ESTIMATED),
    ]
