"""
Cálculo de puntos.

Tabla de puntos (definida por el usuario):

FASE DE GRUPOS
  - 5 pts: resultado exacto de un partido (marcador exacto).
  - 2 pt:  acertar el ganador (incluye empate) en fase de grupos.
  - 2 pt:  acertar la posición exacta de un equipo dentro de su grupo (4 por grupo).

CLASIFICADOS POR RONDA
  - Octavos: 5 
  - Cuartos: 8 
  - Semis: 12 
  - Finalistas:15 

MARCADOR EXACTO EN ELIMINATORIA (el orden top-bottom importa pero no importa que equiposn llegaron a ese bracket):
    - R32 (dieciseisavos): 4
    - R16 (octavos):       5
    - QF  (cuartos):       6
    - SF  (semis):         7
    - 3rd place:           4
    - Final:               8

POSICIÓN FINAL
  - 30 campeón
  - 15 subcampeón
  - 5 tercer puesto
  - 2  cuarto puesto

PREMIOS INDIVIDUALES
  - Bota Oro:     10
  - Balón Oro:    10
  - Guante Oro:   10
  - Mejor Joven:  5
  - Mejor Gol:    5  (admin lo define)
"""
import difflib
import re
import unicodedata
from collections import defaultdict
from typing import Dict, List, Optional

from django.db.models import Sum

from .models import (
    BettingGroup, Participant, Match,
    GroupMatchPrediction, GroupStandingPrediction,
    BracketPrediction, KnockoutScorePrediction,
    AwardPrediction, AwardActual, AWARD_POINTS,
    ROUND_GROUP, ROUND_R32, ROUND_R16, ROUND_QF, ROUND_SF, ROUND_3RD, ROUND_FINAL,
    SLOT_CHAMPION, SLOT_RUNNER_UP, SLOT_THIRD, SLOT_FOURTH,
)
from .bracket import (
    actual_group_standings, bracket_from_standings, best_thirds,
    R32_PAIRINGS, round_matches, actual_bracket_and_matches,
)


# Tabla de puntos para clasificación a cada ronda
ROUND_CORRECT_SLOT_POINTS = {
    ROUND_R16: (5, 5),
    ROUND_QF:  (8, 8),
    ROUND_SF:  (12, 12),
    # finalistas = participar en la final (estar en FINAL_1 o FINAL_2)
    ROUND_FINAL: (15, 15),
}

# Puntos por posición final (campeón, subcampeón, etc.)
FINAL_POSITION_POINTS = {
    SLOT_CHAMPION:  30,
    SLOT_RUNNER_UP: 15,
    SLOT_THIRD:     5,
    SLOT_FOURTH:    2,
}

# Puntos por marcador exacto de un partido de eliminatoria (orden top-bottom)
KNOCKOUT_SCORE_POINTS = {
    ROUND_R32: 4,
    ROUND_R16: 5,
    ROUND_QF:  6,
    ROUND_SF:  7,
    ROUND_3RD: 4,
    ROUND_FINAL: 8,
}


def group_stage_complete() -> bool:
    """Devuelve True cuando todos los partidos de fase de grupos ya terminaron."""
    total_group_matches = Match.objects.filter(round=ROUND_GROUP).count()
    if total_group_matches == 0:
        return False
    finished_group_matches = Match.objects.filter(
        round=ROUND_GROUP,
        status=Match.STATUS_COMPLETED,
    ).count()
    return finished_group_matches == total_group_matches


# ============================================================
# Cálculo de bracket REAL (qué equipos están en cada slot,
# y quién ganó cada llave eliminatoria) basándonos en Match real
# ============================================================
def _actual_team_for_round_slot(round_name: str, slot_idx: int) -> Optional[Match]:
    """Busca el partido REAL para un slot de ronda eliminatoria.

    Asumimos que en la API, los matches de R16/QF/SF/Final tienen match_number
    o algún campo que permite ordenarlos. Como fallback ordenamos por kickoff_utc.
    """
    qs = Match.objects.filter(round=round_name).order_by('match_number', 'kickoff_utc')
    matches = list(qs)
    if 0 <= slot_idx - 1 < len(matches):
        return matches[slot_idx - 1]
    return None


def build_actual_bracket() -> Dict[str, str]:
    """
    Devuelve el dict slot -> equipo REAL para todos los slots (R32, R16, QF, SF,
    THIRD, FINAL, CHAMPION/RUNNER_UP/THIRD_PLACE/FOURTH_PLACE), basado en
    resultados reales de la API ya cargados en `Match`.

    Los equipos se colocan según el cuadro OFICIAL (OFFICIAL_R32) emparejando los
    partidos reales por equipos —no por match_number—, porque la API ordena los
    partidos por fecha, no por posición de la llave.

    IMPORTANTE: Solo devuelve equipos si la fase de grupos ya terminó completa.
    """
    if not group_stage_complete():
        return {}
    bracket, _slot_match = actual_bracket_and_matches()
    return bracket


