"""
Vistas de la quiniela. Sin autenticación. Las "sesiones" son simplemente
escoger en pantalla qué grupo y qué participante quieres usar.
"""
from collections import defaultdict
import os

from django.contrib import messages
from django.db.models import Count
from django.http import HttpResponse, HttpResponseRedirect
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
    bracket_from_standings, round_matches, real_r32_slots,
)
from .scoring import (
    participant_points_breakdown, betting_group_leaderboard,
    group_stage_complete, _points_group_match,
)
from .pdf_reports import build_participant_predictions_pdf
from .wc_api import sync_matches_to_db


ADMIN_SESSION_KEY = 'is_app_admin'


def is_app_admin(request):
    return bool(request.session.get(ADMIN_SESSION_KEY, False))


def _ensure_admin_or_redirect(request, fallback='inicio:home'):
    if is_app_admin(request):
        return None
    messages.error(request, 'Acción solo permitida para administrador.')
    return redirect(fallback)


def ensure_group_matches_synced(request=None):
    """
    Carga partidos desde la API solo si todavía no existe la fase de grupos.
    Se usa para evitar que el usuario tenga que pulsar el botón de sincronizar.
    """
    if Match.objects.filter(round=ROUND_GROUP).exists():
        return False

    try:
        created, updated = sync_matches_to_db()
    except Exception as exc:
        if request is not None:
            messages.error(request, f'No se pudieron sincronizar los partidos: {exc}')
        return False

    if request is not None:
        messages.success(
            request,
            f'Partidos sincronizados automáticamente: {created} creados, {updated} actualizados.'
        )
    return True


# ============================================================
# Home: ver grupos existentes
# ============================================================
def home(request):
    groups = BettingGroup.objects.all()
    return render(request, 'inicio/home.html', {
        'groups': groups,
        'is_app_admin': is_app_admin(request),
    })


@require_http_methods(['GET', 'POST'])
def admin_login(request):
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''

        allowed_username = os.getenv('ADMIN_PANEL_USERNAME', 'Alysaliu')
        allowed_password = os.getenv('ADMIN_PANEL_PASSWORD', 'Penyapenya5422')

        if username == allowed_username and password == allowed_password:
            request.session[ADMIN_SESSION_KEY] = True
            messages.success(request, 'Sesión de administrador iniciada.')
            return redirect(request.POST.get('next') or 'inicio:home')

        messages.error(request, 'Credenciales de administrador inválidas.')

    return render(request, 'inicio/admin_login.html', {
        'next': request.GET.get('next') or request.POST.get('next') or reverse('inicio:home'),
    })


@require_POST
def admin_logout(request):
    request.session.pop(ADMIN_SESSION_KEY, None)
    messages.info(request, 'Sesión de administrador cerrada.')
    return redirect(request.POST.get('next') or 'inicio:home')


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
    admin_mode = is_app_admin(request)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add':
            name = (request.POST.get('name') or '').strip()
            if name:
                Participant.objects.get_or_create(betting_group=bg, name=name)
            return redirect('inicio:manage_participants', bg_id=bg.id)
        if action == 'delete':
            if not admin_mode:
                messages.error(request, 'Solo el administrador puede eliminar participantes.')
                return redirect('inicio:manage_participants', bg_id=bg.id)
            pid = request.POST.get('participant_id')
            if pid:
                Participant.objects.filter(id=pid, betting_group=bg).delete()
            return redirect('inicio:manage_participants', bg_id=bg.id)
        if action == 'toggle_lock':
            if not admin_mode:
                messages.error(request, 'Solo el administrador puede bloquear predicciones.')
                return redirect('inicio:manage_participants', bg_id=bg.id)
            pid = request.POST.get('participant_id')
            participant = Participant.objects.filter(id=pid, betting_group=bg).first()
            if participant:
                participant.predictions_locked = not participant.predictions_locked
                participant.save(update_fields=['predictions_locked'])
                state = 'bloqueadas' if participant.predictions_locked else 'desbloqueadas'
                messages.success(request, f'Predicciones de {participant.name} {state}.')
            return redirect('inicio:manage_participants', bg_id=bg.id)

    return render(request, 'inicio/manage_participants.html', {
        'bg': bg,
        'participants': bg.participants.all(),
        'is_app_admin': admin_mode,
    })


