# webapp/wsgi.py

from webapp import create_app

# This `app` object is what WSGI servers (Gunicorn, uWSGI, Render, etc.) will look for
app = create_app()
