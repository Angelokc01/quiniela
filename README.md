# Quiniela Mundial 2026 – Django

App de Django para hacer una quiniela del Mundial 2026 con familia y amigos.
Sin autenticación: cada persona se identifica eligiendo su nombre en el grupo.

## Stack
- Django 4.2+
- SQLite (default)
- API: [wc2026api.com](https://api.wc2026api.com/docs)

## Instalación

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py createsuperuser   # para entrar al admin

# Trae los 104 partidos desde la API
python manage.py sync_matches

python manage.py runserver
```

## Sincronizar la API
Cada vez que termine un partido del mundial corre:

```bash
python manage.py sync_matches
```

Esto:
1. Trae todos los partidos de wc2026api.
2. Upsertea en la BD local.
3. Recalcula puntos (en realidad los puntos se calculan on-demand, así que basta con sincronizar).

Si quieres automatizar, usa cron o GitHub Actions cada ~30 minutos durante el mundial.

## Lo que falta y vale la pena considerar

Léelo al final del README — está en la respuesta que generé en el chat.
