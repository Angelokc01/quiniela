"""
Cliente para wc2026api.com.

Documentación: https://api.wc2026api.com/docs

Endpoints que usamos:
    GET /matches           -> lista de los 104 partidos

Headers:
    Authorization: Bearer <token>
"""
from datetime import datetime
import requests
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Match


def _headers():
    return {
        'Authorization': f'Bearer {settings.WC2026_API_TOKEN}',
        'Accept': 'application/json',
    }


def fetch_matches():
    """Devuelve la lista cruda de partidos desde la API."""
    url = f'{settings.WC2026_API_URL}/matches'
    resp = requests.get(url, headers=_headers(), timeout=20)
    resp.raise_for_status()
    data = resp.json()
    # La API a veces devuelve directamente una lista, otras un dict con 'data'
    if isinstance(data, dict):
        return data.get('data') or data.get('matches') or []
    return data


def _to_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return parse_datetime(value)


def sync_matches_to_db():
    """
    Trae todos los partidos de la API y los upsertea en la BD local.
    Devuelve cuántos se crearon y cuántos se actualizaron.
    """
    created = 0
    updated = 0
    for raw in fetch_matches():
        api_id = raw.get('id') or raw.get('match_id')
        if api_id is None:
            continue

        defaults = {
            'match_number': raw.get('match_number') or 0,
            'round': raw.get('round') or 'group',
            'group_name': raw.get('group_name') or '',
            'home_team': raw.get('home_team') or '',
            'away_team': raw.get('away_team') or '',
            'stadium': raw.get('stadium') or '',
            'kickoff_utc': _to_dt(raw.get('kickoff_utc')),
            'status': raw.get('status') or 'scheduled',
            'home_score': raw.get('home_score'),
            'away_score': raw.get('away_score'),
            'last_synced': timezone.now(),
        }

        obj, was_created = Match.objects.update_or_create(
            api_id=api_id, defaults=defaults
        )
        if was_created:
            created += 1
        else:
            updated += 1
    return created, updated
