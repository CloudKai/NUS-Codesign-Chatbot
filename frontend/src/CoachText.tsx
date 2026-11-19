/** Format saved coach text while keeping model output outside the HTML trust boundary. */
import { lazy, memo, Suspense } from 'react';

const Markdown = lazy(() => import('react-markdown'));

export const CoachText = memo(function CoachText({ text }: { text: string }) {
  return <div className="message-content coach-text">
    <Suspense fallback={<div className="message-content">{text}</div>}><Markdown skipHtml disallowedElements={['img']} components={{
      a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
    }}>{text}</Markdown></Suspense>
  </div>;
});