@require_POST
def delete_group(request, bg_id):
    denied = _ensure_admin_or_redirect(request)
    if denied is not None:
        return denied

    bg = get_object_or_404(BettingGroup, id=bg_id)
    group_name = bg.name
    bg.delete()
    messages.success(request, f'Grupo "{group_name}" eliminado junto con sus participantes.')
    return redirect('inicio:home')


# ============================================================
# Elegir participante para empezar a predecir / ver puntajes
# ============================================================
def choose_participant(request):
    ensure_group_matches_synced(request)
    groups = BettingGroup.objects.prefetch_related('participants').all()
    return render(request, 'inicio/choose_participant.html', {
        'groups': groups,
    })


# ============================================================
# Dashboard del participante: links a cada subsección
# ============================================================
def predictions_dashboard(request, participant_id):
    participant = get_object_or_404(Participant, id=participant_id)
    ensure_group_matches_synced(request)

    n_matches_group = Match.objects.filter(round=ROUND_GROUP).count()
    n_preds_group = GroupMatchPrediction.objects.filter(participant=participant).count()

    standings_done = GroupStandingPrediction.objects.filter(
        participant=participant).count()

    # El bracket se habilita cuando la fase de grupos termina en el torneo.
    group_done = group_stage_complete()
    group_predictions_done = (n_preds_group >= n_matches_group and n_matches_group > 0)

    bracket_count = BracketPrediction.objects.filter(participant=participant).count()
    awards_count = AwardPrediction.objects.filter(participant=participant).count()

    breakdown = participant_points_breakdown(participant)

    return render(request, 'inicio/predictions_dashboard.html', {
        'participant': participant,
        'n_matches_group': n_matches_group,
        'n_preds_group': n_preds_group,
        'group_done': group_done,
        'group_predictions_done': group_predictions_done,
        'standings_done': standings_done,
        'bracket_count': bracket_count,
        'awards_count': awards_count,
        'breakdown': breakdown,
        'is_app_admin': is_app_admin(request),
    })


def download_predictions_pdf(request, participant_id, mode):
    participant = get_object_or_404(Participant, id=participant_id)
    ensure_group_matches_synced(request)

    if mode not in {'blank', 'complete'}:
        messages.error(request, 'Modo de PDF inválido.')
        return redirect('inicio:predictions_dashboard', participant_id=participant.id)

    pdf_bytes = build_participant_predictions_pdf(participant, blank=(mode == 'blank'))
    safe_name = participant.name.strip().replace(' ', '_') or 'participante'
    filename = f'quiniela_{safe_name}_{mode}.pdf'

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ============================================================
# Predicciones fase de grupos
# ============================================================
def predict_group_stage(request, participant_id):
    participant = get_object_or_404(Participant, id=participant_id)
    ensure_group_matches_synced(request)
    submitted_positions = {}
    admin_mode = is_app_admin(request)

    if request.method == 'POST' and participant.predictions_locked and not admin_mode:
        messages.error(request, 'Las predicciones de este participante están bloqueadas por el administrador.')
        return redirect('inicio:predict_group_stage', participant_id=participant.id)

    if request.method == 'POST':
        pending_group_preds = []
        pending_standing_preds = []

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
            # No permitir editar si el partido ya empezó (admin puede sobrepasar esto)
            if match.kickoff_in_past and not admin_mode:
                continue
            pending_group_preds.append((match, hs, as_))

        # Guardamos primero los marcadores válidos para no perderlos si
        # luego falla la validación de posiciones del grupo.
        for match, hs, as_ in pending_group_preds:
            GroupMatchPrediction.objects.update_or_create(
                participant=participant, match=match,
                defaults={'home_score': hs, 'away_score': as_},
            )

        # También guardar predicciones de POSICIÓN del grupo si las enviaron
        positions_by_group = defaultdict(list)
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
            positions_by_group[group_name].append((team, pos))
            pending_standing_preds.append((group_name, team, pos))
            submitted_positions[(group_name, team)] = pos

        invalid_groups = []
        for group_name, items in positions_by_group.items():
            positions = [pos for _team, pos in items]
            expected = {1, 2, 3, 4}
            if len(items) != 4 or set(positions) != expected:
                invalid_groups.append(group_name)
                continue
            if len(set(positions)) != 4:
                invalid_groups.append(group_name)

        if invalid_groups:
            messages.error(
                request,
                'Cada grupo debe tener 4 equipos con posiciones únicas del 1 al 4. '
                f'Revisa: {", ".join(sorted(set(invalid_groups)))}.'
            )
        else:
            for group_name, team, pos in pending_standing_preds:
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
            'locked': m.kickoff_in_past and not admin_mode,
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
                'user_pos': submitted_positions.get((g, row['team']), existing_pos.get((g, row['team']), idx)),
                'stats': row,
            })

    return render(request, 'inicio/predict_group_stage.html', {
        'participant': participant,
        'grouped': dict(sorted(grouped.items())),
        'standings_table': dict(sorted(standings_table.items())),
        'is_app_admin': admin_mode,
    })


