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
