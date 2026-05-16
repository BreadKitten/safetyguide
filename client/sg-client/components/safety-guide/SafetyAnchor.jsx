export function SafetyAnchor() {
  return (
    <div className='ui w-full bg-sage-500 text-cream-50 text-sm backdrop-blur'>
      <div className='mx-auto flex max-w-4xl flex-wrap items-center justify-between gap-x-6 gap-y-1 px-5 py-2.5'>
        <div className='flex items-center gap-2'>
          {/* <span className="breath" aria-hidden="true" /> */}
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
        <div className='opacity-80'>
          This assistant is informational. It is not emergency dispatch.
        </div>
      </div>
    </div>
  );
}
