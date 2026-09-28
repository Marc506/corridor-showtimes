from scraper import language as L
from scraper.models import Screening, VenueConfig
from scraper.normalize import is_english_primary, language_from_text


def test_language_from_text():
    assert language_from_text("In French, Wolof, Manjak, and Portuguese Creole with English subtitles") == \
        "French, Wolof, Manjak, Portuguese Creole"
    assert language_from_text("Mexico/Spain, In Spanish with English subtitles, 2025, 102 min, DCP") == "Spanish"
    assert language_from_text("In English and Spanish with English subtitles") == "English, Spanish"
    assert language_from_text("1925, 106 min, 35mm, silent") == "Silent"
    assert language_from_text("1984, 91 min, DCP") is None          # no mention = unknown, not English
    assert is_english_primary("English, Spanish") is True
    assert is_english_primary("Japanese, English") is False
    assert is_english_primary(None) is None


def test_search_title_cleanup():
    assert L.search_title("EC: Strike") == "Strike"
    assert L.search_title("Jollof Films Presents: Faat Kiné") == "Faat Kiné"
    assert L.search_title("J. Hoberman presents Moi, un noir") == "Moi, un noir"
    assert L.search_title("Kwaidan (4K Restoration)") == "Kwaidan"
    assert L.search_title("I Love Boosters w/ Q&A") == "I Love Boosters"
    assert L.search_title("Blues + Breakfast (Table Top Dolly)") is None
    assert L.search_title("Women in Animation PGM 2: On Being a Woman") is None
    assert L.search_title("Talk: Lee Chang-dong") is None


class FakeTmdb(L.TmdbLanguage):
    """TmdbLanguage with canned API responses (no network, no cache file)."""

    def __init__(self, results, credits=None):
        self.results, self.credits, self.calls = results, credits or {}, []
        self.cache, self.disabled, self._last = {"languages": {"ja": "Japanese", "en": "English", "cn": "Cantonese"}, "films": {}}, False, 0

    def _get(self, path, **params):
        self.calls.append(path)
        if path == "/search/movie":
            return {"results": self.results}
        if path.startswith("/movie/"):
            return {"crew": [{"job": "Director", "name": n} for n in self.credits.get(int(path.split("/")[2]), [])]}
        raise AssertionError(path)

    def save(self):
        pass


def test_tmdb_matches_on_year():
    t = FakeTmdb([{"id": 1, "title": "Happy Together", "original_title": "春光乍洩", "release_date": "1997-05-30", "original_language": "cn"},
                  {"id": 2, "title": "Happy Together", "original_title": "Happy Together", "release_date": "1989-01-01", "original_language": "en"}])
    assert t.lookup("Happy Together", 1997, None) == "Cantonese"
    assert t.lookup("Happy Together", 1997, None) == "Cantonese" and t.calls.count("/search/movie") == 1   # cached


def test_tmdb_uses_director_to_break_ties():
    films = [{"id": 1, "title": "Troy", "release_date": "2004-05-13", "original_language": "en"},
             {"id": 2, "title": "Troy", "release_date": "2005-01-01", "original_language": "ja"}]
    t = FakeTmdb(films, credits={1: ["Wolfgang Petersen"], 2: ["Someone Else"]})
    assert t.lookup("Troy", 2004, "Wolfgang Petersen") == "English"


def test_tmdb_without_year_needs_an_unambiguous_exact_match():
    one = FakeTmdb([{"id": 5, "title": "Possible Love", "release_date": "2026-09-01", "original_language": "ja"}])
    assert one.lookup("Possible Love", None, None) == "Japanese"
    fuzzy = FakeTmdb([{"id": 6, "title": "Possible Lovers", "release_date": "2026-09-01", "original_language": "en"}])
    assert fuzzy.lookup("Possible Love", None, None) is None
    old_twins = FakeTmdb([{"id": 7, "title": "Rose", "release_date": "1990-01-01", "original_language": "en"},
                          {"id": 8, "title": "Rose", "release_date": "2001-01-01", "original_language": "fr"}])
    assert old_twins.lookup("Rose", None, None) is None


def _s(title, lang=None, year=None):
    return Screening(id=title, venue_id="v", title=title, start="2026-09-28T19:00:00-04:00", day="2026-09-28",
                     language=lang, year=year)


