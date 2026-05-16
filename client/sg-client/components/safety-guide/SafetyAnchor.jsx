import { MapPin } from 'lucide-react';

export function SafetyAnchor() {
  return (
    <div className='ui w-full sticky top-0 z-50 bg-sage-500 text-cream-50 text-sm backdrop-blur'>
      <div className='mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-x-6 gap-y-1 px-5 py-2.5'>
        <div className='flex items-center gap-2'>
          <span>
            If you are in immediate danger, call{' '}
            <a
              href='tel:911'
              className='font-semibold underline underline-offset-2'
            >
              911
            </a>
            .
          </span>
        </div>

        <div className='flex items-center gap-4 opacity-90'>
          <span className='hidden sm:block'>
            This assistant is informational. It is not emergency dispatch.
          </span>

          <a
            href='/map'
            className='flex items-center gap-1 rounded-md bg-cream-50/10 px-3 py-1.5 text-cream-50 transition hover:bg-cream-50/20'
          >
            <MapPin className='h-4 w-4' />
            <span>Find nearest help</span>
          </a>
        </div>
      </div>
    </div>
  );
}
