"""
Lógica del bracket del Mundial 2026.

Funciones principales:
- group_standings_from_predictions(participant): genera la tabla de cada grupo
  según las predicciones de marcadores que dio el participante. Devuelve un dict
  group_name -> lista ordenada de equipos por posición.
- compute_actual_group_standings(): lo mismo pero con resultados REALES de la API
  (Match.is_finished). Sirve para calificar.
- bracket_from_standings(standings): a partir de las posiciones (1A, 2B, mejor tercero…)
  arma todos los slots R32_1..R32_32, los emparejamientos a R16, etc., asumiendo que
  todos los equipos avanzan por orden.

Pairings oficiales R32 (de FIFA):
   1E vs 3ABCDF, 1I vs 3CDFGH, 2A vs 2B, 1F vs 2C, 2K vs 2L, 1H vs 2J,
   1D vs 3BEFIJ, 1G vs 3AEHIJ, 1C vs 2F, 2E vs 2I, 1A vs 3CEFHI,
   1L vs 3EHIJK, 1J vs 2H, 2D vs 2G, 1B vs 3EFGIJ, 1K vs 3DEIJL.

Estos pairings los modelamos con un esquema simplificado: hay slots fijos
"1A", "2A", ..."1L", "2L" para los 12 ganadores y 12 segundos, y 8 slots de
"3*_1".."3*_8" para los mejores terceros (ordenados por ranking 1..8). En
cada partido el "tercero" se asigna por su ranking según la tabla oficial:
en el orden en que aparecen R32_1..R32_16 abajo.

NOTA: la asignación exacta del enésimo mejor tercero a un slot R32 depende
de qué GRUPOS son los terceros que clasifican. La regla oficial de FIFA es
una tabla con 15 combinaciones según los 8 grupos de origen de los terceros.
Para simplificar (y dado que la API ya nos da los Match con sus equipos),
usamos un fallback: si el Match real ya existe en la BD para un slot, su
equipo home/away es el "ground truth". Si no existe aún, ranqueamos los
terceros por puntos y le asignamos por orden a los slots disponibles.
"""
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from .models import (
    Match, GroupMatchPrediction, GroupStandingPrediction,
    ROUND_GROUP, ROUND_R32, ROUND_R16, ROUND_QF, ROUND_SF, ROUND_3RD, ROUND_FINAL,
    BRACKET_SLOTS,
)


# ---------------------------------------------------------------
# Pairings fijos R32 (orden: slot_top, slot_bottom). Es la lista FIFA.
# Los terceros se nombran '3rd_1'..'3rd_8' por ranking de mejores terceros.
# ---------------------------------------------------------------
R32_PAIRINGS = [
    # (R32_idx, slot_top_ref, slot_bottom_ref)
    (1,  '1E', '3rd_1'),
    (2,  '1I', '3rd_2'),
    (3,  '2A', '2B'),
    (4,  '1F', '2C'),
    (5,  '2K', '2L'),
    (6,  '1H', '2J'),
    (7,  '1D', '3rd_3'),
    (8,  '1G', '3rd_4'),
    (9,  '1C', '2F'),
    (10, '2E', '2I'),
    (11, '1A', '3rd_5'),
    (12, '1L', '3rd_6'),
    (13, '1J', '2H'),
    (14, '2D', '2G'),
    (15, '1B', '3rd_7'),
    (16, '1K', '3rd_8'),
]

# Pairings R16 (cuál ganador de R32_x juega con quién). Estructura estándar
# de árbol binario: R16_i recibe a R32_(2i-1) y R32_(2i).
R16_PAIRINGS = [(i, 2 * i - 1, 2 * i) for i in range(1, 9)]
QF_PAIRINGS = [(i, 2 * i - 1, 2 * i) for i in range(1, 5)]
SF_PAIRINGS = [(i, 2 * i - 1, 2 * i) for i in range(1, 3)]


# ---------------------------------------------------------------
# Standings de fase de grupos
# ---------------------------------------------------------------
def _new_row(team):
    return {'team': team, 'P': 0, 'W': 0, 'D': 0, 'L': 0,
            'GF': 0, 'GA': 0, 'GD': 0, 'Pts': 0}


