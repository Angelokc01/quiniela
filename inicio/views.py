"""
Vistas de la quiniela. Sin autenticación. Las "sesiones" son simplemente
escoger en pantalla qué grupo y qué participante quieres usar.
"""
from collections import defaultdict

from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from .models import (
    BettingGroup, Participant, Match,
    GroupMatchPrediction, GroupStandingPrediction,
    BracketPrediction, KnockoutScorePrediction,
    AwardPrediction, AwardActual,
    AWARD_CHOICES, AWARD_POINTS,
    ROUND_GROUP, ROUND_R32, ROUND_R16, ROUND_QF, ROUND_SF, ROUND_3RD, ROUND_FINAL,
    SLOT_CHAMPION, SLOT_RUNNER_UP, SLOT_THIRD, SLOT_FOURTH,
)
from .bracket import (
    actual_group_standings, predicted_group_standings,
    bracket_from_standings, round_matches,
)
from .scoring import (
    participant_points_breakdown, betting_group_leaderboard,
    build_actual_bracket,
)
from .wc_api import sync_matches_to_db


# ============================================================
# Home: ver grupos existentes
# ============================================================
def home(request):
    groups = BettingGroup.objects.all()
    return render(request, 'inicio/home.html', {
        'groups': groups,
    })


# ============================================================
# Sistema de puntos
# ============================================================
def sistema_puntos(request):
    return render(request, 'inicio/sistema_puntos.html')


# ============================================================
# Crear grupo
# ============================================================
@require_http_methods(['GET', 'POST'])
def create_group(request):
    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        if not name:
            messages.error(request, 'Pon un nombre al grupo.')
        else:
            try:
                bg = BettingGroup.objects.create(name=name)
                return redirect('inicio:manage_participants', bg_id=bg.id)
            except Exception as e:
                messages.error(request, f'Error al crear el grupo: {e}')

    return render(request, 'inicio/create_group.html')


# ============================================================
# Manejar participantes de un grupo
# ============================================================
@require_http_methods(['GET', 'POST'])
def manage_participants(request, bg_id):
    bg = get_object_or_404(BettingGroup, id=bg_id)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add':
            name = (request.POST.get('name') or '').strip()
            if name:
                Participant.objects.get_or_create(betting_group=bg, name=name)
            return redirect('inicio:manage_participants', bg_id=bg.id)
        if action == 'delete':
            pid = request.POST.get('participant_id')
            if pid:
                Participant.objects.filter(id=pid, betting_group=bg).delete()
            return redirect('inicio:manage_participants', bg_id=bg.id)

    return render(request, 'inicio/manage_participants.html', {
        'bg': bg,
        'participants': bg.participants.all(),
    })


# ============================================================
# Elegir participante para empezar a predecir / ver puntajes
# ============================================================
def choose_participant(request):
    groups = BettingGroup.objects.prefetch_related('participants').all()
    return render(request, 'inicio/choose_participant.html', {
        'groups': groups,
    })


# ============================================================
# Dashboard del participante: links a cada subsección
# ============================================================
def predictions_dashboard(request, participant_id):
    participant = get_object_or_404(Participant, id=participant_id)

    n_matches_group = Match.objects.filter(round=ROUND_GROUP).count()
    n_preds_group = GroupMatchPrediction.objects.filter(participant=participant).count()

    standings_done = GroupStandingPrediction.objects.filter(
        participant=participant).count()

    # ¿el participante completó la fase de grupos para que se le habilite el bracket?
    group_done = (n_preds_group >= n_matches_group and n_matches_group > 0)

    bracket_count = BracketPrediction.objects.filter(participant=participant).count()
    awards_count = AwardPrediction.objects.filter(participant=participant).count()

    breakdown = participant_points_breakdown(participant)

    return render(request, 'inicio/predictions_dashboard.html', {
        'participant': participant,
        'n_matches_group': n_matches_group,
        'n_preds_group': n_preds_group,
        'group_done': group_done,
        'standings_done': standings_done,
        'bracket_count': bracket_count,
        'awards_count': awards_count,
        'breakdown': breakdown,
    })


