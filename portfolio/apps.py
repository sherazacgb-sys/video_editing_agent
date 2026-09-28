from django.apps import AppConfig


class PortfolioConfig(AppConfig):
    # Owns the public personal pages (homepage, /about/, legal pages, and the blog via
    # the Post model; case studies later),
    # kept apart from `videos` so the product app doesn't carry the site owner's bio.
    name = 'portfolio'