def test_fill_languages_precedence():
    rows = [_s("From Site", "Korean"), _s("Happy Together", year=1997), _s("Unknown Thing")]
    tmdb = FakeTmdb([{"id": 1, "title": "Happy Together", "release_date": "1997-05-30", "original_language": "cn"}])
    L.fill_languages(rows, VenueConfig(id="v", name="V", scraper="x", default_language="Japanese"), tmdb)
    assert [r.language for r in rows] == ["Korean", "Cantonese", "Japanese"]
    rows = [_s("Unknown Thing")]
    L.fill_languages(rows, VenueConfig(id="v", name="V", scraper="x"), None)
    assert rows[0].language is None


def test_sources_extract_language(parse_fixture):
    from tests.conftest import FIXTURES
    from scraper.sources.bam import parse_detail
    url = "https://www.anthologyfilmarchives.org/film_screenings/calendar?view=list&month=10&year=2026"
    afa = parse_fixture("anthology", ("2026-10.html", url))
    assert next(r for r in afa if r.title == "Alanis").language == "Spanish"
    assert next(r for r in afa if r.title == "EC: Strike").language == "Silent"
    pfs = parse_fixture("filmadelphia", "feed.json")
    assert next(r for r in pfs if r.title == "A Separation").language == "Farsi"
    assert "language" not in parse_detail((FIXTURES / "bam" / "detail_tony.html").read_text())


def test_opera_broadcasts_are_subtitled_not_tmdb():
    rows = [_s("Macbeth"), _s("Cosi Fan Tutte"), _s("Seventies Structures")]
    rows[0].series, rows[1].note = "Met Opera Live in HD", "Live Broadcast, Opera"
    rows[2].series = "Celebrating the Film-Makers' Cooperative"          # 'Cooperative' is not opera
    tmdb = FakeTmdb([{"id": 1, "title": "Macbeth", "release_date": "2026-01-01", "original_language": "en"}])
    L.fill_languages(rows, VenueConfig(id="v", name="V", scraper="x"), tmdb)
    assert [r.language for r in rows] == ["Opera (subtitled)", "Opera (subtitled)", None]


def test_possessive_director_prefix():
    assert L.search_title("Ken Russell’s The Devils") == "The Devils"
    assert L.search_title("Schindler's List") == "Schindler's List"
    assert L.search_title("Bram Stoker's Dracula") == "Bram Stoker's Dracula"


def test_hints_borrow_year_from_other_venue():
    hints = L.title_hints([("Fatherland", 2026, "Paweł Pawlikowski"), ("Ken Russell’s The Devils", 1971, "Ken Russell")])
    films = [{"id": 1, "title": "Fatherland", "release_date": "2026-05-01", "original_language": "pl"},
             {"id": 2, "title": "Fatherland", "release_date": "1994-01-01", "original_language": "en"},
             {"id": 3, "title": "Fatherland", "release_date": "2025-01-01", "original_language": "tl"}]
    rows = [_s("Fatherland")]
    tmdb = FakeTmdb(films)
    tmdb.cache["languages"]["pl"] = "Polish"
    L.fill_languages(rows, VenueConfig(id="v", name="V", scraper="x"), tmdb, hints)
    assert rows[0].language == "Polish"
    assert hints[L.title_norm("The Devils")][0] == 1971


def test_no_year_picks_clearly_famous_film():
    t = FakeTmdb([{"id": 1, "title": "The Innocent", "original_title": "L'innocente", "release_date": "1976-01-01", "original_language": "it", "popularity": 12.0},
                  {"id": 2, "title": "Who Was Guilty", "original_title": "L'innocente", "release_date": "1913-01-01", "original_language": "it", "popularity": 0.6}])
    t.cache["languages"]["it"] = "Italian"
    assert t.lookup("L'Innocente", None, None) == "Italian"


def test_no_year_prefers_this_years_premiere_and_language_consensus():
    from scraper.normalize import today_local
    y = today_local().year
    t = FakeTmdb([{"id": 1, "title": "Minotaur", "release_date": f"{y}-05-01", "original_language": "ja", "popularity": 5.9},
                  {"id": 2, "title": "Minotaur", "release_date": f"{y - 2}-01-01", "original_language": "en", "popularity": 1.0},
                  {"id": 3, "title": "Minotaur", "release_date": "2006-01-01", "original_language": "en", "popularity": 2.6}])
    assert t.lookup("Minotaur", None, None) == "Japanese"
    same = FakeTmdb([{"id": 1, "title": "X", "release_date": "1976-01-01", "original_language": "cn", "popularity": 3.3},
                     {"id": 2, "title": "X", "release_date": "1913-01-01", "original_language": "cn", "popularity": 1.8}])
    assert same.lookup("X", None, None) == "Cantonese"
