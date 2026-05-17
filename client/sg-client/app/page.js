'use client';

import { AppHeader } from '@/components/safety-guide/AppHeader';
import { SafetyAnchor } from '@/components/safety-guide/SafetyAnchor';
import { ScopeNote } from '@/components/safety-guide/ScopeNote';
import { StarterPrompts } from '@/components/safety-guide/StarterPrompts';
import { useState, useRef, useEffect } from 'react';

export default function Home() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef(null);

  function handleStarterSelect(starter) {
    setInput(starter);
  }

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, busy]);

  async function send(e) {
    e.preventDefault();
    const query = input.trim();
    if (!query || busy) return;

    setMessages((m) => [...m, { role: 'user', text: query }]);
    setInput('');
    setBusy(true);

    // meta arrives before any tokens; hold it here until the first token lands.
    let pendingMeta = { citations: [], gated: false };
    // Whether we've added the assistant message bubble yet.
    let messageAdded = false;

    // Add the assistant bubble on first token so no empty shell shows during retrieval.
    const addMessage = (fields) => {
      setMessages((m) => [
        ...m,
        { role: 'assistant', citations: [], gated: false, streaming: true, ...fields },
      ]);
      messageAdded = true;
    };

    // Patch the last message in the array (only valid after addMessage).
    const patch = (fields) =>
      setMessages((m) => {
        const next = [...m];
        next[next.length - 1] = { ...next[next.length - 1], ...fields };
        return next;
      });

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      });

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      outer: while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop(); // keep the incomplete trailing line in the buffer
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const event = JSON.parse(line.slice(6));
          if (event.type === 'meta') {
            pendingMeta = { citations: event.citations, gated: event.gated };
          } else if (event.type === 'token') {
            if (!messageAdded) {
              addMessage({ text: event.text, ...pendingMeta });
            } else {
              setMessages((m) => {
                const next = [...m];
                const last = next[next.length - 1];
                next[next.length - 1] = { ...last, text: last.text + event.text };
                return next;
              });
            }
          } else if (event.type === 'done') {
            if (messageAdded) patch({ streaming: false });
            break outer;
          }
        }
      }
    } catch (err) {
      const errMsg = { text: `Network error: ${String(err)}`, gated: true, streaming: false };
      if (messageAdded) patch(errMsg);
      else addMessage(errMsg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className='flex flex-col min-h-screen bg-cream-50'>
      {/* Header */}
      <SafetyAnchor />

      <main className='mx-auto flex w-full max-w-[80%] flex-1 flex-col px-4 py-6'>
        <AppHeader />
        {/* Messages */}
        <div ref={scrollRef} className='flex-1 space-y-4 overflow-y-auto pb-4'>
          {messages.length === 0 && (
            <p className='text-sm text-sage-700 text-center'>
              Ask about earthquakes, wildfires, floods, power outages, or other
              disaster prep. Answers are grounded in local sources only.
            </p>
          )}

          {messages.map((m, i) => (
            <Message key={i} m={m} />
          ))}

          {busy && (
            <div className='text-sm italic text-sage-700'>Thinking…</div>
          )}
        </div>
        {/* Input */}
        <form onSubmit={send} className='mt-2 flex gap-2'>
          <input
            type='text'
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={busy}
            placeholder='What should I do during an earthquake?'
            className='flex-1 rounded-lg border border-sage-200 bg-white px-4 py-3 text-ink-900 placeholder-sage-700/60 outline-none focus:border-sage-400 disabled:opacity-60'
          />
          <button
            type='submit'
            disabled={busy || !input.trim()}
            className='rounded-full bg-ink-900 px-5 py-3 text-sm font-medium text-cream-50 transition hover:bg-ink-800 disabled:opacity-50'
          >
            Send →
          </button>
        </form>

        <p className='text-sage-700 pt-5 pl-3 text-1xl'>Quick prompts:</p>
        <StarterPrompts onSelect={handleStarterSelect} />

        <ScopeNote />
      </main>
    </div>
  );
}

function basename(path) {
  if (!path) return '';
  return String(path).split(/[\\/]/).pop();
}

// Strip a run of [n] citation markers the model sometimes emits at the very
// start of a response before the answer body (e.g. "[3][4]\n\nFor two weeks…").
function stripLeadingCitations(text) {
  return text.replace(/^\s*(\[\d+\]\s*)+\n/, '').trimStart();
}

function Message({ m }) {
  const isUser = m.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 border ${
          isUser
            ? 'bg-ink-900 text-cream-50 border-ink-900'
            : 'bg-white text-ink-900 border-sage-100'
        }`}
      >
        <div className='whitespace-pre-wrap text-sm leading-relaxed'>
          {isUser ? m.text : stripLeadingCitations(m.text)}
        </div>

        {!isUser && !m.streaming && m.citations?.length > 0 && (
          <ol className='mt-3 space-y-1 border-t border-sage-100 pt-2 text-xs text-sage-700'>
            {m.citations.map((c, idx) => (
              <li key={c.chunk_id ?? idx}>
                <details>
                  <summary className='cursor-pointer'>
                    <span className='font-mono'>[{idx + 1}]</span>{' '}
                    <span className='font-medium'>{basename(c.source)}</span>
                    {c.page ? ` · p.${c.page}` : ''}
                    {c.disaster_type && c.disaster_type !== 'general'
                      ? ` · ${c.disaster_type}`
                      : ''}
                  </summary>

                  <p className='mt-1 whitespace-pre-wrap pl-6 text-sage-600'>
                    {c.text}
                  </p>
                </details>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
