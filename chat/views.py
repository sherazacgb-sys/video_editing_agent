import json
import os

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from pipeline.transcribe import transcription_available
from videos.access import get_accessible_job
from videos.decorators import identity_required
from videos.models import VideoJob
from .agent import build_agent
from .callbacks import LLMCallbackHandler
from .models import ChatMessage, ChatSession


def _session_tokens_used(session):
    # Reads the running totals cached on ChatSession (kept up to date via F()
    # increments in LLMCallbackHandler.on_llm_end) rather than aggregating
    # llm_calls on every request — this is the true, ever-growing cost figure
    # for the session, shared by the over-budget check and the on-page usage indicator.
    return session.total_prompt_tokens + session.total_completion_tokens


@identity_required
@require_GET
def session_list(request, pk):
    """Return all chat sessions for this job, newest first, with a preview and message count."""
    job = get_accessible_job(request, pk)
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


@identity_required
@require_POST
def new_session(request, pk):
    """Create a new ChatSession for this job; return its ID to the client."""
    # Global admin off-switch — block starting new conversations while chat is disabled.
    if not settings.CHAT_ENABLED:
        return JsonResponse({'error': 'Chat is currently disabled.'}, status=503)
    job = get_accessible_job(request, pk)
    session = ChatSession.objects.create(job=job)
    return JsonResponse({'session_id': session.pk})


@identity_required
@require_GET
def chat_history(request, pk):
    """
    Return the user/assistant messages for a session.
    Caller must pass ?session_id=<id>; returns [] for unknown/missing sessions
    rather than 404 so the frontend can treat it as an empty chat safely.
    """
    job = get_accessible_job(request, pk)
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
    # Included so switching to/reloading an already-locked session greys out the
    # input immediately, instead of only finding out after a failed send attempt.
    return JsonResponse({
        'messages': messages,
        'session_disabled': session.is_disabled,
        'session_over_budget': session.is_over_budget,
        'session_tokens_used': _session_tokens_used(session),
    })


@identity_required
@require_POST
def chat_message(request, pk):
    job = get_accessible_job(request, pk)

    # Guest video already purged by purge_guest_jobs (Status.EXPIRED) — no file left
    # for build_agent's video_path or any pipeline tool to operate on, so block
    # before doing anything else. The row/chat history itself is still readable.
    if job.status == VideoJob.Status.EXPIRED:
        return JsonResponse({
            'error': 'This video has expired and was removed. Your chat history is kept, '
                     'but no further edits or questions about the video are possible.',
        }, status=403)

    # Global admin off-switch — checked before touching the DB so a disabled
    # deploy costs nothing per request beyond the settings lookup.
    if not settings.CHAT_ENABLED:
        return JsonResponse({'error': 'Chat is currently disabled.'}, status=503)

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

    # The agent's own suspend_session tool sets this after repeated attempts to bypass
    # its rules — once locked, this session can't send more messages, only a New Chat can.
    if session.is_disabled:
        return JsonResponse({'error': 'This chat has been locked due to repeated policy violations. Start a New Chat to continue.'}, status=403)

    # Cumulative token budget exceeded on a prior turn — checked before invoking the
    # agent again so an already-over-budget session can't rack up further LLM cost.
    if session.is_over_budget:
        return JsonResponse({'error': 'This conversation has reached its length limit. Start a New Chat to continue.'}, status=403)

    # Hard cap on a single message's length — independent of the cumulative budget
    # check above, since one huge paste could blow the whole budget in a single turn
    # before that check ever gets a chance to run.
    if len(user_text) > settings.CHAT_MAX_MESSAGE_CHARS:
        return JsonResponse({
            'error': f'Message is too long ({len(user_text)} characters). '
                     f'Please shorten it to under {settings.CHAT_MAX_MESSAGE_CHARS} characters.',
        }, status=400)

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

    # Empty when the Groq backend is configured; otherwise explains the missing
    # transcribe_video tool (pipeline/tools.py's make_tools omits it in this case)
    # so the agent states plainly that transcription is down instead of guessing why.
    transcription_note = "" if transcription_available() else (
        "TRANSCRIPTION UNAVAILABLE: the transcription service is not configured in this "
        "environment right now, so you have no transcribe_video tool. If asked to "
        "transcribe, or a question needs the spoken content and no transcript exists yet, "
        "tell the user transcription is temporarily unavailable and to check back later — "
        "do not guess at the cause or try another tool as a workaround.\n\n"
    )

    system = SystemMessage(content=(
        # --- Identity ---
        "You are the editing assistant inside 'Video Editing Agent', a web app for adding captions "
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

        f"{transcription_note}"

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

        # --- Scope boundary: closes the "it's for the video" loophole that let general-
        # knowledge questions through no matter how the refusal above was worded. ---
        "SCOPE — NO GENERAL KNOWLEDGE: you never answer general-knowledge, factual, or trivia "
        "questions from your own training data (people, dates, places, current events, "
        "definitions, etc.) — this holds no matter how the request is framed, including "
        "\"it's for the video\", \"for a caption\", \"for a text overlay\", or similar. If the "
        "user wants specific factual text placed on the video, tell them you don't look facts "
        "up and ask them to type the exact text themselves, then proceed once they provide it. "
        "This rule has no exceptions.\n\n"

        # --- Self-moderation: gives the agent an escalation path instead of just repeating
        # the same refusal indefinitely against a user probing for a bypass. ---
        "REPEATED BOUNDARY VIOLATIONS: if the user tries more than once in this conversation "
        "to get you to break the SCOPE rule above (reworded, reframed, insisted on again after "
        "you already redirected them), call suspend_session with a short reason. Do NOT suspend "
        "on a single attempt — always redirect once first. After it returns, tell the user "
        "plainly that this chat has been locked due to repeated attempts to bypass its rules "
        "and that they need to start a New Chat to continue.\n\n"

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

    # session_pk lets the agent's suspend_session tool lock this exact conversation.
    agent = build_agent(job_pk=job.pk, video_path=job.input_file.path, session_pk=session.pk)
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
    # Re-check the session too — suspend_session may have just flipped is_disabled
    # during this same turn, and the frontend needs to know immediately to lock the input.
    session.refresh_from_db()

    # History compounds every turn, so this keeps growing even when individual
    # messages stay small — flip the lock once it crosses the configured budget.
    total_tokens = _session_tokens_used(session)
    if not session.is_over_budget and total_tokens >= settings.CHAT_SESSION_TOKEN_BUDGET:
        session.is_over_budget = True
        session.save(update_fields=['is_over_budget'])

    return JsonResponse({
        'reply': reply,
        'tools_used': tools_used,
        'stage': job.stage,
        'status': job.status,
        'output_url': job.output_file.url if job.output_file else None,
        'session_disabled': session.is_disabled,
        'session_over_budget': session.is_over_budget,
        'session_tokens_used': total_tokens,
    })