# ============================================================
# Predicciones fase de grupos
# ============================================================
def predict_group_stage(request, participant_id):
    participant = get_object_or_404(Participant, id=participant_id)

    if request.method == 'POST':
        # Guardar todos los marcadores enviados
        for key, value in request.POST.items():
            if not key.startswith('home_') and not key.startswith('away_'):
                continue
            try:
                _, match_id = key.split('_', 1)
                match_id = int(match_id)
            except (ValueError, TypeError):
                continue
            # buscamos pareja
            home_val = request.POST.get(f'home_{match_id}')
            away_val = request.POST.get(f'away_{match_id}')
            if home_val == '' or away_val == '' or home_val is None or away_val is None:
                continue
            try:
                hs = int(home_val); as_ = int(away_val)
            except ValueError:
                continue
            match = Match.objects.filter(id=match_id, round=ROUND_GROUP).first()
            if not match:
                continue
            # No permitir editar si el partido ya empezó
            if match.kickoff_in_past:
                continue
            GroupMatchPrediction.objects.update_or_create(
                participant=participant, match=match,
                defaults={'home_score': hs, 'away_score': as_},
            )

        # También guardar predicciones de POSICIÓN del grupo si las enviaron
        for key, value in request.POST.items():
            if not key.startswith('pos_|'):
                continue
            try:
                _prefix, group_name, team = key.split('|', 2)
            except ValueError:
                continue
            if not value:
                continue
            try:
                pos = int(value)
            except ValueError:
                continue
            GroupStandingPrediction.objects.update_or_create(
                participant=participant,
                group_name=group_name,
                team=team,
                defaults={'position': pos},
            )
        messages.success(request, 'Predicciones guardadas.')
        return redirect('inicio:predict_group_stage', participant_id=participant.id)

    # GET: armar contexto
    matches = list(Match.objects.filter(round=ROUND_GROUP).order_by(
        'group_name', 'kickoff_utc', 'match_number'))

    # Predicciones existentes
    existing = {p.match_id: p for p in
                GroupMatchPrediction.objects.filter(participant=participant)}

    grouped = defaultdict(list)
    for m in matches:
        pred = existing.get(m.id)
        grouped[m.group_name].append({
            'match': m,
            'pred': pred,
            'locked': m.kickoff_in_past,
        })

    # Standings de las predicciones del participante → para mostrar posiciones sugeridas
    pred_standings = predicted_group_standings(participant)

    # Predicciones existentes de posición
    existing_pos = {(p.group_name, p.team): p.position
                    for p in GroupStandingPrediction.objects.filter(participant=participant)}

    # Para cada grupo, lista [(team, pred_position, current_pos_from_scores)]
    standings_table = {}
    for g, rows in pred_standings.items():
        standings_table[g] = []
        for idx, row in enumerate(rows, start=1):
            standings_table[g].append({
                'team': row['team'],
                'auto_pos': idx,
                'user_pos': existing_pos.get((g, row['team']), idx),
                'stats': row,
            })

    return render(request, 'inicio/predict_group_stage.html', {
        'participant': participant,
        'grouped': dict(sorted(grouped.items())),
        'standings_table': dict(sorted(standings_table.items())),
    })


