/** Mount the static lecture pilot; saved transcripts are never stored in the browser. */
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { createReaderQueryClient } from './api/queryClient';
import App from './App';
import './tailwind.css';
import './styles.css';
import { preloadMarkdown } from './CoachText';

preloadMarkdown();
const queryClient = createReaderQueryClient();
createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={queryClient}><App/></QueryClientProvider>,
);
