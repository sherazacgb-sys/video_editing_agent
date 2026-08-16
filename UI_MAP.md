# UI Map

Where things actually are in the app. Kept in sync with the templates by hand —
see the rule in `CLAUDE.md` ("UI map"). This file is read at runtime by the
`read_ui_map` chat-agent tool (`pipeline/tools.py`), so keep it accurate and
free of internal jargon the agent shouldn't repeat verbatim to a user.

## Layout shared by every page (`videos/templates/videos/base.html`)

- **Left sidebar** (`<aside>`, far left edge of the screen). Its contents
  depend on the page — see below, it is NOT always the job list.
- **Main panel** (everything right of the sidebar) — page-specific content.

### Left sidebar on the upload page and anywhere else that doesn't override it
- Top: "Video Editing Agent" logo/link (goes to the upload page).
- Middle: list of the user's video jobs, each row a thumbnail + filename +
  status (Pending/Processing/Done/Failed). A trash-can icon appears on hover
  to delete that job.
- Bottom: theme toggle (sun/moon icon, "Dark mode"/"Light mode" label), then one
  of three things depending on identity: the signed-in user's avatar/username
  (click opens a dropdown with plan badge, "Upgrade" link if on Free, and "Sign
  out"); a guest's "Guest-xxxx" label (short id) with a note underneath that
  video isn't saved and chat is kept briefly, linking to the login page to
  sign in; or, for a not-yet-identified visitor, a plain "Sign in" link (rare —
  see the login-page gate below, which normally intercepts before this point).

### Left sidebar on a job's detail page (`job_detail.html`) — REPLACED with the chat panel
On this page the sidebar is NOT the job list — it becomes the **chat/agent
panel**:
- Top row: "History ▾" (click to drop down a list of past chat sessions for
  this job) on the left, "New Chat" button on the right, sharing one row.
- Directly under that row: a thin hairline progress line (no text) showing how
  much of this session's token budget has been used — turns amber near the
  limit, red once a New Chat is required. Hover it for the exact numbers/percent.
- The chat message feed (scrolls).
- Bottom: text input + "Send" button to talk to the agent. The Send button
  itself fills like a rising water level as you type, showing how close the
  message is to the length limit (dark tint climbing, then red once actually
  over the limit and Send is blocked) — hover the button for the exact "N /
  max" character count.
- The job list + profile footer from the default sidebar are not shown here.

## Login page (`user_accounts/templates/registration/login.html`) — standalone, not part of base.html's layout

Shown to anyone not yet identified (no account session, no guest cookie) who
tries to reach any page — e.g. a brand-new visitor hitting the site for the
first time lands here before the upload page, not after it.

- Username/password fields + "Sign in" button.
- Below a divider: a "Continue as guest" button — skips creating an account
  and goes straight to the upload page. A line under it warns that guest
  videos aren't saved and sign-in is needed to keep/export them.
- Once either path is taken, the choice sticks for that browser (a signed-in
  session or a guest cookie) — this page isn't shown again until both expire.

## Cookie consent banner — bottom bar, appears on every page until dismissed

A bar fixed to the bottom of the screen (on top of everything, including the
login page) explaining the site uses a necessary cookie for sessions/guest
identity, with "Reject" and "Accept" buttons. Shown once per browser the
first time any page loads, then not shown again once either button is
clicked. Reject doesn't currently disable anything (there's no tracking/ad
cookie to gate) — it just records the choice.

## Feedback modal — job detail page, right-docked overlay

A true modal — dims the whole page — but the panel itself is docked to the
right edge instead of centered: a 1-5 star rating plus an optional comment
box, "Submit" or "Maybe later" to close. Two ways to open it:
- **Automatic**: guests only, pops up once per video the first time it reaches
  a real result (captions/overlay applied — export itself is Pro-only so
  guests don't get that far). Won't reopen for that same job again once
  shown (submitted or dismissed either way).
- **Manual**: a "Feedback" button in the job detail header bar (next to
  Export), available to everyone — guest or signed-in — anytime, as many
  times as they like.

## Job detail page main panel (`job_detail.html`)

- **Header bar** (top): filename on the left. On the right, a "Feedback"
  button (everyone, opens the feedback modal — see below) always shows, then
  Pro-plan users additionally see a resolution dropdown (Original/1080p/720p/
  480p) and an "Export" button that renders and downloads the final video.
  Free-plan users don't see the export controls, just Feedback.
- **Video player** (left side, larger): shows the original upload before
  captions/overlays exist, or the live preview once they do. Underneath it is
  a custom playback bar (play/pause button, elapsed/total time, a seek bar
  you can click or drag to scrub, and a mute button) — not the browser's
  built-in video controls. Hovering the seek bar shows a small tooltip with
  the timestamp under the cursor.
  - **Expired guest video**: once a guest's video has been purged (past the
    retention window), this area shows a plain text notice instead — "This
    video has expired and was removed" / "Your chat history is kept a bit
    longer" — no player, no controls. The chat input below is greyed out
    with a matching placeholder and can't be used again (unlike a locked
    session, "New Chat" doesn't undo this — the video itself is gone).