# ============================================================
# Predicciones del bracket eliminatorio
# ============================================================
def predict_bracket(request, participant_id):
    participant = get_object_or_404(Participant, id=participant_id)
    admin_mode = is_app_admin(request)

    if request.method == 'POST' and participant.predictions_locked and not admin_mode:
        messages.error(request, 'Las predicciones de este participante están bloqueadas por el administrador.')
        return redirect('inicio:predict_bracket', participant_id=participant.id)

    # Los dieciseisavos salen de los partidos REALES de la API (round_of_32):
    # esa es la base oficial e igual para todos. Si la API aún no tiene los
    # cruces de eliminatoria, se usa un cálculo provisional desde las posiciones
    # de grupo para no dejar la pantalla vacía.
    suggested_bracket = real_r32_slots()
    if not suggested_bracket:
        suggested_bracket = bracket_from_standings(actual_group_standings())

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

    # Definición de rondas: (round, etiqueta, prefijo de la siguiente ronda,
    #                         etiqueta corta de la siguiente ronda)
    round_defs = [
        (ROUND_R32, 'Dieciseisavos de final', 'R16', 'Octavos'),
        (ROUND_R16, 'Octavos de final', 'QF', 'Cuartos'),
        (ROUND_QF, 'Cuartos de final', 'SF', 'Semifinales'),
        (ROUND_SF, 'Semifinales', 'FINAL', 'la Final'),
        (ROUND_3RD, 'Tercer y cuarto puesto', None, None),
        (ROUND_FINAL, 'Final', None, None),
    ]

    def win_lose_slots(round_name, match_no, next_prefix):
        """Devuelve (slot_ganador, slot_perdedor) destino para un partido."""
        if round_name == ROUND_FINAL:
            return SLOT_CHAMPION, SLOT_RUNNER_UP
        if round_name == ROUND_3RD:
            return SLOT_THIRD, SLOT_FOURTH
        if round_name == ROUND_SF:
            return f'FINAL_{match_no}', f'THIRD_{match_no}'
        return f'{next_prefix}_{match_no}', ''

    rounds = []
    for round_name, label, next_prefix, next_label in round_defs:
        is_r32 = round_name == ROUND_R32
        matches = []
        for match_no, (st, sb) in enumerate(round_matches(round_name), start=1):
            ks = saved_scores.get((st, sb))
            win_slot, lose_slot = win_lose_slots(round_name, match_no, next_prefix)
            if is_r32:
                # Base oficial de la API: no se sobreescribe con valores viejos.
                team_top = suggested_bracket.get(st, '')
                team_bottom = suggested_bracket.get(sb, '')
            else:
                # Rondas siguientes: el JS las recalcula desde los ganadores.
                team_top = saved_bracket.get(st, '')
                team_bottom = saved_bracket.get(sb, '')
            matches.append({
                'no': match_no,
                'slot_top': st,
                'slot_bottom': sb,
                'team_top': team_top,
                'team_bottom': team_bottom,
                'home_score': ks.home_score if ks is not None else '',
                'away_score': ks.away_score if ks is not None else '',
                'winner': saved_bracket.get(win_slot, ''),
                'win_slot': win_slot,
                'lose_slot': lose_slot,
            })
        rounds.append({
            'key': round_name,
            'label': label,
            'next_label': next_label,
            'is_r32': is_r32,
            'matches': matches,
        })

    podium = [
        {'slot': SLOT_CHAMPION, 'label': 'Campeón', 'rank': '1°',
         'team': saved_bracket.get(SLOT_CHAMPION, '')},
        {'slot': SLOT_RUNNER_UP, 'label': 'Subcampeón', 'rank': '2°',
         'team': saved_bracket.get(SLOT_RUNNER_UP, '')},
        {'slot': SLOT_THIRD, 'label': 'Tercer puesto', 'rank': '3°',
         'team': saved_bracket.get(SLOT_THIRD, '')},
        {'slot': SLOT_FOURTH, 'label': 'Cuarto puesto', 'rank': '4°',
         'team': saved_bracket.get(SLOT_FOURTH, '')},
    ]

    return render(request, 'inicio/predict_bracket.html', {
        'participant': participant,
        'rounds': rounds,
        'podium': podium,
        'locked': participant.predictions_locked and not admin_mode,
    })


