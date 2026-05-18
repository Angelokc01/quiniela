"""
Cálculo de puntos.

Tabla de puntos (definida por el usuario):

FASE DE GRUPOS
  - 3 pts: resultado exacto de un partido (marcador exacto).
  - 1 pt:  acertar el ganador (incluye empate) en fase de grupos.
  - 1 pt:  acertar la posición exacta de un equipo dentro de su grupo (4 por grupo).

CLASIFICADOS POR RONDA
  - Dieciseisavos (R32): 6 si el equipo está en la MISMA llave; 3 si está en R32
    pero en llave diferente.
  - Octavos (R16): 12 llave correcta, 6 incorrecta.
    (¡ojo a la redacción del usuario! En su mensaje dice "6 puntos equipo exacto
    en octavos / 3 puntos equipo en octavos llave diferente" — interpretamos eso
    como dieciseisavos = R32 = 6/3, y octavos R16 = 12/6.)
    Releyendo: el usuario escribió literalmente:
      "6 puntos equipo exacto en octavos de final. 3 puntos equipo en octavos
       de final pero en llave diferente. 12 puntos equipo en cuartos llave
       correcta 6 incorrecta."
    Su nomenclatura: "octavos de final" = R32 (porque el mundial 2026 tiene R32
    como octavos coloquialmente). Mantenemos esa interpretación.
  - Cuartos (QF):    12 llave correcta, 6 incorrecta.
  - Semis (SF):      24 llave correcta, 12 incorrecta.
  - Finalistas:      30 llave correcta, 15 incorrecta.

POSICIÓN FINAL
  - 50 campeón
  - 30 subcampeón
  - 15 tercer puesto
  - 8  cuarto puesto

MARCADOR EXACTO EN ELIMINATORIA (no importa quiénes jueguen, sólo el marcador,
  en el orden top-bottom del bracket del usuario):
  - R32 (dieciseisavos): 4
  - R16 (octavos):       5
  - QF  (cuartos):       6
  - SF  (semis):         7
  - 3rd place:           7
  - Final:               8

PREMIOS INDIVIDUALES
  - Bota Oro:     10
  - Balón Oro:    10
  - Guante Oro:   10
  - Mejor Joven:  5
  - Mejor Gol:    5  (admin lo define)
"""
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
    R32_PAIRINGS, round_matches,
)


# Tabla de puntos para clasificación a cada ronda
ROUND_CORRECT_SLOT_POINTS = {
    ROUND_R32: (6, 3),   # (mismo slot, otro slot pero misma ronda)
    ROUND_R16: (12, 6),
    ROUND_QF:  (12, 6),
    ROUND_SF:  (24, 12),
    # finalistas = participar en la final (estar en FINAL_1 o FINAL_2)
    ROUND_FINAL: (30, 15),
}

# Puntos por posición final (campeón, subcampeón, etc.)
FINAL_POSITION_POINTS = {
    SLOT_CHAMPION:  50,
    SLOT_RUNNER_UP: 30,
    SLOT_THIRD:     15,
    SLOT_FOURTH:    8,
}

