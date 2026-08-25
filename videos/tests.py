import uuid

from django.contrib.auth.models import AnonymousUser, User
from django.http import Http404
from django.test import RequestFactory, TestCase

from .access import get_accessible_job, get_accessible_jobs
from .models import VideoJob


class GetAccessibleJobTests(TestCase):
    """
    videos/access.py's get_accessible_job/get_accessible_jobs are the only thing
    standing between one account/guest and another's video — everything else
    (job detail, chat, downloads) trusts whatever these return. Covering this
    first since a bug here is a real cross-account data leak, not just a UI glitch.
    """

    def setUp(self):
        # RequestFactory builds a bare request — no middleware runs, so
        # .user/.guest_id (normally set by AuthenticationMiddleware and
        # GuestIdentityMiddleware) are attached by hand in each test below.
        self.factory = RequestFactory()

    def _request(self, user=None, guest_id=None):
        # Stands in for what GuestIdentityMiddleware/AuthenticationMiddleware
        # would have set on a real request, without needing the full middleware stack.
        request = self.factory.get('/')
        request.user = user or AnonymousUser()
        request.guest_id = guest_id
        return request

    def test_authenticated_user_can_access_own_job(self):
        # Baseline: an account can look up a job it actually owns.
        user = User.objects.create_user(username='alice', password='x')
        job = VideoJob.objects.create(owner=user)
        request = self._request(user=user)
        self.assertEqual(get_accessible_job(request, job.pk), job)

    def test_authenticated_user_cannot_access_other_users_job(self):
        # The core cross-account leak this function exists to prevent: guessing
        # another account's job pk must 404, not return the row.
        owner = User.objects.create_user(username='alice', password='x')
        other = User.objects.create_user(username='mallory', password='x')
        job = VideoJob.objects.create(owner=owner)
        request = self._request(user=other)
        with self.assertRaises(Http404):
            get_accessible_job(request, job.pk)

    def test_guest_can_access_own_job(self):
        # Same rule as above, but for the guest_id identity path instead of owner.
        guest_id = uuid.uuid4()
        job = VideoJob.objects.create(owner=None, guest_id=guest_id)
        request = self._request(guest_id=guest_id)
        self.assertEqual(get_accessible_job(request, job.pk), job)

    def test_guest_cannot_access_another_guests_job(self):
        # A guest with a different guest_id cookie must not be able to reach
        # someone else's job just by guessing/enumerating the pk.
        job = VideoJob.objects.create(owner=None, guest_id=uuid.uuid4())
        request = self._request(guest_id=uuid.uuid4())
        with self.assertRaises(Http404):
            get_accessible_job(request, job.pk)

    def test_guest_cannot_access_an_owned_job(self):
        # owner__isnull=True in the guest lookup should keep an authenticated
        # account's job out of reach for guest requests entirely, even one that
        # happens to guess a matching-looking identity.
        user = User.objects.create_user(username='alice', password='x')
        job = VideoJob.objects.create(owner=user)
        request = self._request(guest_id=uuid.uuid4())
        with self.assertRaises(Http404):
            get_accessible_job(request, job.pk)

    def test_get_accessible_jobs_filters_by_authenticated_user(self):
        # The sidebar job list must only ever show the requester's own jobs.
        user = User.objects.create_user(username='alice', password='x')
        other = User.objects.create_user(username='mallory', password='x')
        mine = VideoJob.objects.create(owner=user)
        VideoJob.objects.create(owner=other)
        request = self._request(user=user)
        self.assertEqual(list(get_accessible_jobs(request)), [mine])

    def test_get_accessible_jobs_filters_by_guest_id(self):
        # Same guarantee as above, for the guest_id identity path.
        guest_id = uuid.uuid4()
        mine = VideoJob.objects.create(owner=None, guest_id=guest_id)
        VideoJob.objects.create(owner=None, guest_id=uuid.uuid4())
        request = self._request(guest_id=guest_id)
        self.assertEqual(list(get_accessible_jobs(request)), [mine])
