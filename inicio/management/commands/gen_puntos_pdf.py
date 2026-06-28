# -*- coding: utf-8 -*-
"""
python manage.py gen_puntos_pdf

Regenera el PDF estático del sistema de puntos
(static/inicio/docs/sistema_puntos_quiniela.pdf) a partir de la tabla de puntos.
Si cambias los puntos, corre este comando para actualizar el PDF descargable.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether,
)

GREEN      = colors.HexColor('#15543a')
GREEN2     = colors.HexColor('#1f6b4c')
GREEN_HEAD = colors.HexColor('#2f7d5a')
GOLD       = colors.HexColor('#8a6d1f')
GOLD_HEAD  = colors.HexColor('#a8851f')
ZEBRA      = colors.HexColor('#f1f5f2')
ZEBRA_GOLD = colors.HexColor('#faf6e9')
INK        = colors.HexColor('#1f2937')
MUTED      = colors.HexColor('#475569')
LINE       = colors.HexColor('#cbd5e1')

MARGIN = 42
FULL = A4[0] - 2 * MARGIN

hwhite = ParagraphStyle('hwhite', fontName='Helvetica-Bold', fontSize=9,
                        textColor=colors.white, leading=11)
cell = ParagraphStyle('cell', fontName='Helvetica', fontSize=9, textColor=INK, leading=11)
cell_sm = ParagraphStyle('cellsm', fontName='Helvetica', fontSize=8.3, textColor=MUTED, leading=10)
pts_green = ParagraphStyle('ptsg', fontName='Helvetica-Bold', fontSize=10, textColor=GREEN2, leading=12)
pts_gold = ParagraphStyle('ptsgo', fontName='Helvetica-Bold', fontSize=10, textColor=GOLD, leading=12)
title_white = ParagraphStyle('tw', fontName='Helvetica-Bold', fontSize=11,
                             textColor=colors.white, alignment=TA_CENTER, leading=14)


def _banner():
    tstyle = ParagraphStyle('bt', fontName='Helvetica-Bold', fontSize=20,
                            textColor=colors.white, alignment=TA_CENTER, leading=24)
    sstyle = ParagraphStyle('bs', fontName='Helvetica', fontSize=10.5,
                            textColor=colors.HexColor('#d8efe4'), alignment=TA_CENTER, leading=14)
    t = Table([[Paragraph('SISTEMA DE PUNTOS — QUINIELA', tstyle)],
               [Paragraph('Fase de Grupos · Eliminatorias · Posición Final · Premios', sstyle)]],
              colWidths=[FULL])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), GREEN),
        ('TOPPADDING', (0, 0), (-1, 0), 16), ('BOTTOMPADDING', (0, 0), (-1, 0), 3),
        ('TOPPADDING', (0, 1), (-1, 1), 0), ('BOTTOMPADDING', (0, 1), (-1, 1), 15),
        ('LEFTPADDING', (0, 0), (-1, -1), 12), ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    return t


def _section_header(num, title, color):
    st = ParagraphStyle('sh', fontName='Helvetica-Bold', fontSize=13,
                        textColor=colors.white, leading=16)
    t = Table([[Paragraph('%s&nbsp;&nbsp;&nbsp;%s' % (num, title), st)]], colWidths=[FULL])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), color),
        ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 12), ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    return t


def _crit_table(rows, header_color, zebra, pts_style):
    w = [FULL * 0.50, FULL * 0.16, FULL * 0.34]
    data = [[Paragraph('Criterio', hwhite), Paragraph('Puntos', hwhite), Paragraph('Descripción', hwhite)]]
    for c, p, d in rows:
        data.append([Paragraph(c, cell), Paragraph(p, pts_style), Paragraph(d, cell_sm)])
    t = Table(data, colWidths=w, repeatRows=1)
    style = [
        ('BACKGROUND', (0, 0), (-1, 0), header_color),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('BOX', (0, 0), (-1, -1), 0.5, LINE),
        ('LINEBELOW', (0, 0), (-1, -2), 0.4, LINE),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(('BACKGROUND', (0, i), (-1, i), zebra))
    t.setStyle(TableStyle(style))
    return t


def _note_box(text):
    ns = ParagraphStyle('note', fontName='Helvetica', fontSize=8.6, textColor=INK, leading=11)
    t = Table([[Paragraph(text, ns)]], colWidths=[FULL])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#eef6f1')),
        ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#bcd9c9')),
        ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    return t


def _resumen():
    w = [FULL * 0.30, FULL * 0.26, FULL * 0.44]
    data = [
        [Paragraph('RESUMEN RÁPIDO DE PUNTOS', title_white), '', ''],
        [Paragraph('Sección', hwhite), Paragraph('Máximo posible', hwhite), Paragraph('Detalles clave', hwhite)],
        [Paragraph('Fase de Grupos', cell), Paragraph('5 pts / partido', cell_sm),
         Paragraph('Marcador exacto = 5 | 1X2 = 2 | Posición = 2', cell_sm)],
        [Paragraph('Equipo avanza (Elim.)', cell), Paragraph('Hasta 15 pts', cell_sm),
         Paragraph('R16=5 | QF=8 | SF=12 | Finalistas=15', cell_sm)],
        [Paragraph('Marcador exacto (Elim.)', cell), Paragraph('8 pts (Final)', cell_sm),
         Paragraph('R32=4 | R16=5 | QF=6 | SF=7 | 3°=4 | Final=8', cell_sm)],
        [Paragraph('Posición final', cell), Paragraph('30 pts (Campeón)', cell_sm),
         Paragraph('1°=30 | 2°=15 | 3°=5 | 4°=2', cell_sm)],
        [Paragraph('Premios individuales', cell), Paragraph('10 pts c/u', cell_sm),
         Paragraph('Bota / Balón / Guante = 10 | Joven / Gol = 5', cell_sm)],
    ]
    t = Table(data, colWidths=w, repeatRows=2)
    style = [
        ('SPAN', (0, 0), (-1, 0)),
        ('BACKGROUND', (0, 0), (-1, 0), GREEN),
        ('BACKGROUND', (0, 1), (-1, 1), GREEN_HEAD),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('BOX', (0, 0), (-1, -1), 0.5, LINE),
        ('LINEBELOW', (0, 1), (-1, -2), 0.4, LINE),
    ]
    for i in range(2, len(data)):
        if i % 2 == 1:
            style.append(('BACKGROUND', (0, i), (-1, i), ZEBRA))
    t.setStyle(TableStyle(style))
    return t


def build_story():
    story = [_banner(), Spacer(1, 16)]

    story.append(KeepTogether([
        _section_header('1', 'Fase de Grupos', GREEN2), Spacer(1, 8),
        _crit_table([
            ('Marcador exacto', '5 pts', 'Ej: predices 2-1 y termina 2-1'),
            ('Resultado correcto (1X2)', '2 pts', 'Aciertas si gana local, hay empate o gana visitante'),
            ('Posición exacta del equipo en el grupo', '2 pts', 'Aciertas la posición final dentro del grupo (1°, 2°, 3°, 4°)'),
        ], GREEN_HEAD, ZEBRA, pts_green),
    ]))
    story.append(Spacer(1, 16))

    story.append(KeepTogether([
        _section_header('2', 'Eliminatorias — Equipo que Avanza', GREEN2), Spacer(1, 8),
        _crit_table([
            ('Octavos de Final (R16)', '5 pts', 'Por cada equipo acertado que avanza a esta ronda'),
            ('Cuartos de Final (QF)', '8 pts', 'Por cada equipo acertado que avanza a esta ronda'),
            ('Semifinales (SF)', '12 pts', 'Por cada equipo acertado que avanza a esta ronda'),
            ('Finalistas', '15 pts', 'Por cada finalista acertado (campeón o subcampeón)'),
        ], GREEN_HEAD, ZEBRA, pts_green),
    ]))
    story.append(Spacer(1, 16))

    story.append(KeepTogether([
        _section_header('3', 'Resultado Exacto en Eliminatorias', GREEN2), Spacer(1, 8),
        _crit_table([
            ('Ronda de 32 (R32)', '4 pts', 'Acierta el marcador exacto del partido'),
            ('Octavos de Final (R16)', '5 pts', 'Acierta el marcador exacto del partido'),
            ('Cuartos de Final (QF)', '6 pts', 'Acierta el marcador exacto del partido'),
            ('Semifinales (SF)', '7 pts', 'Acierta el marcador exacto del partido'),
            ('Tercer puesto', '4 pts', 'Acierta el marcador exacto del partido'),
            ('Final', '8 pts', 'Acierta el marcador exacto del partido'),
        ], GREEN_HEAD, ZEBRA, pts_green),
    ]))
    story.append(Spacer(1, 8))
    story.append(_note_box(
        '<b>Nota:</b> el orden del marcador importa (3-1 no es lo mismo que 1-3), '
        'pero <b>no importa qué equipos hayan llegado a ese cruce</b>: se compara tu '
        'marcador con el resultado real del partido en esa posición de la llave. '
        'En partidos con prórroga se evalúa el resultado a los 120’ (los penaltis no cuentan).'))
    story.append(Spacer(1, 16))

    story.append(KeepTogether([
        _section_header('4', 'Posición Final del Torneo', GOLD), Spacer(1, 8),
        _crit_table([
            ('Campeón', '30 pts', 'El equipo que levanta el trofeo'),
            ('Subcampeón', '15 pts', 'El finalista perdedor'),
            ('Tercer puesto', '5 pts', 'Ganador del partido por el 3er lugar'),
            ('Cuarto puesto', '2 pts', 'Perdedor del partido por el 3er lugar'),
        ], GOLD_HEAD, ZEBRA_GOLD, pts_gold),
    ]))
    story.append(Spacer(1, 16))

    story.append(KeepTogether([
        _section_header('5', 'Premios Individuales', GREEN2), Spacer(1, 8),
        _crit_table([
            ('Bota de Oro', '10 pts', 'Máximo goleador del torneo'),
            ('Balón de Oro', '10 pts', 'Mejor jugador del torneo'),
            ('Guante de Oro', '10 pts', 'Mejor portero del torneo'),
            ('Mejor Jugador Joven', '5 pts', 'Mejor jugador joven del torneo'),
            ('Mejor Gol del Mundial', '5 pts', 'Lo define el administrador'),
        ], GREEN_HEAD, ZEBRA, pts_green),
    ]))
    story.append(Spacer(1, 18))

    story.append(_resumen())
    story.append(Spacer(1, 14))

    footer = ParagraphStyle('foot', fontName='Helvetica-Oblique', fontSize=8.5,
                            textColor=MUTED, alignment=TA_CENTER, leading=11)
    story.append(Paragraph(
        'Sistema de puntos diseñado para equilibrar la quiniela durante todo el torneo · '
        'Fases eliminatorias evaluadas a 120 minutos', footer))
    return story


class Command(BaseCommand):
    help = 'Regenera el PDF estático del sistema de puntos.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output', default=None,
            help='Ruta de salida del PDF (por defecto, el PDF estático descargable).')

    def handle(self, *args, **opts):
        out = opts['output'] or str(
            Path(settings.BASE_DIR) / 'static' / 'inicio' / 'docs' / 'sistema_puntos_quiniela.pdf')
        doc = SimpleDocTemplate(
            out, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=30, bottomMargin=30,
            title='Sistema de puntos — Quiniela Mundial 2026',
            author='Quiniela Mundial 2026')
        doc.build(build_story())
        self.stdout.write(self.style.SUCCESS('PDF del sistema de puntos generado en: %s' % out))
