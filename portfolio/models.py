import math

from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe


class PostQuerySet(models.QuerySet):
    def published(self):
        # What the public blog may show: not a draft, and the publish date has arrived.
        # The date check lets a post be scheduled by giving it a future published_at.
        return self.filter(is_draft=False, published_at__lte=timezone.now())


class Post(models.Model):
    """One blog article: build logs, war stories and notes, written in Django admin.

    Kept in the database (not Markdown files in git) so a post can be published or
    fixed from admin without a redeploy. Posts go up here first and are cross-posted
    to Medium; medium_url records the copy, and the post page will set this site as
    the canonical source so the Medium copy doesn't compete with it in search.
    """

    # The label shown above the title on cards; same three kinds the homepage uses
    KIND_BUILD_LOG = 'build_log'
    KIND_WAR_STORY = 'war_story'
    KIND_NOTE = 'note'
    KIND_CHOICES = [
        (KIND_BUILD_LOG, 'Build log'),
        (KIND_WAR_STORY, 'War story'),
        (KIND_NOTE, 'Note'),
    ]
    # Plural labels for the /blog/ filter chips ("War stories", not "War storys")
    KIND_PLURALS = [
        (KIND_BUILD_LOG, 'Build logs'),
        (KIND_WAR_STORY, 'War stories'),
        (KIND_NOTE, 'Notes'),
    ]

    title = models.CharField(max_length=200)
    # URL part (/blog/<slug>/); unique so two posts can't claim the same address.
    # Filled from the title automatically in admin.
    slug = models.SlugField(max_length=200, unique=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_BUILD_LOG)
    # One or two sentences: the card text on the list pages and the page's meta
    # description, so it's capped at what search results actually display.
    summary = models.CharField(max_length=300)
    # The article itself, in Markdown (headings, lists, links, code blocks, tables)
    body = models.TextField(help_text='Markdown. Headings, lists, links, ```code blocks``` and tables work.')
    # Drafts are never shown publicly. Defaults to True so a half-written post saved
    # from admin can't go live by accident.
    is_draft = models.BooleanField(default=True, help_text='Untick to publish.')
    # Date shown on the post and used for ordering. A future date schedules the post.
    published_at = models.DateTimeField(default=timezone.now)
    # Link to the Medium copy, shown as "Also on Medium" on the post page; optional
    medium_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PostQuerySet.as_manager()

    class Meta:
        ordering = ['-published_at']  # newest first everywhere (list page, homepage)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        # The post's page; also gives admin its "View on site" button
        return reverse('post_detail', args=[self.slug])

    def body_html(self):
        # Markdown -> HTML for the post page. Imported here rather than at module top
        # so migrations and the rest of the site still load if the package is missing.
        import markdown
        # Raw HTML in the body is passed through unescaped. Acceptable only because
        # posts are written by the site owner in admin, never by visitors; if that
        # ever changes, sanitise here (e.g. with nh3) before mark_safe.
        html = markdown.markdown(
            self.body,
            extensions=['fenced_code', 'tables', 'sane_lists'],  # ``` blocks, tables, predictable lists
        )
        return mark_safe(html)

    @property
    def reading_minutes(self):
        # "N min read" on cards: ~200 words a minute, never shown as 0
        return max(1, math.ceil(len(self.body.split()) / 200))