# ============================================================
# Puntos por fase de grupos
# ============================================================
def _points_group_match(pred: GroupMatchPrediction, match: Match) -> int:
    if not match.is_finished:
        return 0
    # 5 pts marcador exacto
    if pred.home_score == match.home_score and pred.away_score == match.away_score:
        return 5
    # 2 pts acertar el ganador (o empate)
    def sign(a, b):
        return 0 if a == b else (1 if a > b else -1)
    if sign(pred.home_score, pred.away_score) == sign(match.home_score, match.away_score):
        return 2
    return 0


def _points_group_standing(pred: GroupStandingPrediction,
                           actual_standings: Dict[str, list]) -> int:
    """2 pts si el equipo quedó en la posición exacta dentro de su grupo."""
    rows = actual_standings.get(pred.group_name, [])
    # Sólo se otorga el punto si la fase de grupos del grupo terminó.
    # Lo aproximamos: todos los 6 partidos del grupo están finalizados.
    if len(rows) < 4:
        return 0
    # ¿están los 6 partidos del grupo finalizados?
    total = sum(r['P'] for r in rows)
    if total < 12:  # 4 equipos * 3 partidos cada uno = 12 partidos-equipo
        return 0
    target_pos = pred.position  # 1..4
    if target_pos < 1 or target_pos > len(rows):
        return 0
    if rows[target_pos - 1]['team'] == pred.team:
        return 2
    return 0


# ============================================================
# Puntos por bracket (qué equipo en qué slot)
# ============================================================
def _round_of_slot(slot: str) -> Optional[str]:
    if slot.startswith('R32_'): return ROUND_R32
    if slot.startswith('R16_'): return ROUND_R16
    if slot.startswith('QF_'):  return ROUND_QF
    if slot.startswith('SF_'):  return ROUND_SF
    if slot.startswith('THIRD_'): return ROUND_3RD
    if slot.startswith('FINAL_'): return ROUND_FINAL
    return None


def _points_bracket_team(pred_team: str, pred_slot: str,
                         actual_bracket: Dict[str, str]) -> int:
    """
    Da puntos por poner un equipo en un slot del bracket.
    - 'mismo slot' (=mismo equipo en el mismo slot)            → puntos altos
    - 'mismo round, otro slot' (el equipo SÍ llegó a esa ronda) → puntos medios
    """
    round_name = _round_of_slot(pred_slot)
    if round_name is None:
        return 0
    if round_name not in ROUND_CORRECT_SLOT_POINTS:
        return 0
    correct_pts, partial_pts = ROUND_CORRECT_SLOT_POINTS[round_name]

    actual_team = actual_bracket.get(pred_slot)
    if actual_team is None:
        return 0  # esa ronda aún no está definida en la realidad

    if actual_team == pred_team:
        return correct_pts

    # Está el equipo en otro slot de la MISMA ronda?
    for slot, team in actual_bracket.items():
        if _round_of_slot(slot) == round_name and team == pred_team:
            return partial_pts
    return 0


def _points_final_positions(participant: Participant,
                            actual_bracket: Dict[str, str]) -> int:
    """Campeón/Subcampeón/3er/4to puesto desde BracketPrediction con esos slots."""
    pts = 0
    for slot, slot_pts in FINAL_POSITION_POINTS.items():
        actual = actual_bracket.get(slot)
        if actual is None:
            continue
        pred = BracketPrediction.objects.filter(
            participant=participant, slot=slot
        ).first()
        if pred and pred.team == actual:
            pts += slot_pts
    return pts


# ============================================================
# Puntos por marcador exacto en partidos eliminatorios
# ============================================================
def _points_knockout_scores(participant: Participant) -> int:
    """
    Para cada predicción de marcador en eliminatoria, si el resultado REAL del
    partido de ese cruce del bracket coincide en marcador (orden top-bottom),
    suma puntos.

    El partido real de cada cruce se obtiene emparejando por equipos según el
    cuadro oficial (no por match_number), igual que el bracket que ve el usuario.
    """
    _bracket, slot_match = actual_bracket_and_matches()
    total = 0
    for pred in KnockoutScorePrediction.objects.filter(participant=participant):
        real_match = slot_match.get((pred.slot_top, pred.slot_bottom))
        if real_match is None or not real_match.is_finished:
            continue
        if (pred.home_score == real_match.home_score and
                pred.away_score == real_match.away_score):
            total += KNOCKOUT_SCORE_POINTS.get(pred.round, 0)
    return total


