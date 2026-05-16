import { SAFETY_SCOPE } from '@/lib/safety-guide/content';

export function ScopeNote() {
  return (
    <details className='ui mt-8 text-sm text-sage-700'>
      <summary className='inline-flex items-center gap-2 font-medium text-sage-900'>
        <span>Disclaimer: What SafetyGuide is, and is not</span>
        <span className='text-sage-500' aria-hidden='true'>
          v
        </span>
      </summary>
      <div className='mt-3 grid gap-4 sm:grid-cols-2'>
        <ScopeList
          heading='It is'
          items={SAFETY_SCOPE.is}
          className='bg-sage-50 border-sage-100'
        />
        <ScopeList
          heading='It is not'
          items={SAFETY_SCOPE.isNot}
          className='bg-cream-100 border-cream-200'
        />
      </div>
    </details>
  );
}

function ScopeList({ heading, items, className }) {
  return (
    <div className={`rounded-lg border p-4 ${className}`}>
      <div className='mb-1 font-semibold text-sage-900'>{heading}</div>
      <ul className='ml-5 list-disc space-y-1'>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