def _apply_match(table, home, away, hs, as_):
    if home not in table:
        table[home] = _new_row(home)
    if away not in table:
        table[away] = _new_row(away)
    th, ta = table[home], table[away]
    th['P'] += 1; ta['P'] += 1
    th['GF'] += hs; th['GA'] += as_; th['GD'] = th['GF'] - th['GA']
    ta['GF'] += as_; ta['GA'] += hs; ta['GD'] = ta['GF'] - ta['GA']
    if hs > as_:
        th['W'] += 1; ta['L'] += 1; th['Pts'] += 3
    elif hs < as_:
        ta['W'] += 1; th['L'] += 1; ta['Pts'] += 3
    else:
        th['D'] += 1; ta['D'] += 1; th['Pts'] += 1; ta['Pts'] += 1


def _sort_rows(rows):
    """Orden FIFA simplificado: Pts, GD, GF, nombre."""
    return sorted(rows, key=lambda r: (-r['Pts'], -r['GD'], -r['GF'], r['team']))


def actual_group_standings() -> Dict[str, List[dict]]:
    """Tablas reales de los 12 grupos, usando resultados finalizados de la API."""
    groups = defaultdict(dict)  # group_name -> {team: row}
    for m in Match.objects.filter(round=ROUND_GROUP):
        # asegurar filas existentes incluso si aún no hay marcador
        for t in (m.home_team, m.away_team):
            groups[m.group_name].setdefault(t, _new_row(t))
        if m.is_finished:
            _apply_match(groups[m.group_name], m.home_team, m.away_team,
                         m.home_score, m.away_score)
    return {g: _sort_rows(list(tbl.values())) for g, tbl in groups.items()}


def predicted_group_standings(participant) -> Dict[str, List[dict]]:
    """Tablas que SALEN de las predicciones de marcador del participante.

    Si para algún partido falta su predicción, ese partido se ignora (el equipo
    igual aparece en la tabla con 0 puntos).
    """
    preds = {p.match_id: p for p in
             GroupMatchPrediction.objects.filter(participant=participant)
             .select_related('match')}

    groups = defaultdict(dict)
    for m in Match.objects.filter(round=ROUND_GROUP):
        for t in (m.home_team, m.away_team):
            groups[m.group_name].setdefault(t, _new_row(t))
        pred = preds.get(m.id)
        if pred is not None:
            _apply_match(groups[m.group_name], m.home_team, m.away_team,
                         pred.home_score, pred.away_score)
    return {g: _sort_rows(list(tbl.values())) for g, tbl in groups.items()}


# ---------------------------------------------------------------
# Cálculo de "mejores terceros"
# ---------------------------------------------------------------
def best_thirds(standings: Dict[str, List[dict]]) -> List[dict]:
    """Devuelve los 8 mejores terceros ordenados (mejor primero)."""
    thirds = []
    for g, rows in standings.items():
        if len(rows) >= 3:
            row = dict(rows[2])  # copia
            row['group'] = g
            thirds.append(row)
    thirds.sort(key=lambda r: (-r['Pts'], -r['GD'], -r['GF'], r['team']))
    return thirds[:8]


# ---------------------------------------------------------------
# Resolver el bracket desde los standings
# ---------------------------------------------------------------
def _resolve_ref(ref: str, standings: Dict[str, List[dict]],
                 thirds: List[dict]) -> Optional[str]:
    """Convierte una referencia tipo '1A' o '3rd_4' al nombre del equipo."""
    if ref.startswith('3rd_'):
        idx = int(ref.split('_')[1]) - 1
        if 0 <= idx < len(thirds):
            return thirds[idx]['team']
        return None
    # caso '1A', '2C', etc.
    pos = int(ref[0])
    grp = ref[1]
    rows = standings.get(grp, [])
    if len(rows) >= pos:
        return rows[pos - 1]['team']
    return None


def bracket_from_standings(standings: Dict[str, List[dict]]) -> Dict[str, str]:
    """
    A partir de las tablas, devuelve un dict de SLOT -> equipo, sólo para R32.
    Para R16/QF/SF/Final/Champion necesitamos saber QUIÉN GANÓ cada llave; eso
    se calcula con `bracket_from_knockout_scores`.
    """
    thirds = best_thirds(standings)
    result = {}
    for r32_idx, top_ref, bot_ref in R32_PAIRINGS:
        top_team = _resolve_ref(top_ref, standings, thirds)
        bot_team = _resolve_ref(bot_ref, standings, thirds)
        # slot_top = R32_(2i-1), slot_bottom = R32_(2i)  (par/ impar de R32)
        slot_top = f'R32_{2 * r32_idx - 1}'
        slot_bottom = f'R32_{2 * r32_idx}'
        if top_team:
            result[slot_top] = top_team
        if bot_team:
            result[slot_bottom] = bot_team
    return result


