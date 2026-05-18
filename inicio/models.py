"""
Modelos para la Quiniela Mundial 2026.

Notas clave de diseño:
- Un "Grupo" en esta app es el grupo de personas (familia/amigos) que apuestan.
- El "grupo del mundial" (A..L) se guarda como string en Match.group_name.
- Match es un espejo local de la API wc2026api. Lo sincronizamos con un management
  command para no depender de la red en cada request.
- Las predicciones eliminatorias se guardan en dos modelos:
    * BracketPrediction: qué equipo va en cada slot (R16_1, R16_2, ..., FINAL_WINNER...).
    * KnockoutScorePrediction: el marcador del partido en ese slot (4/5/6/7/8 pts).
"""
from django.db import models
from django.utils import timezone


# ------------------------------------------------------------
# Constantes de rondas / slots de la llave
# ------------------------------------------------------------
ROUND_GROUP = 'group'
ROUND_R32 = 'round_of_32'  # dieciseisavos
ROUND_R16 = 'round_of_16'  # octavos
ROUND_QF = 'quarter_final'
ROUND_SF = 'semi_final'
ROUND_3RD = 'third_place'
ROUND_FINAL = 'final'

ROUND_CHOICES = [
    (ROUND_GROUP, 'Fase de grupos'),
    (ROUND_R32, 'Dieciseisavos'),
    (ROUND_R16, 'Octavos'),
    (ROUND_QF, 'Cuartos'),
    (ROUND_SF, 'Semifinal'),
    (ROUND_3RD, 'Tercer puesto'),
    (ROUND_FINAL, 'Final'),
]

# Slots de la llave eliminatoria. Cada slot es una "posición" en el bracket
# donde un equipo aterriza. Los slots de R32 son 32, de R16 son 16, etc.
# Esto nos permite saber si el participante puso el equipo correcto en la
# llave correcta (mismo slot) o sólo en la ronda correcta (otro slot).
BRACKET_SLOTS = {
    ROUND_R32: [f'R32_{i}' for i in range(1, 33)],
    ROUND_R16: [f'R16_{i}' for i in range(1, 17)],
    ROUND_QF:  [f'QF_{i}'  for i in range(1, 9)],
    ROUND_SF:  [f'SF_{i}'  for i in range(1, 5)],
    ROUND_3RD: ['THIRD_1', 'THIRD_2'],
    ROUND_FINAL: ['FINAL_1', 'FINAL_2'],
}

# Slots especiales para ganadores finales
SLOT_CHAMPION = 'CHAMPION'
SLOT_RUNNER_UP = 'RUNNER_UP'
SLOT_THIRD = 'THIRD_PLACE'
SLOT_FOURTH = 'FOURTH_PLACE'


# ------------------------------------------------------------
# Grupos de apuestas (familia / amigos) y participantes
# ------------------------------------------------------------
class BettingGroup(models.Model):
    name = models.CharField(max_length=120, unique=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class Participant(models.Model):
    betting_group = models.ForeignKey(
        BettingGroup, on_delete=models.CASCADE, related_name='participants'
    )
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['name']
        unique_together = [('betting_group', 'name')]

    def __str__(self):
        return f'{self.name} - {self.betting_group.name}'


# ------------------------------------------------------------
# Espejo local de la API
# ------------------------------------------------------------
class Match(models.Model):
    """
    Espejo de un partido devuelto por wc2026api.com.
    Lo poblamos con `python manage.py sync_matches`.
    """
    STATUS_SCHEDULED = 'scheduled'
    STATUS_LIVE = 'live'
    STATUS_COMPLETED = 'completed'
    STATUS_CHOICES = [
        (STATUS_SCHEDULED, 'Programado'),
        (STATUS_LIVE, 'En vivo'),
        (STATUS_COMPLETED, 'Finalizado'),
    ]

    # id de la API (no PK por seguridad, pero único)
    api_id = models.IntegerField(unique=True)
    match_number = models.IntegerField()
    round = models.CharField(max_length=20, choices=ROUND_CHOICES)
    group_name = models.CharField(max_length=2, blank=True, default='')
    home_team = models.CharField(max_length=80)
    away_team = models.CharField(max_length=80)
    stadium = models.CharField(max_length=200, blank=True, default='')
    kickoff_utc = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_SCHEDULED)
    home_score = models.IntegerField(null=True, blank=True)
    away_score = models.IntegerField(null=True, blank=True)

    last_synced = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['match_number']

    def __str__(self):
        return f'#{self.match_number} {self.home_team} vs {self.away_team}'

    @property
    def is_finished(self):
        return self.status == self.STATUS_COMPLETED and \
               self.home_score is not None and self.away_score is not None

    @property
    def kickoff_in_past(self):
        return self.kickoff_utc and self.kickoff_utc <= timezone.now()

    @property
    def winner(self):
        if not self.is_finished:
            return None
        if self.home_score > self.away_score:
            return self.home_team
        if self.away_score > self.home_score:
            return self.away_team
        return 'DRAW'


