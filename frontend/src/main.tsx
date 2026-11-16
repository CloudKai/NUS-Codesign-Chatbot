/** Mount the static lecture pilot; saved transcripts are never stored in the browser. */
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';

createRoot(document.getElementById('root')!).render(<App/>);
