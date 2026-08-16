from django.urls import path
from . import views

urlpatterns = [
    path('', views.upload, name='upload'),
    path('guest/continue/', views.continue_as_guest, name='continue_as_guest'),
    path('job/<int:pk>/', views.job_detail, name='job_detail'),
    # transcribe/build-captions no longer have direct-POST routes — those actions
    # now only run through the chat agent's tools (pipeline/tools.py), triggered
    # via the Skills tab cards in job_detail.html.
    path('job/<int:pk>/render/', views.run_render, name='run_render'),
    path('job/<int:pk>/subtitles.vtt', views.subtitles_vtt, name='subtitles_vtt'),
    path('job/<int:pk>/state/', views.job_state, name='job_state'),
    path('job/<int:pk>/feedback/', views.submit_feedback, name='submit_feedback'),
    path('job/<int:pk>/assets/upload/', views.upload_asset, name='upload_asset'),
    path('job/<int:pk>/delete/', views.delete_job, name='delete_job'),
]
