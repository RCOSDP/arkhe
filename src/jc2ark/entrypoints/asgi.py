import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jc2ark.entrypoints.settings")
application = get_asgi_application()
