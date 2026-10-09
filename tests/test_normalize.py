import pytest

from scraper.normalize import smart_title


@pytest.mark.parametrize("raw,expected", [
    ("MY BROTHER'S WEDDING", "My Brother's Wedding"),
    ("EC: IVAN THE TERRIBLE: PARTS 1 & 2", "EC: Ivan the Terrible: Parts 1 & 2"),
    ("SGT. KABUKIMAN NYPD", "Sgt. Kabukiman NYPD"),
    ("CITIZEN TOXIE: THE TOXIC AVENGER IV", "Citizen Toxie: The Toxic Avenger IV"),
    ("VIKA KIRCHENBAUER PGM 1", "Vika Kirchenbauer PGM 1"),
    ("THE SECRET LIFE OF…ANTHOLOGY FILM ARCHIVES", "The Secret Life of…Anthology Film Archives"),
    ("CANNIBAL! THE MUSICAL", "Cannibal! The Musical"),
    ("BRYDIE O’CONNOR", "Brydie O’Connor"),
    ("I AM CUBA", "I Am Cuba"),
    ("CRY", "Cry"),
    ("Happy Together", "Happy Together"),        # mixed case untouched
])
def test_smart_title(raw, expected):
    assert smart_title(raw) == expected


def test_format_suffix_in_titles():
    from scraper.normalize import split_format_suffix
    assert split_format_suffix("Idlewild (35mm)") == ("Idlewild", "35mm")
    assert split_format_suffix("The Misconceived - 35MM") == ("The Misconceived", "35mm")
    assert split_format_suffix("Blade Runner (4K Restoration)") == ("Blade Runner", None)
    assert split_format_suffix("Up - Down") == ("Up - Down", None)


def test_la_is_an_article_before_a_word_and_los_angeles_otherwise():
    from scraper.normalize import smart_title
    assert smart_title("LA BOLA NEGRA") == "La Bola Negra"
    assert smart_title("VIVA LA VIDA") == "Viva la Vida"
    assert smart_title("TO LIVE AND DIE IN LA") == "To Live and Die in LA"
    assert smart_title("LA 92") == "LA 92"
