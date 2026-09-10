"""HTML views for the coach console, landing page, and legal notices.

Rendered server-side as pure strings with zero build step, no npm, and no JS framework.
Mobile-first layout designed for a coach on a phone at the gym or on a laptop.
"""

from __future__ import annotations

from html import escape

from app.coach.roster import BUCKET_LABEL, BUCKET_ORDER, Bucket, PendingMessage, Roster


# ------------------------------------------------------------------------------
# Base CSS: Powerlifting visual identity (calibrated plates palette, mobile-first)
# Red 25kg (Action/Deload), Yellow 15kg (Watch/Stall), Blue 20kg (Meet/Nav), Green 10kg (On track)
# ------------------------------------------------------------------------------
_BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;0,800;1,400&family=Newsreader:ital,opsz,wght@1,6..72,300;1,6..72,400;1,6..72,500&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
  --bg: #09090b;
  --surface: #101014;
  --surface-raised: #14141a;
  --surface-inset: #0d0d10;
  --card: #131318;
  --card-hover: #181820;
  --border: rgba(255, 255, 255, 0.08);
  --border-strong: rgba(255, 255, 255, 0.16);
  --line: rgba(255, 255, 255, 0.08);
  --line-strong: rgba(255, 255, 255, 0.16);
  --ink: #ffffff;
  --ink-secondary: #e4e4e7;
  --ink-soft: #a1a1aa;
  --ink-faint: #71717a;
  --faint: #71717a;
  --soft: #d4d4d8;
  
  --unseen-blush: #f6c8c3;
  --unseen-sand: #efded9;
  
  /* Competition Calibrated Plates */
  --plate-red: #ef4444;
  --plate-red-bg: rgba(239, 68, 68, 0.12);
  --plate-red-border: rgba(239, 68, 68, 0.3);
  --plate-red-text: #fca5a5;
  --act: #ef4444;

  --plate-yellow: #f59e0b;
  --plate-yellow-bg: rgba(245, 158, 11, 0.12);
  --plate-yellow-border: rgba(245, 158, 11, 0.3);
  --plate-yellow-text: #fde68a;
  --watch: #f59e0b;

  --plate-blue: #3b82f6;
  --plate-blue-bg: rgba(59, 130, 246, 0.12);
  --plate-blue-border: rgba(59, 130, 246, 0.3);
  --plate-blue-text: #93c5fd;
  --meet: #3b82f6;

  --plate-green: #10b981;
  --plate-green-bg: rgba(16, 185, 129, 0.12);
  --plate-green-border: rgba(16, 185, 129, 0.3);
  --plate-green-text: #86efac;
  --fine: #10b981;

  --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --font-serif: 'Newsreader', 'Saol Display', Georgia, serif;
  --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

*, *::before, *::after { box-sizing: border-box; }

html {
  background: var(--bg);
  color: var(--ink);
  font-size: 15px;
  -webkit-text-size-adjust: 100%;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font-sans);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  overflow-x: hidden;
}

.unseen-ambient {
  position: fixed;
  top: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 100vw;
  height: 650px;
  background: radial-gradient(circle at 50% 10%, rgba(246, 200, 195, 0.04) 0%, rgba(59, 130, 246, 0.02) 40%, transparent 70%);
  pointer-events: none;
  z-index: 0;
}

.wrap {
  position: relative;
  z-index: 1;
  max-width: 860px;
  margin: 0 auto;
  padding: 24px 20px 80px;
}

.wrap-wide {
  position: relative;
  z-index: 1;
  max-width: 1200px;
  margin: 0 auto;
  padding: 28px 28px 80px;
}

/* Authenticated Workspace Shell */
.app-shell {
  position: relative;
  z-index: 1;
  max-width: 1240px;
  margin: 0 auto;
  padding: 24px 24px 80px;
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 36px;
}

/* Side Nav */
.side-nav {
  position: sticky;
  top: 24px;
  align-self: start;
  min-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
  padding: 8px 0;
}

.side-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 700;
  font-size: 16px;
  letter-spacing: 0.04em;
  color: var(--ink);
  text-decoration: none;
  margin-bottom: 32px;
  text-transform: uppercase;
}

.brand-badge {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid var(--border-strong);
  color: var(--unseen-blush);
  padding: 3px 8px;
  border-radius: 9999px;
  font-family: var(--font-mono);
}

.side-links {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.side-links a {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 14px;
  border-radius: 9999px;
  color: var(--ink-soft);
  text-decoration: none;
  font-size: 13.5px;
  font-weight: 500;
  transition: all 0.2s ease;
  border: 1px solid transparent;
}

.side-links a:hover {
  background: rgba(255, 255, 255, 0.04);
  color: var(--ink);
  border-color: var(--border);
}

.side-links a.active {
  background: #ffffff;
  color: #09090b;
  border-color: #ffffff;
  font-weight: 600;
}

.nav-count {
  min-width: 20px;
  text-align: center;
  padding: 1px 6px;
  border-radius: 9999px;
  background: var(--plate-red);
  color: #ffffff;
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 11px;
}

.side-links a.active .nav-count {
  background: #09090b;
  color: #ffffff;
}

.side-meta {
  margin-top: auto;
  padding: 20px 10px 0;
  font-size: 12px;
  color: var(--ink-faint);
  border-top: 1px solid var(--border);
  line-height: 1.5;
}

.side-meta strong {
  color: var(--ink-soft);
}

.side-meta a {
  color: var(--plate-red);
  text-decoration: none;
  font-weight: 500;
}

.side-meta a:hover {
  text-decoration: underline;
}

/* Workspace Main */
.workspace {
  min-width: 0;
}

.workspace-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 20px;
  padding: 0 0 20px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 28px;
}

.eyebrow {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--unseen-blush);
  margin-bottom: 6px;
}

.workspace-head h1 {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin: 0;
  line-height: 1.2;
}

.workspace-sub {
  color: var(--ink-soft);
  font-size: 14px;
  margin: 6px 0 0;
  max-width: 680px;
}

.workspace-date {
  white-space: nowrap;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink-faint);
  letter-spacing: 0.05em;
}

/* Stat Grid */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 28px;
}

.stat {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px 18px;
  transition: border-color 0.2s ease;
}

.stat:hover {
  border-color: var(--border-strong);
}

.stat strong {
  display: block;
  font-size: 30px;
  font-weight: 700;
  line-height: 1.1;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
}

.stat span {
  display: block;
  margin-top: 6px;
  color: var(--ink-faint);
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-weight: 600;
}

.stat.alert strong { color: var(--plate-red); }
.stat.ready strong { color: var(--plate-green); }

/* Dashboard Grid & Panels */
.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(280px, 0.85fr);
  gap: 24px;
}

.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 20px 22px;
  margin-bottom: 16px;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.panel-head h2 {
  margin: 0;
  color: var(--ink);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  font-family: var(--font-mono);
}

.panel-head a {
  font-size: 12.5px;
  color: var(--unseen-blush);
  text-decoration: none;
  font-weight: 500;
  transition: opacity 0.2s ease;
}

.panel-head a:hover {
  opacity: 0.8;
  text-decoration: underline;
}

.athlete-line {
  display: grid;
  grid-template-columns: minmax(150px, 1fr) minmax(130px, 0.8fr) auto;
  gap: 16px;
  align-items: center;
  padding: 12px 0;
  border-top: 1px solid var(--border);
}

.athlete-line:first-of-type {
  border-top: 0;
}

.athlete-name {
  color: var(--ink);
  font-weight: 600;
  text-decoration: none;
  font-size: 14.5px;
}

.athlete-name:hover {
  color: var(--unseen-blush);
}

.muted {
  color: var(--ink-faint);
  font-size: 12.5px;
}

.signal {
  font-size: 13px;
  color: var(--ink-soft);
}

.readiness-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px;
  border-radius: 9999px;
  font-family: var(--font-mono);
  font-weight: 600;
  font-size: 11px;
  background: var(--surface-inset);
  border: 1px solid var(--border);
  white-space: nowrap;
}

.readiness-pill.green {
  color: var(--plate-green-text);
  background: var(--plate-green-bg);
  border-color: var(--plate-green-border);
}

.readiness-pill.yellow, .readiness-pill.orange {
  color: var(--plate-yellow-text);
  background: var(--plate-yellow-bg);
  border-color: var(--plate-yellow-border);
}

.readiness-pill.red {
  color: var(--plate-red-text);
  background: var(--plate-red-bg);
  border-color: var(--plate-red-border);
}

.flow-step {
  display: grid;
  grid-template-columns: 28px 1fr;
  gap: 12px;
  margin: 14px 0;
}

.flow-step b {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--unseen-blush);
}

