'use client';

import { useState, useRef, useEffect } from 'react';

// Each message: { role: "user" | "assistant", text, citations?, gated? }.
// `citations` mirrors GenerationResult.citations from server/src/generate.py:
// list of { chunk_id, text, source, page, disaster_type, score } in the same
// order as the [n] markers in `text` (safety-first reordered).

export default function Home() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef(null);

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

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessages((m) => [
          ...m,
          {
            role: 'assistant',
            text: data?.error
              ? `Backend error: ${data.error}`
              : `Backend error (${res.status}).`,
            gated: true,
          },
        ]);
      } else {
        setMessages((m) => [
          ...m,
          {
            role: 'assistant',
            text: data.answer,
            citations: data.citations ?? [],
            gated: !!data.gated,
          },
        ]);
      }
    } catch (err) {
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          text: `Network error: ${String(err)}`,
          gated: true,
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className='flex flex-col flex-1 min-h-screen bg-zinc-50 dark:bg-black'>
      <header className='border-b border-amber-300 bg-amber-100 px-4 py-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100'>
        <strong>Emergency?</strong> Call 911. This assistant is for preparation
        and general guidance only.
      </header>

      <main className='mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 py-6'>
        <h1 className='mb-4 text-2xl font-semibold text-zinc-900 dark:text-zinc-50'>
          SafetyGuide
        </h1>

        <div ref={scrollRef} className='flex-1 space-y-4 overflow-y-auto pb-4'>
          {messages.length === 0 && (
            <p className='text-sm text-zinc-500'>
              Ask about earthquakes, wildfires, floods, power outages, or other
              disaster prep. Answers are grounded in local sources only.
            </p>
          )}
          {messages.map((m, i) => (
            <Message key={i} m={m} />
          ))}
          {busy && (
            <div className='text-sm italic text-zinc-500'>Thinking…</div>
          )}
        </div>

        <form onSubmit={send} className='mt-2 flex gap-2'>
          <input
            type='text'
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={busy}
            placeholder='What should I do during an earthquake?'
            className='flex-1 rounded-lg border border-zinc-300 bg-white px-4 py-3 text-zinc-900 placeholder-zinc-400 outline-none focus:border-zinc-500 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50'
          />
          <button
            type='submit'
            disabled={busy || !input.trim()}
            className='rounded-lg bg-zinc-900 px-5 py-3 text-sm font-medium text-white transition hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-300'
          >
            Send
          </button>
        </form>
      </main>
    </div>
  );
}

function Message({ m }) {
  const isUser = m.role === 'user';
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 ${
          isUser
            ? 'bg-zinc-900 text-zinc-50 dark:bg-zinc-50 dark:text-zinc-900'
            : 'bg-white text-zinc-900 ring-1 ring-zinc-200 dark:bg-zinc-900 dark:text-zinc-50 dark:ring-zinc-800'
        }`}
      >
        <div className='whitespace-pre-wrap text-sm leading-relaxed'>
          {m.text}
        </div>
        {!isUser && m.citations && m.citations.length > 0 && (
          <ol className='mt-3 space-y-1 border-t border-zinc-200 pt-2 text-xs text-zinc-600 dark:border-zinc-800 dark:text-zinc-400'>
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
                  <p className='mt-1 whitespace-pre-wrap pl-6 text-zinc-500 dark:text-zinc-400'>
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

function basename(path) {
  if (!path) return 'source';
  const parts = String(path).split(/[\\/]/);
  return parts[parts.length - 1] || path;
}
