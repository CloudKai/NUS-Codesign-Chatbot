/** HTTP status selects safe recovery copy without echoing private server errors. */
export class ApiError extends Error {
  constructor(public status: number) { super('Reader request failed'); }
}
