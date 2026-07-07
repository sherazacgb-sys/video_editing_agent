import json
import os

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from videos.models import VideoJob
from .agent import build_agent
from .callbacks import LLMCallbackHandler
from .models import ChatMessage, ChatSession


def _get_owned_job(request, pk):
    # Same ownership gate as videos/views.py — a session/message belongs to a
    # job, so scoping the job lookup to the requesting user is what stops one
    # account from reading or chatting on another account's video.
    return get_object_or_404(VideoJob, pk=pk, owner=request.user)


@login_required
@require_GET
def session_list(request, pk):
    """Return all chat sessions for this job, newest first, with a preview and message count."""
    job = _get_owned_job(request, pk)
    sessions = []
    for s in job.chat_sessions.prefetch_related('messages').order_by('-created_at'):
        first_user = s.messages.filter(role=ChatMessage.Role.USER).first()
        if first_user:
            # Truncate long previews so the sidebar row stays compact.
            raw = first_user.content
            preview = (raw[:50] + '…') if len(raw) > 50 else raw
        else:
            preview = ''
        msg_count = s.messages.filter(
            role__in=[ChatMessage.Role.USER, ChatMessage.Role.ASSISTANT]
        ).count()
        sessions.append({
            'id': s.pk,
            'created_at': s.created_at.isoformat(),
            'preview': preview,
            'message_count': msg_count,
        })
    return JsonResponse({'sessions': sessions})


@login_required
@require_POST
def new_session(request, pk):
    """Create a new ChatSession for this job; return its ID to the client."""
    job = _get_owned_job(request, pk)
    session = ChatSession.objects.create(job=job)
    return JsonResponse({'session_id': session.pk})


@login_required
@require_GET
def chat_history(request, pk):
    """
    Return the user/assistant messages for a session.
    Caller must pass ?session_id=<id>; returns [] for unknown/missing sessions
    rather than 404 so the frontend can treat it as an empty chat safely.
    """
    job = _get_owned_job(request, pk)
    session_id = request.GET.get('session_id')
    if not session_id:
        return JsonResponse({'messages': []})
    try:
        session = ChatSession.objects.get(pk=session_id, job=job)
    except ChatSession.DoesNotExist:
        return JsonResponse({'messages': []})
    # Surface user/assistant turns for display, but tag each assistant message with
    # the tool_call names that immediately preceded it (same AIMessage — see the
    # write order in chat_message below) so the frontend can show a "tool used"
    # chip. Absence of a chip is the signal that a reply had no backing tool call.
    messages = []
    pending_tools = []
    for m in session.messages.all():
        if m.role == ChatMessage.Role.TOOL_CALL:
            pending_tools.append(m.tool_name)
        elif m.role == ChatMessage.Role.USER:
            messages.append({'role': m.role, 'content': m.content, 'tools_used': []})
        elif m.role == ChatMessage.Role.ASSISTANT:
            messages.append({'role': m.role, 'content': m.content, 'tools_used': pending_tools})
            pending_tools = []
    return JsonResponse({'messages': messages})