.flow-step strong {
  display: block;
  font-size: 13.5px;
  color: var(--ink);
}

.flow-step p {
  margin: 3px 0 0;
  font-size: 12.5px;
  color: var(--ink-faint);
  line-height: 1.5;
}

/* Directory Tools & Table */
.directory-tools {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 16px;
}

.directory-tools input {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 9999px;
  color: var(--ink);
  padding: 10px 18px;
  font-family: inherit;
  font-size: 13.5px;
  flex: 1;
}

.directory-tools input:focus {
  outline: none;
  border-color: var(--unseen-blush);
}

.directory-tools select {
  padding: 10px 16px;
  border: 1px solid var(--border);
  border-radius: 9999px;
  background: var(--surface);
  color: var(--ink);
  font-family: inherit;
  font-size: 13px;
}

.directory {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
}

.directory-row {
  display: grid;
  grid-template-columns: minmax(150px, 1.2fr) minmax(140px, 1fr) 95px 105px;
  gap: 14px;
  align-items: center;
  padding: 14px 18px;
  border-top: 1px solid var(--border);
}

.directory-row:first-child {
  border-top: 0;
}

.directory-head {
  background: var(--surface-inset);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-family: var(--font-mono);
  color: var(--ink-faint);
}

/* Review / Outbox Message Cards */
.message-card {
  border-left-width: 4px;
  padding: 0;
  overflow: hidden;
  border-radius: 14px;
  margin-bottom: 16px;
}

.message-card.needs_you { border-left-color: var(--plate-red); }
.message-card.watch { border-left-color: var(--plate-yellow); }
.message-card.meet_prep { border-left-color: var(--plate-blue); }
.message-card.fine { border-left-color: var(--plate-green); }

.message-card .panel-head {
  padding: 16px 18px 0;
  margin-bottom: 14px;
}

.message-card form {
  padding: 0 18px 18px;
  display: block;
}

.message-card form textarea {
  width: 100%;
  min-height: 110px;
  background: var(--surface-inset);
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--ink);
  font-family: inherit;
  padding: 10px 12px;
  font-size: 13.5px;
  line-height: 1.5;
  resize: vertical;
}

.message-card form textarea:focus {
  outline: none;
  border-color: var(--unseen-blush);
}

.evidence-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  background: var(--surface-inset);
  padding: 12px 18px;
  margin: 0;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}

.evidence-grid span, .draft-label {
  display: block;
  font-size: 10.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-family: var(--font-mono);
  color: var(--ink-faint);
  font-weight: 600;
}

.evidence-grid strong {
  display: block;
  font-size: 13px;
  margin-top: 4px;
  line-height: 1.35;
  color: var(--ink-secondary);
}

.evidence-reason {
  margin: 0;
  padding: 12px 18px;
  font-size: 13px;
  color: var(--ink-soft);
}

.draft-label {
  margin: 12px 0 6px;
}

.review-note {
  padding: 14px 18px;
  border: 1px solid var(--border);
  border-left: 4px solid var(--unseen-blush);
  background: var(--surface);
  color: var(--ink-secondary);
  border-radius: 12px;
  margin-bottom: 24px;
  font-size: 13.5px;
  line-height: 1.5;
}

.review-note strong {
  color: var(--ink);
}

/* Buttons */
button {
  cursor: pointer;
  font-family: inherit;
  transition: all 0.2s ease;
}

button.approve, .btn-primary {
  background: #ffffff;
  color: #09090b;
  border: 1px solid #ffffff;
  border-radius: 9999px;
  font-weight: 600;
  font-size: 13.5px;
  padding: 9px 18px;
}

button.approve:hover, .btn-primary:hover {
  opacity: 0.92;
  transform: translateY(-1px);
}

button.skip, .btn-secondary {
  background: rgba(255, 255, 255, 0.04);
  color: var(--ink-soft);
  border: 1px solid var(--border);
  border-radius: 9999px;
  font-weight: 500;
  font-size: 13.5px;
  padding: 9px 18px;
}

button.skip:hover, .btn-secondary:hover {
  background: rgba(255, 255, 255, 0.08);
  color: var(--ink);
  border-color: var(--border-strong);
}

/* Clear Injury Form */
.card form {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.card form input[type="text"] {
  flex: 1;
  min-width: 200px;
  background: var(--surface-inset);
  border: 1px solid var(--border);
  border-radius: 9999px;
  color: var(--ink);
  padding: 8px 14px;
  font-size: 13px;
}

.card form input[type="text"]:focus {
  outline: none;
  border-color: var(--unseen-blush);
}

.card form button {
  background: var(--plate-red);
  color: #ffffff;
  border: none;
  border-radius: 9999px;
  padding: 8px 16px;
  font-size: 12.5px;
  font-weight: 600;
}

/* Register & Demo Components */
.register form {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}

.register input[type="text"] {
  background: var(--surface-inset);
  border: 1px solid var(--border);
  border-radius: 9999px;
  color: var(--ink);
  padding: 9px 14px;
  font-size: 13.5px;
}

.register input[type="text"]:focus {
  outline: none;
  border-color: var(--unseen-blush);
}

.register button {
  background: #ffffff;
  color: #09090b;
  border: 1px solid #ffffff;
  border-radius: 9999px;
  padding: 9px 18px;
  font-weight: 600;
  font-size: 13.5px;
}

.register .hint {
  font-size: 12px;
  color: var(--ink-faint);
  margin: 10px 0 0;
}

.demo {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px 18px;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
}

.demo p {
  margin: 0;
  font-size: 13.5px;
  color: var(--ink-soft);
}

.demo button {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border);
  color: var(--ink);
  border-radius: 9999px;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 500;
}

.demo button:hover {
  border-color: var(--border-strong);
}

/* Card & Who */
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px 20px;
  margin-bottom: 12px;
  transition: border-color 0.2s ease;
}

.card:hover {
  border-color: var(--border-strong);
}

.card.needs_you { border-left: 4px solid var(--plate-red); }
.card.watch { border-left: 4px solid var(--plate-yellow); }
.card.meet_prep { border-left: 4px solid var(--plate-blue); }
.card.fine { border-left: 4px solid var(--plate-green); }

.who {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.who a.name {
  font-weight: 700;
  font-size: 16px;
  color: var(--ink);
  text-decoration: none;
}

.who a.name:hover {
  color: var(--unseen-blush);
}

.id {
  font-size: 12px;
  font-family: var(--font-mono);
  color: var(--ink-faint);
}

ul {
  margin: 8px 0 0 0;
  padding-left: 20px;
}

li {
  font-size: 13.5px;
  color: var(--ink-soft);
  margin-bottom: 4px;
}

li.act {
  color: var(--plate-red-text);
  font-weight: 500;
}

/* Badges */
.badge {
  font-size: 11px;
  font-family: var(--font-mono);
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 9999px;
  margin-left: 8px;
  vertical-align: middle;
}

.badge-red {
  color: var(--plate-red-text);
  background: var(--plate-red-bg);
  border: 1px solid var(--plate-red-border);
}

.badge-yellow {
  color: var(--plate-yellow-text);
  background: var(--plate-yellow-bg);
  border: 1px solid var(--plate-yellow-border);
}

.badge-blue {
  color: var(--plate-blue-text);
  background: var(--plate-blue-bg);
  border: 1px solid var(--plate-blue-border);
}

/* Alerts */
.msg {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 13.5px;
  margin-bottom: 20px;
}

.msg.ok {
  background: var(--plate-green-bg);
  border: 1px solid var(--plate-green-border);
  color: var(--plate-green-text);
}

.msg.err {
  background: var(--plate-red-bg);
  border: 1px solid var(--plate-red-border);
  color: var(--plate-red-text);
}

/* Login Box */
.login-box {
  max-width: 440px;
  margin: 60px auto;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 36px 30px;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.4);
}

.login-box h1 {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin: 0 0 8px 0;
}

.login-box p {
  color: var(--ink-soft);
  font-size: 14px;
  margin: 0 0 24px;
  line-height: 1.5;
}

.login-box form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.login-box input[type="password"], .login-box input[type="text"] {
  width: 100%;
  padding: 10px 16px;
  background: var(--surface-inset);
  border: 1px solid var(--border);
  border-radius: 9999px;
  color: var(--ink);
}

.login-box input:focus {
  outline: none;
  border-color: var(--unseen-blush);
}

.login-box button {
  width: 100%;
  padding: 12px;
  font-size: 14px;
}

.back-link {
  display: inline-block;
  font-size: 13px;
  color: var(--unseen-blush);
  text-decoration: none;
}

.back-link:hover {
  text-decoration: underline;
}

