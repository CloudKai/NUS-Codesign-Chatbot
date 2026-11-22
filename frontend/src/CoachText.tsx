/** Format saved coach text while keeping model output outside the HTML trust boundary. */
import { lazy, memo, Suspense } from 'react';

const loadMarkdown = () => import('react-markdown');
const Markdown = lazy(loadMarkdown);

/** Start fetching the markdown chunk at app start so replies rarely render through the fallback. */
export const preloadMarkdown = () => { void loadMarkdown().catch(() => { /* The lazy import retries when a reply renders. */ }); };

/** Plain-text stand-in while the chunk loads: drops markdown marks so `**bold**` never flashes. */
function withoutMarks(text: string) {
  return text
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/^\s{0,3}>\s?/gm, '')
    .replace(/(\*\*|__|~~|`)/g, '')
    .replace(/(^|[\s(])[*_]([^*_\n]+)[*_](?=[\s).,;:!?]|$)/g, '$1$2');
}

/** Set links=false for display-only clamped previews; full messages retain safe external links. */
export const CoachText = memo(function CoachText({ text, links = true }: { text: string; links?: boolean }) {
  return <div className="message-content coach-text">
    <Suspense fallback={<div className="message-content coach-text-loading">{withoutMarks(text)}</div>}><Markdown skipHtml disallowedElements={['img']} components={{
      // react-markdown blanks javascript:, data: and similar addresses. Show that text instead of an empty link that opens a blank tab.
      a: ({ href, children }) => links && href && /^(https?:\/\/|mailto:)/i.test(href)
        ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <>{children}</>,
    }}>{text}</Markdown></Suspense>
  </div>;
});