- **Right panel** (right side of the video, a boxed panel). Has a row of
  plain text tab labels at the top — no icons on any of them:
  - **Skills** tab (default/first tab): a grid of cards, one per thing the
    agent can do (Transcribe, Generate Captions, Add Text Overlay, Place an
    Image, Check Transcript Quality, Restyle Captions). Clicking a card drops
    a ready-made prompt into the chat input for the user to edit or send —
    it does NOT run anything by itself, and there's no status/progress shown
    here. Progress for a running action shows up in the chat instead (a small
    tool-name chip on the agent's reply once it's done).
  - **Assets** tab: an "+ Upload" button (for images/PDFs) at the top, then
    collapsible sections you click to expand/collapse:
    - **Transcript** — the full plain-text transcript, read-only.
    - **Uploaded Files** — images/PDF pages uploaded but not yet placed on
      the video.
    - One section per asset type currently on the timeline (e.g. Captions,
      Text, Images), each listing that asset's text/filename and time range.
  - **Fonts** tab: a grid of font preview cards; clicking one inserts that
    font's name into the chat input box.
  - **Welcome** tab: a rotating tips carousel (informational only).
  - A "▴ Hide" / "▾ Show" button on the far right of the tab bar
    collapses/expands the whole pipeline panel.
- **Timeline** (bottom, spans the full width, only appears once assets
  exist): a horizontal track view of every asset on the video, grouped by
  layer/type. Hovering it shows a tooltip with the timestamp under the
  cursor.

## Answering "where is X" questions

- Transcript → Assets tab → "Transcript" section (job detail page, main
  panel, NOT the sidebar).
- Export/download → header bar, top right, Pro plan only. The Export button
  itself turns into a progress bar while rendering, and shows "Export failed"
  + a "Retry" button if the render fails — there's no separate status panel.
- Uploading an image/PDF → Assets tab → "+ Upload" button.
- Changing fonts → Fonts tab (browse/click to insert a name), then ask the
  agent in chat to apply it — the Fonts tab itself doesn't apply anything.
- Running an action (transcribe, add a text overlay, etc.) without typing it
  from scratch → Skills tab → click the card, edit the inserted prompt if
  needed, then press Send.
- Chat history → in the left sidebar's "History" bar, only on the job detail
  page.
- A locked chat ("This chat has been locked…" placeholder, input greyed out) →
  either the agent suspended it after repeated attempts to bypass its rules,
  or the session hit its cumulative token budget (see the thin progress line
  above the chat feed, under the History/New Chat row). Either way it can't be
  unlocked — click "New Chat" to start a fresh, working session.
- "Why can't I send this message" / message length limit → the Send button
  fills up like water as the message gets longer and turns solid red once it
  blocks Send for being too long; shorten the message and resend.
- Theme (dark/light) and sign-out → bottom of the left sidebar, on every page
  except job detail (where the sidebar is the chat panel instead).
- Using the app without an account → the login page's "Continue as guest"
  button (shown automatically to any not-yet-identified visitor). Guest
  videos aren't saved on the system and can't be exported — sign in for that.
- "Where does it say I'm a guest" → bottom of the left sidebar, on every page
  except job detail (same spot the profile/sign-in footer lives) — shows
  "Guest-xxxx" plus a note that video isn't saved and chat is kept briefly.
- Cookie notice → a bar at the very bottom of the screen, any page, until
  Accept/Reject is clicked once.
- "Why is this job greyed out / my chat won't respond anymore" → the guest
  video retention window has passed (see purge_guest_jobs) — the video file
  is deleted and the job shows "Expired" in the sidebar; the chat panel
  explains the video was removed and stays locked, but past messages are
  still visible until the longer chat retention window passes too.
- "A box popped up on the right asking me to rate/comment" → the feedback
  modal (job detail page). It auto-shows once per video for guests after
  captions/overlay are applied; anyone (guest or signed-in) can also open it
  anytime via the "Feedback" button in the header bar. "Maybe later" or the
  &times; closes it without submitting.
- Leaving feedback intentionally → header bar → "Feedback" button (works for
  everyone, any time — not just the guest auto-popup).
