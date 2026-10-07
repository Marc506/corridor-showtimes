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
    assert L.search_title("Digger in VistaVision") == "Digger"
    assert L.search_title("The Odyssey in IMAX 70mm") == "The Odyssey"


class FakeTmdb(L.TmdbLanguage):
    """TmdbLanguage with canned API responses (no network, no cache file)."""

    def __init__(self, results, credits=None, runtimes=None):
        self.results, self.credits, self.runtimes, self.calls = results, credits or {}, runtimes or {}, []
        self.cache, self.disabled, self._last = {"languages": {"ja": "Japanese", "en": "English", "cn": "Cantonese"}, "films": {}}, False, 0

    def _get(self, path, **params):
        self.calls.append(path)
        if path == "/search/movie":
            return {"results": self.results}
        if path.startswith("/movie/"):
            movie_id = int(path.split("/")[2])
            crew = {"crew": [{"job": "Director", "name": n} for n in self.credits.get(movie_id, [])]}
            if path.endswith("/credits"):
                return crew
            return {"runtime": self.runtimes.get(movie_id, 0), "credits": crew}    # ?append_to_response=credits
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
    tmdb = FakeTmdb(films, credits={1: ["Paweł Pawlikowski"]})
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


# ---- directors from TMDB

def _films_happy():
    return [{"id": 1, "title": "Happy Together", "original_title": "春光乍洩", "release_date": "1997-05-30", "original_language": "cn"},
            {"id": 2, "title": "Happy Together", "release_date": "1989-01-01", "original_language": "en"}]


def test_director_and_year_filled_from_a_sure_match():
    tmdb = FakeTmdb(_films_happy(), credits={1: ["Wong Kar-wai"]})
    hints = L.title_hints([("Happy Together", 1997, None)])
    rows = [_s("Happy Together")]                                   # FLC-style: no year, no director
    L.fill_languages(rows, VenueConfig(id="v", name="V", scraper="x"), tmdb, hints)
    assert (rows[0].language, rows[0].director, rows[0].year) == ("Cantonese", "Wong Kar-wai", 1997)


def test_language_consensus_is_not_enough_for_a_director():
    films = [{"id": 1, "title": "X", "release_date": "1976-01-01", "original_language": "cn", "popularity": 3.3},
             {"id": 2, "title": "X", "release_date": "1913-01-01", "original_language": "cn", "popularity": 1.8}]
    tmdb = FakeTmdb(films, credits={1: ["Someone"], 2: ["Someone Else"]})
    rows = [_s("X")]
    L.fill_languages(rows, VenueConfig(id="v", name="V", scraper="x"), tmdb)
    assert rows[0].language == "Cantonese"
    assert rows[0].director is None and rows[0].year is None        # which "X"? unknown -> leave blank
    assert not any(c.startswith("/movie/") for c in tmdb.calls)     # no credits call for an unsure match


def test_site_director_is_never_overwritten_and_site_language_still_gets_a_director():
    tmdb = FakeTmdb(_films_happy(), credits={1: ["Wong Kar-wai"]})
    keep = _s("Happy Together", lang="Cantonese", year=1997)
    keep.director = "W. K. Wong (as listed)"
    fill = _s("Happy Together", lang="Cantonese", year=1997)        # language from the site, no director
    L.fill_languages([keep, fill], VenueConfig(id="v", name="V", scraper="x"), tmdb)
    assert keep.director == "W. K. Wong (as listed)"
    assert fill.director == "Wong Kar-wai" and fill.language == "Cantonese"


def test_opera_broadcasts_get_no_tmdb_director():
    tmdb = FakeTmdb([{"id": 9, "title": "Macbeth", "release_date": "2026-01-01", "original_language": "en"}],
                    credits={9: ["Film Director"]})
    row = _s("Macbeth")
    row.series = "Met Opera Live in HD"
    L.fill_languages([row], VenueConfig(id="v", name="V", scraper="x"), tmdb)
    assert (row.language, row.director) == ("Opera (subtitled)", None) and tmdb.calls == []


def test_cache_entries_from_before_directors_are_refreshed_once():
    tmdb = FakeTmdb(_films_happy(), credits={1: ["Wong Kar-wai"]})
    tmdb.cache["films"]["happy together|1997|"] = {"lang": "Cantonese", "id": 1, "at": "2026-09-27T00:00:00+00:00"}
    info = tmdb.details("Happy Together", 1997, None)
    assert (info["sure"], info["directors"], info["year"]) == (True, ["Wong Kar-wai"], 1997)
    calls = len(tmdb.calls)
    tmdb.details("Happy Together", 1997, None)
    assert len(tmdb.calls) == calls                                  # cached now


