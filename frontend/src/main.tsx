/** Mount the static React notebook pilot without persistent browser storage. */
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';

createRoot(document.getElementById('root')!).render(<App/>);
