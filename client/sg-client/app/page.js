import Image from "next/image";

export default function Home() {
  return (
    <!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>SafetyGuide — Offline Disaster Relief Assistant</title>
<meta name="description" content="A fully-local, offline-first disaster preparedness assistant. Runs on your laptop with wifi off. Grounded in Ready.gov, American Red Cross, and Washington State Emergency Management Division sources." />
<script src="https://cdn.tailwindcss.com"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<script>
  tailwind.config = {
    theme: {
      extend: {
        colors: {
          cream:  { 50:'#FBF8F2', 100:'#F5EFE4', 200:'#ECE3D0' },
          sage:   { 50:'#F1F4EE', 100:'#E2E9DC', 300:'#A9BBA0', 500:'#6F8A6A', 700:'#4A6248', 900:'#2B3A2A' },
          teal:   { 500:'#3F7F7A', 700:'#2D5C58' },
          amber:  { 100:'#F6EBD2', 500:'#C99A4B', 700:'#8E6A2A' },
          rose:   { 100:'#F5E1DA', 300:'#E5B5A6', 500:'#C97B66' },
          ink:    { 700:'#3B3A36', 900:'#1F1E1B' }
        },
        fontFamily: {
          serif: ['Fraunces','Georgia','serif'],
          sans:  ['Inter','ui-sans-serif','system-ui']
        }
      }
    }
  }
</script>
<style>
  html, body { color: #1F1E1B; }
  body {
    font-family: 'Fraunces', Georgia, serif;
    line-height: 1.65;
    position: relative;
    overflow-x: hidden;
    min-height: 100vh;
    background: #B8C8E0;
  }
  /* Sunset background: cool sky at top -> lavender -> pink -> warm orange sun glow at bottom */
  .aurora {
    position: fixed; inset: 0; z-index: -1; pointer-events: none;
    overflow: hidden;
    background:
      linear-gradient(180deg,
        #B8C8E0 0%,
        #C9C0DC 22%,
        #E5BCD0 42%,
        #F2B8BC 58%,
        #F5A580 78%,
        #F08040 100%);
    animation: sky 14s ease-in-out infinite alternate;
  }
  /* slow, gentle hue shift of the whole sky */
  @keyframes sky {
    0%   { filter: hue-rotate(0deg)   saturate(1); }
    100% { filter: hue-rotate(-6deg)  saturate(1.08); }
  }
  /* The "sun": a warm radial glow anchored bottom-center, slowly breathing */
  .sun {
    position: absolute;
    left: 50%; bottom: -22vmax;
    width: 70vmax; height: 70vmax;
    transform: translateX(-50%);
    border-radius: 9999px;
    background: radial-gradient(circle at 50% 50%,
      #FF7A1A 0%,
      #FF9540 18%,
      rgba(255,180,120,0.55) 38%,
      rgba(255,200,160,0.0) 65%);
    filter: blur(20px);
    animation: sunBreath 9s ease-in-out infinite alternate;
    will-change: transform, opacity;
  }
  @keyframes sunBreath {
    0%   { transform: translateX(-50%) scale(1);    opacity: 0.95; }
    100% { transform: translateX(-52%) scale(1.08); opacity: 1; }
  }
  /* Soft secondary glow drifting horizontally for subtle motion in the warm band */
  .glow {
    position: absolute;
    left: 30%; bottom: 10vmax;
    width: 50vmax; height: 30vmax;
    border-radius: 9999px;
    background: radial-gradient(ellipse at center,
      rgba(255,140,90,0.35) 0%,
      rgba(255,140,90,0.0) 70%);
    filter: blur(30px);
    animation: glowDrift 18s ease-in-out infinite alternate;
  }
  @keyframes glowDrift {
    0%   { transform: translate(-10vw, 0)   scale(1); opacity: .7; }
    100% { transform: translate(12vw, -4vh) scale(1.15); opacity: 1; }
  }
  .ui { font-family: 'Inter', system-ui, sans-serif; }

  /* gentle reveal */
  .reveal { opacity: 0; transform: translateY(8px); animation: rise .9s cubic-bezier(.2,.7,.2,1) forwards; }
  @keyframes rise { to { opacity: 1; transform: none; } }

  /* fade in for staggered children */
  .fade-in { opacity: 0; animation: fadeIn .8s ease forwards; }
  @keyframes fadeIn { to { opacity: 1; } }

  /* breathing dot for "thinking" — slow, not jittery */
  .breath { width:10px; height:10px; border-radius:9999px; background:#6F8A6A;
            box-shadow: 0 0 0 0 rgba(111,138,106,0.4);
            animation: breath 3.2s ease-in-out infinite; }
  @keyframes breath {
    0%,100%{transform:scale(.8); opacity:.55; box-shadow: 0 0 0 0 rgba(111,138,106,0.35);}
    50%    {transform:scale(1.25); opacity:1;  box-shadow: 0 0 0 10px rgba(111,138,106,0);}
  }

  /* shimmer on the brand title */
  .brand {
    background: linear-gradient(100deg, #2B3A2A 0%, #4A6248 35%, #3F7F7A 60%, #4A6248 80%, #2B3A2A 100%);
    background-size: 220% 100%;
    -webkit-background-clip: text; background-clip: text;
    color: transparent;
    animation: shimmer 9s ease-in-out infinite;
  }
  @keyframes shimmer { 0%,100%{background-position:0% 50%;} 50%{background-position:100% 50%;} }

  /* soft focus */
  textarea:focus, button:focus { outline: 2px solid #A9BBA0; outline-offset: 2px; }
  ::selection { background: #E2E9DC; }

  .prose-calm p { margin: 0 0 .9em; }
  .prose-calm ol, .prose-calm ul { margin: 0 0 .9em 1.2em; }
  .prose-calm li { margin: .25em 0; }
  details > summary { list-style: none; cursor: pointer; }
  details > summary::-webkit-details-marker { display: none; }

  /* starter buttons: lift + tint on hover */
  .starter {
    transition: transform .25s ease, background .25s ease, border-color .25s ease, box-shadow .25s ease;
  }
  .starter:hover { transform: translateY(-2px); box-shadow: 0 6px 18px -10px rgba(74,98,72,0.35); }

  /* send button: gentle gradient + hover sheen */
  .send-btn {
    background: linear-gradient(135deg, #4A6248 0%, #3F7F7A 100%);
    transition: transform .2s ease, box-shadow .2s ease, filter .2s ease;
    box-shadow: 0 8px 20px -10px rgba(45,92,88,0.55);
  }
  .send-btn:hover { transform: translateY(-1px); filter: brightness(1.05); box-shadow: 0 12px 26px -12px rgba(45,92,88,0.6); }
  .send-btn .arrow { transition: transform .25s ease; display: inline-block; }
  .send-btn:hover .arrow { transform: translateX(4px); }

  /* composer card */
  .composer-card {
    background: rgba(255,255,255,0.72);
    backdrop-filter: blur(8px);
    transition: border-color .25s ease, box-shadow .25s ease;
    box-shadow: 0 10px 30px -20px rgba(43,58,42,0.25);
  }
  .composer-card:focus-within { border-color: #A9BBA0; box-shadow: 0 14px 36px -18px rgba(63,127,122,0.35); }

  /* user bubble: soft gradient */
  .user-bubble {
    background: linear-gradient(135deg, #4A6248 0%, #3F7F7A 100%);
    box-shadow: 0 8px 22px -14px rgba(45,92,88,0.55);
  }

  /* assistant accent stripe */
  .assistant-stripe {
    width: 3px; border-radius: 9999px;
    background: linear-gradient(180deg, #A9BBA0, #3F7F7A);
  }

  /* citation markers inside the answer body — small pills that jump to the source list */
  .cite-mark {
    display: inline-block;
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 0.72em;
    font-weight: 600;
    line-height: 1;
    padding: 2px 6px;
    margin: 0 2px;
    border-radius: 9999px;
    background: #E2E9DC;
    color: #2B3A2A;
    text-decoration: none;
    vertical-align: 1px;
    transition: background .2s ease, transform .15s ease;
  }
  .cite-mark:hover { background: #A9BBA0; transform: translateY(-1px); }
  .cite-target { scroll-margin-top: 80px; }
  .cite-flash { animation: flash 1.4s ease; }
  @keyframes flash {
    0%   { background: #F6EBD2; }
    100% { background: transparent; }
  }

  /* "offline" badge with a tiny living pulse */
  .offline-badge {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 2px 10px; border-radius: 9999px;
    background: rgba(169,187,160,0.25); color: #2D5C58;
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase;
    border: 1px solid rgba(63,127,122,0.25);
  }
  .offline-dot {
    width: 6px; height: 6px; border-radius: 9999px; background: #3F7F7A;
    animation: pulse 2.4s ease-in-out infinite;
  }
  @keyframes pulse {
    0%,100% { box-shadow: 0 0 0 0 rgba(63,127,122,0.45); }
    50%     { box-shadow: 0 0 0 6px rgba(63,127,122,0); }
  }

  /* disaster-type tag chip inside citations */
  .type-tag {
    display: inline-block;
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 10.5px; font-weight: 600; letter-spacing: 0.04em;
    text-transform: uppercase;
    padding: 1px 7px; border-radius: 9999px;
    background: rgba(63,127,122,0.12); color: #2D5C58;
    margin-left: 6px;
  }
</style>
</head>
<body class="min-h-screen">

<div class="aurora" aria-hidden="true">
  <div class="glow"></div>
  <div class="sun"></div>
</div>

<!-- Persistent safety anchor -->
<div class="ui w-full bg-sage-900/95 text-cream-50 text-sm backdrop-blur">
  <div class="max-w-4xl mx-auto px-5 py-2.5 flex flex-wrap items-center gap-x-6 gap-y-1 justify-between">
    <div class="flex items-center gap-2">
      <span class="breath" aria-hidden="true"></span>
      <span>If you are in immediate danger, call <a href="tel:911" class="underline underline-offset-2 font-semibold">911</a>.</span>
    </div>
    <div class="opacity-80">This assistant is informational. It is not emergency dispatch.</div>
  </div>
</div>

<header class="max-w-4xl mx-auto px-5 pt-12 pb-6 reveal">
  <div class="flex items-center gap-3 flex-wrap">
    <h1 class="brand font-serif text-5xl sm:text-6xl tracking-tight">SafetyGuide</h1>
    <span class="offline-badge" title="Runs entirely on this device. No network calls.">
      <span class="offline-dot" aria-hidden="true"></span>
      Offline · Local
    </span>
  </div>
  <p class="ui mt-2 text-sage-700 text-sm">Disaster preparedness assistant · Pacific Northwest</p>
</header>

<!-- Conversation -->
<main class="max-w-4xl mx-auto px-5 mt-2">
  <div id="thread" class="space-y-6" aria-live="polite"></div>
</main>

<!-- Composer -->
<section class="max-w-4xl mx-auto px-5 mt-6 pb-32">
  <form id="composer" class="composer-card relative rounded-2xl border border-sage-100 p-2 reveal">
    <label for="q" class="sr-only">Ask a question</label>
    <textarea id="q" rows="3"
      class="ui w-full resize-none rounded-xl bg-transparent
             px-4 py-3 text-base text-ink-900 placeholder-sage-700/60
             focus:outline-none"
      placeholder="For example: What should I do in the first minutes of a strong earthquake?"></textarea>
    <div class="ui px-2 pt-1 pb-2 flex flex-wrap items-center justify-between gap-3">
      <div class="text-xs text-sage-700">
        Press <kbd class="px-1.5 py-0.5 rounded bg-cream-100 border border-cream-200">Enter</kbd> to send ·
        <kbd class="px-1.5 py-0.5 rounded bg-cream-100 border border-cream-200">Shift</kbd>+<kbd class="px-1.5 py-0.5 rounded bg-cream-100 border border-cream-200">Enter</kbd> for a new line
      </div>
      <button id="send" type="submit"
        class="send-btn inline-flex items-center gap-2 rounded-full
               text-cream-50 px-5 py-2.5 text-sm font-medium">
        Ask SafetyGuide
        <span class="arrow" aria-hidden="true">→</span>
      </button>
    </div>
  </form>

  <!-- Suggested starters -->
  <div id="starters" class="ui mt-6 flex flex-wrap gap-2">
    <!-- injected -->
  </div>

  <!-- Scope note -->
  <details class="ui mt-8 text-sm text-sage-700">
    <summary class="inline-flex items-center gap-2 text-sage-900 font-medium">
      <span>What SafetyGuide is — and is not</span>
      <span class="text-sage-500" aria-hidden="true">▾</span>
    </summary>
    <div class="mt-3 grid sm:grid-cols-2 gap-4">
      <div class="bg-sage-50 border border-sage-100 rounded-xl p-4">
        <div class="font-semibold text-sage-900 mb-1">It is</div>
        <ul class="list-disc ml-5 space-y-1">
          <li>A calm reference for preparedness and immediate self-protection.</li>
          <li>Grounded in Ready.gov, American Red Cross, and WA EMD source documents.</li>
          <li>Fully offline — questions stay on this device; nothing phones home.</li>
          <li>Designed to refuse rather than guess when the local index lacks evidence.</li>
        </ul>
      </div>
      <div class="bg-cream-100 border border-cream-200 rounded-xl p-4">
        <div class="font-semibold text-sage-900 mb-1">It is not</div>
        <ul class="list-disc ml-5 space-y-1">
          <li>A replacement for 911 or local emergency services.</li>
          <li>A source of live alerts, shelter availability, or routing.</li>
          <li>Medical, legal, or structural-engineering advice.</li>
        </ul>
      </div>
    </div>
  </details>
</section>

<template id="userBubble">
  <div class="reveal flex justify-end">
    <div class="ui user-bubble max-w-[85%] text-cream-50 rounded-2xl rounded-br-md px-4 py-3 text-[15px] whitespace-pre-wrap"></div>
  </div>
</template>

<template id="assistantBubble">
  <article class="reveal">
    <div class="flex items-center gap-2 ui text-xs text-sage-700 mb-2">
      <span class="inline-block w-2 h-2 rounded-full bg-sage-500"></span>
      <span class="font-medium tracking-wide uppercase">SafetyGuide</span>
      <span class="conf-badge hidden ml-2 px-2 py-0.5 rounded-full text-[11px]"></span>
    </div>

    <div class="gated-banner hidden ui mb-3 rounded-xl border border-amber-500/40 bg-amber-100 text-amber-700 px-4 py-3">
      <div class="font-semibold mb-0.5">I could not find reliable information in the local emergency knowledge base.</div>
      <div class="text-sm">Try rephrasing your question, or — for an active emergency — call <a href="tel:911" class="underline">911</a> or contact your local emergency management office.</div>
    </div>

    <div class="answer prose-calm text-[17px] text-ink-900"></div>

    <div class="citations ui mt-4 text-sm hidden">
      <div class="text-xs uppercase tracking-wider text-sage-700 mb-2">Sources</div>
      <ol class="space-y-2 list-decimal ml-5"></ol>
    </div>

    <div class="ui mt-4 text-xs text-sage-700">
      Always follow guidance from local authorities.
    </div>
  </article>
</template>

<script>
// ---------- Starters ----------
const STARTERS = [
  'What should I do during an earthquake?',
  'How much water should I store for two weeks?',
  'Is the food in my fridge safe after the power goes out?',
  'When should I evacuate for a wildfire?',
];
const startersEl = document.getElementById('starters');
STARTERS.forEach((s, i) => {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'starter fade-in text-left text-sm rounded-full border border-sage-100 bg-white/70 px-3.5 py-1.5 text-sage-900 hover:bg-sage-50';
  b.style.animationDelay = (120 * i) + 'ms';
  b.textContent = s;
  b.addEventListener('click', () => {
    document.getElementById('q').value = s;
    document.getElementById('q').focus();
  });
  startersEl.appendChild(b);
});

// ---------- Thread rendering ----------
const thread = document.getElementById('thread');

function addUser(text) {
  const tpl = document.getElementById('userBubble').content.cloneNode(true);
  tpl.querySelector('div > div').textContent = text;
  thread.appendChild(tpl);
  window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
}

function addThinking() {
  const el = document.createElement('div');
  el.className = 'reveal ui flex items-center gap-3 text-sage-700';
  el.innerHTML = '<span class="breath" aria-hidden="true"></span><span>Reading the preparedness guides…</span>';
  thread.appendChild(el);
  return el;
}

// Citation marker linker: turns "[1]" / "[2]" inside the answer body into
// clickable pills that scroll to the matching item in the citations list.
// Backend contract: citations are returned in the safety-reordered order so
// [n] indices line up with the displayed list (see src/generate.py).
let __ansSeq = 0;
function linkifyCitations(html, threadId, maxN) {
  return html.replace(/\[(\d+)\]/g, (m, nStr) => {
    const n = parseInt(nStr, 10);
    if (!n || n > maxN) return m; // leave unparseable markers alone
    return '<a href="#cite-' + threadId + '-' + n + '" class="cite-mark" data-n="' + n + '" data-thread="' + threadId + '">' + n + '</a>';
  });
}

function renderAnswerInto(node, result) {
  const tpl = document.getElementById('assistantBubble').content.cloneNode(true);
  const root = tpl.querySelector('article');
  const answerEl = root.querySelector('.answer');
  const banner   = root.querySelector('.gated-banner');
  const confBadge= root.querySelector('.conf-badge');
  const citesEl  = root.querySelector('.citations');
  const list     = citesEl.querySelector('ol');

  const threadId = ++__ansSeq;
  const citations = Array.isArray(result.citations) ? result.citations : [];

  // Confidence badge — thresholds calibrated to bge-reranker-base on this corpus:
  // relevant top hits land at ~0.85–0.99, noise near ~0.0001, gate at 0.1.
  if (typeof result.confidence === 'number' && !result.gated) {
    confBadge.classList.remove('hidden');
    if (result.confidence >= 0.7) {
      confBadge.textContent = 'high confidence';
      confBadge.classList.add('bg-sage-100','text-sage-900');
    } else if (result.confidence >= 0.3) {
      confBadge.textContent = 'partial match';
      confBadge.classList.add('bg-cream-100','text-amber-700');
    } else {
      confBadge.textContent = 'low match';
      confBadge.classList.add('bg-amber-100','text-amber-700');
    }
  }

  if (result.gated) {
    banner.classList.remove('hidden');
    answerEl.innerHTML = '';
  } else {
    answerEl.innerHTML = linkifyCitations(paragraphize(result.answer || ''), threadId, citations.length);
  }

  if (citations.length) {
    citesEl.classList.remove('hidden');
    citations.forEach((c, i) => {
      const n = i + 1;
      const li = document.createElement('li');
      li.id = 'cite-' + threadId + '-' + n;
      li.className = 'cite-target';

      const title = document.createElement('div');
      title.className = 'font-medium text-sage-900 flex items-center flex-wrap gap-x-1';
      const titleText = document.createElement('span');
      titleText.textContent = c.title || c.source || 'Source';
      title.appendChild(titleText);
      if (c.disaster_type && c.disaster_type !== 'general') {
        const tag = document.createElement('span');
        tag.className = 'type-tag';
        tag.textContent = c.disaster_type;
        title.appendChild(tag);
      }

      const meta = document.createElement('div');
      meta.className = 'text-sage-700 text-xs';
      meta.textContent = [c.source, c.section, (c.page && c.page !== 1) ? `p. ${c.page}` : null]
        .filter(Boolean).join(' · ');

      li.appendChild(title);
      if (meta.textContent) li.appendChild(meta);

      const snippet = c.snippet || (c.text ? truncate(c.text, 220) : null);
      if (snippet) {
        const sn = document.createElement('div');
        sn.className = 'mt-1 text-ink-700 text-[13.5px] italic';
        sn.textContent = '“' + snippet + '”';
        li.appendChild(sn);
      }
      list.appendChild(li);
    });
  }

  node.replaceWith(tpl);
}

// Smooth-scroll + brief flash when a citation pill is clicked
document.addEventListener('click', (e) => {
  const a = e.target.closest('a.cite-mark');
  if (!a) return;
  const href = a.getAttribute('href');
  if (!href || !href.startsWith('#')) return;
  const target = document.getElementById(href.slice(1));
  if (!target) return;
  e.preventDefault();
  target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  target.classList.remove('cite-flash');
  void target.offsetWidth; // restart animation
  target.classList.add('cite-flash');
});

function truncate(s, n) {
  s = String(s).replace(/\s+/g, ' ').trim();
  return s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s;
}

function paragraphize(text) {
  // very light formatter: split blank lines into paragraphs; "- " into list items
  const blocks = String(text).trim().split(/\n{2,}/);
  return blocks.map(b => {
    const lines = b.split('\n').map(s => s.trim()).filter(Boolean);
    const allBullets = lines.length > 1 && lines.every(l => /^[-•]\s+/.test(l));
    if (allBullets) {
      return '<ul>' + lines.map(l => '<li>' + escapeHtml(l.replace(/^[-•]\s+/, '')) + '</li>').join('') + '</ul>';
    }
    const numbered = lines.length > 1 && lines.every(l => /^\d+\.\s+/.test(l));
    if (numbered) {
      return '<ol>' + lines.map(l => '<li>' + escapeHtml(l.replace(/^\d+\.\s+/, '')) + '</li>').join('') + '</ol>';
    }
    return '<p>' + escapeHtml(lines.join(' ')) + '</p>';
  }).join('');
}
function escapeHtml(s){return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

// ---------- BACKEND ADAPTER ----------
// Wire this to `src.generate.answer(query)` via your HTTP layer (Gradio,
// FastAPI, etc.). Backend returns the contract documented in CLAUDE.md:
//   {
//     answer:     string,    // text containing [n] markers; \n\n separates paragraphs
//     citations:  [{ text, source, page, disaster_type }],  // chunks.json shape,
//                                                           // already safety-reordered
//                                                           // so [n] indices line up
//     gated:      boolean,   // true => retrieval gate tripped; `answer` is the canned
//                            // LOW_CONFIDENCE_MESSAGE verbatim (banner replaces it)
//     confidence: number?    // optional: top cross-encoder score for the UI badge
//   }
async function sendQuery({ query }) {
  // === LIVE BACKEND (uncomment when wired) ===
  // const res = await fetch('http://localhost:8000/chat', {
  //   method: 'POST',
  //   headers: { 'Content-Type': 'application/json' },
  //   body: JSON.stringify({ query })
  // });
  // if (!res.ok) throw new Error('Backend error: ' + res.status);
  // return await res.json();

  // === DEV STUB (delete when wired) ===
  await new Promise(r => setTimeout(r, 900 + Math.random() * 700));
  const q = query.toLowerCase();
  if (q.length < 3) {
    return { gated: true, confidence: 0.0, answer: '', citations: [] };
  }
  if (/earthquake|quake|shake/.test(q)) {
    return {
      confidence: 0.92,
      gated: false,
      answer:
        "When shaking begins, drop to your hands and knees before the quake throws you down [1]. This protects you and lets you move if you need to.\n\n" +
        "- Cover your head and neck with one arm. If a sturdy table is within reach, get under it; otherwise move next to an interior wall away from windows [1].\n" +
        "- Hold on to your shelter (or your head and neck) until the shaking stops [2].\n" +
        "- Stay where you are. Most injuries happen when people try to move during shaking [3].\n\n" +
        "After the shaking stops, expect aftershocks. Check yourself for injuries before helping others, and be cautious of broken glass, fallen objects, and damaged structures [2].",
      citations: [
        { source: 'Ready.gov — Earthquakes', page: 1, disaster_type: 'earthquake',
          text: 'Drop, Cover, and Hold On. Drop to your hands and knees so the earthquake does not knock you down. Cover your head and neck with one arm and hand.' },
        { source: 'WA EMD — 2 Weeks Ready', page: 7, disaster_type: 'earthquake',
          text: 'Hold on to any sturdy cover until the shaking stops. Be prepared to move with your shelter if it shifts.' },
        { source: 'American Red Cross — Earthquake Safety', page: 1, disaster_type: 'earthquake',
          text: 'Most injuries during earthquakes happen when people try to move to a different location inside the building, or try to leave.' }
      ]
    };
  }
  if (/water|drink/.test(q)) {
    return {
      confidence: 0.88,
      gated: false,
      answer:
        "Plan for one gallon of water per person per day, for at least two weeks [1]. That covers drinking, basic hygiene, and food preparation.\n\n" +
        "- Store water in food-grade containers in a cool, dark place [2].\n" +
        "- Replace stored water every six months, or use commercially sealed bottled water and follow the printed date [1].\n" +
        "- Include extra water for pets, for anyone who is pregnant or ill, and for hot weather [1].",
      citations: [
        { source: 'WA EMD — 2 Weeks Ready', page: 4, disaster_type: 'general',
          text: 'Store at least one gallon of water per person per day for two weeks for drinking and sanitation.' },
        { source: 'Ready.gov — Build a Kit', page: 1, disaster_type: 'general',
          text: 'Keep water in a cool, dark place. Replace stored water every six months.' }
      ]
    };
  }
  if (/fridge|food|power|outage/.test(q)) {
    return {
      confidence: 0.81,
      gated: false,
      answer:
        "Keep refrigerator and freezer doors closed as much as possible during a power outage [1]. A closed refrigerator keeps food cold for about four hours; a full freezer holds its temperature for about 48 hours (24 if half full) [1].\n\n" +
        "- Discard any perishable food (meat, poultry, fish, eggs, leftovers) that has been above 40°F for two hours or more [2].\n" +
        "- When in doubt, throw it out. Never taste food to decide if it is safe [2].",
      citations: [
        { source: 'Ready.gov — Food Safety During Power Outage', page: 1, disaster_type: 'outage',
          text: 'Keep the refrigerator and freezer doors closed. The refrigerator will keep food cold for about 4 hours if unopened.' },
        { source: 'American Red Cross — Food Safety', page: 1, disaster_type: 'outage',
          text: 'Throw out perishable food that has been above 40°F (4°C) for two hours or more. When in doubt, throw it out.' }
      ]
    };
  }
  // Low-confidence fallback — backend would return the canned LOW_CONFIDENCE_MESSAGE here
  return {
    confidence: 0.05,
    gated: true,
    answer: '',
    citations: []
  };
}
// ---------------------------------

// ---------- Submission ----------
const form = document.getElementById('composer');
const qEl  = document.getElementById('q');

qEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = qEl.value.trim();
  if (!text) return;
  qEl.value = '';
  addUser(text);

  const thinking = addThinking();

  try {
    const result = await sendQuery({ query: text });
    renderAnswerInto(thinking, result);
  } catch (err) {
    renderAnswerInto(thinking, {
      gated: true,
      confidence: 0,
      answer: '',
      citations: []
    });
    console.error(err);
  }
});
</script>
</body>
</html>

  );
}