def test_future_tmdb_release_year_is_not_used():
    from scraper.normalize import today_local
    nxt = today_local().year + 1
    tmdb = FakeTmdb([{"id": 3, "title": "Premiere", "release_date": f"{nxt}-02-01", "original_language": "de"}],
                    credits={3: ["Isabelle Stever"]})
    tmdb.cache["languages"]["de"] = "German"
    row = _s("Premiere")
    L.fill_languages([row], VenueConfig(id="v", name="V", scraper="x"), tmdb)
    assert (row.director, row.year) == ("Isabelle Stever", None)


def test_runtime_and_end_filled_from_a_sure_match():
    tmdb = FakeTmdb([{"id": 7, "title": "All of a Sudden", "release_date": "2026-06-19", "original_language": "ja"}],
                    credits={7: ["Ryusuke Hamaguchi"]}, runtimes={7: 196})
    row = _s("All of a Sudden")                                      # FLC: no runtime, no end
    L.fill_languages([row], VenueConfig(id="v", name="V", scraper="x"), tmdb)
    assert (row.director, row.runtime_min) == ("Ryusuke Hamaguchi", 196)
    assert row.end == "2026-09-28T22:16:00-04:00"                    # 19:00 + 196 min
    assert sum(c.startswith("/movie/") for c in tmdb.calls) == 1     # directors + runtime in one request


def test_site_runtime_kept_and_unknown_tmdb_runtime_ignored():
    tmdb = FakeTmdb([{"id": 8, "title": "Short Run", "release_date": "2026-01-01", "original_language": "fr"}],
                    credits={8: ["A"]}, runtimes={8: 0})             # TMDB 0 = unknown
    tmdb.cache["languages"]["fr"] = "French"
    unknown = _s("Short Run")
    L.fill_languages([unknown], VenueConfig(id="v", name="V", scraper="x"), tmdb)
    assert unknown.runtime_min is None and unknown.end is None
    listed = _s("Short Run")
    listed.runtime_min, listed.end = 90, "2026-09-28T20:30:00-04:00"
    L.fill_languages([listed], VenueConfig(id="v", name="V", scraper="x"), FakeTmdb(tmdb.results, {8: ["A"]}, {8: 120}))
    assert (listed.runtime_min, listed.end) == (90, "2026-09-28T20:30:00-04:00")


def test_a_listed_director_must_match_even_a_single_candidate():
    """Film Forum: 'You Had to Be There' by Nick Davis (2026) is not TMDB's only exact title, a 2012 short."""
    films = [{"id": 11, "title": "You Had to Be There", "release_date": "2012-10-22", "original_language": "en"},
             {"id": 12, "title": "You Had to Be There: How the Toronto Godspell Ignited the Comedy Revolution...",
              "release_date": "2026-09-18", "original_language": "en"}]
    tmdb = FakeTmdb(films, credits={11: ["John Albarian"], 12: ["Nick Davis"]}, runtimes={11: 20, 12: 94})
    row = _s("You Had to Be There")
    row.director = "Nick Davis"
    L.fill_languages([row], VenueConfig(id="v", name="V", scraper="x"), tmdb)
    assert (row.year, row.runtime_min, row.language) == (2026, 94, "English")      # the long-titled film
    wrong = FakeTmdb(films[:1], credits={11: ["John Albarian"]}, runtimes={11: 20})
    row2 = _s("You Had to Be There")
    row2.director = "Nick Davis"
    L.fill_languages([row2], VenueConfig(id="v", name="V", scraper="x"), wrong)
    assert (row2.year, row2.runtime_min) == (None, None)                            # unknown beats wrong


def test_title_prefix_candidates_need_a_director():
    films = [{"id": 21, "title": "Alien: Resurrection", "release_date": "1997-11-12", "original_language": "en"}]
    tmdb = FakeTmdb(films, credits={21: ["Jean-Pierre Jeunet"]}, runtimes={21: 109})
    row = _s("Alien")                                                               # no director listed
    L.fill_languages([row], VenueConfig(id="v", name="V", scraper="x"), tmdb)
    assert (row.runtime_min, row.director) == (None, None)


def test_same_person_tolerates_spelling_and_order():
    assert L.same_person("Oleksandr Dovzhenko", "Alexander Dovzhenko")
    assert L.same_person("Stephen Lisberger", "Steven Lisberger")
    assert L.same_person("Tsai Ming-liang", "Ming-liang Tsai")
    assert L.same_person("Lars Von Trier", "Lars von Trier")
    assert not L.same_person("Nick Davis", "John Albarian")
    assert not L.same_person("Multiple Dirs", "Jean Renoir")