/* Footer */
footer {
  border-top: 1px solid var(--border);
  padding-top: 24px;
  margin-top: 48px;
  font-size: 12.5px;
  color: var(--faint);
  line-height: 1.6;
}

@media(max-width:860px){
  .app-shell { display: block; padding: 16px 16px 60px; }
  .side-nav { position: static; min-height: 0; padding: 0; margin-bottom: 24px; }
  .side-brand { margin-bottom: 14px; }
  .side-links { flex-direction: row; overflow-x: auto; padding-bottom: 4px; }
  .side-links a { white-space: nowrap; }
  .side-meta { display: none; }
  .dashboard-grid { grid-template-columns: 1fr; }
  .stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .directory-row { grid-template-columns: minmax(135px, 1fr) minmax(120px, 1fr) 80px; }
  .directory-row > *:nth-child(4) { display: none; }
}

@media(max-width:540px){
  .workspace-head { align-items: flex-start; }
  .workspace-head h1 { font-size: 23px; }
  .workspace-date { display: none; }
  .athlete-line { grid-template-columns: 1fr auto; }
  .athlete-line .signal { grid-column: 1 / -1; }
  .directory-row { grid-template-columns: 1fr auto; }
  .directory-row > *:nth-child(2) { grid-column: 1 / -1; }
  .directory-head { display: none; }
  .evidence-grid { grid-template-columns: 1fr; }
}
"""


# ------------------------------------------------------------------------------
# Roster View & Outbox Card Helpers
# ------------------------------------------------------------------------------
def _card(entry) -> str:
    """Render an individual athlete card."""
    items = "".join(
        f'<li class="{"act" if f.action else ""}">{escape(f.detail)}</li>'
        for f in entry.flags
    )
    meta = []
    if entry.latest_session:
        meta.append(entry.latest_session)
    if entry.readiness_score is not None:
        meta.append(f"readiness {entry.readiness_score}/100")
    if entry.last_activity:
        meta.append(f"last log {entry.last_activity}")
    meta_html = (
        f'<p class="muted" style="margin:6px 0 0">{escape(" · ".join(meta))}</p>'
        if meta else ""
    )
    body = f"{meta_html}<ul>{items}</ul>" if items else meta_html
    form = ""
    if entry.needs_action and entry.injury_days_open is not None:
        form = (
            '<form method="post" action="/coach/clear-injury">'
            f'<input type="hidden" name="athlete_id" value="{escape(entry.athlete_id)}">'
            '<input type="text" name="reason" required maxlength="200" '
            'placeholder="Who cleared them, and on what basis">'
            '<button type="submit">Clear injury</button>'
            '</form>'
        )

    # Semantic badge label to guarantee severity is clear without color alone
    badge_markup = ""
    if entry.bucket is Bucket.NEEDS_YOU:
        badge_markup = '<span class="badge badge-red">[!] Needs Action</span>'
    elif entry.bucket is Bucket.WATCH:
        badge_markup = '<span class="badge badge-yellow">[!] Watch</span>'
    elif entry.bucket is Bucket.MEET_PREP:
        badge_markup = '<span class="badge badge-blue">[#] Meet Prep</span>'

    return (
        f'<div class="card {entry.bucket.value}">'
        f'<div class="who"><div><a class="name" href="/coach/athlete/{escape(entry.athlete_id)}">{escape(entry.display_name)}</a> {badge_markup}</div>'
        f'<span class="id">{escape(entry.athlete_id)}</span></div>'
        f"{body}{form}</div>"
    )


def _coach_nav(*, active: str, coach: str, pending_count: int = 0) -> str:
    """Stable product navigation shared by every authenticated coach page."""
    links = (
        ("overview", "/coach", "Overview"),
        ("athletes", "/coach/athletes", "Athletes / Roster"),
        ("review", "/coach/outbox", "Review queue / Outbox"),
    )
    nav = []
    for key, href, label in links:
        count = (
            f'<span class="nav-count">{pending_count}</span>'
            if key == "review" and pending_count else ""
        )
        nav.append(
            f'<a class="{"active" if key == active else ""}" href="{href}">'
            f"<span>{label}</span>{count}</a>"
        )
    return (
        '<aside class="side-nav">'
        '<a class="side-brand" href="/coach"><span class="brand-badge">POWER AI</span> Coach Desk</a>'
        f'<nav class="side-links" aria-label="Roster and review">{"".join(nav)}</nav>'
        f'<div class="side-meta">Signed in as<br><strong>{escape(coach)}</strong><br><br>'
        '<a href="/coach/logout">Sign out</a></div></aside>'
    )


def coach_frame(
    body: str,
    *,
    active: str,
    coach: str,
    title: str,
    subtitle: str,
    today,
    pending_count: int = 0,
    extra_style: str = "",
) -> str:
    """The application shell: navigation stays put while the work changes."""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)} — Power AI Coach Desk</title><style>{_BASE_CSS}{extra_style}</style>"
        "</head><body><div class='unseen-ambient'></div><div class='app-shell'>"
        f"{_coach_nav(active=active, coach=coach, pending_count=pending_count)}"
        "<main class='workspace'><div class='workspace-head'><div>"
        f"<div class='eyebrow'>Power AI · Coach Workspace</div><h1>{escape(title)}</h1>"
        f"<p class='workspace-sub'>{escape(subtitle)}</p></div>"
        f"<span class='workspace-date'>{escape(str(today))}</span></div>"
        f"{body}<footer>Power AI &middot; Training Log Agent &middot; Recommendations shown here are assembled from the athlete's "
        "record and deterministic coaching rules. The coach remains the approval gate."
        "</footer></main></div></body></html>"
    )


_REGISTER_FORM = (
    '<section class="register"><h2>Add an athlete</h2>'
    '<div class="card">'
    '<form method="post" action="/coach/athletes/register">'
    '<input type="text" name="name" required maxlength="60" placeholder="Name">'
    '<input type="text" name="athlete_id" required maxlength="20" '
    'placeholder="WhatsApp number, e.g. +919812340001">'
    '<button type="submit">Add</button>'
    '</form>'
    '<p class="hint">The number is their identity - it is how the agent knows who '
    'is texting. They appear on the roster straight away and fill in as they log.</p>'
    '</div></section>'
)


def _demo_controls(roster: Roster, has_demo: bool) -> str:
    """Offer the demo squad on an empty console, and a way to remove it after."""
    if roster.total == 0:
        return (
            '<div class="demo">'
            "<p>Nothing has been logged yet. On a live team this fills up as "
            "athletes text their sessions.</p>"
            '<form method="post" action="/coach/demo/seed">'
            '<button type="submit">Load a demo squad</button></form>'
            "</div>"
        )
    if has_demo:
        return (
            '<div class="demo">'
            "<p>This roster includes demo athletes.</p>"
            '<form method="post" action="/coach/demo/clear">'
            '<button class="skip" type="submit">Remove demo athletes</button></form>'
            "</div>"
        )
    return ""


def render(
    roster: Roster,
    *,
    token: str,
    coach: str,
    message: tuple[str, str] | None = None,
    has_demo: bool = False,
    pending_count: int = 0,
) -> str:
    """Render the operating overview: exceptions, readiness and approval load."""
    banner = ""
    if message:
        kind, text = message
        banner = f'<div class="msg {escape(kind)}">{escape(text)}</div>'

    priorities = [e for e in roster.entries if e.bucket is not Bucket.FINE][:7]
    priority_rows = []
    for entry in priorities:
        signal = " · ".join(f.detail for f in entry.flags) or "No active flags"
        readiness = (
            f'<span class="readiness-pill {escape(entry.readiness_band or "")}">'
            f'{entry.readiness_score}/100</span>'
            if entry.readiness_score is not None else '<span class="muted">No check-in</span>'
        )
        action = ""
        if entry.needs_action and entry.injury_days_open is not None:
            action = (
                '<form method="post" action="/coach/clear-injury" style="grid-column:1/-1">'
                f'<input type="hidden" name="athlete_id" value="{escape(entry.athlete_id)}">'
                '<input type="text" name="reason" required maxlength="200" '
                'placeholder="Who cleared them, and on what basis">'
                '<button type="submit">Clear injury</button></form>'
            )
        priority_rows.append(
            '<div class="athlete-line">'
            f'<div><a class="athlete-name" href="/coach/athlete/{escape(entry.athlete_id)}">'
            f'{escape(entry.display_name)}</a><div class="muted">{escape(entry.latest_session or "No session logged")}</div></div>'
            f'<div class="signal">{escape(signal)}</div>{readiness}{action}</div>'
        )
    priority_body = "".join(priority_rows) or '<p class="empty">No athletes need attention.</p>'
    stats = (
        '<div class="stat-grid">'
        f'<div class="stat alert"><strong>{roster.needing_attention}</strong><span>Need attention</span></div>'
        f'<div class="stat"><strong>{pending_count}</strong><span>Awaiting approval</span></div>'
        f'<div class="stat ready"><strong>{roster.checked_in_today}</strong><span>Checked in today</span></div>'
        f'<div class="stat"><strong>{roster.total}</strong><span>Active athletes</span></div>'
        '</div>'
    )
    workflow = (
        '<div class="panel"><div class="panel-head"><h2>Daily agent loop</h2></div>'
        '<div class="flow-step"><b>1</b><div><strong>Observe</strong><p>Sleep, readiness, training and nutrition arrive through WhatsApp.</p></div></div>'
        '<div class="flow-step"><b>2</b><div><strong>Prepare</strong><p>Rules combine today\'s check-in with history and current trends.</p></div></div>'
        '<div class="flow-step"><b>3</b><div><strong>Verify</strong><p>You edit or approve; only your approved wording can leave the queue.</p></div></div>'
        '</div>'
    )
    squad_links = ", ".join(
        f'<a class="athlete-name" href="/coach/athlete/{escape(entry.athlete_id)}">'
        f'{escape(entry.display_name)}</a>' for entry in roster.entries
    ) or '<span class="empty">No athletes yet.</span>'
    squad_panel = (
        '<div class="panel"><div class="panel-head"><h2>Squad at a glance</h2>'
        '<a href="/coach/athletes">Open directory →</a></div>'
        f'<p style="font-size:13px;line-height:1.8;margin:0">{squad_links}</p></div>'
    )
    body = (
        f"{banner}{stats}"
        '<div class="dashboard-grid"><div>'
        '<div class="panel"><div class="panel-head"><h2>Today\'s priorities</h2>'
        '<a href="/coach/athletes">View all athletes →</a></div>'
        f'{priority_body}</div></div><div>'
        '<div class="panel"><div class="panel-head"><h2>Approval queue</h2>'
        '<a href="/coach/outbox">Open queue →</a></div>'
        f'<p style="font-size:30px;font-weight:800;margin:2px 0">{pending_count}</p>'
        '<p class="section-note">Prepared messages waiting for a human decision.</p></div>'
        f'{workflow}{squad_panel}</div></div>'
        + (_demo_controls(roster, has_demo) if roster.total == 0 else "")
    )
    return coach_frame(
        body, active="overview", coach=coach, title="Overview",
        subtitle="The decisions and exceptions that need a coach today.",
        today=roster.reviewed_on.isoformat(), pending_count=pending_count,
    )


def render_athletes(
    roster: Roster,
    *,
    coach: str,
    message: tuple[str, str] | None = None,
    has_demo: bool = False,
    pending_count: int = 0,
) -> str:
    """Searchable squad directory with current readiness and training context."""
    banner = ""
    if message:
        kind, text = message
        banner = f'<div class="msg {escape(kind)}">{escape(text)}</div>'
    rows = []
    for entry in roster.entries:
        status = " · ".join(f.detail for f in entry.flags) or "On track"
        readiness = (
            f'<span class="readiness-pill {escape(entry.readiness_band or "")}">{entry.readiness_score}/100</span>'
            if entry.readiness_score is not None else '<span class="muted">Not checked in</span>'
        )
        haystack = f"{entry.display_name} {entry.athlete_id} {entry.bucket.value} {status}".lower()
        rows.append(
            f'<div class="directory-row athlete-record" data-bucket="{entry.bucket.value}" '
            f'data-search="{escape(haystack)}">'
            f'<div><a class="athlete-name" href="/coach/athlete/{escape(entry.athlete_id)}">{escape(entry.display_name)}</a>'
            f'<div class="muted">{escape(entry.athlete_id)}</div></div>'
            f'<div><strong style="font-size:13px">{escape(entry.training_summary or "No training baseline")}</strong>'
            f'<div class="muted">{escape(status)}</div></div>{readiness}'
            f'<div class="muted">{escape(entry.last_activity or "Never")}</div></div>'
        )
    directory = (
        '<div class="directory"><div class="directory-row directory-head">'
        '<span>Athlete</span><span>Current training status</span><span>Readiness</span><span>Last log</span></div>'
        + ("".join(rows) if rows else '<p class="empty" style="padding:16px">No athletes yet.</p>')
        + '</div>'
    )
    tools = (
        '<div class="directory-tools"><input id="athlete-search" type="text" '
        'placeholder="Search athletes or status…" aria-label="Search athletes">'
        '<select id="athlete-filter" aria-label="Filter athlete status">'
        '<option value="all">All statuses</option><option value="needs_you">Needs you</option>'
        '<option value="watch">Watch</option><option value="meet_prep">Meet prep</option>'
        '<option value="fine">On track</option></select></div>'
    )
    script = """<script>
