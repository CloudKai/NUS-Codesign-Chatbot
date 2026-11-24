/** All private reader entries are rooted in a verified owner identity. */
export const queryKeys = {
  owner: (owner: string) => ['reader', owner] as const,
  notebooks: (owner: string) => ['reader', owner, 'notebooks'] as const,
};
