from __future__ import annotations

import json
import math
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from functools import lru_cache
from html import unescape
from html.parser import HTMLParser


CALENDAR_URL = "https://athletics.ca/events/"
WORLD_CALENDAR_URL = "https://worldathletics.org/competition/calendar-results"
USER_AGENT = "Stride athlete events/1.0"
SPORT_TERMS = {
    "track & field": ("track & field", "track and field", "track", "field", "cross country"),
    "track and field": ("track & field", "track and field", "track", "field", "cross country"),
    "athletics": ("track & field", "track and field", "track", "field", "cross country"),
    "running": ("running", "marathon", "cross country", "road race", "trail", "track & field"),
    "cross country": ("cross country", "track", "athletics"),
}


class _EventCardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[dict[str, str]] = []
        self.current: dict[str, object] | None = None
        self.capture: str | None = None
        self.anchor: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = attributes.get("class", "").split()
        if tag == "article" and "item" in classes:
            self.current = {"title_parts": [], "subtitle_parts": [], "text_parts": [], "links": []}
            return
        if self.current is None:
            return
        if tag == "span" and "toggle-header" in classes:
            self.capture = "title_parts"
        elif tag == "span" and "sub-title" in classes:
            self.capture = "subtitle_parts"
        if tag == "a":
            self.anchor = {"href": attributes.get("href", ""), "text": ""}

    def handle_data(self, data: str) -> None:
        if self.current is None:
            return
        text = unescape(data).strip()
        if not text:
            return
        self.current["text_parts"].append(text)
        if self.capture:
            self.current[self.capture].append(text)
        if self.anchor:
            self.anchor["text"] += f" {text}"

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return
        if tag == "a" and self.anchor:
            self.current["links"].append(self.anchor)
            self.anchor = None
        elif tag == "span":
            self.capture = None
        elif tag == "article":
            self._finish_card()

    def _finish_card(self) -> None:
        assert self.current is not None
        title = " ".join(self.current["title_parts"])
        subtitle = " ".join(self.current["subtitle_parts"])
        links = self.current["links"]
        event_url = ""
        registration_url = ""
        for link in links:
            label = " ".join(link["text"].split()).lower()
            if "register" in label:
                registration_url = link["href"]
            elif "view event" in label:
                event_url = link["href"]
        if title and subtitle and (event_url or registration_url):
            self.events.append(
                {
                    "title": title,
                    "date_location": subtitle,
                    "location": subtitle.rsplit(" - ", 1)[-1].strip(),
                    "event_url": event_url,
                    "registration_url": registration_url,
                    "details": " ".join(self.current["text_parts"]),
                }
            )
        self.current = None
        self.capture = None
        self.anchor = None


def parse_event_cards(document: str) -> list[dict[str, str]]:
    parser = _EventCardParser()
    parser.feed(document)
    return parser.events


def parse_world_calendar(document: str) -> tuple[list[dict[str, str]], list[dict[str, object]], int]:
    marker = '<script id="__NEXT_DATA__" type="application/json">'
    start = document.find(marker)
    if start < 0:
        raise ValueError("The World Athletics calendar data was not found.")
    payload_text = document[start + len(marker) :].split("</script>", maxsplit=1)[0]
    page = json.loads(payload_text)["props"]["pageProps"]
    calendar = page["initialEvents"]
    countries = calendar["options"]["regions"]["country"]
    events = calendar.get("results", [])
    return countries, events, int(calendar.get("hits", len(events)))


def _sport_terms(sport: str) -> tuple[str, ...]:
    normalized = sport.strip().lower()
    return SPORT_TERMS.get(normalized, ())


def event_matches_sport(event: dict[str, str], sport: str) -> bool:
    terms = _sport_terms(sport)
    if not terms:
        return False
    text = f"{event['title']} {event['details']}".lower()
    if "coach training" in text or "official training" in text:
        return False
    return any(term in text for term in terms)


def event_start_date(date_location: str) -> date | None:
    date_text = date_location.rsplit(" - ", 1)[0].strip()
    patterns = (
        r"^(\d{1,2})\s+([A-Za-z]+)\s*-\s*\d{1,2}\s+[A-Za-z]+,\s*(\d{4})$",
        r"^(\d{1,2})(?:\s*-\s*\d{1,2})?\s+([A-Za-z]+),?\s*(\d{4})$",
    )
    for pattern in patterns:
        match = re.match(pattern, date_text)
        if match:
            day, month, year = match.groups()
            try:
                return datetime.strptime(f"{day} {month} {year}", "%d %B %Y").date()
            except ValueError:
                return None
    return None