# ============================================================
# Predicciones del bracket eliminatorio
# ============================================================
def predict_bracket(request, participant_id):
    participant = get_object_or_404(Participant, id=participant_id)

    # Para poder predecir bracket, necesitamos saber qué equipos clasifican.
    # Usamos las predicciones del participante para derivar quién va a R32 (=top 2
    # de cada grupo + 8 mejores terceros según sus predicciones).
    pred_standings = predicted_group_standings(participant)
    suggested_bracket = bracket_from_standings(pred_standings)
    # suggested_bracket: dict slot R32_x -> equipo (según predicciones de fase de grupos)

    def next_slot_for_round(round_name, slot_top):
        try:
            number = int(slot_top.split('_')[1])
        except (IndexError, ValueError):
            return None
        if round_name == ROUND_R32:
            return f'R16_{(number + 1) // 2}'
        if round_name == ROUND_R16:
            return f'QF_{(number + 1) // 2}'
        if round_name == ROUND_QF:
            return f'SF_{(number + 1) // 2}'
        if round_name == ROUND_SF:
            return f'FINAL_{(number + 1) // 2}'
        return None

    def resolve_match_winner(round_name, team_top, team_bottom, score, selected_winner):
        if selected_winner in (team_top, team_bottom):
            return selected_winner
        if not score:
            return ''
        try:
            hs = int(score.home_score)
            as_ = int(score.away_score)
        except (TypeError, ValueError):
            return ''
        if hs > as_:
            return team_top
        if as_ > hs:
            return team_bottom
        return ''

    if request.method == 'POST':
        # Guardar BracketPrediction (team por slot)
        for key, value in request.POST.items():
            if not key.startswith('slot__'):
                continue
            slot = key[len('slot__'):]
            if not value:
                continue
            BracketPrediction.objects.update_or_create(
                participant=participant, slot=slot,
                defaults={'team': value.strip()},
            )
        # Guardar marcadores de eliminatoria
        for round_name in (ROUND_R32, ROUND_R16, ROUND_QF, ROUND_SF, ROUND_3RD, ROUND_FINAL):
            for slot_top, slot_bottom in round_matches(round_name):
                h_key = f'kscore_h__{slot_top}__{slot_bottom}'
                a_key = f'kscore_a__{slot_top}__{slot_bottom}'
                hv = request.POST.get(h_key); av = request.POST.get(a_key)
                if hv in (None, '') or av in (None, ''):
                    continue
                try:
                    hs = int(hv); as_ = int(av)
                except ValueError:
                    continue
                KnockoutScorePrediction.objects.update_or_create(
                    participant=participant,
                    slot_top=slot_top, slot_bottom=slot_bottom,
                    defaults={'round': round_name, 'home_score': hs, 'away_score': as_},
                )

        # Regenerar el bracket desde cero para evitar valores obsoletos en rondas
        # posteriores cuando se cambia un resultado anterior.
        BracketPrediction.objects.filter(
            participant=participant,
        ).exclude(slot__startswith='R32_').delete()

        bracket_state = {
            bp.slot: bp.team
            for bp in BracketPrediction.objects.filter(
                participant=participant,
                slot__startswith='R32_')
        }
        knockout_rounds = [ROUND_R32, ROUND_R16, ROUND_QF, ROUND_SF]
        for round_name in knockout_rounds:
            for match_index, (slot_top, slot_bottom) in enumerate(round_matches(round_name), start=1):
                score = KnockoutScorePrediction.objects.filter(
                    participant=participant,
                    slot_top=slot_top,
                    slot_bottom=slot_bottom,
                ).first()
                selected_winner = request.POST.get(
                    f'winner__{slot_top}__{slot_bottom}',
                    bracket_state.get(next_slot_for_round(round_name, slot_top), ''),
                )
                team_top = bracket_state.get(slot_top, '')
                team_bottom = bracket_state.get(slot_bottom, '')
                winner = resolve_match_winner(round_name, team_top, team_bottom, score, selected_winner)
                next_slot = next_slot_for_round(round_name, slot_top)
                if not next_slot:
                    continue
                if winner:
                    bracket_state[next_slot] = winner
                    BracketPrediction.objects.update_or_create(
                        participant=participant,
                        slot=next_slot,
                        defaults={'team': winner},
                    )
                    if round_name == ROUND_SF:
                        loser = team_bottom if winner == team_top else team_top
                        third_slot = f'THIRD_{match_index}'
                        bracket_state[third_slot] = loser
                        BracketPrediction.objects.update_or_create(
                            participant=participant,
                            slot=third_slot,
                            defaults={'team': loser},
                        )

        # Tercer puesto: se resuelve con el partido específico de tercer lugar.
        for slot_top, slot_bottom in round_matches(ROUND_3RD):
            score = KnockoutScorePrediction.objects.filter(
                participant=participant,
                slot_top=slot_top,
                slot_bottom=slot_bottom,
            ).first()
            selected_winner = request.POST.get(f'winner__{slot_top}__{slot_bottom}', '')
            team_top = bracket_state.get(slot_top, request.POST.get(f'slot__{slot_top}', '').strip())
            team_bottom = bracket_state.get(slot_bottom, request.POST.get(f'slot__{slot_bottom}', '').strip())
            winner = resolve_match_winner(ROUND_3RD, team_top, team_bottom, score, selected_winner)
            if not winner:
                continue
            loser = team_bottom if winner == team_top else team_top
            BracketPrediction.objects.update_or_create(
                participant=participant,
                slot=SLOT_THIRD,
                defaults={'team': winner},
            )
            BracketPrediction.objects.update_or_create(
                participant=participant,
                slot=SLOT_FOURTH,
                defaults={'team': loser},
            )

        # Final: se deja el campeón/subcampeón si ya están definidos los slots.
        final_score = KnockoutScorePrediction.objects.filter(
            participant=participant,
            round=ROUND_FINAL,
        ).first()
        final_top = bracket_state.get('FINAL_1', '')
        final_bottom = bracket_state.get('FINAL_2', '')
        final_selected = request.POST.get('winner__FINAL_1__FINAL_2', '')
        final_winner = resolve_match_winner(ROUND_FINAL, final_top, final_bottom, final_score, final_selected)
        if final_winner:
            final_loser = final_bottom if final_winner == final_top else final_top
            BracketPrediction.objects.update_or_create(
                participant=participant,
                slot=SLOT_CHAMPION,
                defaults={'team': final_winner},
            )
            BracketPrediction.objects.update_or_create(
                participant=participant,
                slot=SLOT_RUNNER_UP,
                defaults={'team': final_loser},
            )
        
        messages.success(request, 'Bracket guardado y completado automáticamente.')
        return redirect('inicio:predict_bracket', participant_id=participant.id)

    # GET: armar contexto
    # Predicciones actuales del participante (team por slot)
    saved_bracket = {bp.slot: bp.team for bp in
                     BracketPrediction.objects.filter(participant=participant)}
    # Marcadores guardados
    saved_scores = {(k.slot_top, k.slot_bottom): k for k in
                    KnockoutScorePrediction.objects.filter(participant=participant)}

    # Helper para construir filas por ronda
    def build_round(round_name):
        out = []
        for st, sb in round_matches(round_name):
            ks = saved_scores.get((st, sb))
            next_slot = next_slot_for_round(round_name, st)
            out.append({
                'slot_top': st,
                'slot_bottom': sb,
                'team_top': saved_bracket.get(st, suggested_bracket.get(st, '')),
                'team_bottom': saved_bracket.get(sb, suggested_bracket.get(sb, '')),
                'home_score': ks.home_score if ks else '',
                'away_score': ks.away_score if ks else '',
                'winner': saved_bracket.get(next_slot, '') if next_slot else '',
            })
        return out

    # En R32 los equipos ya vienen del bracket sugerido; el usuario sólo predice marcador.
    # En R16 en adelante, el usuario puede ESCRIBIR qué equipo cree que va a estar
    # en cada slot.
    rounds_data = [
        ('R32 — Dieciseisavos', ROUND_R32, build_round(ROUND_R32), True),
        ('R16 — Octavos', ROUND_R16, build_round(ROUND_R16), False),
        ('Cuartos', ROUND_QF, build_round(ROUND_QF), False),
        ('Semifinales', ROUND_SF, build_round(ROUND_SF), False),
        ('Tercer puesto', ROUND_3RD, build_round(ROUND_3RD), False),
        ('Final', ROUND_FINAL, build_round(ROUND_FINAL), False),
    ]

    final_positions = []
    for slot, label in [(SLOT_CHAMPION, 'Campeón'),
                        (SLOT_RUNNER_UP, 'Subcampeón'),
                        (SLOT_THIRD, '3er puesto'),
                        (SLOT_FOURTH, '4to puesto')]:
        final_positions.append({
            'slot': slot, 'label': label,
            'team': saved_bracket.get(slot, ''),
            'editable': slot in (SLOT_CHAMPION, SLOT_RUNNER_UP),
        })

    return render(request, 'inicio/predict_bracket.html', {
        'participant': participant,
        'rounds_data': rounds_data,
        'final_positions': final_positions,
    })


