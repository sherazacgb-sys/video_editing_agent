# UI Map

Where things actually are in the app. Kept in sync with the templates by hand —
see the rule in `CLAUDE.md` ("UI map"). This file is read at runtime by the
`read_ui_map` chat-agent tool (`pipeline/tools.py`), so keep it accurate and
free of internal jargon the agent shouldn't repeat verbatim to a user.

## Public site layout (`portfolio/templates/portfolio/base.html`) — shared by the homepage, Privacy notice and Terms of use

Every public page (not the video app) has the same sticky top bar and footer
described under the homepage below. Their section links always go to the
sections on the homepage, so from another page they take you to the homepage and
scroll to that section. The "Sheraz Labs" wordmark in the top bar and footer
goes to the homepage. "Back to top" scrolls to the top of whichever page you're on.
This is a different layout from the video app's `videos/templates/videos/base.html`.

## Public homepage (`/`, `portfolio/templates/portfolio/index.html`) — uses the public site layout above

The site's actual root — Sheraz's personal homepage (who Sheraz is and what
Sheraz builds), not the video tool itself, and not gated by sign-in or guest
identity. Anyone can view it. The video tool is the Video Editing Agent, reached at
`/upload/`. Bright, full-width layout (white/light-gray alternating bands,
card grids) with a blue accent for anything clickable, yellow reserved for
the headline underline, and teal for "Live" badges.

- **Sticky top bar** (stays visible while scrolling, one row): "Sheraz Labs"
  wordmark on the left (goes to the homepage / its top); section links on the
  right — Products, Case studies, Blog, About (Blog opens the `/blog/` page and
  About the `/about/` page; the others jump to homepage sections). On small screens
  (phones, narrow windows) those links are replaced by a **menu button**
  (three-line icon) at the top right; tapping it opens a dropdown under the
  header with the same four links, and tapping a link or the X closes it.
  Nothing else is in the header: no GitHub/LinkedIn icons and no "Let's
  talk" button (those live in the hero, the contact band and the footer).
  There is no scroll-progress bar or section-jump strip under it.
