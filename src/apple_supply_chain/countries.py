"""Country reference data and name resolution (supplier list, Comtrade, XBRL members)."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import cache
from importlib import resources


@dataclass(frozen=True)
class Country:
    iso3: str
    name: str
    comtrade_code: str
    region: str


def _norm(text: str) -> str:
    text = text.replace("\u2019", "'").lower()
    text = re.sub(r"[\s,;]+", " ", text)
    return text.strip(" .")


@cache
def countries() -> tuple[Country, ...]:
    ref = resources.files("apple_supply_chain.reference").joinpath("countries.csv")
    with ref.open(encoding="utf-8") as fh:
        return tuple(
            Country(r["iso3"], r["name"], r["comtrade_code"], r["region"])
            for r in csv.DictReader(fh)
        )


@cache
def _aliases() -> dict[str, Country]:
    ref = resources.files("apple_supply_chain.reference").joinpath("countries.csv")
    by_iso = {c.iso3: c for c in countries()}
    out: dict[str, Country] = {}
    with ref.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            c = by_iso[r["iso3"]]
            for name in [r["name"], r["iso3"], *filter(None, r["aliases"].split("|"))]:
                out[_norm(name)] = c
    return out


def resolve(name: str) -> Country | None:
    return _aliases().get(_norm(name))


def by_comtrade_code(code: str | int) -> Country | None:
    code = str(code)
    return next((c for c in countries() if c.comtrade_code == code), None)


@cache
def _max_alias_words() -> int:
    return max(len(a.split()) for a in _aliases())


def split_trailing_country(text: str) -> tuple[str, Country | None]:
    """Split ``"Guangdong, Jiangsu China mainland"`` into (``"Guangdong, Jiangsu"``, CHN).

    Uses the longest run of trailing words that is a known country name or alias.
    """
    words = text.split()
    for n in range(min(_max_alias_words(), len(words)), 0, -1):
        candidate = " ".join(words[-n:])
        country = resolve(candidate)
        if country is not None:
            return " ".join(words[:-n]).rstrip(" ,;"), country
    return text, None