def r32_pairings_for_display() -> List[Tuple[str, str]]:
    """Devuelve pares de (slot_top, slot_bottom) en orden de partido R32_1..R32_16."""
    pairs = []
    for r32_idx, _t, _b in R32_PAIRINGS:
        pairs.append((f'R32_{2 * r32_idx - 1}', f'R32_{2 * r32_idx}'))
    return pairs


# ---------------------------------------------------------------
# Dieciseisavos OFICIALES del Mundial 2026 (cuadro oficial FIFA).
# El orden ES la posicion en el bracket: el ganador del partido i se enfrenta
# al del partido i+1 en octavos -> (1 vs 2), (3 vs 4), (5 vs 6), (7 vs 8) ...
# Partidos 1-8 = mitad izquierda (un finalista); 9-16 = mitad derecha (el otro).
# Es la base del bracket que se le muestra a TODOS los participantes mientras
# la API todavia no entregue los partidos reales de eliminatoria.
# ---------------------------------------------------------------
OFFICIAL_R32 = [
    # --- Mitad izquierda del cuadro ---
    ('Alemania', 'Paraguay'),
    ('Francia', 'Suecia'),
    ('Sudáfrica', 'Canadá'),
    ('Países Bajos', 'Marruecos'),
    ('Portugal', 'Croacia'),
    ('España', 'Austria'),
    ('Estados Unidos', 'Bosnia y Herzegovina'),
    ('Bélgica', 'Senegal'),
    # --- Mitad derecha del cuadro ---
    ('Brasil', 'Japón'),
    ('Costa de Marfil', 'Noruega'),
    ('México', 'Ecuador'),
    ('Inglaterra', 'República Democrática del Congo'),
    ('Argentina', 'Cabo Verde'),
    ('Australia', 'Egipto'),
    ('Suiza', 'Argelia'),
    ('Colombia', 'Ghana'),
]


def _official_r32_slots() -> Dict[str, str]:
    slots = {}
    for i, (home, away) in enumerate(OFFICIAL_R32, start=1):
        slots[f'R32_{2 * i - 1}'] = home
        slots[f'R32_{2 * i}'] = away
    return slots


def real_r32_slots() -> Dict[str, str]:
    """
    Base oficial de los dieciseisavos (igual para TODOS los participantes).

    Prioridad:
      1. Partidos reales de la API (round = round_of_32), si ya estan cargados
         con equipos. Se mapea el partido i (orden por match_number) a:
             R32_(2i-1) = equipo local, R32_(2i) = equipo visitante.
      2. Lista oficial fija OFFICIAL_R32 definida arriba.
    """
    matches = list(Match.objects.filter(round=ROUND_R32)
                   .order_by('match_number', 'kickoff_utc'))
    slots = {}
    for i, m in enumerate(matches, start=1):
        if m.home_team:
            slots[f'R32_{2 * i - 1}'] = m.home_team
        if m.away_team:
            slots[f'R32_{2 * i}'] = m.away_team
    if slots:
        return slots
    return _official_r32_slots()


def round_pairings(round_name: str) -> List[Tuple[str, str, str]]:
    """
    Devuelve [(slot_top, slot_bottom, parent_slot_of_winner), ...] para una ronda.
    parent_slot_of_winner es el slot donde aterriza el ganador del partido.
    """
    pairs = []
    if round_name == ROUND_R16:
        for i, t, b in R16_PAIRINGS:
            pairs.append((f'R32_{t}', f'R32_{b}', f'R16_{i}'))
            # ojo: queremos que el "match" del R16 sea entre R16_(2i-1) y R16_(2i)
        # Reinterpretemos: para R16, los partidos son R16_(2j-1) vs R16_(2j),
        # y el ganador va a QF_j.
        pairs = []
        for j in range(1, 9, 2):
            i = (j + 1) // 2
            pairs.append((f'R16_{j}', f'R16_{j+1}', f'QF_{i}'))
    elif round_name == ROUND_QF:
        for j in range(1, 9, 2):
            i = (j + 1) // 2
            pairs.append((f'QF_{j}', f'QF_{j+1}', f'SF_{i}'))
    elif round_name == ROUND_SF:
        pairs.append(('SF_1', 'SF_2', 'FINAL_1'))
        pairs.append(('SF_3', 'SF_4', 'FINAL_2'))
    elif round_name == ROUND_3RD:
        pairs.append(('THIRD_1', 'THIRD_2', None))
    elif round_name == ROUND_FINAL:
        pairs.append(('FINAL_1', 'FINAL_2', None))
    return pairs


