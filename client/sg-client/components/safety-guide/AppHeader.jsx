export function AppHeader() {
  return (
    <header className='reveal mx-auto max-w-4xl px-5 pb-5 pt-12 flex flex-col items-center text-center'>
      {/* Top row: logo + badge */}
      <div className='flex items-center gap-4'>
        <h1 className='brand font-serif text-5xl tracking-tight sm:text-6xl'>
          S<span className='text-emerald-950'>A</span>FETYGU
          <span className='text-emerald-950'>I</span>DE
        </h1>

        <div className='offline-badge flex items-center gap-2'>
          <span className='offline-dot' aria-hidden='true' />
          <span>Offline / Local</span>
        </div>
      </div>

      {/* Subtitle under both */}
      <p className='ui text-sm text-black mt-2'>
        Disaster preparedness assistant / Pacific Northwest
      </p>
    </header>
  );
}
