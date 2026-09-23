interface D1Result<T = unknown> {
  results?: T[];
  success?: boolean;
  meta?: {
    changes?: number;
    duration?: number;
    rows_read?: number;
    rows_written?: number;
    [key: string]: unknown;
  };
}

interface D1PreparedStatement {
  bind(...values: unknown[]): D1PreparedStatement;
  all<T = unknown>(): Promise<D1Result<T>>;
  first<T = unknown>(): Promise<T | null>;
  run(): Promise<D1Result>;
}

interface D1Database {
  prepare(query: string): D1PreparedStatement;
  batch(statements: D1PreparedStatement[]): Promise<D1Result[]>;
}

interface R2Object {
  key: string;
  size: number;
  etag: string;
  httpEtag: string;
  customMetadata: Record<string, string>;
  checksums: Record<string, string | undefined>;
}

interface R2ObjectBody extends R2Object {
  body: ReadableStream<Uint8Array<ArrayBuffer>>;
}

interface R2Bucket {
  get(key: string): Promise<R2ObjectBody | R2Object | null>;
  head(key: string): Promise<R2Object | null>;
}

interface ScheduledController {
  cron: string;
  scheduledTime: number;
}

interface ExecutionContext {
  waitUntil(promise: Promise<unknown>): void;
  passThroughOnException(): void;
}
