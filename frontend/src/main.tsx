import { StrictMode, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { SystemHealthPage } from './pages/SystemHealthPage';
import { SourcesPage } from './pages/SourcesPage';
import { AddSourcePage } from './pages/AddSourcePage';
import { RunsPage } from './pages/RunsPage';
import './styles.css';

function App() {
  const [page, setPage] = useState<'health' | 'sources' | 'add' | 'runs'>('health');
  return <>
    <header className="topbar"><a className="brand" href="/">Infra<span>Sync</span></a>
      <span className="mode">INFRA SYNC · SOURCE CONTROL</span></header>
    <nav aria-label="Main navigation" className="navigation">
      <button aria-pressed={page === 'health'} onClick={() => setPage('health')}>System Health</button>
      <button aria-pressed={page === 'sources'} onClick={() => setPage('sources')}>Sources</button>
      <button aria-pressed={page === 'add'} onClick={() => setPage('add')}>Add Source</button>
      <button aria-pressed={page === 'runs'} onClick={() => setPage('runs')}>Runs</button>
    </nav>
    {page === 'health' ? <SystemHealthPage /> : page === 'sources' ? <SourcesPage />
      : page === 'runs' ? <RunsPage /> : <AddSourcePage />}
  </>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
