import { SafetyGuideApp } from '@/components/safety-guide/SafetyGuideApp';

export default function Home() {
  return <SafetyGuideApp />;
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
