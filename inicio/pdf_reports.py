from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from pypdf import PdfReader, PdfWriter

from .bracket import round_matches
from .models import (
    AWARD_CHOICES,
    AwardPrediction,
    BracketPrediction,
    GroupMatchPrediction,
    GroupStandingPrediction,
    Match,
    KnockoutScorePrediction,
    ROUND_3RD,
    ROUND_FINAL,
    ROUND_GROUP,
    ROUND_QF,
    ROUND_R16,
    ROUND_R32,
    ROUND_SF,
    SLOT_CHAMPION,
    SLOT_FOURTH,
    SLOT_RUNNER_UP,
    SLOT_THIRD,
)


def _p(text, style):
    return Paragraph(escape(str(text)), style)


def _table(data, col_widths=None, header_rows=1):
    table = Table(data, colWidths=col_widths, repeatRows=header_rows)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f2937')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('LEADING', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return table


def _next_slot_for_round(round_name, slot_top):
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


def _template_pdf_path() -> Path:
    return Path(settings.BASE_DIR) / 'static' / 'inicio' / 'docs' / 'Mundial2026_Predicciones.pdf'


def _template_pdf_bytes() -> bytes:
    return _template_pdf_path().read_bytes()


def _build_complete_predictions_pdf(participant):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=20,
        rightMargin=20,
        topMargin=18,
        bottomMargin=18,
        title=f'Quiniela - {participant.name}',
        author='Quiniela Mundial 2026',
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'PredTitle',
        parent=styles['Title'],
        fontName='Helvetica-Bold',
        fontSize=21,
        leading=24,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#0f172a'),
    )
    subtitle_style = ParagraphStyle(
        'PredSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=12,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#475569'),
    )
    section_style = ParagraphStyle(
        'PredSection',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=18,
        textColor=colors.HexColor('#111827'),
        spaceBefore=8,
        spaceAfter=6,
    )
    sub_style = ParagraphStyle(
        'PredSub',
        parent=styles['Heading3'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=13,
        textColor=colors.HexColor('#1f2937'),
        spaceBefore=6,
        spaceAfter=4,
    )
    cell_style = ParagraphStyle(
        'PredCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10,
    )

    group_matches = {}
    group_teams = {}
    for match in Match.objects.filter(round=ROUND_GROUP).order_by('group_name', 'kickoff_utc', 'match_number'):
        group_matches.setdefault(match.group_name, []).append(match)
        team_list = group_teams.setdefault(match.group_name, [])
        for team in (match.home_team, match.away_team):
            if team not in team_list:
                team_list.append(team)

    saved_group_scores = {pred.match_id: pred for pred in GroupMatchPrediction.objects.filter(participant=participant)}
    saved_positions = {
        (pred.group_name, pred.team): pred.position
        for pred in GroupStandingPrediction.objects.filter(participant=participant)
    }
    saved_bracket = {pred.slot: pred.team for pred in BracketPrediction.objects.filter(participant=participant)}
    saved_awards = {pred.award: pred.player_name for pred in AwardPrediction.objects.filter(participant=participant)}
    saved_knockout_scores = {
        (pred.slot_top, pred.slot_bottom): pred
        for pred in KnockoutScorePrediction.objects.filter(participant=participant)
    }

    story = []
    story.append(Paragraph('Quiniela Mundial 2026', title_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f'{participant.name} - {participant.betting_group.name}', subtitle_style))
    story.append(Paragraph('Resumen con mis predicciones', subtitle_style))
    story.append(Paragraph(f'Generado: {timezone.localtime().strftime("%d/%m/%Y %H:%M")}', subtitle_style))
    story.append(Spacer(1, 10))

    story.append(Paragraph('Fase de grupos', section_style))
    for group_name in sorted(group_matches.keys()):
        story.append(Paragraph(f'Grupo {group_name}', sub_style))
        match_rows = [[
            _p('#', cell_style),
            _p('Partido', cell_style),
            _p('Marcador', cell_style),
        ]]
        for match in group_matches[group_name]:
            pred = saved_group_scores.get(match.id)
            score = f'{pred.home_score}-{pred.away_score}' if pred is not None else ''
            kickoff = ''
            if match.kickoff_utc:
                kickoff = timezone.localtime(match.kickoff_utc).strftime('%d/%m %H:%M')
            match_label = f'{match.home_team} vs {match.away_team}'
            if kickoff:
                match_label = f'{match_label} ({kickoff})'
            match_rows.append([
                _p(match.match_number, cell_style),
                _p(match_label, cell_style),
                _p(score, cell_style),
            ])

        story.append(_table(match_rows, [28, 420, 90]))
        story.append(Spacer(1, 6))

        standings_rows = [[
            _p('Equipo', cell_style),
            _p('Posición', cell_style),
        ]]
        for team in group_teams.get(group_name, []):
            position = saved_positions.get((group_name, team), '')
            standings_rows.append([
                _p(team, cell_style),
                _p(position, cell_style),
            ])
        story.append(_table(standings_rows, [360, 120]))
        story.append(Spacer(1, 10))

    story.append(PageBreak())
    story.append(Paragraph('Premios individuales', section_style))
    awards_rows = [[
        _p('Premio', cell_style),
        _p('Jugador', cell_style),
    ]]
    for award_key, label in AWARD_CHOICES:
        awards_rows.append([
            _p(label, cell_style),
            _p(saved_awards.get(award_key, ''), cell_style),
        ])
    story.append(_table(awards_rows, [320, 360]))

    doc.build(story)
    return buffer.getvalue()


def build_participant_predictions_pdf(participant, blank=False):
    """Genera el PDF pedido usando la plantilla compartida como base."""
    template_bytes = _template_pdf_bytes()
    if blank:
        return template_bytes

    return _build_complete_predictions_pdf(participant)