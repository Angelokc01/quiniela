"""
python manage.py sync_matches
Trae todos los partidos desde wc2026api y los guarda/actualiza en la BD local.
Después recalcula los puntajes de todos los participantes.
"""
from django.core.management.base import BaseCommand

from inicio.wc_api import sync_matches_to_db
from inicio.scoring import recalculate_all_scores


class Command(BaseCommand):
    help = 'Sincroniza partidos desde wc2026api y recalcula puntajes.'

    def add_arguments(self, parser):
        parser.add_argument('--no-recalc', action='store_true',
                            help='No recalcular puntajes después del sync.')

    def handle(self, *args, **opts):
        self.stdout.write('Sincronizando partidos desde wc2026api…')
        created, updated = sync_matches_to_db()
        self.stdout.write(self.style.SUCCESS(
            f'  Creados: {created} · Actualizados: {updated}'
        ))

        if not opts['no_recalc']:
            self.stdout.write('Recalculando puntajes…')
            recalculate_all_scores()
            self.stdout.write(self.style.SUCCESS('  Listo.'))