# ------------------------------------------------------------
# Predicciones
# ------------------------------------------------------------
class GroupMatchPrediction(models.Model):
    """Predicción de marcador para un partido de fase de grupos."""
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE,
                                    related_name='group_predictions')
    match = models.ForeignKey(Match, on_delete=models.CASCADE,
                              related_name='group_predictions')
    home_score = models.IntegerField()
    away_score = models.IntegerField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('participant', 'match')]

    def __str__(self):
        return f'{self.participant.name}: {self.match} → {self.home_score}-{self.away_score}'


class GroupStandingPrediction(models.Model):
    """
    Predicción de la posición de un equipo dentro de su grupo del mundial.
    Ej: el participante dice "Brasil queda 1ro del grupo B".
    """
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE,
                                    related_name='standing_predictions')
    group_name = models.CharField(max_length=2)  # A..L
    team = models.CharField(max_length=80)
    position = models.IntegerField()  # 1..4

    class Meta:
        unique_together = [('participant', 'group_name', 'team')]
        ordering = ['group_name', 'position']

    def __str__(self):
        return f'{self.participant.name}: {self.team} en posición {self.position} del {self.group_name}'


class BracketPrediction(models.Model):
    """
    Predicción de qué equipo va en cada slot del bracket eliminatorio.
    También usamos slots especiales: CHAMPION, RUNNER_UP, THIRD_PLACE, FOURTH_PLACE.
    """
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE,
                                    related_name='bracket_predictions')
    slot = models.CharField(max_length=20)  # ej: 'R32_1', 'R16_3', 'CHAMPION'
    team = models.CharField(max_length=80)

    class Meta:
        unique_together = [('participant', 'slot')]
        ordering = ['slot']

    def __str__(self):
        return f'{self.participant.name}: {self.slot}={self.team}'


class KnockoutScorePrediction(models.Model):
    """
    Predicción del marcador exacto de un partido de la fase eliminatoria.
    Va atada a un slot de partido (par de slots) más una ronda, no al Match real,
    porque queremos calificar por "orden del marcador" aún si los equipos no coinciden.

    home_score / away_score se interpretan en el orden:
       'top' slot (slot_top) — 'bottom' slot (slot_bottom)
    """
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE,
                                    related_name='knockout_scores')
    round = models.CharField(max_length=20, choices=ROUND_CHOICES)
    slot_top = models.CharField(max_length=20)     # ej: R32_1
    slot_bottom = models.CharField(max_length=20)  # ej: R32_2
    home_score = models.IntegerField()
    away_score = models.IntegerField()

    class Meta:
        unique_together = [('participant', 'slot_top', 'slot_bottom')]

    def __str__(self):
        return (f'{self.participant.name}: {self.slot_top} vs {self.slot_bottom} '
                f'→ {self.home_score}-{self.away_score}')


# ------------------------------------------------------------
# Premios (Bota, Balón, Guante, Joven, Mejor Gol)
# ------------------------------------------------------------
AWARD_GOLDEN_BOOT = 'golden_boot'
AWARD_GOLDEN_BALL = 'golden_ball'
AWARD_GOLDEN_GLOVE = 'golden_glove'
AWARD_YOUNG_PLAYER = 'young_player'
AWARD_BEST_GOAL = 'best_goal'

AWARD_CHOICES = [
    (AWARD_GOLDEN_BOOT, 'Bota de Oro (10 pts)'),
    (AWARD_GOLDEN_BALL, 'Balón de Oro (10 pts)'),
    (AWARD_GOLDEN_GLOVE, 'Guante de Oro (10 pts)'),
    (AWARD_YOUNG_PLAYER, 'Mejor Jugador Joven (5 pts)'),
    (AWARD_BEST_GOAL, 'Mejor Gol del Mundial (5 pts)'),
]

AWARD_POINTS = {
    AWARD_GOLDEN_BOOT: 10,
    AWARD_GOLDEN_BALL: 10,
    AWARD_GOLDEN_GLOVE: 10,
    AWARD_YOUNG_PLAYER: 5,
    AWARD_BEST_GOAL: 5,
}


class AwardPrediction(models.Model):
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE,
                                    related_name='award_predictions')
    award = models.CharField(max_length=20, choices=AWARD_CHOICES)
    player_name = models.CharField(max_length=120)

    class Meta:
        unique_together = [('participant', 'award')]

    def __str__(self):
        return f'{self.participant.name}: {self.get_award_display()} = {self.player_name}'


class AwardActual(models.Model):
    """
    El ganador REAL de cada premio. Se llena desde el admin de Django
    cuando termine el mundial (o cuando se conozca el dato).
    """
    award = models.CharField(max_length=20, choices=AWARD_CHOICES, unique=True)
    player_name = models.CharField(max_length=120, blank=True, default='')

    def __str__(self):
        return f'{self.get_award_display()}: {self.player_name or "(sin definir)"}'