const search=document.getElementById('athlete-search');
const filter=document.getElementById('athlete-filter');
function filterAthletes(){const q=search.value.trim().toLowerCase();const f=filter.value;
document.querySelectorAll('.athlete-record').forEach(row=>{row.hidden=!row.dataset.search.includes(q)||(f!=='all'&&row.dataset.bucket!==f);});}
search.addEventListener('input',filterAthletes);filter.addEventListener('change',filterAthletes);
</script>"""
    body = f"{banner}{_demo_controls(roster, has_demo)}{tools}{directory}{_REGISTER_FORM}{script}"
    return coach_frame(
        body, active="athletes", coach=coach, title="Athletes",
        subtitle="Current status, recent progress and readiness across the full squad.",
        today=roster.reviewed_on.isoformat(), pending_count=pending_count,
    )


def _outbox_card(item: PendingMessage) -> str:
    a = item.athlete
    reasons = " · ".join(escape(f.detail) for f in a.flags) or "nothing flagged"
    readiness = (
        f"{a.readiness_score}/100 · {a.readiness_band}"
        if a.readiness_score is not None else "No same-day check-in"
    )
    return (
        f'<div class="card {a.bucket.value} message-card">'
        '<div class="panel-head"><div>'
        f'<a class="athlete-name" href="/coach/athlete/{escape(item.athlete_id)}">'
        f'{escape(a.display_name)}</a>'
        f'<div class="muted">{escape(item.message_kind.replace("_", " ").title())} · '
        f'{escape(item.local_date)}</div></div>'
        '<span class="readiness-pill yellow">Awaiting approval</span></div>'
        '<div class="evidence-grid">'
        f'<div><span>Training trend</span><strong>{escape(a.training_summary or "No baseline")}</strong></div>'
        f'<div><span>Latest session</span><strong>{escape(a.latest_session or "Nothing logged")}</strong></div>'
        f'<div><span>Readiness</span><strong>{escape(readiness)}</strong></div>'
        '</div>'
        f'<p class="evidence-reason"><b>Why it is surfaced:</b> {reasons}</p>'
        '<form method="post" action="/coach/outbox/review">'
        f'<input type="hidden" name="athlete_id" value="{escape(item.athlete_id)}">'
        f'<input type="hidden" name="message_kind" value="{escape(item.message_kind)}">'
        f'<input type="hidden" name="local_date" value="{escape(item.local_date)}">'
        '<label class="draft-label">Message the athlete will receive</label>'
        f'<textarea name="body" maxlength="1400">{escape(item.body)}</textarea>'
        '<div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap;">'
        '<button class="approve" type="submit" name="decision" value="approved">'
        f'Approve for {escape(item.local_date)}</button>'
        '<button class="skip" type="submit" name="decision" value="skipped">'
        "Don\u2019t send</button></div></form></div>"
    )


def render_outbox(
    pending: tuple[PendingMessage, ...],
    *,
    token: str = "",
    coach: str,
    today,
    message: tuple[str, str] | None = None,
) -> str:
    """Render the outbox review queue."""
    banner = ""
    if message:
        kind, text = message
        banner = f'<div class="msg {escape(kind)}">{escape(text)}</div>'

    if not pending:
        body = (
            '<p class="empty">Nothing is queued. Drafts appear the evening before '
            "each athlete's morning, in their own timezone.</p>"
        )
    else:
        cards = [_outbox_card(item) for item in pending]
        body = (
            f"<section><h2>Queued for tomorrow <span class='n'>{len(pending)}</span></h2>"
            + "".join(cards)
            + "</section>"
        )

    intro = (
        '<div class="review-note"><strong>Human approval is the final step.</strong> '
        'The agent prepared each draft from recorded history and current status. '
        'Edit freely, approve it, or hold it back. Nothing below has been sent.</div>'
    )
    return coach_frame(
        f"{banner}{intro}{body}", active="review", coach=coach,
        title="Review queue / Outbox",
        subtitle="Verify the evidence, edit the wording, then approve what goes to each athlete.",
        today=today.isoformat(), pending_count=len(pending),
    )


# ------------------------------------------------------------------------------
# Login Page
# ------------------------------------------------------------------------------
def render_login(error: str | None = None, message: str | None = None) -> str:
    """Render the coach sign-in page."""
    error_markup = f'<div class="msg err">{escape(error)}</div>' if error else ""
    msg_markup = f'<div class="msg ok">{escape(message)}</div>' if message else ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Power AI — Coach Access</title>
  <style>{_BASE_CSS}</style>
</head>
<body>
  <div class="unseen-ambient"></div>
  <div class="wrap">
    <div class="login-box">
      <div class="side-brand" style="margin-bottom:12px;">
        <span class="brand-badge">POWER AI</span> Coach Access
      </div>
      <h1>Coach Sign In</h1>
      <p>Enter the coach access token configured for this squad. Signing in sets an HTTP-only secure cookie so credentials don't leak into URLs or screenshots.</p>
      {error_markup}
      {msg_markup}
      <form method="post" action="/coach/login">
        <label style="font-size:11px;font-weight:600;letter-spacing:0.1em;text-transform:uppercase;color:var(--faint);" for="token">ACCESS TOKEN</label>
        <input type="password" id="token" name="token" required autofocus autocomplete="current-password" placeholder="Paste token here">
        <button type="submit" class="btn-primary">Authenticate &rarr;</button>
      </form>
      <div style="margin-top:24px;text-align:center;">
        <a class="back-link" href="/">&larr; Back to Power AI Overview</a>
      </div>
    </div>
  </div>
</body>
</html>"""


