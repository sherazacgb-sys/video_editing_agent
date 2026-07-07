from django.apps import AppConfig


class UserAccountsConfig(AppConfig):
    name = 'user_accounts'

    def ready(self):
        # Import models so the post_save signal for auto-creating UserProfile is registered
        import user_accounts.models  # noqa: F401
