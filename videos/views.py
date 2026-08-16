import mimetypes
import os
import re as _re
import subprocess
import tempfile
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from pipeline.transcribe import get_duration_seconds
from pipeline.overlay import composite_overlay
from pipeline.tools import USER_FACING_SKILLS  # curated tool subset rendered as Skill cards on job_detail
from .access import get_accessible_job, get_accessible_jobs
from .decorators import identity_required
from .models import VideoJob, UploadedAsset, GuestFeedback

# Generous enough for a photo or a several-page PDF, small enough to keep
# per-page rasterization fast on the synchronous request path.
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}
_PDF_EXTS = {'.pdf'}
_MAX_PDF_PAGES = 20  # caps rasterization cost for unusually long PDFs

# Container formats the ffmpeg/ffprobe-based pipeline can decode. Checked by
# extension as a cheap pre-filter only — the real content check is the ffprobe
# decode attempt in upload() below, since an extension alone can be spoofed.
_VIDEO_EXTS = {'.mp4', '.mov', '.webm', '.avi'}

# Per-tier caps on upload size and duration — guests get the smallest allowance,
# pro accounts the largest. Longer/larger videos produce proportionally more
# caption assets, and read_assets (pipeline/tools.py) lists every asset in one
# shot — an uncapped video can blow past the LLM's context window in a single
# tool call, so even the pro tier stays bounded.
_MAX_VIDEO_BYTES = {
    'guest': 50 * 1024 * 1024,
    'free': 100 * 1024 * 1024,
    'pro': 250 * 1024 * 1024,
}
_MAX_DURATION_SECONDS = {
    'guest': 10 * 60,
    'free': 20 * 60,
    'pro': 45 * 60,
}


def _video_tier(request) -> str:
    # Which upload limits apply to this request — same defensive profile lookup
    # as user_accounts/context_processors.py's user_plan (a UserProfile may not
    # exist yet for accounts created before that app was added).
    if not request.user.is_authenticated:
        return 'guest'
    try:
        return 'pro' if request.user.profile.is_pro else 'free'
    except Exception:
        return 'free'


@require_POST
def continue_as_guest(request):
    # Handles the "Continue as guest" choice on the login page: mints a fresh
    # guest_id and sets it as a cookie, which is what identity_required
    # (videos/decorators.py) checks for on every subsequent request from this
    # browser. GuestIdentityMiddleware itself never mints one on its own.
    next_url = request.POST.get('next') or ''
    # Reject an absolute/external next (open-redirect guard) — same check Django's
    # own LoginView applies to its next param — falling back to the upload page.
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = 'upload'
    response = redirect(next_url)
    if not request.user.is_authenticated and request.guest_id is None:
        new_guest_id = uuid.uuid4()
        response.set_cookie(
            settings.GUEST_ID_COOKIE_NAME,
            str(new_guest_id),
            max_age=settings.GUEST_ID_COOKIE_MAX_AGE,
            httponly=True,  # not readable from JS — nothing client-side needs it
            samesite='Lax',
            secure=not settings.DEBUG,  # requires HTTPS once actually deployed behind it
        )
    return response


def serve_media(request, path):
    full_path = os.path.realpath(os.path.join(settings.MEDIA_ROOT, path))
    if not full_path.startswith(os.path.realpath(settings.MEDIA_ROOT)):
        raise Http404
    if not os.path.isfile(full_path):
        raise Http404
    # The stored relative `path` must correspond to a file the requesting user (or
    # guest — see GuestIdentityMiddleware/videos/access.py) actually owns — otherwise
    # this view would let anyone download any file on disk just by knowing/guessing
    # its path (e.g. outputs/<other job id>_rendered.mp4).
    if request.user.is_authenticated:
        job_q = Q(owner=request.user)
        asset_q = Q(job__owner=request.user)
    else:
        job_q = Q(owner__isnull=True, guest_id=request.guest_id)
        asset_q = Q(job__owner__isnull=True, job__guest_id=request.guest_id)
    is_owned = (
        VideoJob.objects.filter(job_q, input_file=path).exists()
        or VideoJob.objects.filter(job_q, output_file=path).exists()
        or UploadedAsset.objects.filter(asset_q, file=path).exists()
    )
    if not is_owned:
        raise Http404

    file_size = os.path.getsize(full_path)
    content_type, _ = mimetypes.guess_type(full_path)
    content_type = content_type or 'application/octet-stream'

    range_header = request.META.get('HTTP_RANGE', '').strip()
    if range_header:
        m = _re.match(r'bytes=(\d+)-(\d*)', range_header)
        if m:
            first = int(m.group(1))
            last = int(m.group(2)) if m.group(2) else file_size - 1
            last = min(last, file_size - 1)
            length = last - first + 1
            f = open(full_path, 'rb')
            f.seek(first)
            response = HttpResponse(f.read(length), status=206, content_type=content_type)
            response['Content-Range'] = f'bytes {first}-{last}/{file_size}'
            response['Accept-Ranges'] = 'bytes'
            response['Content-Length'] = length
            return response

    response = FileResponse(open(full_path, 'rb'), content_type=content_type)
    response['Accept-Ranges'] = 'bytes'
    response['Content-Length'] = file_size
    return response


@identity_required
def upload(request):
    # Scope the sidebar list to the requester's own jobs — signed-in or guest
    # (see videos/access.py for how the two identities are told apart).
    jobs = get_accessible_jobs(request)
    # guest/free/pro — resolved once so the GET hint and the POST validation
    # below always agree on which caps apply to this requester.
    tier = _video_tier(request)
    max_bytes = _MAX_VIDEO_BYTES[tier]
    max_duration = _MAX_DURATION_SECONDS[tier]
    if request.method == 'POST':
        if not request.user.is_authenticated and jobs.count() >= settings.GUEST_MAX_OPEN_JOBS:
            # Guests have no account to rate-limit against, so cap concurrent open
            # jobs per guest identity instead — see GUEST_MAX_OPEN_JOBS in settings.
            messages.error(
                request,
                f"Guests can have up to {settings.GUEST_MAX_OPEN_JOBS} videos at a time. "
                "Delete an old one, or sign in for unlimited.",
            )
            return redirect('upload')
        file = request.FILES.get('video')
        if file:
            ext = os.path.splitext(file.name)[1].lower()
            if ext not in _VIDEO_EXTS:
                # Reject obviously-wrong containers before ever touching disk/ffprobe.
                # This is only a cheap pre-filter, not a security boundary — a renamed
                # non-video file with an allowed extension is caught below by the
                # ffprobe decode check instead.
                messages.error(
                    request,
                    f"Unsupported file type '{ext or 'unknown'}'. Allowed formats: "
                    f"{', '.join(sorted(e.lstrip('.').upper() for e in _VIDEO_EXTS))}.",
                )
                return redirect('upload')
            if file.size > max_bytes:
                messages.error(
                    request,
                    f"Video is {file.size / (1024 * 1024):.1f}MB — max is "
                    f"{max_bytes // (1024 * 1024)}MB on your plan.",
                )
                return redirect('upload')
            # Write the upload to a temp file so ffprobe has a real filesystem path to
            # inspect — small uploads arrive as in-memory files with no path of their own.
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=ext)
            try:
                with os.fdopen(tmp_fd, 'wb') as tmp:
                    for chunk in file.chunks():
                        tmp.write(chunk)
                try:
                    duration = get_duration_seconds(tmp_path)
                except subprocess.CalledProcessError:
                    # ffprobe couldn't decode this at all — e.g. a non-video file renamed
                    # to look like one. This is the real content check; the extension
                    # allowlist above is just a cheap pre-filter, not a security boundary.
                    messages.error(
                        request,
                        "Couldn't read this file as a video. It may be corrupted or "
                        "not actually a video file.",
                    )
                    return redirect('upload')
                if duration > max_duration:
                    # Reject before ever creating a VideoJob/saving to permanent storage.
                    # Flash via messages + redirect (not render) so a page refresh re-fetches
                    # the upload page with GET instead of the browser re-POSTing the file.
                    messages.error(
                        request,
                        f"Video is {duration / 60:.1f} minutes long — max is "
                        f"{max_duration // 60} minutes on your plan.",
                    )
                    return redirect('upload')
            finally:
                os.unlink(tmp_path)

            # Rewind so VideoJob.objects.create can read the upload from the start again —
            # file.chunks() above already consumed the stream once for the ffprobe check.
            file.seek(0)
            if request.user.is_authenticated:
                job = VideoJob.objects.create(owner=request.user, input_file=file, status=VideoJob.Status.PENDING)
            else:
                job = VideoJob.objects.create(guest_id=request.guest_id, input_file=file, status=VideoJob.Status.PENDING)
            return redirect('job_detail', pk=job.pk)
    return render(request, 'videos/upload.html', {
        'jobs': jobs,
        # Drives the "max N minutes / max size" hint on the drop zone — kept in sync
        # with the actual enforced per-tier limits instead of hardcoding numbers.
        'max_duration_minutes': max_duration // 60,
        'max_size_mb': max_bytes // (1024 * 1024),
    })


@identity_required
def job_detail(request, pk):
    job = get_accessible_job(request, pk)
    jobs = get_accessible_jobs(request)

    seen_layers = {}
    for asset in (job.assets or []):
        layer = asset.get('layer', 1)
        if layer not in seen_layers:
            seen_layers[layer] = asset.get('type', f'layer {layer}')

    timeline_layers = [
        {'layer': k, 'label': v}
        for k, v in sorted(seen_layers.items())
    ]

    return render(request, 'videos/job_detail.html', {
        'job': job,
        'jobs': jobs,
        'timeline_layers': timeline_layers,
        # Export is pro-only; job_detail.html gates the button on the existing
        # `user_plan` context processor (user_accounts/context_processors.py)
        # rather than a separate flag passed here.
        'skills': USER_FACING_SKILLS,  # rendered as Skill cards via json_script in the template
        # Surfaced in the template as JS constants so the chat input's live char
        # counter and session-budget bar match the server-enforced caps exactly.
        'chat_max_message_chars': settings.CHAT_MAX_MESSAGE_CHARS,
        'chat_session_token_budget': settings.CHAT_SESSION_TOKEN_BUDGET,
    })


def _serialize_uploaded_asset(a):
    return {
        'id': a.pk,
        'kind': a.kind,
        'name': a.original_name,
        'url': a.file.url,
        'page_number': a.page_number,
        'source_pdf_id': a.source_pdf_id,
    }


@identity_required
def job_state(request, pk):
    job = get_accessible_job(request, pk)
    output_url = job.output_file.url if job.output_file else None
    # Which uploaded files already have a matching image asset on the timeline,
    # so the Assets panel can show "placed" vs "available" without re-deriving it.
    placed_file_ids = {a.get('content', {}).get('file_id') for a in (job.assets or [])}
    uploaded_files = [
        {**_serialize_uploaded_asset(a), 'placed': a.pk in placed_file_ids}
        for a in job.uploaded_assets.all()
    ]
    return JsonResponse({
        'status': job.status,
        'stage': job.stage or '',
        # Render percent (0–100) for the Export button's progress bar; only
        # meaningful while a render is processing, 0 the rest of the time.
        'progress': job.progress,
        'assets': job.assets or [],
        'output_url': output_url,
        # Full transcript text (Groq's verbose_json "text" field) for the Assets tab;
        # empty string until transcribe_video has run, so the tab has something to check against.
        'transcript_text': (job.transcript or {}).get('text', ''),
        'uploaded_files': uploaded_files,
    })


@identity_required
@require_POST
def submit_feedback(request, pk):
    # get_accessible_job authorizes the same way every other job-scoped view does
    # (owner match or guest_id cookie match) — a guest can only leave feedback
    # against a job that's actually theirs, not by guessing another job's pk.
    job = get_accessible_job(request, pk)
    try:
        rating = int(request.POST.get('rating', ''))
    except ValueError:
        return JsonResponse({'error': 'rating must be an integer 1-5'}, status=400)
    if not 1 <= rating <= 5:
        return JsonResponse({'error': 'rating must be between 1 and 5'}, status=400)
    GuestFeedback.objects.create(
        job=job,
        # None for a signed-in user — the modal is only ever shown to guests
        # (see job_detail.html), but the field/endpoint aren't hard-restricted to
        # guests so they stay reusable if this is ever opened up to everyone.
        guest_id=request.guest_id,
        rating=rating,
        comment=request.POST.get('comment', '').strip(),
    )
    return JsonResponse({'ok': True})


def _rasterize_pdf_pages(job, pdf_asset):
    # Renders each PDF page to a PNG so it can go through the same image-overlay
    # path as a directly-uploaded image, instead of needing a second compositing
    # code path for PDFs in the render pipeline.
    import fitz  # PyMuPDF
    from django.core.files.base import ContentFile

    pages = []
    doc = fitz.open(pdf_asset.file.path)
    try:
        page_count = min(doc.page_count, _MAX_PDF_PAGES)
        base_name = os.path.splitext(pdf_asset.original_name)[0]
        for i in range(page_count):
            page = doc.load_page(i)
            # 2x zoom ≈ 150dpi — sharp enough for a video overlay without being huge.
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            png_bytes = pix.tobytes('png')
            name = f"{base_name}_page{i + 1}.png"
            page_asset = UploadedAsset(
                job=job, kind=UploadedAsset.Kind.IMAGE, original_name=name,
                source_pdf=pdf_asset, page_number=i + 1,
            )
            page_asset.file.save(name, ContentFile(png_bytes), save=True)
            pages.append(page_asset)
    finally:
        doc.close()
    return pages


@identity_required
@require_POST
def upload_asset(request, pk):
    job = get_accessible_job(request, pk)
    file = request.FILES.get('file')
    if not file:
        return JsonResponse({'error': 'no file provided'}, status=400)
    if file.size > _MAX_UPLOAD_BYTES:
        return JsonResponse({'error': f'file exceeds {_MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit'}, status=400)

    ext = os.path.splitext(file.name)[1].lower()
    created = []

    if ext in _IMAGE_EXTS:
        created.append(UploadedAsset.objects.create(
            job=job, file=file, kind=UploadedAsset.Kind.IMAGE, original_name=file.name,
        ))
    elif ext in _PDF_EXTS:
        pdf_asset = UploadedAsset.objects.create(
            job=job, file=file, kind=UploadedAsset.Kind.PDF, original_name=file.name,
        )
        created.append(pdf_asset)
        created.extend(_rasterize_pdf_pages(job, pdf_asset))
    else:
        return JsonResponse({'error': 'unsupported file type — use an image (png/jpg/webp/gif) or PDF'}, status=400)

    return JsonResponse({'created': [_serialize_uploaded_asset(a) for a in created]})


def _seconds_to_vtt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    ms = int((s % 1) * 1000)
    return f"{h:02d}:{m:02d}:{int(s):02d}.{ms:03d}"


@identity_required
def subtitles_vtt(request, pk):
    job = get_accessible_job(request, pk)
    assets = job.assets or []

    lines = ["WEBVTT", ""]
    for asset in sorted(assets, key=lambda a: a['start']):
        if asset.get('type') not in ('caption', 'text'):
            continue
        start = _seconds_to_vtt_time(asset['start'])
        end = _seconds_to_vtt_time(asset['end'])
        pos = asset.get('position', {'x': 0.5, 'y': 0.85})
        x = pos.get('x', 0.5)
        y = pos.get('y', 0.85)
        if x < 0.3:
            align, position = "left", "10%"
        elif x > 0.7:
            align, position = "right", "90%"
        else:
            align, position = "center", "50%"
        line_pct = f"{int(y * 100)}%"
        lines.append(f"{start} --> {end} align:{align} position:{position} line:{line_pct}")
        lines.append(asset['content']['text'])
        lines.append("")

    response = HttpResponse("\n".join(lines), content_type="text/vtt; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response


@identity_required
@require_POST
def delete_job(request, pk):
    job = get_accessible_job(request, pk)
    # Delete media files from disk before removing the DB record so we don't
    # leave orphaned files in MEDIA_ROOT if the delete succeeds.
    if job.input_file:
        job.input_file.delete(save=False)
    if job.output_file:
        job.output_file.delete(save=False)
    job.delete()
    return redirect('upload')


@login_required
@require_POST
def run_render(request, pk):
    import os

    # Guard server-side (not just hiding the button) so a free-plan user can't
    # trigger export by POSTing the URL directly — export is a pro-only feature.
    if not request.user.profile.is_pro:
        raise Http404

    job = get_accessible_job(request, pk)
    job.status = VideoJob.Status.PROCESSING
    # Reset progress so a re-export starts the bar at 0 instead of flashing the
    # previous render's last value on the first poll.
    job.progress = 0
    job.save(update_fields=['status', 'progress'])

    # Called from inside the ffmpeg loop with the encode percent. A queryset
    # .update() writes just the one column — it can't clobber other fields, and
    # it skips model save() overhead on a callback that fires many times.
    def _update_progress(pct):
        VideoJob.objects.filter(pk=job.pk).update(progress=pct)

    try:
        outputs_dir = os.path.join(settings.MEDIA_ROOT, 'outputs')
        os.makedirs(outputs_dir, exist_ok=True)
        output_path = os.path.join(outputs_dir, f"{job.pk}_rendered.mp4")

        # Read user's resolution choice from the export dropdown; default to original.
        resolution = request.POST.get('resolution', 'original')
        composite_overlay(
            job.input_file.path, job.assets, output_path,
            resolution=resolution, progress_callback=_update_progress,
        )

        job.output_file = f"outputs/{job.pk}_rendered.mp4"
        job.stage = VideoJob.Stage.RENDERED
        job.status = VideoJob.Status.DONE
        job.save()
    except Exception as e:
        job.status = VideoJob.Status.FAILED
        job.error_message = str(e)

    job.save()
    return redirect('job_detail', pk=job.pk)