# Landing Page (GET /) & Public Legal Views — Unseen Studio Redesign
# ------------------------------------------------------------------------------

_UNSEEN_LANDING_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;0,800;1,400&family=Newsreader:ital,opsz,wght@1,6..72,300;1,6..72,400;1,6..72,500&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
  --bg: #09090b;
  --bg-surface: #101014;
  --bg-card: #131318;
  --bg-card-hover: #181820;
  --border: rgba(255, 255, 255, 0.08);
  --border-strong: rgba(255, 255, 255, 0.16);
  --border-subtle: rgba(255, 255, 255, 0.04);
  --ink: #ffffff;
  --ink-secondary: #e4e4e7;
  --ink-soft: #a1a1aa;
  --ink-faint: #71717a;
  
  --unseen-blush: #f6c8c3;
  --unseen-sand: #efded9;
  
  --plate-red: #ef4444;
  --plate-red-bg: rgba(239, 68, 68, 0.12);
  --plate-yellow: #f59e0b;
  --plate-yellow-bg: rgba(245, 158, 11, 0.12);
  --plate-blue: #3b82f6;
  --plate-blue-bg: rgba(59, 130, 246, 0.12);
  --plate-green: #10b981;
  --plate-green-bg: rgba(16, 185, 129, 0.12);

  --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  --font-serif: 'Newsreader', 'Saol Display', 'Playfair Display', Georgia, serif;
  --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

*, *::before, *::after {
  box-sizing: border-box;
}

html {
  background: var(--bg);
  color: var(--ink);
  scroll-behavior: smooth;
  font-size: 16px;
  -webkit-text-size-adjust: 100%;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font-sans);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  overflow-x: hidden;
}

.unseen-ambient {
  position: fixed;
  top: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 100vw;
  height: 650px;
  background: radial-gradient(circle at 50% 10%, rgba(246, 200, 195, 0.04) 0%, rgba(59, 130, 246, 0.02) 40%, transparent 70%);
  pointer-events: none;
  z-index: 0;
}

.unseen-wrapper {
  position: relative;
  z-index: 1;
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 28px 80px;
}

/* Header & Nav */
.unseen-header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(9, 9, 11, 0.82);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
  padding: 18px 0;
  margin-bottom: 48px;
}

.unseen-header-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}

.unseen-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  text-decoration: none;
  color: var(--ink);
  font-weight: 700;
  font-size: 15px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.unseen-brand .reg {
  font-size: 11px;
  opacity: 0.6;
  vertical-align: super;
}

.unseen-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-soft);
  letter-spacing: 0.05em;
}

.pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--plate-green);
  box-shadow: 0 0 8px var(--plate-green);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0% { transform: scale(0.95); opacity: 0.8; }
  50% { transform: scale(1.15); opacity: 1; }
  100% { transform: scale(0.95); opacity: 0.8; }
}

.unseen-nav {
  display: flex;
  align-items: center;
  gap: 20px;
}

.unseen-nav a.nav-link {
  color: var(--ink-soft);
  text-decoration: none;
  font-size: 13.5px;
  font-weight: 500;
  letter-spacing: 0.02em;
  transition: color 0.2s ease;
}

.unseen-nav a.nav-link:hover {
  color: var(--ink);
}

/* Pill Buttons */
.unseen-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 22px;
  border-radius: 9999px;
  text-decoration: none;
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  cursor: pointer;
  border: 1px solid transparent;
}

.unseen-btn-primary {
  background: #ffffff;
  color: #09090b;
}

.unseen-btn-primary:hover {
  background: #f4f4f5;
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(255, 255, 255, 0.15);
}

.unseen-btn-ghost {
  background: transparent;
  color: #ffffff;
  border: 1px solid var(--border-strong);
}

.unseen-btn-ghost:hover {
  border-color: rgba(255, 255, 255, 0.4);
  background: rgba(255, 255, 255, 0.05);
  transform: translateY(-1px);
}

.unseen-btn-lg {
  padding: 16px 36px;
  font-size: 15px;
}

.unseen-btn .arrow {
  transition: transform 0.25s ease;
}

.unseen-btn:hover .arrow {
  transform: translate(2px, -2px);
}

/* Hero Section */
.unseen-hero {
  padding: 40px 0 60px;
}

.unseen-hero-tag {
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  color: var(--unseen-blush);
  margin-bottom: 24px;
}

.unseen-hero-h1 {
  font-size: clamp(2.6rem, 6.2vw, 4.8rem);
  line-height: 1.04;
  letter-spacing: -0.035em;
  font-weight: 700;
  color: var(--ink);
  margin: 0 0 28px 0;
  max-width: 1040px;
}

.unseen-serif {
  font-family: var(--font-serif);
  font-style: italic;
  font-weight: 300;
  color: var(--unseen-blush);
  letter-spacing: -0.01em;
}

.unseen-hero-lead {
  font-size: clamp(1.1rem, 2vw, 1.35rem);
  line-height: 1.55;
  color: var(--ink-soft);
  max-width: 820px;
  margin: 0 0 36px 0;
}

.unseen-cta-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 56px;
}

/* Metadata / Specs Strip */
.unseen-specs-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 24px;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  padding: 28px 0;
  margin: 40px 0 64px;
}

.spec-col {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.spec-num {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-faint);
  letter-spacing: 0.08em;
}

.spec-name {
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ink-soft);
}

.spec-detail {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--ink);
}

/* Sections */
.unseen-section {
  margin-bottom: 80px;
}

.section-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.section-idx {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--unseen-blush);
  font-weight: 600;
}

.section-label {
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  color: var(--ink-faint);
}

.section-title {
  font-size: clamp(1.8rem, 4vw, 2.6rem);
  line-height: 1.15;
  letter-spacing: -0.025em;
  font-weight: 700;
  color: var(--ink);
  margin: 0 0 24px 0;
}

.section-lead {
  font-size: 16px;
  color: var(--ink-soft);
  max-width: 780px;
  margin: 0 0 32px 0;
}

/* Filter Bar */
.unseen-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 36px;
}

.filter-pill {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  color: var(--ink-soft);
  padding: 8px 18px;
  border-radius: 9999px;
  font-family: var(--font-mono);
  font-size: 12px;
  letter-spacing: 0.04em;
  cursor: pointer;
  transition: all 0.2s ease;
}

.filter-pill:hover {
  color: var(--ink);
  border-color: var(--border-strong);
}

.filter-pill.active {
  background: #ffffff;
  color: #09090b;
  border-color: #ffffff;
  font-weight: 600;
}

/* Project / Case Card */
.case-item {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 44px;
  margin-bottom: 40px;
  transition: border-color 0.25s ease, background-color 0.25s ease;
}

.case-item:hover {
  border-color: var(--border-strong);
}

.case-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 24px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 20px;
}

.case-tag {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--unseen-blush);
}

.case-badge-group {
  display: flex;
  gap: 8px;
}

.tag-badge {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.05em;
  padding: 3px 8px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--border);
  color: var(--ink-soft);
}

