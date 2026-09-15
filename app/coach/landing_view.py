"""The public product story: enough to understand Power AI, then try it.

Detailed architecture, deployment instructions and evidence belong in the
repository.  The landing page stays focused on the coach's job, the agent loop
and the boundary between automation and human judgement.
"""

from __future__ import annotations


_GITHUB = "https://github.com/Shlok-K-ps/training-log-agent"
_BOLT = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13.5 2 4 13.5h7L10 22l10-12h-7z"/></svg>'


def render_landing() -> str:
    """Render a short, scannable public landing page."""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>Power AI — The training-day agent</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>⚡</text></svg>">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400..800&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/static/tokens.css">
  <link rel="stylesheet" href="/static/app.css">
  <style>
    .lean-hero{{padding-bottom:56px}}
    .lean-hero .hero-lead{{max-width:720px}}
    .lean-proof{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:34px 0 26px}}
    .lean-proof div{{padding:16px 18px;border-radius:16px;background:var(--card);box-shadow:var(--shadow-card)}}
    .lean-proof b{{display:block;margin-bottom:4px;font-size:16px}}
    .lean-proof span{{color:var(--text-2);font-size:14px;line-height:1.4}}
    .lean-example{{max-width:820px;margin:0 auto}}
    .lean-example .showcase-body{{padding:22px}}
    .lean-example-note{{margin:14px 0 0;color:var(--text-2);font-size:13px;text-align:center}}
    .lean-section{{padding-top:72px}}
    .agent-parts{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:24px}}
    .agent-part{{padding:18px;border-radius:18px;background:var(--card);box-shadow:var(--shadow-card)}}
    .agent-part span{{display:block;margin-bottom:18px;color:var(--tint);font-size:12px;font-weight:750;letter-spacing:.06em}}
    .agent-part h3{{margin-bottom:7px;font-size:18px}}
    .agent-part p{{color:var(--text-2);font-size:14px;line-height:1.5}}
    .control-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-top:24px}}
    .control-card{{padding:20px 22px;border-radius:20px;background:var(--card);box-shadow:var(--shadow-card)}}
    .control-card h3{{margin:5px 0 12px;font-size:20px}}
    .control-card ul{{margin:0;padding-left:19px;color:var(--text-2);font-size:14px;line-height:1.75}}
    .lean-cta{{margin-top:72px;padding:48px 24px;border-radius:28px;background:var(--card);box-shadow:var(--shadow-card);text-align:center}}
    .lean-cta h2{{margin:8px auto 10px;max-width:680px;font-size:clamp(30px,5vw,52px);letter-spacing:-.045em}}
    .lean-cta p{{max-width:590px;margin:0 auto;color:var(--text-2);line-height:1.55}}
    .lean-cta .cta-row{{justify-content:center}}
    @media(max-width:820px){{.agent-parts{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
    @media(max-width:640px){{.lean-proof,.agent-parts,.control-grid{{grid-template-columns:1fr}}.lean-section{{padding-top:52px}}.lean-cta{{margin-top:52px;padding:36px 18px}}}}
  </style>
</head>
<body>
  <header class="site-header">
    <div class="site-header-inner">
      <a class="brand-link" href="/">
        <span class="mac-app-icon" aria-hidden="true">{_BOLT}</span>
        <span class="brand-name">Power AI</span>
        <span class="brand-badge">Training-day agent</span>
      </a>
      <nav class="site-nav">
        <a class="nav-link" href="#how-it-works">How it works</a>
        <a class="nav-link" href="{_GITHUB}" target="_blank" rel="noopener">GitHub &nearr;</a>
        <a class="nav-link" href="/coach">Coach console</a>
        <a class="btn btn-mac-primary" href="/demo">Watch the demo</a>
      </nav>
    </div>
  </header>

  <main class="wrapper">
    <section class="hero lean-hero">
      <div class="mac-pill-eyebrow"><span class="mac-pill-icon">⚡</span> Built for powerlifting coaches</div>
      <h1 class="hero-h1">The agent runs the training day.<br><span class="serif">The coach handles the exceptions.</span></h1>
      <p class="hero-lead">Power AI checks in with athletes on Telegram, follows the day through, and brings the coach only what needs human judgement.</p>
      <div class="cta-row">
        <a class="btn btn-mac-primary btn-lg" href="/demo" data-primary-cta>Watch the agent work &rarr;</a>
        <a class="btn btn-ghost btn-lg" href="{_GITHUB}" target="_blank" rel="noopener">View the code &nearr;</a>
      </div>
      <p class="hero-lead" style="font-size:14px;margin-top:10px">90-second fictional demo · no login · nothing sent</p>

      <div class="lean-proof" aria-label="What Power AI does">
        <div><b>Checks in first</b><span>Starts each planned training day without waiting for the coach.</span></div>
        <div><b>Handles the routine</b><span>Follows up, applies safe limits and records what happened.</span></div>
        <div><b>Escalates the exception</b><span>Stops on pain or risk and asks the coach to decide.</span></div>
      </div>

      <div class="showcase-container lean-example" aria-label="Example athlete message">
        <div class="messages-header"><span class="avatar" aria-hidden="true">{_BOLT}</span><span class="messages-contact">Power AI</span></div>
        <div class="showcase-body">
          <div class="chat-box">
            <div class="chat-bubble chat-athlete">slept 5h, knee hurts on stairs<span class="chat-meta">07:46</span></div>
            <div class="chat-bubble chat-agent">
              <div class="chat-reply-header"><span class="chat-verdict tag-act">Coach needed</span><span class="chat-meta">07:46</span></div>
              <div class="chat-logged-line">&check; Recovery low · pain reported</div>
              <div class="chat-body-line">Training guidance paused. The coach has the evidence and decision options.</div>
            </div>
          </div>
          <p class="lean-example-note">The language model reads the message. Tested rules decide when the agent must stop.</p>
        </div>
      </div>
    </section>

    <section id="how-it-works" class="content-section lean-section">
      <div class="section-head">
        <span class="mac-eyebrow">Four parts of the agent</span>
        <h2 class="section-title">It receives, reasons, acts, <span class="serif">and learns from history.</span></h2>
      </div>
      <div class="agent-parts">
        <article class="agent-part"><span>01 · RECEIVE</span><h3>Gets the signal</h3><p>Reads training, sleep, readiness and pain updates from Telegram.</p></article>
        <article class="agent-part"><span>02 · REASON</span><h3>Chooses the next step</h3><p>Turns the message into facts, then applies fixed coaching and safety rules.</p></article>
        <article class="agent-part"><span>03 · ACT</span><h3>Continues the work</h3><p>Sends check-ins, follow-ups, routine sessions and coach escalations itself.</p></article>
        <article class="agent-part"><span>04 · REMEMBER</span><h3>Improves the workflow</h3><p>Keeps every training day and safely adapts check-in timing from response history.</p></article>
      </div>
    </section>

    <section class="content-section lean-section">
      <div class="section-head">
        <span class="mac-eyebrow">Clear authority</span>
        <h2 class="section-title">Automation for repetition. <span class="serif">A coach for judgement.</span></h2>
      </div>
      <div class="control-grid">
        <article class="control-card"><span class="feature-badge badge-blue">THE AGENT HANDLES</span><h3>Routine training days</h3><ul><li>Scheduled check-ins and follow-ups</li><li>Coach-approved sessions within fixed limits</li><li>Outcome tracking and missed replies</li></ul></article>
        <article class="control-card"><span class="feature-badge badge-red">THE COACH DECIDES</span><h3>Anything outside the limits</h3><ul><li>Injuries and pain reports</li><li>Red recovery and unusual cases</li><li>Plans, clearances and policy changes</li></ul></article>
      </div>
    </section>

    <section class="lean-cta">
      <span class="mac-eyebrow">See the complete loop</span>
      <h2>Watch one fictional training day in 90 seconds.</h2>
      <p>The demo uses the real agent flow with temporary data. For architecture, tests and deployment instructions, use the GitHub repository.</p>
      <div class="cta-row">
        <a class="btn btn-mac-primary btn-lg" href="/demo">Watch the safe demo &rarr;</a>
        <a class="btn btn-ghost btn-lg" href="{_GITHUB}" target="_blank" rel="noopener">Read the technical details &nearr;</a>
      </div>
    </section>
  </main>

  <footer class="site-footer">
    <div class="wrapper"><div class="footer-bottom">
      <div>Power AI · Training Log Agent</div>
      <div><a href="/privacy">Privacy</a> · <a href="/terms">Terms</a> · <a href="{_GITHUB}" target="_blank" rel="noopener">GitHub</a></div>
      <div>The public demo is fictional. The real coach console is private.</div>
    </div></div>
  </footer>
</body>
</html>"""
