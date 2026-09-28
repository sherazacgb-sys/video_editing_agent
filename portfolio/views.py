from django.http import Http404
from django.shortcuts import get_object_or_404, render

from .models import Post


def index(request):
    # Public personal homepage — deliberately has no @identity_required, since anyone
    # (no account, no guest cookie) should be able to read it before ever entering the
    # app. The video tool itself lives at /upload/ in `videos`.
    # The Blog section shows the three newest published posts (an empty list shows a
    # "coming soon" line instead of cards).
    latest_posts = Post.objects.published()[:3]
    return render(request, 'portfolio/index.html', {'latest_posts': latest_posts})


def about(request):
    # Long-form About page (story, what I build, toolkit, timeline). Public and static,
    # like the homepage; linked from the nav, footer and the homepage's About block.
    return render(request, 'portfolio/about.html')


def blog_list(request):
    # /blog/: every published post, newest first. Optional ?kind=build_log|war_story|note
    # narrows it to one kind; anything else is ignored rather than erroring, so a stale
    # or mistyped link still shows the full list.
    posts = Post.objects.published()
    kind = request.GET.get('kind', '')
    valid_kinds = dict(Post.KIND_CHOICES)
    if kind in valid_kinds:
        posts = posts.filter(kind=kind)
    else:
        kind = ''  # "All" chip is the active one
    return render(request, 'portfolio/blog_list.html', {
        'posts': posts,
        'active_kind': kind,
        # (value, plural label) pairs for the filter chips, in the model's order
        'kinds': Post.KIND_PLURALS,
    })


def post_detail(request, slug):
    # /blog/<slug>/: one article. Visitors only ever see published posts; drafts and
    # scheduled posts 404 for them, so an unfinished post can't leak via a guessed URL.
    # Staff (the site owner, logged into admin) can open any post, so a draft can be
    # previewed on the real page before unticking "draft".
    post = get_object_or_404(Post, slug=slug)
    is_live = Post.objects.published().filter(pk=post.pk).exists()
    if not is_live and not request.user.is_staff:
        raise Http404('No such post')
    return render(request, 'portfolio/post_detail.html', {
        'post': post,
        'is_preview': not is_live,  # shows a yellow "draft preview" banner to staff
    })


def privacy(request):
    # Privacy notice for the whole site (homepage + Video Editing Agent demo). Lives in
    # `portfolio` rather than `videos` because it covers the site owner's obligations
    # site-wide, not just the product app. Public, no identity gate, static content.
    return render(request, 'portfolio/privacy.html')


def terms(request):
    # Terms of use for the site and the Video Editing Agent research demo. Same
    # reasoning as privacy(): site-wide legal page, public, static content.
    return render(request, 'portfolio/terms.html')