.case-title {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--ink);
  margin: 0 0 12px 0;
}

.case-desc {
  font-size: 15px;
  color: var(--ink-soft);
  max-width: 820px;
  margin: 0 0 28px 0;
}

/* WhatsApp Interactive Simulator */
.scenario-selector {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}

.scenario-btn {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border);
  color: var(--ink-soft);
  padding: 7px 14px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.scenario-btn:hover {
  color: var(--ink);
  border-color: var(--border-strong);
}

.scenario-btn.active {
  background: rgba(246, 200, 195, 0.1);
  border-color: var(--unseen-blush);
  color: #ffffff;
}

.chat-container {
  background: #0d1117;
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 24px;
  max-width: 660px;
}

.chat-header {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  font-family: var(--font-mono);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-faint);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  padding-bottom: 12px;
  margin-bottom: 20px;
}

.chat-bubble {
  max-width: 82%;
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.5;
  margin-bottom: 14px;
  position: relative;
}

.chat-athlete {
  background: #1e2633;
  color: #e6edf3;
  margin-left: auto;
  border-bottom-right-radius: 4px;
}

.chat-agent {
  background: #161b22;
  color: #c9d1d9;
  border: 1px solid rgba(255, 255, 255, 0.08);
  margin-right: auto;
  border-bottom-left-radius: 4px;
}

.chat-meta {
  display: block;
  font-size: 11px;
  color: #8b949e;
  text-align: right;
  margin-top: 4px;
  font-family: var(--font-mono);
}

.chat-verdict {
  display: inline-block;
  font-weight: 700;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--plate-yellow-bg);
  color: var(--plate-yellow);
  border: 1px solid var(--plate-yellow);
  margin: 6px 0;
}

/* 3-Layer Architecture Grid */
.grid-3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  margin-top: 24px;
}

.feature-card {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 28px 24px;
  position: relative;
  transition: all 0.25s ease;
}

.feature-card:hover {
  background: rgba(255, 255, 255, 0.04);
  border-color: var(--border-strong);
  transform: translateY(-2px);
}

.feature-card h3 {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--ink);
  margin: 12px 0 8px 0;
}

.feature-card p {
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--ink-soft);
  margin: 0;
}

.badge {
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 3px 8px;
  border-radius: 4px;
  display: inline-block;
}

.badge-blue {
  background: var(--plate-blue-bg);
  color: var(--plate-blue);
  border: 1px solid rgba(59, 130, 246, 0.3);
}

.badge-yellow {
  background: var(--plate-yellow-bg);
  color: var(--plate-yellow);
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.badge-red {
  background: var(--plate-red-bg);
  color: var(--plate-red);
  border: 1px solid rgba(239, 68, 68, 0.3);
}

/* Authority Table */
.table-wrap {
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: 14px;
  margin-top: 24px;
}

table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 14px;
}

th {
  background: rgba(255, 255, 255, 0.03);
  padding: 14px 18px;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--ink-soft);
  border-bottom: 1px solid var(--border);
}

td {
  padding: 14px 18px;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--ink-secondary);
}

tr:last-child td {
  border-bottom: none;
}

tr:hover td {
  background: rgba(255, 255, 255, 0.015);
}

/* Meet Data Metrics */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-top: 24px;
}

.stat-tile {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
}

.stat-val {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--ink);
  display: block;
}

.stat-lbl {
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
  margin-top: 4px;
  display: block;
}

/* Manifesto Callout */
.unseen-manifesto {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid var(--border);
  border-left: 3px solid var(--unseen-blush);
  border-radius: 12px;
  padding: 24px 28px;
  margin: 56px 0;
}

.manifesto-tag {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--unseen-blush);
  margin-bottom: 8px;
}

.manifesto-text {
  font-size: 14.5px;
  color: var(--ink-secondary);
  line-height: 1.6;
  margin: 0;
}

/* Oversized Unseen Footer */
.unseen-footer {
  border-top: 1px solid var(--border);
  padding-top: 80px;
  margin-top: 100px;
}

.unseen-footer-hero {
  margin-bottom: 64px;
}

.footer-kicker {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--unseen-blush);
  margin-bottom: 16px;
}

.footer-headline {
  font-size: clamp(2.4rem, 5.5vw, 4.2rem);
  line-height: 1.05;
  letter-spacing: -0.03em;
  font-weight: 700;
  color: var(--ink);
  margin: 0 0 32px 0;
}

.unseen-footer-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 20px;
  padding-top: 32px;
  border-top: 1px solid var(--border);
  font-size: 13px;
  color: var(--ink-faint);
}

.unseen-footer-bottom a {
  color: var(--ink-soft);
  text-decoration: none;
  transition: color 0.2s ease;
}

.unseen-footer-bottom a:hover {
  color: var(--ink);
}

.footer-clock {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink-faint);
}

.back-to-top {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ink-soft);
  text-decoration: none;
}

.back-to-top:hover {
  color: var(--ink);
}

/* Legal view container */
.unseen-legal-container {
  max-width: 780px;
  margin: 40px auto 80px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 48px;
}

.unseen-legal-container h1 {
  font-size: 32px;
  letter-spacing: -0.02em;
  margin: 0 0 24px 0;
}

.unseen-legal-container p {
  font-size: 15px;
  line-height: 1.7;
  color: var(--ink-secondary);
  margin-bottom: 20px;
}

/* Responsive adjustments */
@media (max-width: 900px) {
  .unseen-specs-strip {
    grid-template-columns: repeat(2, 1fr);
  }
  .grid-3 {
    grid-template-columns: 1fr;
  }
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .unseen-wrapper {
    padding: 0 18px 60px;
  }
  .unseen-header-inner {
    padding: 0 18px;
  }
  .unseen-nav {
    display: none;
  }
  .unseen-specs-strip {
    grid-template-columns: 1fr;
  }
  .stats-grid {
    grid-template-columns: 1fr;
  }
  .case-item {
    padding: 24px 18px;
  }
  .unseen-legal-container {
    padding: 28px 20px;
  }
}
"""

_LANDING_JS = """
  const scenarios = {
    stall: {
      athlete: 'squat 3x5 at 140 today, felt way harder than tuesday, rpe 9',
      time: '17:42',
      verdictText: 'Squat — Stalled',
      detail: 'Flat at 140 kg for 2 sessions with RPE climbing &mdash; same bar, more effort.'
    },
    injury: {
      athlete: 'bench 100kg 3x5 sharp pain in front left shoulder on rep 4',
      time: '18:15',
      verdictText: '🚨 Injury Flag: Left Shoulder',
      detail: 'Acute pain logged. Progression immediately locked until cleared by Coach.'
    },
    pr: {
      athlete: 'deadlift 220 1x5 moved like butter rpe 7',
      time: '19:04',
      verdictText: 'Deadlift — Progressing',
      detail: '+5kg progression verified. RPE in target band (7.0 &le; 8.0).'
    }
  };

  function switchScenario(key) {
    const data = scenarios[key];
    if (!data) return;

    document.querySelectorAll('.scenario-btn').forEach(btn => btn.classList.remove('active'));
    if (window.event && window.event.target) {
      window.event.target.classList.add('active');
    }

    const athleteBubble = document.getElementById('chat-athlete-msg');
    const agentBubble = document.getElementById('chat-agent-msg');

    athleteBubble.innerHTML = data.athlete + '<span class="chat-meta">' + data.time + ' &check;&check;</span>';
    agentBubble.innerHTML = '&check; Logged: ' + (key === 'stall' ? 'Squat 3x5 @ 140 kg RPE 9' : (key === 'injury' ? 'Bench 100 kg 3x5 RPE 8' : 'Deadlift 220 kg 1x5 RPE 7')) + '<br>' +
      '<span class="chat-verdict">' + data.verdictText + '</span><br>' +
      data.detail +
      '<span class="chat-meta">' + data.time + '</span>';
  }

  function filterCase(category) {
    document.querySelectorAll('.filter-pill').forEach(btn => btn.classList.remove('active'));
    if (window.event && window.event.target) {
      window.event.target.classList.add('active');
    }

    document.querySelectorAll('.case-item').forEach(item => {
      if (category === 'all' || item.getAttribute('data-case') === category) {
        item.style.display = 'block';
      } else {
        item.style.display = 'none';
      }
    });
  }

  function updateClock() {
    const el = document.getElementById('utc-clock');
    if (!el) return;
    const now = new Date();
    el.textContent = now.toUTCString().split(' ')[4] + ' UTC';
  }
  setInterval(updateClock, 1000);
  updateClock();
