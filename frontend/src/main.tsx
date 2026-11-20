/** Mount the static lecture pilot; saved transcripts are never stored in the browser. */
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';
import { preloadMarkdown } from './CoachText';

preloadMarkdown();
createRoot(document.getElementById('root')!).render(<App/>);