- **Hero** (top of the page): two columns. Left: the "From chatbots to pipelines — AI
  that actually does the work." headline ("does the work" underlined in
  yellow), then a short intro line ("I'm Sheraz, an AI engineer in
  London..."), a "See my
  work" button (jumps to Products) and a "Let's talk" button
  (jumps to contact). Right: a decorative agent-graph illustration (request →
  agent → four tool chips → "Deployed" badge); nothing in it is clickable.
- **Credentials strip**: a white band under the hero. A small centred label
  on top reads "The foundations behind the builds"; below it is a row of pill
  badges that slowly slides right-to-left in a loop (it pauses while the
  mouse is over it). Blue badges are certifications — AWS Solutions
  Architect – Associate (SAA-C03), Google Project Management, Google Data
  Analytics; yellow badges are degrees — MSc Data Science (Kingston
  University London), BS Computer Science (University of Sialkot). None of
  them are clickable. If the device is set to reduce motion, the badges sit
  still in a centred row instead of moving.
- **Tools strip**: directly under the credentials strip, in the same white
  band. A small centred label reads "The stack I ship with"; below it is a
  row of plain white pill badges, each showing a tool's logo and name —
  LangGraph, LangChain, Gemini, Groq, DeepSeek, Whisper, scikit-learn,
  TensorFlow, OpenCV, pandas, NumPy, Python, Django, PostgreSQL, FFmpeg, AWS,
  Docker, Nginx, Linux, Git. It slides the opposite way to the credentials
  row (left-to-right) and also pauses on hover. None are clickable. With
  reduced motion it sits still in a centred, wrapping row.
- **Section headings (homepage)**: every section below the strips opens with
  its name as a large bold heading — "Products", "Case studies", "Blog", "About" — and (except About) a one-line grey subtitle under it.
  There are no small uppercase section labels any more.
- **Products** — CURRENTLY HIDDEN: this section is not shown on the homepage
  right now (the nav/footer "Products" links jump nowhere). When restored:
  (subtitle "Finished and published. Things you can use
  today."): one wide card for **Work Box**, the Android shift & pay tracker.
  Left: the app icon, the name with a green "Live on Google Play" tag, a short
  description, three fact chips (500+ downloads, one-time Pro, offline
  on-device data) and a black "Get it on Google Play" button that opens the
  Play Store listing in a new tab. Right: a grey "What it does" panel with
  four ticked features. Nothing else in the card is clickable.
- **Case studies** (subtitle "Experiments and research: what AI can do when
  it is built properly."): one large card titled "Video Editing Agent" with a
  blue "Research prototype" tag. Left: the problem, three "hard problems
  solved" points, a "Read case study" button (not wired to a page yet) and a
  "Try the research demo" button (`/upload/`).
  Right: the real C4 container architecture diagram as a thumbnail — clicking
  it opens the full-size image in a new tab.
- **Blog** (subtitle "Build logs and bug war stories."): up to three cards for
  the newest published posts (kind label, title, summary, date and "N min
  read"); clicking a card opens that post. An "All posts →" link under them goes
  to `/blog/`. With nothing published yet, the cards are replaced by one white
  box saying "First posts coming soon" (not clickable).
- **About**: a small round photo of Sheraz with name and role, two short bio
  paragraphs, and a "More about me" link to the `/about/` page.
  ("What I build" is no longer on the homepage; it moved to the About page.)
- **Closing call-to-action**: a dark band near the bottom with a "Working on
  an AI system? Let's talk." heading and a yellow "Email me" button.
- **Footer**: five columns on wide screens (two per row on tablets, one on
  phones). (1) The wordmark, a one-line description, and a row of three round
  icon buttons — GitHub, LinkedIn, email — that turn blue on hover. (2)
  "Explore": Products and Case studies (homepage sections), Blog (the
  `/blog/` page) and About (the `/about/` page). (3) "Products": Work Box with a green "Live" tag (→ its Google
  Play listing, new tab). (4) "Case studies": Video Editing Agent with a blue
  "Prototype" tag (→ the Case studies section on this page). (5) "Connect": GitHub, LinkedIn, the email address and CV,
  each with its logo/icon in a small square beside the name (CV isn't
  uploaded yet, so that link goes nowhere). Bottom bar: "© <year> Sheraz
  Ali. Built with Django, deployed on AWS." on the left; on the right,
  "Privacy notice" and "Terms of use" links (to `/privacy/` and `/terms/`)
  and a "Back to top ↑" link.

## About page (`/about/`, `portfolio/templates/portfolio/about.html`) — uses the public site layout

Sheraz's long-form About page, reached from "About" in the top bar, the footer's
Explore column, and the homepage's "More about me" link. Top to bottom:

- **Intro**: on the left, a round photo of Sheraz with three round icon buttons
  under it — Email (opens your email app), LinkedIn and GitHub (new tab); they
  turn blue on hover. On the right, the big "Hi, I'm Sheraz." heading, a small
  blue "AI engineer · London" line, and two short paragraphs. On phones the photo
  and icons sit on top, centred, with the text below.
- **How I got here**: on wide screens the heading sits on the left and the
  story on the right (stacked on phones). Four paragraphs of Sheraz's story (electronics store →
  CS degree and AssistivePro → Django developer → MSc and placement in London →
  agentic AI now). "Video Editing Agent" links to the homepage's Case studies
  section; "Work Box" opens its Google Play listing in a new tab.
- **What I build**: the three cards that used to be on the homepage — Agentic
  workflows ("See the Video Editing Agent" → homepage Case studies section),
  AI-powered media & automation ("Try the research demo" → `/upload/`), Cloud
  deployment on AWS ("View the architecture" → the full diagram image).
- **Toolkit**: the same tool badges as the homepage strip, standing still and
  grouped under three small labels: AI and machine learning, Backend and data,
  Cloud and infrastructure. None are clickable.
- **Experience and education**: two timelines side by side (stacked on
  phones), newest first. Experience: the placement at a facilities services
  company (not named), Junior Django Developer, Assistant Manager at an
  electronics store. Education and certifications: MSc Data Science, BS
  Computer Science, AWS Solutions Architect – Associate, Google certificates.
  Nothing is clickable.
- **Closing call-to-action**: the same dark "Working on an AI system? Let's
  talk." band with the yellow "Email me" button as on the homepage.

## Blog list page (`/blog/`, `portfolio/templates/portfolio/blog_list.html`) — uses the public site layout

Reached from "Blog" in the top bar and footer, and "All posts →" on the homepage.

- **Top band**: big "Blog" heading, a one-line intro, and a row of round
  **filter buttons**: All, Build logs, War stories, Notes. The selected one is
  filled blue; clicking another shows only that kind (the address gets
  `?kind=...`).
- **Post cards**: a grid of every published post, newest first (same cards as
  the homepage). Clicking a card opens the post.
- **Empty state**: if nothing matches, a white box says "Nothing here yet"
  (with a "See all posts" link when a filter is on).
- Posts are written and published by the site owner in Django admin
  (Portfolio → Posts); drafts never appear here.

## Blog post page (`/blog/<slug>/`, `portfolio/templates/portfolio/post_detail.html`) — uses the public site layout

- **"← All posts"** link at the top, back to `/blog/`.
- **Header**: kind label in blue, the title, the summary in larger grey text, then
  "Sheraz Ali · date · N min read".
- **Article body**: the post text (headings, lists, links, dark code blocks,
  tables, images).
- **Bottom of the article**: "← More posts" (back to `/blog/`) on the left and,
  if the post is also on Medium, an "Also on Medium" button (new tab) on the right.
- Then the same dark "Let's talk" band as the homepage.
- **Draft preview** (site owner only, when logged into admin): a yellow box
  at the top says "Draft preview. Only you can see this post." with a link to edit it
  in admin. Everyone else gets "page not found" for unpublished posts.

## Privacy notice page (`/privacy/`, `portfolio/templates/portfolio/privacy.html`) — uses the public site layout

- **Top bar and footer**: the same sticky top bar (wordmark + section links /
  menu button) and full footer as the homepage. There is no separate "← Back to
  home" link any more; the wordmark goes home.
- **Page body**: one white document card with the "Privacy notice" title, a
  yellow "short version" box at the top (asks people not to upload anything
  personal), then numbered sections: who runs the site, 18+ only, what is
  collected, lawful basis, providers (AWS London, Groq US, DeepSeek China),
  international transfers, retention times, cookies, your rights (email
  sherazacgb@gmail.com), complaints (ICO), changes.
- Linked from: the homepage footer's bottom bar, the guest screen's agreement
  checkbox, the note under the upload page's Continue button, and the cookie
  banner.

## Terms of use page (`/terms/`, `portfolio/templates/portfolio/terms.html`) — uses the public site layout

- Same top bar, document card and footer as the Privacy notice page above.
- **Page body**: "Terms of use" title, a yellow "short version" box (free
  research demo, may break or disappear, never upload anything personal),
  then numbered sections: about the terms (links to the privacy notice), 18+
  only, research demo not a product, what you can upload, acceptable use, AI
  output can be wrong, no guarantees, liability, the site itself, changes,
  law (England and Wales), contact email.
- Linked from the same places as the privacy notice.

## Layout shared by every page inside the app (`videos/templates/videos/base.html`)

- **Left sidebar** (`<aside>`, far left edge of the screen). Its contents
  depend on the page — see below, it is NOT always the job list.
- **Main panel** (everything right of the sidebar) — page-specific content.

### Upload page (`/upload/`) main area
- The drop zone, then the "Continue" button that sends the video. Directly
  under the button, a small note: "Research demo: please don't upload anything
  personal or confidential." with "Terms of use" and "Privacy notice" links
  (open in a new tab). Shown to guests and signed-in users alike.

### Left sidebar on the upload page and anywhere else that doesn't override it
- Top: a small grey "← Sheraz Labs" link (goes back to the public homepage,
  `/`), then the "Video Editing Agent" logo/link (goes to the upload page).
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
tries to reach the upload page or anything past it — a brand-new visitor can
freely browse the public homepage (`/`) first, and only hits this gate once
they click into "Video Agent" (`/upload/`) or a job page.

- Top-left, above the "Video Editing Agent" title: a small grey "← Back to
  Sheraz Labs" link to the public homepage (`/`).
- Guest-only for now — the username/password sign-in form is commented out in
  the template (not deleted; there's no working sign-up flow yet, so there'd
  be no account to sign in with). Re-enable it once sign-up exists.
- A short required intake form: "Where did you get this link?" (text), "What
  are you going to use this for?" (textarea), and "Are you looking for an AI
  engineer for your projects?" (yes/no) — answers are saved as a
  `GuestIntake` row (browsable in Django admin) the moment the guest identity
  is minted. All three are required (HTML `required`, backed by a server-side
  check in `continue_as_guest`); leaving one blank on a raw POST redirects
  back here with an error message instead of silently dropping the data.
- An unticked **agreement checkbox** just above the button: "I'm 18 or over,
  I agree to the Terms of use, and I won't upload anything personal or
  confidential. See the Privacy notice." — both links open in a new tab. It
  must be ticked to continue (also re-checked on the server).
- "Continue as guest" button submits the intake form, skips creating an
  account, and goes straight to the upload page. Under it, a small note:
  "Guest uploads are deleted after about 6 hours."
- Once a guest identity is minted (or a session exists), the choice sticks for
  that browser — this page isn't shown again until it expires.

## Cookie consent banner — bottom bar, appears on every page until dismissed

A bar fixed to the bottom of the screen (on top of everything, including the
login page) explaining the site uses a necessary cookie for sessions/guest
identity, with a "Privacy notice" link and "Reject" and "Accept" buttons. Shown once per browser the
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