"""


def render_landing(*, is_logged_in: bool = False) -> str:
    """Render the public landing page styled like Unseen Studio (unseen.co/projects)."""
    coach_link = "/coach" if is_logged_in else "/coach/login"
    coach_text = "Open Console" if is_logged_in else "Coach Sign In"

    arrow_svg = '<svg class="arrow" width="14" height="14" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="2" d="M3 13L13 3M13 3H5M13 3V11"/></svg>'

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Power AI — WhatsApp Powerlifting Coach</title>
  <style>{_UNSEEN_LANDING_CSS}</style>
</head>
<body>
  <div class="unseen-ambient"></div>

  <!-- Header Navigation (Unseen Studio style) -->
  <header class="unseen-header">
    <div class="unseen-header-inner">
      <a class="unseen-brand" href="/">
        Training Log Agent<span class="reg">&reg;</span>
      </a>
      <div class="unseen-status-badge">
        <span class="pulse-dot"></span>
        <span>AGENT ONLINE &middot; DETERMINISTIC</span>
      </div>
      <nav class="unseen-nav">
        <a class="nav-link" href="#protocols">01 Protocols</a>
        <a class="nav-link" href="#architecture">02 Architecture</a>
        <a class="nav-link" href="#boundaries">03 Boundaries</a>
        <a class="nav-link" href="https://github.com/Shlok-K-ps/training-log-agent" target="_blank" rel="noopener">GitHub &nearr;</a>
        <a class="unseen-btn unseen-btn-primary" href="{coach_link}">
          <span>{coach_text}</span>
          {arrow_svg}
        </a>
      </nav>
    </div>
  </header>

  <div class="unseen-wrapper">
    <!-- Hero Section -->
    <section class="unseen-hero">
      <div class="unseen-hero-tag">[ PROTOCOL 01 // WHATSAPP POWERLIFTING INTELLIGENCE ]</div>
      <h1 class="unseen-hero-h1">
        The coach reads exceptions,<br>
        <span class="unseen-serif">not twenty WhatsApp texts a day.</span>
      </h1>
      <p class="unseen-hero-lead">
        A powerlifting coach's real bottleneck isn't writing programs &mdash; it's copying workout numbers from messages, remembering who's hurt, spotting lifters who stalled a month ago, and noticing when an athlete goes silent.
      </p>
      <div class="unseen-cta-row">
        <a class="unseen-btn unseen-btn-primary unseen-btn-lg" href="{coach_link}">
          <span>{coach_text}</span>
          {arrow_svg}
        </a>
        <a class="unseen-btn unseen-btn-ghost unseen-btn-lg" href="https://github.com/Shlok-K-ps/training-log-agent" target="_blank" rel="noopener">
          <span>Read Source on GitHub</span>
          {arrow_svg}
        </a>
      </div>

      <!-- Studio Specs Strip -->
      <div class="unseen-specs-strip">
        <div class="spec-col">
          <span class="spec-num">01</span>
          <span class="spec-name">INGESTION</span>
          <span class="spec-detail">WhatsApp Cloud API</span>
        </div>
        <div class="spec-col">
          <span class="spec-num">02</span>
          <span class="spec-name">SCHEMA PARSER</span>
          <span class="spec-detail">Gemini Flash</span>
        </div>
        <div class="spec-col">
          <span class="spec-num">03</span>
          <span class="spec-name">DECISION ENGINE</span>
          <span class="spec-detail">Pure Python Rules</span>
        </div>
        <div class="spec-col">
          <span class="spec-num">04</span>
          <span class="spec-name">GROUND TRUTH</span>
          <span class="spec-detail">Top 300 All-Time Dots</span>
        </div>
      </div>
    </section>

    <!-- Showcase Projects Section (Unseen Studio projects/ layout) -->
    <section id="protocols" class="unseen-section">
      <div class="section-meta">
        <span class="section-idx">01</span>
        <span class="section-label">SHOWCASE PROJECTS &amp; PROTOCOLS</span>
      </div>
      <h2 class="section-title">Curated Systems <span class="unseen-serif">&amp; Case Studies</span></h2>
      <p class="section-lead">
        Explore the four deterministic mechanisms that power the squad &mdash; from raw incoming athlete WhatsApp streams to zero-hallucination verdict rules.
      </p>

      <!-- Category Filter Tabs -->
      <div class="unseen-filters" role="tablist">
        <button class="filter-pill active" onclick="filterCase('all')">All Protocols (04)</button>
        <button class="filter-pill" onclick="filterCase('chat')">01 WhatsApp Simulation</button>
        <button class="filter-pill" onclick="filterCase('arch')">02 Three-Layer Split</button>
        <button class="filter-pill" onclick="filterCase('bound')">03 Authority Boundaries</button>
        <button class="filter-pill" onclick="filterCase('data')">04 Meet Benchmarks</button>
      </div>

      <!-- Case 01: Interactive WhatsApp Conversation -->
      <article class="case-item" data-case="chat">
        <div class="case-header">
          <div>
            <div class="case-tag">[ PROJECT 01 // REALISTIC WHATSAPP CONVERSATION ]</div>
            <h3 class="case-title">Raw Lifter Notes &rarr; Structured Verdicts</h3>
          </div>
          <div class="case-badge-group">
            <span class="tag-badge">PARSING</span>
            <span class="tag-badge">DETERMINISTIC</span>
          </div>
        </div>
        <p class="case-desc">
          Lifters text raw shorthand notes straight from the squat rack. Gemini Flash extracts the workout into typed function schemas, but <em>never drafts advice</em>. Pure Python evaluates the sets and assigns an immediate deterministic verdict.
        </p>

        <!-- Interactive Scenario Switcher -->
        <div class="scenario-selector">
          <button class="scenario-btn active" onclick="switchScenario('stall')">Scenario A: Stalled Squat (140kg)</button>
          <button class="scenario-btn" onclick="switchScenario('injury')">Scenario B: Acute Shoulder Pain</button>
          <button class="scenario-btn" onclick="switchScenario('pr')">Scenario C: Bench Press PR</button>
        </div>

        <div class="chat-container">
          <div class="chat-header">
            <span>WhatsApp Conversation</span>
            <span>Deterministic Reply</span>
          </div>
          <div id="chat-athlete-msg" class="chat-bubble chat-athlete">
            squat 3x5 at 140 today, felt way harder than tuesday, rpe 9
            <span class="chat-meta">17:42 &check;&check;</span>
          </div>
          <div id="chat-agent-msg" class="chat-bubble chat-agent">
            &check; Logged: Squat 3x5 @ 140 kg RPE 9<br>
            <span class="chat-verdict">Squat — Stalled</span><br>
            Flat at 140 kg for 2 sessions with RPE climbing &mdash; same bar, more effort.
            <span class="chat-meta">17:42</span>
          </div>
        </div>
      </article>

      <!-- Case 02: 3-Layer Architecture -->
      <article id="architecture" class="case-item" data-case="arch">
        <div class="case-header">
          <div>
            <div class="case-tag">[ PROJECT 02 // ARCHITECTURAL PROTOCOL ]</div>
            <h3 class="case-title">The Core Separation <span class="n">3 LAYERS</span></h3>
          </div>
          <div class="case-badge-group">
            <span class="tag-badge">ZERO DRIFT</span>
            <span class="tag-badge">PYTHON 3.11</span>
          </div>
        </div>
        <p class="case-desc">
          Messy input needs a language model; coaching advice real humans lift under must be provable, repeatable, and deterministic. The split is the whole design:
        </p>
        <div class="grid-3">
          <div class="feature-card">
            <span class="badge badge-blue">LAYER 1 &middot; PARSE</span>
            <h3>Gemini Flash</h3>
            <p>Extracts unstructured English into 20 typed function schemas. Ceilings and ratios are range-checked. <em>The model cannot write reply text.</em></p>
          </div>
          <div class="feature-card">
            <span class="badge badge-yellow">LAYER 2 &middot; STORE</span>
            <h3>Single SQLite Timeline</h3>
            <p>Every message is an immutable observation. Phone numbers serve as tenant identity. Calendar tokens and locations are encrypted at rest.</p>
          </div>
          <div class="feature-card">
            <span class="badge badge-red">LAYER 3 &middot; DECIDE</span>
            <h3>Pure Python Rules</h3>
            <p>Zero model. Zero API calls. Zero randomness. Evaluates session deltas, RPE slides, deloads, and sleep recovery deterministically.</p>
          </div>
        </div>
      </article>

      <!-- Case 03: Authority Boundaries -->
      <article id="boundaries" class="case-item" data-case="bound">
        <div class="case-header">
          <div>
            <div class="case-tag">[ PROJECT 03 // SAFETY GOVERNANCE ]</div>
            <h3 class="case-title">Authority Boundaries <span class="n">WHO DECIDES WHAT</span></h3>
          </div>
          <div class="case-badge-group">
            <span class="tag-badge">HARDENED GATES</span>
            <span class="tag-badge">COACH SAFETY</span>
          </div>
        </div>
        <p class="case-desc">
          Safety is enforced by immutable software boundaries, not system prompt guidelines. Neither the lifter nor the LLM has permission to override coaching gates.
        </p>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Action</th>
                <th>Athlete</th>
                <th>Agent</th>
                <th>Coach</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Report session, pain, sleep, food</td>
                <td><strong>&check; Allowed</strong></td>
                <td>&mdash;</td>
                <td>&mdash;</td>
              </tr>
              <tr>
                <td>Parse message into structured data</td>
                <td>&mdash;</td>
                <td><strong>&check; Allowed</strong></td>
                <td>&mdash;</td>
              </tr>
              <tr>
                <td>Judge progressing / stalled / deload</td>
                <td>&mdash;</td>
                <td><strong>&check; Deterministic</strong></td>
                <td>&mdash;</td>
              </tr>
              <tr>
                <td>Open an injury flag</td>
                <td>&check; Allowed</td>
                <td>&check; Allowed</td>
                <td>&check; Allowed</td>
              </tr>
              <tr>
                <td><strong>Close an injury flag</strong></td>
                <td><span style="color:var(--plate-red); font-weight:600;">&cross; Enforced in code</span></td>
                <td><span style="color:var(--plate-red); font-weight:600;">&cross; Enforced in code</span></td>
                <td><strong style="color:var(--plate-green);">&check; Coach Only</strong></td>
              </tr>
              <tr>
                <td>Approve supplement regimen</td>
                <td>&cross;</td>
                <td>&cross;</td>
                <td><strong style="color:var(--plate-green);">&check; Coach Only</strong></td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>

      <!-- Case 04: Grounded in Meet Data -->
      <article id="benchmarks" class="case-item" data-case="data">
        <div class="case-header">
          <div>
            <div class="case-tag">[ PROJECT 04 // EMPIRICAL VALIDATION ]</div>
            <h3 class="case-title">Grounded in Meet Data <span class="n">TOP 300 ALL-TIME</span></h3>
          </div>
          <div class="case-badge-group">
            <span class="tag-badge">OPENPOWERLIFTING</span>
            <span class="tag-badge">CI TESTED</span>
          </div>
        </div>
        <p class="case-desc">
          Validation bounds and plausibility checks are derived directly from OpenPowerlifting competition results (top 300 lifters by Dots, Raw+Wraps). Recomputed in continuous integration so code cannot drift from empirical evidence.
        </p>
        <div class="stats-grid">
          <div class="stat-tile">
            <span class="stat-val">300</span>
            <span class="stat-lbl">All-Time Top Lifters</span>
          </div>
          <div class="stat-tile">
            <span class="stat-val">500 kg</span>
            <span class="stat-lbl">Max Plausible Squat</span>
          </div>
          <div class="stat-tile">
            <span class="stat-val">365 kg</span>
            <span class="stat-lbl">Max Plausible Bench</span>
          </div>
          <div class="stat-tile">
            <span class="stat-val">460 kg</span>
            <span class="stat-lbl">Max Plausible Deadlift</span>
          </div>
        </div>
      </article>
    </section>

    <!-- Transparent Engineering Note -->
    <div class="unseen-manifesto">
      <div class="manifesto-tag">[ MANIFESTO // ZERO TRACKERS &middot; PURE PYTHON ]</div>
      <p class="manifesto-text">
        <strong>Transparent Note:</strong> This is a student-built engineering project for a 20-athlete powerlifting squad, not a venture-backed commercial SaaS. Zero trackers, zero analytics cookies, and no runtime framework beyond Python and SQLite.
      </p>
    </div>

    <!-- Oversized Unseen Studio Footer -->
    <footer class="unseen-footer">
      <div class="unseen-footer-hero">
        <div class="footer-kicker">READY FOR SQUAD DEPLOYMENT</div>
        <h2 class="footer-headline">
          The squad on WhatsApp.<br>
          <span class="unseen-serif">The coach in control.</span>
        </h2>
        <div class="footer-cta-wrap">
          <a class="unseen-btn unseen-btn-primary unseen-btn-lg" href="{coach_link}">
            <span>{coach_text}</span>
            {arrow_svg}
          </a>
        </div>
      </div>

      <div class="unseen-footer-bottom">
        <div>Training Log Agent &middot; Built for Powerlifting Teams</div>
        <div>
          <a href="/privacy">Privacy Policy</a> &middot;
          <a href="/terms">Terms of Service</a> &middot;
          <a href="https://github.com/Shlok-K-ps/training-log-agent" target="_blank" rel="noopener">GitHub</a>
        </div>
        <div class="footer-clock">
          <span id="utc-clock">00:00:00 UTC</span> &middot; HOSTED ON RENDER
        </div>
        <div>
          <a href="#" class="back-to-top">Back to Top &uarr;</a>
        </div>
      </div>
    </footer>
  </div>

  <!-- Interactive Client Script -->
  <script>{_LANDING_JS}</script>
</body>
</html>"""


