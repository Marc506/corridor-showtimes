def test_filmlinc_filters_passes(parse_fixture):
    rows = parse_fixture("filmlinc", "showtimes.json")
    titles = {r.title for r in rows}
    assert "Fatherland" in titles
    assert not any("Pass" in t or "Voucher" in t for t in titles)


def test_filmlinc_fields(parse_fixture):
    rows = parse_fixture("filmlinc", "showtimes.json")
    r = next(r for r in rows if r.title == "Possible Love" and r.start == "2026-10-23T13:00:00-04:00")
    assert r.day == "2026-10-23"
    assert r.screen == "Francesca Beale Theater"
    assert r.detail_url == "https://www.filmlinc.org/films/possible-love/"
    assert r.ticket_url.startswith("https://purchase.filmlinc.org/")


def test_filmlinc_partner_venues_and_series(parse_fixture):
    rows = parse_fixture("filmlinc", "showtimes.json")
    assert "BAM" in {r.screen for r in rows}              # partner venues keep venue_id=filmlinc
    assert all(r.venue_id == "filmlinc" for r in rows)
    nyff = next(r for r in rows if r.title == "Fatherland" and r.day == "2026-10-04")
    assert nyff.series == "New York Film Festival"
    assert next(r for r in rows if r.title == "Parsifal").series == "Met Opera Live in HD"


def test_non_screening_regex_does_not_eat_real_titles():
    from scraper.sources.filmlinc import NON_SCREENING
    for t in ("2026 NYFF Express Pass", "2026 NYFF Volunteer Vouchers", "Membership Package"):
        assert NON_SCREENING.search(t)
    for t in ("The Passion of Joan of Arc", "A Passage to India", "Passing"):
        assert not NON_SCREENING.search(t)
