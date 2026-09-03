import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { SystemHealthPage } from './pages/SystemHealthPage';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <header className="topbar"><a className="brand" href="/">Infra<span>Sync</span></a>
      <span className="mode">READ-ONLY · WEB-1</span></header>
    <SystemHealthPage />
  </StrictMode>,
);