# ============================================================
# Predicciones de premios
# ============================================================
def predict_awards(request, participant_id):
    participant = get_object_or_404(Participant, id=participant_id)

    if request.method == 'POST':
        for award_key, _label in AWARD_CHOICES:
            value = (request.POST.get(award_key) or '').strip()
            if value:
                AwardPrediction.objects.update_or_create(
                    participant=participant, award=award_key,
                    defaults={'player_name': value},
                )
            else:
                AwardPrediction.objects.filter(
                    participant=participant, award=award_key).delete()
        messages.success(request, 'Premios guardados.')
        return redirect('inicio:predict_awards', participant_id=participant.id)

    saved = {a.award: a.player_name for a in
             AwardPrediction.objects.filter(participant=participant)}
    awards = [{
        'key': k, 'label': lbl, 'points': AWARD_POINTS[k],
        'value': saved.get(k, ''),
    } for k, lbl in AWARD_CHOICES]

    return render(request, 'inicio/predict_awards.html', {
        'participant': participant,
        'awards': awards,
    })


# ============================================================
# Leaderboard del grupo de apuestas
# ============================================================
def leaderboard(request, bg_id):
    bg = get_object_or_404(BettingGroup, id=bg_id)
    rows = betting_group_leaderboard(bg)
    return render(request, 'inicio/leaderboard.html', {
        'bg': bg, 'rows': rows,
    })


def participant_detail(request, bg_id, participant_id):
    bg = get_object_or_404(BettingGroup, id=bg_id)
    participant = get_object_or_404(Participant, id=participant_id, betting_group=bg)
    breakdown = participant_points_breakdown(participant)
    return render(request, 'inicio/participant_detail.html', {
        'bg': bg, 'participant': participant, 'breakdown': breakdown,
    })


# ============================================================
# Sincronizar API a mano
# ============================================================
@require_POST
def sync_now(request):
    try:
        created, updated = sync_matches_to_db()
        messages.success(request,
            f'Sincronizado: {created} creados, {updated} actualizados.')
    except Exception as e:
        messages.error(request, f'Error sincronizando: {e}')
    return redirect(request.POST.get('next') or 'inicio:home')