# ============================================================
# Predicciones de premios
# ============================================================
def predict_awards(request, participant_id):
    participant = get_object_or_404(Participant, id=participant_id)

    if request.method == 'POST':
        if participant.predictions_locked and not is_app_admin(request):
            messages.error(request, 'Las predicciones de este participante están bloqueadas por el administrador.')
            return redirect('inicio:predict_awards', participant_id=participant.id)
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
# Próximos partidos y predicciones por partido
# ============================================================
def _selected_betting_group(request, groups):
    """Devuelve el grupo de apuestas elegido vía ?bg=, o el primero disponible."""
    bg_id = request.GET.get('bg')
    if bg_id:
        for g in groups:
            if str(g.id) == str(bg_id):
                return g
    return groups[0] if groups else None


def upcoming_matches(request):
    """Lista de próximos partidos de fase de grupos y resultados recientes.
    Cada partido enlaza a la lista de predicciones del grupo de apuestas elegido.
    """
    ensure_group_matches_synced(request)
    groups = list(BettingGroup.objects.prefetch_related('participants').all())
    selected_group = _selected_betting_group(request, groups)

    group_matches = Match.objects.filter(round=ROUND_GROUP)
    upcoming = list(
        group_matches.exclude(status=Match.STATUS_COMPLETED)
        .order_by('kickoff_utc', 'match_number')
    )
    recent = list(
        group_matches.filter(status=Match.STATUS_COMPLETED)
        .order_by('-kickoff_utc', '-match_number')[:12]
    )

    pred_counts = {}
    n_participants = 0
    if selected_group:
        n_participants = selected_group.participants.count()
        match_ids = [m.id for m in upcoming] + [m.id for m in recent]
        counts = (
            GroupMatchPrediction.objects
            .filter(participant__betting_group=selected_group, match_id__in=match_ids)
            .values('match_id')
            .annotate(n=Count('match_id'))
        )
        pred_counts = {row['match_id']: row['n'] for row in counts}

    def decorate(matches):
        return [{'match': m, 'n_preds': pred_counts.get(m.id, 0)} for m in matches]

    return render(request, 'inicio/upcoming_matches.html', {
        'groups': groups,
        'selected_group': selected_group,
        'upcoming': decorate(upcoming),
        'recent': decorate(recent),
        'n_participants': n_participants,
    })


def match_predictions(request, match_id):
    """Predicciones de todos los participantes de un grupo para un partido."""
    match = get_object_or_404(Match, id=match_id)
    groups = list(BettingGroup.objects.prefetch_related('participants').all())
    selected_group = _selected_betting_group(request, groups)

    rows = []
    n_with_pred = 0
    if selected_group:
        preds = {
            p.participant_id: p
            for p in GroupMatchPrediction.objects.filter(
                match=match, participant__betting_group=selected_group
            )
        }
        for participant in selected_group.participants.all():
            pred = preds.get(participant.id)
            points = None
            outcome = None
            if pred is not None:
                n_with_pred += 1
                if match.is_finished:
                    points = _points_group_match(pred, match)
                    outcome = 'exact' if points == 5 else ('result' if points == 2 else 'miss')
            rows.append({
                'participant': participant,
                'pred': pred,
                'points': points,
                'outcome': outcome,
            })

    return render(request, 'inicio/match_predictions.html', {
        'match': match,
        'groups': groups,
        'selected_group': selected_group,
        'rows': rows,
        'n_with_pred': n_with_pred,
        'is_group_match': match.round == ROUND_GROUP,
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
