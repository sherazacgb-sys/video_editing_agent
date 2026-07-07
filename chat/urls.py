from django.urls import path
from . import views

urlpatterns = [
    path('job/<int:pk>/chat/', views.chat_message, name='chat_message'),
    path('job/<int:pk>/chat/history/', views.chat_history, name='chat_history'),
    path('job/<int:pk>/chat/sessions/', views.session_list, name='chat_sessions'),
    path('job/<int:pk>/chat/session/new/', views.new_session, name='new_chat_session'),
]