@login_required
@require_POST
def chat_message(request, pk):
    job = _get_owned_job(request, pk)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'invalid JSON'}, status=400)

    user_text = body.get('message', '').strip()
    session_id = body.get('session_id')
    if not user_text:
        return JsonResponse({'error': 'empty message'}, status=400)
    if not session_id:
        return JsonResponse({'error': 'missing session_id'}, status=400)

    try:
        session = ChatSession.objects.get(pk=session_id, job=job)
    except ChatSession.DoesNotExist:
        return JsonResponse({'error': 'invalid session'}, status=404)

    # Save the user message BEFORE invoking the agent. This way, if the user
    # reloads during a slow inference, the page sees a pending user message and
    # starts polling — no message is lost and no re-send is needed.
    user_msg = ChatMessage.objects.create(
        session=session,
        role=ChatMessage.Role.USER,
        content=user_text,
    )

    # Build LangChain history from this session only (exclude the just-saved user msg
    # — we'll append it to input_messages manually so the order is correct).
    history = []
    for msg in session.messages.exclude(pk=user_msg.pk):
        if msg.role == ChatMessage.Role.USER:
            history.append(HumanMessage(content=msg.content))
        elif msg.role == ChatMessage.Role.ASSISTANT:
            history.append(AIMessage(content=msg.content))

    try:
        from pipeline.captions import _get_aspect_ratio
        vid_w, vid_h = _get_aspect_ratio(job.input_file.path)
        dims_note = (
            f"Video dimensions: {vid_w}×{vid_h} px "
            f"({'portrait' if vid_h > vid_w else 'landscape'}).\n"
            f"font_size is calibrated to a 1920×1080 render — font_size=72 scales to "
            f"{round(72 * vid_h / 1080)}px on this video. "
            f"At font_size=72, roughly {int(vid_w * 0.9 / (72 * vid_h / 1080 * 0.6))} characters fit per line. "
            "Adjust font_size and text length accordingly.\n"
        )
    except Exception:
        dims_note = ""

    video_filename = os.path.basename(job.input_file.name)

    system = SystemMessage(content=(
        # --- Identity ---
        "You are the editing assistant inside min_vid, a web app for adding captions "
        "and text overlays to videos. You are NOT a general-purpose AI. You have exactly "
        "the tools listed below — nothing more.\n\n"

        # --- Current video ---
        f"The user is editing: {video_filename}\n"
        f"{dims_note}"
        f"Pipeline state: "
        f"transcript={'ready' if job.transcript else 'not yet generated'}, "
        f"timeline assets={len(job.assets) if job.assets else 0}, "
        f"uploaded files={job.uploaded_assets.filter(kind='image').count()}.\n"
        "Ground any suggestions in this state — e.g. do not suggest styling, editing, "
        "or generating captions if timeline assets is 0 or transcript is not yet generated; "
        "suggest transcribing first instead.\n\n"

        # --- App context: what the agent cannot do ---
        "WHAT YOU CANNOT DO — be direct about these limits:\n"
        "- You cannot accept a new VIDEO upload via chat. If the user wants to work on a "
        "different video, they should go back to the home page and upload a new file.\n"
        "- You CAN place images/PDF pages onto the video, but only ones the user already "
        "uploaded from the Assets panel's Upload button — you cannot receive files through chat. "
        "Use list_uploaded_files to see what's available and insert_image_asset to place one.\n"
        "- You cannot download or fetch videos from external URLs.\n"
        "- You cannot edit the video content (cut, trim, merge, add music, etc.) — "
        "only captions, text overlays, and uploaded images.\n"
        "- You cannot render or export the video — there is no render tool. Exporting only "
        "happens when the user clicks the \"Export\" button in the top-right corner of the page. "
        "If asked to export or download, tell the user to use that button.\n"
        "- The browser preview is intentionally lower resolution than the final video — this is "
        "by design, so edits play back instantly in real time. It is not a bug. The exported file "
        "from the \"Export\" button is full quality.\n\n"

        # --- Tool usage rules ---
        "TOOL USAGE RULES — follow these strictly:\n"
        "1. Only call a tool when the user explicitly asks for that action. "
        "Never auto-chain to the next pipeline step without being asked.\n"
        "2. transcribe_video: only when the user asks to transcribe, OR when they ask "
        "a question about the video's spoken content and no transcript exists yet. "
        "After transcribing to answer a content question, answer it — do NOT then call generate_captions.\n"
        "3. generate_captions: only when the user explicitly asks to generate, add, or build captions.\n"
        "4. For edits (text, position, color, size, font, deletions): use update_asset or delete_asset. "
        "These take effect instantly in the browser — no re-render needed.\n"
        "5. insert_image_asset: only when the user explicitly asks to place/add an uploaded image "
        "or PDF page onto the video. If you don't already know its file id, call list_uploaded_files "
        "first — match by filename/description rather than guessing.\n"
        "6. update_image_asset: for styling an image already on the timeline (rounded corners, "
        "opacity, border). Use read_assets first to get its ID — never use update_asset for images.\n"
        "7. Never tell the user a change was made unless you actually called the corresponding tool "
        "and got back a successful tool_result for it in this turn. Do not narrate an action as done "
        "from memory of a past turn or assumption — if unsure whether something is already applied, "
        "call read_assets to check first.\n\n"

        # --- Style ---
        "STYLE: Be concise and direct. No emojis. No bullet-point menus unless asked. "
        "If a tool returns an error, report it plainly — do not speculate beyond what the error says. "
        "When in doubt about what the user wants, ask one short question."
    ))

    agent = build_agent(job_pk=job.pk, video_path=job.input_file.path)
    input_messages = [system] + history + [HumanMessage(content=user_text)]
    result = agent.invoke(
        {"messages": input_messages},
        config={"callbacks": [LLMCallbackHandler(session_pk=session.pk)]},
    )

    # Everything the agent produced after our input
    new_messages = result["messages"][len(input_messages):]

    reply = "Done."
    # Every tool actually invoked this turn, in call order — returned to the
    # frontend so it can render a "tool used" chip. An empty list here despite a
    # confident-sounding reply is exactly the hallucinated-success case we've hit
    # before (the model claims a change without calling the tool that makes it).
    tools_used = []

    for msg in new_messages:
        if isinstance(msg, AIMessage):
            usage = msg.usage_metadata or {}
            prompt_tokens = usage.get("input_tokens")
            completion_tokens = usage.get("output_tokens")

            # Tool-call decision(s) — one DB record per tool invoked
            for tc in (msg.tool_calls or []):
                tools_used.append(tc.get("name"))
                ChatMessage.objects.create(
                    session=session,
                    role=ChatMessage.Role.TOOL_CALL,
                    tool_name=tc.get("name"),
                    content=json.dumps(tc.get("args", {})),
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            # Final reply (AIMessage with actual text content)
            if msg.content:
                reply = msg.content
                ChatMessage.objects.create(
                    session=session,
                    role=ChatMessage.Role.ASSISTANT,
                    content=reply,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
        elif isinstance(msg, ToolMessage):
            ChatMessage.objects.create(
                session=session,
                role=ChatMessage.Role.TOOL_RESULT,
                tool_name=getattr(msg, "name", None),
                content=msg.content,
            )

    job.refresh_from_db()
    return JsonResponse({
        'reply': reply,
        'tools_used': tools_used,
        'stage': job.stage,
        'status': job.status,
        'output_url': job.output_file.url if job.output_file else None,
    })
