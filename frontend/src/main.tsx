/** Mount the static lecture pilot; saved transcripts are never stored in the browser. */
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import './tailwind.css';
import './styles.css';
import { preloadMarkdown } from './CoachText';

preloadMarkdown();
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 0,
      gcTime: 0,
      retry: false,
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
    },
    mutations: { retry: false },
  },
});
createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={queryClient}><App/></QueryClientProvider>,
);