# ------------------------------------------------------------------------------
# Privacy and Terms Pages (Styled in Unseen Studio aesthetic)
# ------------------------------------------------------------------------------
def render_privacy() -> str:
    """Render the styled privacy policy."""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Power AI — Privacy Policy</title>
  <style>{_UNSEEN_LANDING_CSS}</style>
</head>
<body>
  <div class="unseen-ambient"></div>
  <header class="unseen-header">
    <div class="unseen-header-inner">
      <a class="unseen-brand" href="/">
        Training Log Agent<span class="reg">&reg;</span>
      </a>
      <nav class="unseen-nav">
        <a class="nav-link" href="/">&larr; Return to Home</a>
        <a class="nav-link" href="/terms">Terms of Service</a>
      </nav>
    </div>
  </header>

  <div class="unseen-wrapper">
    <div class="unseen-legal-container">
      <div class="unseen-hero-tag">[ LEGAL // TRANSPARENCY &amp; DATA PRIVACY ]</div>
      <h1>Privacy Policy</h1>
      <p>Calendar connection is optional. The service reads event start/end times and usable locations only to plan travel and training. It does not retain event titles, descriptions, attendees or meeting content.</p>
      <p>OAuth tokens and saved places are encrypted at rest with Fernet cryptography when the calendar integration is configured. Confirmed workout references are stored until the athlete asks to delete them. Calendar data is never sold and is never sent to the language model.</p>
      <p>Training, sleep, readiness and nutrition messages may be sent to the configured language-model provider for structured parsing. Coaching decisions are made by deterministic application rules in pure Python, not by that model.</p>
      <p>Athletes can send <em>“disconnect calendar”</em> in WhatsApp to delete stored calendar tokens, or <em>“forget my locations”</em> to erase saved home, office and gym places.</p>
      <div style="margin-top:32px;padding-top:20px;border-top:1px solid var(--border);">
        <a href="/" class="unseen-btn unseen-btn-ghost">&larr; Return to Home</a>
      </div>
    </div>
  </div>
</body>
</html>"""


def render_terms() -> str:
    """Render the styled terms of service."""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Power AI — Terms of Service</title>
  <style>{_UNSEEN_LANDING_CSS}</style>
</head>
<body>
  <div class="unseen-ambient"></div>
  <header class="unseen-header">
    <div class="unseen-header-inner">
      <a class="unseen-brand" href="/">
        Training Log Agent<span class="reg">&reg;</span>
      </a>
      <nav class="unseen-nav">
        <a class="nav-link" href="/">&larr; Return to Home</a>
        <a class="nav-link" href="/privacy">Privacy Policy</a>
      </nav>
    </div>
  </header>

  <div class="unseen-wrapper">
    <div class="unseen-legal-container">
      <div class="unseen-hero-tag">[ LEGAL // BOUNDARIES &amp; MEDICAL DISCLAIMER ]</div>
      <h1>Terms of Service</h1>
      <p>This service is a training-log and planning aid, not medical care or clinical diagnostic software. Athletes remain responsible for confirming calendar changes and following medical advice from their coach, clinician, or registered dietitian.</p>
      <p>Injury flags immediately suppress all load progression advice. The agent never prescribes load to an injured athlete; clearance requires explicit authorization by a named human coach or medical practitioner.</p>
      <div style="margin-top:32px;padding-top:20px;border-top:1px solid var(--border);">
        <a href="/" class="unseen-btn unseen-btn-ghost">&larr; Return to Home</a>
      </div>
    </div>
  </div>
</body>
</html>"""
