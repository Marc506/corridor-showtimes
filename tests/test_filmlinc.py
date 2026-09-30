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


def test_borough_editions_lose_the_place_from_the_title():
    import json
    from scraper.models import RawPage
    from scraper.sources.filmlinc import split_place
    from tests.conftest import scraper_for
    feed = {"films": [
        {"id": "1", "title": "Bucking Fastard", "slug": "bucking-fastard", "showtimes": [
            {"dateTimeET": "2026-10-03T18:00:00-04:00", "venue": "Alice Tully Hall", "presaleSchedule": {"presaleType": "nyff"}}]},
        {"id": "2", "title": "Bucking Fastard Bronx", "slug": "bucking-fastard-bronx", "showtimes": [
            {"dateTimeET": "2026-10-04T19:00:00-04:00", "venue": "AMC Bay Plaza Cinema"}]}]}
    rows = scraper_for("filmlinc").parse([RawPage(url="x", body=json.dumps(feed), fetched_at="2026-09-25T01:00:00Z", ext="json")])
    bronx = next(r for r in rows if r.screen == "AMC Bay Plaza Cinema")
    assert (bronx.title, bronx.note, bronx.series) == ("Bucking Fastard", "Bronx", "New York Film Festival")
    assert bronx.detail_url.endswith("/bucking-fastard-bronx/")          # still links to its own page
    assert split_place("Queens of the Stone Age", set()) == ("Queens of the Stone Age", None)
    assert split_place("A Bronx Tale", set()) == ("A Bronx Tale", None)
    assert split_place("Paterson Staten Island", set()) == ("Paterson", "Staten Island")