@lru_cache(maxsize=128)
def geocode_place(place_name: str) -> dict[str, str | float] | None:
    query = urllib.parse.urlencode({"name": place_name, "count": 1, "language": "en", "format": "json"})
    request = urllib.request.Request(
        f"https://geocoding-api.open-meteo.com/v1/search?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        results = payload.get("results", [])
        if not results:
            return None
        place = results[0]
        return {
            "name": str(place.get("name", place_name)),
            "admin1": str(place.get("admin1", "")),
            "country": str(place.get("country", "")),
            "latitude": float(place["latitude"]),
            "longitude": float(place["longitude"]),
        }
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        return None


def _distance_km(first: dict[str, str | float], second: dict[str, str | float]) -> float:
    latitude_1 = math.radians(float(first["latitude"]))
    latitude_2 = math.radians(float(second["latitude"]))
    latitude_delta = latitude_2 - latitude_1
    longitude_delta = math.radians(float(second["longitude"]) - float(first["longitude"]))
    haversine = math.sin(latitude_delta / 2) ** 2 + math.cos(latitude_1) * math.cos(latitude_2) * math.sin(longitude_delta / 2) ** 2
    return 6371 * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


@lru_cache(maxsize=1)
def world_athletics_countries() -> dict[str, int]:
    request = urllib.request.Request(WORLD_CALENDAR_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        document = response.read().decode("utf-8", "replace")
    countries, _, _ = parse_world_calendar(document)
    country_ids = {
        _country_key(str(country["name"])): int(country["id"])
        for country in countries
        if country.get("id") is not None
    }
    for alias, canonical in {
        "united states of america": "united states",
        "usa": "united states",
        "uk": "united kingdom",
        "turkiye": "turkey",
        "czechia": "czech republic",
        "ivory coast": "cote divoire",
    }.items():
        if _country_key(canonical) in country_ids:
            country_ids[_country_key(alias)] = country_ids[_country_key(canonical)]
    return country_ids


def _country_key(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).casefold()
    return "".join(character for character in normalized if character.isalnum())


def event_city_query(venue: str) -> str:
    cleaned = re.sub(r"\s*\([A-Z]{3}\)\s*$", "", venue).strip()
    if not cleaned or cleaned.casefold().startswith("various"):
        return ""
    parts = [part.strip() for part in cleaned.split(",") if part.strip()]
    candidates = []
    if parts:
        if parts[-1].upper() not in {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}:
            candidates.append(parts[-1])
        if len(parts) > 1:
            candidates.append(", ".join(parts[-2:]))
    candidates.append(cleaned)
    for candidate in dict.fromkeys(candidates):
        if geocode_place(candidate):
            return candidate
    return ""


def _event_place_and_coordinates(record: dict[str, object]) -> tuple[str, dict[str, str | float] | None]:
    event_place = event_city_query(str(record.get("venue") or ""))
    return event_place, geocode_place(event_place) if event_place else None


@lru_cache(maxsize=40)
def world_calendar_events(country_id: int, start_date: str, end_date: str) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    total_hits = 0
    for offset in range(0, 500, 100):
        query = urllib.parse.urlencode(
            {
                "regionType": "country",
                "regionId": country_id,
                "startDate": start_date,
                "endDate": end_date,
                "offset": offset,
            }
        )
        request = urllib.request.Request(f"{WORLD_CALENDAR_URL}?{query}", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=20) as response:
            document = response.read().decode("utf-8", "replace")
        _, page_records, total_hits = parse_world_calendar(document)
        records.extend(page_records)
        if not page_records or len(records) >= total_hits:
            break
    return tuple(records[:500])


def find_world_athletics_events(
    sport: str,
    city: str,
    radius_km: int,
    athlete_location: dict[str, str | float],
) -> dict[str, object]:
    try:
        country_ids = world_athletics_countries()
        country_id = country_ids.get(_country_key(str(athlete_location["country"])))
        if country_id is None:
            return {
                "events": [],
                "error": f"World Athletics does not list a country calendar for {athlete_location['country']}; no unverified events are shown.",
            }
        start = date.today()
        end = date(start.year + 1, start.month, min(start.day, 28))
        records = world_calendar_events(country_id, start.isoformat(), end.isoformat())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as error:
        return {"events": [], "error": f"World Athletics' official calendar is unavailable right now ({type(error).__name__})."}

    candidates = []
    for record in records:
        disciplines = str(record.get("disciplines") or "")
        event = {
            "title": str(record.get("name") or ""),
            "date_location": f"{record.get('dateRange') or record.get('startDate') or 'Date to be confirmed'} - {record.get('venue') or 'Venue to be confirmed'}",
            "location": str(record.get("venue") or ""),
            "details": f"{disciplines} {record.get('competitionGroup') or ''}",
        }
        if not event["title"] or not event_matches_sport(event, sport):
            continue
        if str(record.get("undeterminedCompetitionPeriod") or "").strip():
            continue
        candidates.append((record, event))
    with ThreadPoolExecutor(max_workers=12) as executor:
        locations = list(executor.map(_event_place_and_coordinates, (record for record, _ in candidates)))
    matches = []
    for (record, event), (event_place, event_location) in zip(candidates, locations):
        if not event_location:
            continue
        distance = _distance_km(athlete_location, event_location)
        if distance > radius_km:
            continue
        was_url = str(record.get("wasUrl") or "")
        event_url = urllib.parse.urljoin(WORLD_CALENDAR_URL, was_url) if was_url else (
            f"{WORLD_CALENDAR_URL}?"
            + urllib.parse.urlencode(
                {
                    "regionType": "country",
                    "regionId": country_id,
                    "query": event["title"],
                    "startDate": start.isoformat(),
                    "endDate": end.isoformat(),
                }
            )
        )
        matches.append(
            {
                **event,
                "date_location": f"{record.get('dateRange') or record.get('startDate')} - {event_place}",
                "event_url": event_url,
                "registration_url": "",
                "distance_km": round(distance),
                "source": "World Athletics official calendar",
            }
        )
    matches.sort(key=lambda event: (event["distance_km"], event["date_location"]))
    query = urllib.parse.urlencode(
        {
            "regionType": "country",
            "regionId": country_id,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
        }
    )
    return {
        "events": matches,
        "location": f"{athlete_location['name']}, {athlete_location['admin1'] or athlete_location['country']}",
        "source_url": f"{WORLD_CALENDAR_URL}?{query}",
        "source": "World Athletics official calendar",
        "error": "",
    }


def find_nearby_events(sport: str, city: str, radius_km: int = 250) -> dict[str, object]:
    athlete_location = geocode_place(city)
    if not athlete_location:
        return {"events": [], "error": f"Couldn't locate {city}. Check the city name and try again."}
    terms = _sport_terms(sport)
    if not terms:
        return {
            "events": [],
            "error": f"The live official event feed currently supports track & field, athletics, running, and cross country, not {sport or 'this sport'} yet.",
        }
    if athlete_location["country"] != "Canada":
        return find_world_athletics_events(sport, city, radius_km, athlete_location)
    province = str(athlete_location["admin1"])
    if not province:
        return {"events": [], "error": "The location service could not identify a province for this city."}
    query = urllib.parse.urlencode({"_year": "upcoming", "_province": province})
    request = urllib.request.Request(f"{CALENDAR_URL}?{query}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            document = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {"events": [], "error": f"Athletics Canada's official calendar is unreachable right now ({type(error).__name__})."}
    matches = []
    for event in parse_event_cards(document):
        if not event_matches_sport(event, sport):
            continue
        start_date = event_start_date(event["date_location"])
        if start_date and start_date < date.today():
            continue
        event_place = event_city_query(event["location"])
        event_location = geocode_place(event_place) if event_place else None
        if not event_location:
            continue
        distance = _distance_km(athlete_location, event_location)
        if distance <= radius_km:
            matches.append({**event, "location": event_place, "distance_km": round(distance), "source": "Athletics Canada official calendar"})
    matches.sort(key=lambda event: (event["distance_km"], event["date_location"]))
    return {
        "events": matches,
        "province": province,
        "location": f"{athlete_location['name']}, {athlete_location['admin1']}",
        "source_url": f"{CALENDAR_URL}?{query}",
        "source": "Athletics Canada official calendar",
        "error": "",
    }
