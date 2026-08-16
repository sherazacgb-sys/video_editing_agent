from django.shortcuts import get_object_or_404

from .models import VideoJob


def get_accessible_job(request, pk):
    """
    Look up a VideoJob the requester actually owns — a signed-in account via
    `owner`, or a guest via the identity GuestIdentityMiddleware assigned them
    (request.guest_id). 404s on any mismatch, same as the old owner-only check,
    so one account/guest can never read or mutate another's job by guessing a pk.
    """
    if request.user.is_authenticated:
        return get_object_or_404(VideoJob, pk=pk, owner=request.user)
    return get_object_or_404(VideoJob, pk=pk, owner__isnull=True, guest_id=request.guest_id)


def get_accessible_jobs(request):
    """Same identity rule as get_accessible_job, for the sidebar's job list."""
    if request.user.is_authenticated:
        return VideoJob.objects.filter(owner=request.user)
    return VideoJob.objects.filter(owner__isnull=True, guest_id=request.guest_id)
