# shops/apps.py
from django.apps import AppConfig


class ShopsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "shops"

    def ready(self):
        # Importe les signaux pour qu'ils soient enregistrés au démarrage
        from . import signals  # noqa: F401