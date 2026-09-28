from django.urls import path

from . import views

urlpatterns = [
    # Site root. Keeps the URL name 'index' it had while it lived in `videos`,
    # so any {% url 'index' %} keeps resolving after the move.
    path('', views.index, name='index'),
    # About page; the homepage keeps only a short teaser that links here.
    path('about/', views.about, name='about'),
    # Blog: list of published posts, and one post by its slug
    path('blog/', views.blog_list, name='blog'),
    path('blog/<slug:slug>/', views.post_detail, name='post_detail'),
    # UK GDPR privacy notice. Linked from the homepage footer, the guest screen's
    # agreement checkbox, the upload page and the cookie banner.
    path('privacy/', views.privacy, name='privacy'),
    # Terms of use for the demo; linked from the same places as the privacy notice.
    path('terms/', views.terms, name='terms'),
]