# Listas de "matches" por ronda (slot_top, slot_bottom) en orden de partido.
def round_matches(round_name: str) -> List[Tuple[str, str]]:
    if round_name == ROUND_R32:
        return r32_pairings_for_display()
    if round_name == ROUND_R16:
        return [(f'R16_{2*i-1}', f'R16_{2*i}') for i in range(1, 9)]
    if round_name == ROUND_QF:
        return [(f'QF_{2*i-1}', f'QF_{2*i}') for i in range(1, 5)]
    if round_name == ROUND_SF:
        return [('SF_1', 'SF_2'), ('SF_3', 'SF_4')]
    if round_name == ROUND_3RD:
        return [('THIRD_1', 'THIRD_2')]
    if round_name == ROUND_FINAL:
        return [('FINAL_1', 'FINAL_2')]
    return []


# ---------------------------------------------------------------
# Mapear slots a Matches REALES de la API (cuando ya existan)
# ---------------------------------------------------------------
def actual_team_for_slot(slot: str, actual_bracket: Dict[str, str]) -> Optional[str]:
    """
    Resuelve qué equipo ESTÁ realmente en un slot, según resultados reales.
    `actual_bracket` es el dict slot->team computado a partir de los standings
    reales + ganadores reales de cada llave eliminatoria.
    """
    return actual_bracket.get(slot)


# ---------------------------------------------------------------
# Auto-completado de bracket: derivar ganadores de una ronda
# ---------------------------------------------------------------
def derive_round_winners(participant, current_round: str) -> Dict[str, str]:
    """
    Basándose en las predicciones de marcador de 'current_round',
    devuelve un dict {slot_ganador: equipo_ganador} para cada partido.
    
    Por ejemplo, si current_round=ROUND_R32, devuelve los ganadores de cada 
    partido R32 según los KnockoutScorePrediction del participante.
    
    Devuelve dict slot -> equipo_que_va_a_la_siguiente_ronda.
    """
    from .models import KnockoutScorePrediction
    
    winners = {}  # slot_siguiente_ronda -> equipo
    bracket_preds = {bp.slot: bp.team for bp in 
                     __import__('django.db.models', fromlist=['Q']).Q}
    # Cargar predicciones de equipos para esta ronda
    from .models import BracketPrediction
    bracket_preds = {bp.slot: bp.team for bp in
                     BracketPrediction.objects.filter(participant=participant)}
    
    # Obtener los scores predichos para esta ronda
    scores = {(ks.slot_top, ks.slot_bottom): ks for ks in
              KnockoutScorePrediction.objects.filter(
                  participant=participant, round=current_round)}
    
    # Para cada partido en esta ronda, derivar el ganador
    for slot_top, slot_bottom in round_matches(current_round):
        ks = scores.get((slot_top, slot_bottom))
        if ks is None:
            continue
        
        # Obtener los equipos que juegan en estos slots
        team_top = bracket_preds.get(slot_top)
        team_bottom = bracket_preds.get(slot_bottom)
        
        if not team_top or not team_bottom:
            continue
        
        # Determinar ganador: si home_score > away_score, gana el slot_top
        winner = team_top if ks.home_score > ks.away_score else team_bottom
        
        # Determinar el slot de la siguiente ronda para el ganador
        # Parseamos los números de los slots para asignar al siguiente round
        try:
            if current_round == ROUND_R32:
                # R32_1, R32_2 -> R16_1
                num_top = int(slot_top.split('_')[1])
                next_slot = f'R16_{(num_top + 1) // 2}'
            elif current_round == ROUND_R16:
                # R16_1, R16_2 -> QF_1
                num_top = int(slot_top.split('_')[1])
                next_slot = f'QF_{(num_top + 1) // 2}'
            elif current_round == ROUND_QF:
                # QF_1, QF_2 -> SF_1
                num_top = int(slot_top.split('_')[1])
                next_slot = f'SF_{(num_top + 1) // 2}'
            elif current_round == ROUND_SF:
                # SF_1, SF_2 -> FINAL_1; SF_3, SF_4 -> FINAL_2
                num_top = int(slot_top.split('_')[1])
                next_slot = f'FINAL_{(num_top + 1) // 2}'
            else:
                continue
            
            winners[next_slot] = winner
        except (ValueError, IndexError):
            continue
    
    return winners
