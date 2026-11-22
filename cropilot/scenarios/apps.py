from django.apps import AppConfig


class ScenariosConfig(AppConfig):
    """Demo scenarios: definitions/*.json and `python manage.py scenario` (list, status, validate, switch)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "scenarios"
    verbose_name = "Scenariusze demo"
