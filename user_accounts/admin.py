from django.contrib import admin
from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan')
    list_editable = ('plan',)  # Allow plan changes directly from the list view