# Puntos por marcador exacto de un partido de eliminatoria (orden top-bottom)
KNOCKOUT_SCORE_POINTS = {
    ROUND_R32: 4,
    ROUND_R16: 5,
    ROUND_QF:  6,
    ROUND_SF:  7,
    ROUND_3RD: 7,
    ROUND_FINAL: 8,
}


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
    
    IMPORTANTE: Solo devuelve equipos de R32 si hay partidos finalizados en fase
    de grupos. Si la fase de grupos aún no ha comenzado, devuelve un dict vacío
    para evitar dar puntos erróneamente.
    """
    # Verificar si hay partidos finalizados en fase de grupos
    finished_group_matches = Match.objects.filter(
        round=ROUND_GROUP, status=Match.STATUS_COMPLETED).count()
    
    # Si no hay partidos finalizados aún, devolver dict vacío
    if finished_group_matches == 0:
        return {}
    
    standings = actual_group_standings()
    bracket = bracket_from_standings(standings)  # R32_1..R32_32

    # R16: ganador de cada partido R32 va a R16_i (i=1..16) en orden del partido.
    # En FIFA, el partido R32_1 vs R32_2 produce el equipo de R16_1, etc.
    # En nuestro modelo, los matches R16 los ordenamos por match_number en la API
    # — y asumimos esa misma asignación.
    def fill_round(round_name, prev_pairs, target_slot_fn):
        for idx, (slot_top, slot_bottom) in enumerate(prev_pairs, start=1):
            m = _actual_team_for_round_slot(round_name, idx)
            if not m or not m.is_finished:
                continue
            winner = m.winner
            if winner == 'DRAW':
                # ronda de KO, no debería haber empate como ganador final
                continue
            bracket[target_slot_fn(idx)] = winner

    # R16: 16 partidos, parejas (R32_1,R32_2)..(R32_31,R32_32) → R16_1..R16_16
    r32_pairs = [(f'R32_{2*i-1}', f'R32_{2*i}') for i in range(1, 17)]
    fill_round(ROUND_R16, r32_pairs, lambda i: f'R16_{i}')

    # QF: 8 partidos R16 → QF_1..QF_8
    r16_pairs = [(f'R16_{2*i-1}', f'R16_{2*i}') for i in range(1, 9)]
    fill_round(ROUND_QF, r16_pairs, lambda i: f'QF_{i}')

    # SF: 4 partidos QF → SF_1..SF_4
    qf_pairs = [(f'QF_{2*i-1}', f'QF_{2*i}') for i in range(1, 5)]
    fill_round(ROUND_SF, qf_pairs, lambda i: f'SF_{i}')

    # Final: 2 partidos SF → FINAL_1, FINAL_2
    sf_pairs = [('SF_1', 'SF_2'), ('SF_3', 'SF_4')]
    fill_round(ROUND_FINAL, sf_pairs, lambda i: f'FINAL_{i}')

    # 3er puesto: los PERDEDORES de las semifinales
    for idx, (st, sb) in enumerate(sf_pairs, start=1):
        m = _actual_team_for_round_slot(ROUND_SF, idx)
        if not m or not m.is_finished:
            continue
        winner = m.winner
        loser = m.away_team if winner == m.home_team else m.home_team
        bracket[f'THIRD_{idx}'] = loser

    # CHAMPION / RUNNER_UP: ganador y perdedor de la final
    final_match = _actual_team_for_round_slot(ROUND_FINAL, 1)
    if final_match and final_match.is_finished:
        winner = final_match.winner
        loser = final_match.away_team if winner == final_match.home_team else final_match.home_team
        bracket[SLOT_CHAMPION] = winner
        bracket[SLOT_RUNNER_UP] = loser

    # 3rd / 4th place: ganador y perdedor del partido por el 3er puesto
    third_match = _actual_team_for_round_slot(ROUND_3RD, 1)
    if third_match and third_match.is_finished:
        winner = third_match.winner
        loser = third_match.away_team if winner == third_match.home_team else third_match.home_team
        bracket[SLOT_THIRD] = winner
        bracket[SLOT_FOURTH] = loser

    return bracket


# ============================================================
# Puntos por fase de grupos
# ============================================================
def _points_group_match(pred: GroupMatchPrediction, match: Match) -> int:
    if not match.is_finished:
        return 0
    # 3 pts marcador exacto
    if pred.home_score == match.home_score and pred.away_score == match.away_score:
        return 3
    # 1 pt acertar el ganador (o empate)
    def sign(a, b):
        return 0 if a == b else (1 if a > b else -1)
    if sign(pred.home_score, pred.away_score) == sign(match.home_score, match.away_score):
        return 1
    return 0


def _points_group_standing(pred: GroupStandingPrediction,
                           actual_standings: Dict[str, list]) -> int:
    """1 pt si el equipo quedó en la posición exacta dentro de su grupo."""
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
        return 1
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
    partido en ESOS slots coincide en marcador (orden top-bottom), suma puntos.
    """
    total = 0
    preds = KnockoutScorePrediction.objects.filter(participant=participant)
    for pred in preds:
        round_name = pred.round
        # los partidos en una ronda están en el orden de round_matches(round_name)
        pairs = round_matches(round_name)
        try:
            idx = pairs.index((pred.slot_top, pred.slot_bottom))
        except ValueError:
            continue
        real_match = _actual_team_for_round_slot(round_name, idx + 1)
        if real_match is None or not real_match.is_finished:
            continue
        if (pred.home_score == real_match.home_score and
                pred.away_score == real_match.away_score):
            total += KNOCKOUT_SCORE_POINTS.get(round_name, 0)
    return total


# ============================================================
# Premios individuales
# ============================================================
def _points_awards(participant: Participant) -> int:
    actuals = {a.award: (a.player_name or '').strip().lower()
               for a in AwardActual.objects.all()}
    total = 0
    for pred in AwardPrediction.objects.filter(participant=participant):
        actual = actuals.get(pred.award, '')
        if actual and pred.player_name.strip().lower() == actual:
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
