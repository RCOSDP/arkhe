import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jc2ark.entrypoints.settings")
application = get_wsgi_application()
