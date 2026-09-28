from django.contrib import admin

from .models import Post


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    # Blog writing happens here, so the list shows what matters when managing posts:
    # which are live, when they went out, and their kind.
    list_display = ('title', 'kind', 'is_draft', 'published_at', 'updated_at')
    list_filter = ('is_draft', 'kind')
    search_fields = ('title', 'summary', 'body')
    # Slug is typed for you from the title (still editable before first save)
    prepopulated_fields = {'slug': ('title',)}
    date_hierarchy = 'published_at'
    readonly_fields = ('created_at', 'updated_at')
    # Writing fields first; publishing controls and the Medium link grouped below
    fieldsets = (
        (None, {'fields': ('title', 'slug', 'kind', 'summary', 'body')}),
        ('Publishing', {'fields': ('is_draft', 'published_at', 'medium_url')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )
