import mimetypes
import os
import re as _re

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from pipeline.transcribe import transcribe
from pipeline.captions import build_captions
from pipeline.overlay import composite_overlay
from .models import VideoJob, UploadedAsset

# Generous enough for a photo or a several-page PDF, small enough to keep
# per-page rasterization fast on the synchronous request path.
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}
_PDF_EXTS = {'.pdf'}
_MAX_PDF_PAGES = 20  # caps rasterization cost for unusually long PDFs


def _get_owned_job(request, pk):
    # Every job-scoped view must look jobs up this way — filtering by owner
    # (not just pk) is what actually prevents one account from reading or
    # mutating another account's job by guessing/incrementing the id in the URL.
    return get_object_or_404(VideoJob, pk=pk, owner=request.user)


@login_required
def serve_media(request, path):
    full_path = os.path.realpath(os.path.join(settings.MEDIA_ROOT, path))
    if not full_path.startswith(os.path.realpath(settings.MEDIA_ROOT)):
        raise Http404
    if not os.path.isfile(full_path):
        raise Http404
    # The stored relative `path` must correspond to a file the requesting user
    # actually owns (their own job's input/output, or an asset on one of their
    # jobs) — otherwise this view would let anyone download any file on disk
    # just by knowing/guessing its path (e.g. outputs/<other job id>_rendered.mp4).
    is_owned = (
        VideoJob.objects.filter(owner=request.user, input_file=path).exists()
        or VideoJob.objects.filter(owner=request.user, output_file=path).exists()
        or UploadedAsset.objects.filter(job__owner=request.user, file=path).exists()
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


@login_required
def upload(request):
    # Scope the sidebar list to the signed-in user's own jobs only.
    jobs = VideoJob.objects.filter(owner=request.user)
    if request.method == 'POST':
        file = request.FILES.get('video')
        if file:
            job = VideoJob.objects.create(owner=request.user, input_file=file, status=VideoJob.Status.PENDING)
            return redirect('job_detail', pk=job.pk)
    return render(request, 'videos/upload.html', {'jobs': jobs})


@login_required
def job_detail(request, pk):
    job = _get_owned_job(request, pk)
    jobs = VideoJob.objects.filter(owner=request.user)

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


@login_required
def job_state(request, pk):
    job = _get_owned_job(request, pk)
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
        # Human-readable labels for display; JS keeps using the raw lowercase
        # 'status'/'stage' values above for color-mapping and stage comparisons.
        'status_display': job.get_status_display(),
        'stage_display': job.get_stage_display() if job.stage else '',
        'assets': job.assets or [],
        'output_url': output_url,
        # Full transcript text (Groq's verbose_json "text" field) for the Assets tab;
        # empty string until transcribe_video has run, so the tab has something to check against.
        'transcript_text': (job.transcript or {}).get('text', ''),
        'uploaded_files': uploaded_files,
    })


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


@login_required
@require_POST
def upload_asset(request, pk):
    job = _get_owned_job(request, pk)
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


@login_required
def subtitles_vtt(request, pk):
    job = _get_owned_job(request, pk)
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


@login_required
@require_POST
def delete_job(request, pk):
    job = _get_owned_job(request, pk)
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
def run_transcribe(request, pk):
    job = _get_owned_job(request, pk)
    job.status = VideoJob.Status.PROCESSING
    job.save(update_fields=['status'])

    try:
        result = transcribe(job.input_file.path)
        job.transcript = result
        job.stage = VideoJob.Stage.TRANSCRIBED
        job.status = VideoJob.Status.PENDING
    except Exception as e:
        job.status = VideoJob.Status.FAILED
        job.error_message = str(e)

    job.save()
    return redirect('job_detail', pk=job.pk)


@login_required
@require_POST
def run_build_captions(request, pk):
    job = _get_owned_job(request, pk)
    job.status = VideoJob.Status.PROCESSING
    job.save(update_fields=['status'])

    try:
        result = build_captions(job.input_file.path, job.transcript)
        job.assets = result
        job.stage = VideoJob.Stage.CAPTIONED
        job.status = VideoJob.Status.PENDING
    except Exception as e:
        job.status = VideoJob.Status.FAILED
        job.error_message = str(e)

    job.save()
    return redirect('job_detail', pk=job.pk)


@login_required
@require_POST
def run_render(request, pk):
    import os
    from django.conf import settings

    job = _get_owned_job(request, pk)
    job.status = VideoJob.Status.PROCESSING
    job.save(update_fields=['status'])

    try:
        outputs_dir = os.path.join(settings.MEDIA_ROOT, 'outputs')
        os.makedirs(outputs_dir, exist_ok=True)
        output_path = os.path.join(outputs_dir, f"{job.pk}_rendered.mp4")

        # Read user's resolution choice from the export dropdown; default to original.
        resolution = request.POST.get('resolution', 'original')
        composite_overlay(job.input_file.path, job.assets, output_path, resolution=resolution)

        job.output_file = f"outputs/{job.pk}_rendered.mp4"
        job.stage = VideoJob.Stage.RENDERED
        job.status = VideoJob.Status.DONE
        job.save()
    except Exception as e:
        job.status = VideoJob.Status.FAILED
        job.error_message = str(e)

    job.save()
    return redirect('job_detail', pk=job.pk)
