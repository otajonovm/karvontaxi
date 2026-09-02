"""Karvon Taxi — faqat G'uzor ↔ Toshkent yo'nalishi."""

from __future__ import annotations

GUZOR = "G'uzor"
TASHKENT = "Toshkent"

CARGO_TYPES: list[tuple[str, str]] = [
    ("hujjat", "Hujjat / paket"),
    ("posilka", "Posilka"),
    ("oziq", "Oziq-ovqat"),
    ("mebel", "Mebel / jihoz"),
    ("boshqa", "Boshqa yuk"),
]


def route_for(code: str) -> tuple[str, str]:
    if code in {"g2t", "v2t"}:
        return GUZOR, TASHKENT
    return TASHKENT, GUZOR


def _norm(text: str) -> str:
    return (
        text.lower()
        .replace("‘", "'")
        .replace("`", "'")
        .replace("g'uzor", "guzor")
        .replace(" ", "")
    )


def is_corridor(from_location: str, to_location: str) -> bool:
    blob = _norm(from_location) + " " + _norm(to_location)
    return "guzor" in blob and "toshkent" in blob
