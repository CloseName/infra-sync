import { StrictMode, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { SystemHealthPage } from './pages/SystemHealthPage';
import { SourcesPage } from './pages/SourcesPage';
import './styles.css';

function App() {
  const [page, setPage] = useState<'health' | 'sources'>('health');
  return <>
    <header className="topbar"><a className="brand" href="/">Infra<span>Sync</span></a>
      <span className="mode">READ-ONLY · WEB-2</span></header>
    <nav aria-label="Main navigation" className="navigation">
      <button aria-pressed={page === 'health'} onClick={() => setPage('health')}>System Health</button>
      <button aria-pressed={page === 'sources'} onClick={() => setPage('sources')}>Sources</button>
    </nav>
    {page === 'health' ? <SystemHealthPage /> : <SourcesPage />}
  </>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
