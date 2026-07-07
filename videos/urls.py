from django.urls import path
from . import views

urlpatterns = [
    path('', views.upload, name='upload'),
    path('job/<int:pk>/', views.job_detail, name='job_detail'),
    path('job/<int:pk>/transcribe/', views.run_transcribe, name='run_transcribe'),
    path('job/<int:pk>/build-captions/', views.run_build_captions, name='run_build_captions'),
    path('job/<int:pk>/render/', views.run_render, name='run_render'),
    path('job/<int:pk>/subtitles.vtt', views.subtitles_vtt, name='subtitles_vtt'),
    path('job/<int:pk>/state/', views.job_state, name='job_state'),
    path('job/<int:pk>/assets/upload/', views.upload_asset, name='upload_asset'),
    path('job/<int:pk>/delete/', views.delete_job, name='delete_job'),
]
