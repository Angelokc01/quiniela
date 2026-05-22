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

# Crea tu archivo de entorno local a partir de .env.example
# y completa las variables privadas antes de ejecutar en producción.

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

## Despliegue en Render

El repositorio incluye [render.yaml](render.yaml) para desplegar la web y la base de datos gratis en Render.

Pasos rápidos:

1. En Render, crea un nuevo Blueprint desde este repositorio.
2. Render leerá el archivo [render.yaml](render.yaml) y creará el servicio web y la base de datos.
3. Define o revisa estas variables de entorno:
	- `SECRET_KEY`
	- `DEBUG=False`
	- `ALLOWED_HOSTS=tu-servicio.onrender.com`
	- `CSRF_TRUSTED_ORIGINS=https://tu-servicio.onrender.com`
	- `WC2026_API_URL=https://api.wc2026api.com`
	- `WC2026_API_TOKEN=...`
4. El servicio web usa `gunicorn quiniela.wsgi:application` como comando de arranque.
5. Copia el `DATABASE_URL` externo de tu base de datos de Render y guárdalo como secreto en GitHub con el nombre `DATABASE_URL_EXTERNAL`.
6. Guarda también `SECRET_KEY` y `WC2026_API_TOKEN` como secretos en GitHub.
7. El workflow [sync_matches](.github/workflows/sync_matches.yml) ejecuta `python manage.py sync_matches` cada 30 minutos usando GitHub Actions.

Notas:

- En producción, Render usa PostgreSQL mediante `DATABASE_URL`.
- Los archivos estáticos se recogen con `python manage.py collectstatic --noinput` durante el build.
- No dejes el token de la API hardcodeado en el código; usa variables de entorno.
- Si no quieres depender de GitHub Actions, entonces el despliegue ya no será 100% gratis porque Render cobra por cron jobs.

## Lo que falta y vale la pena considerar

Léelo al final del README — está en la respuesta que generé en el chat.
