/** Bounded readable plaintext projection of a saved artifact document.
 * Shared by the artifact-to-canvas dialog and the canvas stale-linkage update.
 */
import type { ArtifactDocument } from './api';

/** One top-level block's readable text; structured blocks resolve to nested text. */
function blockText(block: unknown): string {
  const lines: string[] = [];
  const walk = (node: unknown): void => {
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (node && typeof node === 'object') {
      const record = node as { text?: unknown; content?: unknown };
      if (typeof record.text === 'string') lines.push(record.text);
      if (Array.isArray(record.content)) record.content.forEach(walk);
    }
  };
  walk(block);
  return lines.join(' ').trim();
}

/** Readable saved text for the whole document or one top-level block index. */
export function artifactPlainText(document: ArtifactDocument | null | undefined,
                                  source: 'document' | number = 'document'): string {
  const blocks = (document?.content ?? []).filter(
    block => block && typeof block === 'object');
  if (source === 'document') {
    return blocks.map(block => blockText(block)).filter(Boolean).join('\n\n');
  }
  return blockText(blocks[source] ?? null);
}
