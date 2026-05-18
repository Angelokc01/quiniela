from django.urls import path

from . import views

app_name = 'inicio'

urlpatterns = [
    # Home: elegir tipo de grupo
    path('', views.home, name='home'),

    # Grupos
    path('grupos/crear/', views.create_group, name='create_group'),
    path('grupos/<int:bg_id>/participantes/', views.manage_participants,
         name='manage_participants'),

    # Predicciones
    path('predicciones/', views.choose_participant, name='choose_participant'),
    path('predicciones/<int:participant_id>/', views.predictions_dashboard,
         name='predictions_dashboard'),
    path('predicciones/<int:participant_id>/grupos/', views.predict_group_stage,
         name='predict_group_stage'),
    path('predicciones/<int:participant_id>/bracket/', views.predict_bracket,
         name='predict_bracket'),
    path('predicciones/<int:participant_id>/premios/', views.predict_awards,
         name='predict_awards'),

    # Tabla / puntajes
    path('tabla/<int:bg_id>/', views.leaderboard, name='leaderboard'),
    path('tabla/<int:bg_id>/participante/<int:participant_id>/',
         views.participant_detail, name='participant_detail'),

    # Acción: sincronizar API (botón)
    path('sync/', views.sync_now, name='sync_now'),
]
