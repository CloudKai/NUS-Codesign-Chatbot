/** All private reader entries are rooted in a verified owner identity. */
export const queryKeys = {
  owner: (owner: string) => ['reader', owner] as const,
  notebooks: (owner: string) => ['reader', owner, 'notebooks'] as const,
  preferences: (owner: string) => ['reader', owner, 'preferences'] as const,
  notebookSettings: (owner: string, thread: string) => ['reader', owner, 'notebook', thread, 'settings'] as const,
  sources: (owner: string, thread: string) => ['reader', owner, 'sources', thread] as const,
  uploads: (owner: string, thread: string) => ['reader', owner, 'uploads', thread] as const,
  bookmarks: (owner: string, thread: string) => ['reader', owner, 'bookmarks', thread] as const,
  project: (owner: string, thread: string) => ['reader', owner, 'project', thread] as const,
  deepReview: (owner: string, thread: string) => ['reader', owner, 'deep-review', thread] as const,
};
