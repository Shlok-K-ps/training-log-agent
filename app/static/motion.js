// Power AI interface motion: scroll-aware bars, counters and the landing conversation demo.
(function () {
  'use strict';

  const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Bars gain their hairline and material once content scrolls beneath them, and
  // the compact title appears when the large title leaves the screen — as on iOS.
  function initScrollState() {
    const body = document.body;
    let ticking = false;
    const update = () => {
      body.classList.toggle('has-scrolled', window.scrollY > 4);
      ticking = false;
    };
    window.addEventListener('scroll', () => {
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(update);
      }
    }, { passive: true });
    update();

    const title = document.querySelector('.workspace-head h1');
    if (title && 'IntersectionObserver' in window) {
      new IntersectionObserver(([entry]) => {
        body.classList.toggle('title-hidden', !entry.isIntersecting && entry.boundingClientRect.top < 60);
      }, { rootMargin: '-56px 0px 0px 0px' }).observe(title);
    }
  }

  function initCounters() {
    if (prefersReduced) return;
    document.querySelectorAll('[data-counter]').forEach((el) => {
      const target = parseInt(el.getAttribute('data-target') || el.textContent, 10);
      if (isNaN(target) || target === 0) return;
      let start = null;
      const duration = 700;
      const step = (now) => {
        if (start === null) start = now;
        const progress = Math.min((now - start) / duration, 1);
        el.textContent = Math.round((1 - Math.pow(1 - progress, 3)) * target);
        if (progress < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
      // Frames pause in background tabs; never leave a count stranded mid-way.
      setTimeout(() => { el.textContent = target; }, duration + 150);
    });
  }

  const scenarios = {
    stall: {
      athlete: 'squat 3x5 at 140 today, felt way harder than tuesday, rpe 9',
      time: '17:42',
      verdictBadge: 'Squat — Stalled',
      verdictClass: 'tag-watch',
      logged: 'Squat 3x5 @ 140 kg RPE 9',
      detail: 'Flat at 140 kg for 2 sessions with RPE climbing &mdash; same bar, more effort.'
    },
    injury: {
      athlete: 'bench 100kg 3x5 sharp pain in front left shoulder on rep 4',
      time: '18:15',
      verdictBadge: 'Injury flag · Left shoulder',
      verdictClass: 'tag-act',
      logged: 'Bench 100 kg 3x5 RPE 8',
      detail: 'Acute pain logged. Progression is locked until a coach records clearance.'
    },
    pr: {
      athlete: 'deadlift 220 1x5 moved like butter rpe 7',
      time: '19:04',
      verdictBadge: 'Deadlift — Progressing',
      verdictClass: 'tag-fine',
      logged: 'Deadlift 220 kg 1x5 RPE 7',
      detail: '+5 kg progression verified. RPE in target band (7.0 &le; 8.0).'
    }
  };

  window.switchScenario = function (key) {
    const data = scenarios[key];
    if (!data) return;

    document.querySelectorAll('.scenario-btn').forEach((btn) => {
      const active = btn.getAttribute('data-scenario') === key;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });

    const athleteEl = document.getElementById('chat-athlete-msg');
    const agentEl = document.getElementById('chat-agent-msg');
    if (athleteEl) {
      athleteEl.innerHTML = `${data.athlete}<span class="chat-meta">${data.time} &check;&check;</span>`;
    }
    if (agentEl) {
      agentEl.innerHTML = `
        <div class="chat-reply-header">
          <span class="chat-verdict ${data.verdictClass}">${data.verdictBadge}</span>
          <span class="chat-meta">${data.time}</span>
        </div>
        <div class="chat-logged-line">&check; Logged: ${data.logged}</div>
        <div class="chat-body-line">${data.detail}</div>
      `;
    }
    [athleteEl, agentEl].forEach((el, i) => {
      if (!el || prefersReduced) return;
      el.classList.remove('bubble-pop');
      void el.offsetWidth;
      el.style.animationDelay = `${i * 140}ms`;
      el.classList.add('bubble-pop');
    });
  };

  // Bulk approval only covers untouched drafts, so it switches off the moment
  // the coach starts editing any message on the page.
  function initBulkGuard() {
    const bulk = document.querySelector('[data-bulk-approve]');
    if (!bulk) return;
    const fields = [...document.querySelectorAll('.message-card textarea')];
    const eligible = bulk.dataset.eligible !== '0';
    const update = () => {
      bulk.disabled = !eligible || fields.some((field) => field.value !== field.defaultValue);
    };
    fields.forEach((field) => field.addEventListener('input', update));
    update();
  }

  function updateClock() {
    const el = document.getElementById('utc-clock');
    if (!el) return;
    el.textContent = new Date().toUTCString().split(' ')[4] + ' UTC';
  }

  function init() {
    initScrollState();
    initCounters();
    initBulkGuard();
    if (document.getElementById('utc-clock')) {
      updateClock();
      setInterval(updateClock, 1000);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
