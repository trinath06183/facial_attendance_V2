from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.accounts'
    label = 'accounts'

    def ready(self):
        # import signals so the @receiver decorators are registered at startup.
        import apps.accounts.signals  # noqa: f401
