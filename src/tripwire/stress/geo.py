"""Map event places (GDELT locations, frame places) to US state codes for the geography channel."""

import re

STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO",
    "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
    "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC",
}
_NAME = re.compile(r"\b(" + "|".join(sorted(map(re.escape, STATES), key=len, reverse=True)) + r")\b")
_ADM1 = re.compile(r"^US([A-Z]{2})$")


def states_from(places: list[str], adm1_codes: list[str] | None = None) -> set[str]:
    """US state codes named in place strings ("Tampa, Florida, United States") or GDELT ADM1 codes ("USFL")."""
    found = {STATES[m.group(1)] for p in places for m in _NAME.finditer(p or "")}
    for code in adm1_codes or []:
        if m := _ADM1.match(code or ""):
            found.add(m.group(1))
    # "Washington" alone is usually the city (DC, US government), not the state.
    if "WA" in found and not any("Washington State" in p or "Washington, United States" in (p or "")
                                 for p in places):
        found.discard("WA")
    return found
