export class PaletteApiError extends Error {
  readonly code: string;
  readonly status: number;
  constructor(
    message: string,
    status: number,
    code: string,
    readonly retryAfter?: number,
  ) {
    super(message);
    this.name = "PaletteApiError";
    this.code = code;
    this.status = status;
  }
}

