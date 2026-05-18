from django.contrib import admin
from .models import (
    BettingGroup, Participant, Match,
    GroupMatchPrediction, GroupStandingPrediction,
    BracketPrediction, KnockoutScorePrediction,
    AwardPrediction, AwardActual,
)


class ParticipantInline(admin.TabularInline):
    model = Participant
    extra = 1


@admin.register(BettingGroup)
class BettingGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    inlines = [ParticipantInline]


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ('name', 'betting_group', 'created_at')
    list_filter = ('betting_group',)
    search_fields = ('name',)


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ('match_number', 'round', 'group_name', 'home_team',
                    'away_team', 'home_score', 'away_score', 'status',
                    'kickoff_utc')
    list_filter = ('round', 'status', 'group_name')
    search_fields = ('home_team', 'away_team')
    ordering = ('match_number',)


@admin.register(GroupMatchPrediction)
class GroupMatchPredictionAdmin(admin.ModelAdmin):
    list_display = ('participant', 'match', 'home_score', 'away_score', 'updated_at')
    list_filter = ('participant__betting_group',)


@admin.register(GroupStandingPrediction)
class GroupStandingPredictionAdmin(admin.ModelAdmin):
    list_display = ('participant', 'group_name', 'team', 'position')
    list_filter = ('participant__betting_group', 'group_name')


@admin.register(BracketPrediction)
class BracketPredictionAdmin(admin.ModelAdmin):
    list_display = ('participant', 'slot', 'team')
    list_filter = ('participant__betting_group',)
    search_fields = ('slot', 'team')


@admin.register(KnockoutScorePrediction)
class KnockoutScorePredictionAdmin(admin.ModelAdmin):
    list_display = ('participant', 'round', 'slot_top', 'slot_bottom',
                    'home_score', 'away_score')
    list_filter = ('participant__betting_group', 'round')


@admin.register(AwardPrediction)
class AwardPredictionAdmin(admin.ModelAdmin):
    list_display = ('participant', 'award', 'player_name')
    list_filter = ('participant__betting_group', 'award')


@admin.register(AwardActual)
class AwardActualAdmin(admin.ModelAdmin):
    """
    Edita aquí los ganadores reales de los premios cuando se conozcan.
    En particular el Mejor Gol del Mundial (que la API no entrega).
    """
    list_display = ('award', 'player_name')
