import uuid

from django.conf import settings


class GuestIdentityMiddleware:
    """
    Reads a previously-issued guest identity (see views.continue_as_guest, which
    is the only place that ever mints one) into request.guest_id so guest
    visitors can own VideoJobs the same way authenticated users do via `owner`
    — see VideoJob.guest_id and videos/access.py's get_accessible_job.
    Deliberately does NOT mint a new identity for a request that has none — a
    brand-new anonymous visitor should hit the identity_required gate
    (videos/decorators.py) and be sent to choose sign-in vs. guest first.
    Must run after AuthenticationMiddleware (needs request.user resolved).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Authenticated requests already have an identity (request.user) — guest_id
        # only matters for anonymous visitors, so leave it unset otherwise.
        request.guest_id = None

        if not request.user.is_authenticated:
            cookie_value = request.COOKIES.get(settings.GUEST_ID_COOKIE_NAME)
            try:
                request.guest_id = uuid.UUID(cookie_value) if cookie_value else None
            except ValueError:
                # Malformed/tampered cookie value — treat as no identity rather
                # than erroring the request.
                request.guest_id = None

        return self.get_response(request)