# ============================================================
# Premios individuales
# ============================================================
def _normalize_name(s: str) -> str:
    """minúsculas, sin acentos ni puntuación, espacios colapsados."""
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', s.lower()).split())


def _token_match(t1: str, t2: str) -> bool:
    if t1 == t2:
        return True
    if len(t1) >= 4 and len(t2) >= 4:
        # apodos/formas cortas (Rodri~Rodrigo) o typos (Mbape~Mbappe)
        if t1.startswith(t2) or t2.startswith(t1):
            return True
        if difflib.SequenceMatcher(None, t1, t2).ratio() >= 0.85:
            return True
    return False


def award_name_matches(prediction: str, actual: str) -> bool:
    """
    Compara el nombre que puso el participante con el ganador real de forma
    tolerante: ignora mayúsculas, acentos y puntuación, y acepta apellidos,
    nombres incompletos, apodos (Rodri↔Rodrigo) y pequeños errores de tipeo
    (Mbape↔Mbappe). Se ancla en el APELLIDO del ganador para no confundir por
    nombres de pila iguales (p. ej. Julián Álvarez vs Julian Brandt).
    """
    p = _normalize_name(prediction)
    a = _normalize_name(actual)
    if not p or not a:
        return False
    if p == a:
        return True
    # nombre corto contenido en el otro (ej. "Unai" ↔ "Unai Simon")
    if a in p or p in a:
        return True
    ptoks = p.split()
    surname = a.split()[-1]  # apellido del ganador real
    for pt in ptoks:
        if _token_match(pt, surname):
            return True
    # similitud global como último recurso (nombres de una palabra con typo)
    if difflib.SequenceMatcher(None, p, a).ratio() >= 0.86:
        return True
    return False


def _points_awards(participant: Participant) -> int:
    actuals = {a.award: a.player_name for a in AwardActual.objects.all()}
    total = 0
    for pred in AwardPrediction.objects.filter(participant=participant):
        actual = actuals.get(pred.award, '')
        if actual and award_name_matches(pred.player_name, actual):
            total += AWARD_POINTS.get(pred.award, 0)
    return total


# ============================================================
# API pública: puntos por participante / por grupo / breakdown
# ============================================================
def participant_points_breakdown(participant: Participant) -> dict:
    """Devuelve {seccion: puntos} y un total."""
    actual_standings = actual_group_standings()
    actual_bracket = build_actual_bracket()

    # 1. Fase de grupos: marcadores de partidos
    group_match_pts = 0
    for pred in GroupMatchPrediction.objects.filter(participant=participant) \
            .select_related('match'):
        group_match_pts += _points_group_match(pred, pred.match)

    # 2. Posiciones exactas dentro del grupo
    standings_pts = 0
    for pred in GroupStandingPrediction.objects.filter(participant=participant):
        standings_pts += _points_group_standing(pred, actual_standings)

    # 3. Equipos en cada slot del bracket (R32..Final)
    bracket_pts = 0
    for pred in BracketPrediction.objects.filter(participant=participant):
        if pred.slot in FINAL_POSITION_POINTS:
            continue  # se cuentan aparte
        bracket_pts += _points_bracket_team(pred.team, pred.slot, actual_bracket)

    # 4. Campeón / subcampeón / 3er / 4to puesto
    final_pos_pts = _points_final_positions(participant, actual_bracket)

    # 5. Marcadores de eliminatoria
    knockout_score_pts = _points_knockout_scores(participant)

    # 6. Premios
    award_pts = _points_awards(participant)

    total = (group_match_pts + standings_pts + bracket_pts +
             final_pos_pts + knockout_score_pts + award_pts)

    return {
        'group_match_pts': group_match_pts,
        'standings_pts': standings_pts,
        'bracket_pts': bracket_pts,
        'final_pos_pts': final_pos_pts,
        'knockout_score_pts': knockout_score_pts,
        'award_pts': award_pts,
        'total': total,
    }


def participant_total(participant: Participant) -> int:
    return participant_points_breakdown(participant)['total']


def betting_group_leaderboard(betting_group: BettingGroup) -> List[dict]:
    """Lista ordenada [{participant, total, breakdown}] del grupo de apuestas."""
    rows = []
    for p in betting_group.participants.all():
        bd = participant_points_breakdown(p)
        rows.append({'participant': p, 'total': bd['total'], 'breakdown': bd})
    rows.sort(key=lambda r: -r['total'])
    return rows


def recalculate_all_scores():
    """Hook por si en el futuro quisieras cachear puntajes. Por ahora no cachea."""
    # No-op: los puntajes se calculan on-demand. Lo dejamos por si más adelante
    # quieres persistir un score table.
    return
