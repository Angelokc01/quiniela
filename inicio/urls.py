from django.urls import path

from . import views

app_name = 'inicio'

urlpatterns = [
     # Admin de la app (sesión simple)
     path('admin-login/', views.admin_login, name='admin_login'),
     path('admin-logout/', views.admin_logout, name='admin_logout'),

    # Home: elegir tipo de grupo
    path('', views.home, name='home'),

     # Sistema de puntos
     path('sistema-de-puntos/', views.sistema_puntos, name='sistema_puntos'),

    # Grupos
    path('grupos/crear/', views.create_group, name='create_group'),
     path('grupos/<int:bg_id>/eliminar/', views.delete_group, name='delete_group'),
    path('grupos/<int:bg_id>/participantes/', views.manage_participants,
         name='manage_participants'),

    # Predicciones
    path('predicciones/', views.choose_participant, name='choose_participant'),
    path('predicciones/<int:participant_id>/', views.predictions_dashboard,
         name='predictions_dashboard'),
    path('predicciones/<int:participant_id>/pdf/<str:mode>/',
         views.download_predictions_pdf, name='predictions_pdf'),
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
