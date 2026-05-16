export function AppHeader() {
  return (
    <header className='reveal mx-auto max-w-4xl px-5 pb-5 pt-12'>
      <div className='flex flex-wrap items-center gap-3'>
        <h1 className='brand font-serif text-5xl pb-5 tracking-tight sm:text-6xl'>
          SafetyGuide
        </h1>
        <span className='offline-badge'>
          <span className='offline-dot' aria-hidden='true' />
          Offline / Local
        </span>
      </div>
      <p className='ui text-sm text-black'>
        Disaster preparedness assistant / Pacific Northwest
      </p>
    </header>
  );
}