def test_search_title_strips_year_and_anniversary_suffixes():
    assert L.search_title("Medea (1988)") == "Medea"
    assert L.search_title("Ghost in the Shell: 30th Anniversary Remaster") == "Ghost in the Shell"
    assert L.search_title("Tron - 4K Remaster") == "Tron"
    assert L.search_title("1917") == "1917"


def test_this_years_premiere_beats_language_consensus():
    """FLC lists 'Paper Tiger' with no year or director; five TMDB films share the title, all in English,
    and only one (James Gray's) is from this year — that one is the film, not just 'some English film'."""
    from scraper.normalize import today_local
    y = today_local().year
    films = [{"id": 1, "title": "Paper Tiger", "release_date": f"{y}-11-12", "original_language": "en", "popularity": 6.3},
             {"id": 2, "title": "Paper Tiger", "release_date": "2020-10-22", "original_language": "en", "popularity": 1.6},
             {"id": 3, "title": "Paper Tiger", "release_date": "1975-11-05", "original_language": "en", "popularity": 1.6}]
    tmdb = FakeTmdb(films, credits={1: ["James Gray"]}, runtimes={1: 131})
    row = _s("Paper Tiger")
    L.fill_languages([row], VenueConfig(id="v", name="V", scraper="x"), tmdb)
    assert (row.language, row.director, row.runtime_min, row.year) == ("English", "James Gray", 131, y)


def test_prominent_one_of_several_same_title_films_this_year():
    """Two 2026 films called 'Artificial': Guadagnino's (popularity 4.0) and a small one (1.75)."""
    from scraper.normalize import today_local
    y = today_local().year
    films = [{"id": 1, "title": "Artificial", "release_date": f"{y}-12-25", "original_language": "en", "popularity": 4.02},
             {"id": 2, "title": "Artificial", "release_date": f"{y}-10-01", "original_language": "en", "popularity": 1.75},
             {"id": 3, "title": "Artificial", "release_date": "2020-02-01", "original_language": "es", "popularity": 1.88}]
    tmdb = FakeTmdb(films, credits={1: ["Luca Guadagnino"]}, runtimes={1: 128})
    tmdb.cache["languages"]["es"] = "Spanish"
    row = _s("Artificial")
    L.fill_languages([row], VenueConfig(id="v", name="V", scraper="x"), tmdb)
    assert (row.director, row.runtime_min) == ("Luca Guadagnino", 128)
    close = FakeTmdb([dict(films[0], popularity=2.0), films[1], films[2]], credits={1: ["Luca Guadagnino"]})
    close.cache["languages"]["es"] = "Spanish"
    row2 = _s("Artificial")
    L.fill_languages([row2], VenueConfig(id="v", name="V", scraper="x"), close)
    assert row2.director is None                                        # 2.0 vs 1.75: too close to call


def test_imdb_id_from_the_cinema_is_an_exact_match():
    """A cinema that publishes IMDb ids (Somerville's TAPOS feed) gets the film by /find, not by title search."""
    class FindTmdb(FakeTmdb):
        def _get(self, path, **params):
            if path == "/find/tt0080455":
                self.calls.append(path)
                return {"movie_results": [{"id": 525, "original_language": "en", "release_date": "1980-06-16"}]}
            if path == "/find/tt9999999":
                self.calls.append(path)
                return {"movie_results": []}
            return super()._get(path, **params)

    tmdb = FindTmdb([{"id": 1, "title": "The Blues Brothers", "release_date": "2026-01-01", "original_language": "fr"}],
                    credits={525: ["John Landis"]}, runtimes={525: 133})
    rows = [_s("The Blues Brothers"), _s("Unknown Short")]
    rows[0].imdb_id, rows[1].imdb_id = "tt0080455", "tt9999999"
    L.fill_languages(rows, VenueConfig(id="v", name="V", scraper="x"), tmdb)
    assert (rows[0].language, rows[0].director, rows[0].year, rows[0].runtime_min) == ("English", "John Landis", 1980, 133)
    assert "/search/movie" not in tmdb.calls                   # never fell back to a title search
    assert rows[1].language is None and rows[1].director is None


def test_day_and_date_streaming_release():
    def us(*pairs):
        return {"results": [{"iso_3166_1": "US", "release_dates": [{"type": t, "release_date": f"{d}T00:00:00.000Z"} for t, d in pairs]}]}
    assert L.day_and_date(us((2, "2026-10-09"), (4, "2026-10-09")))            # Animals: select theaters + Netflix
    assert not L.day_and_date(us((3, "2026-10-02"), (4, "2027-01-15")))       # a theatrical window first
    assert not L.day_and_date(us((3, "2026-10-02")))
    assert not L.day_and_date({"results": [{"iso_3166_1": "FR", "release_dates": [{"type": 4, "release_date": "2026-10-02"}]}]})

