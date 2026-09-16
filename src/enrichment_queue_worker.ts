/**
 * TypeScript Queue ingress for enrichment.
 *
 * Queue delivery ownership lives here so ack/retry/DLQ transitions do not
 * execute inside the Python Workers Queue wrapper. The enrichment state
 * machine remains in the Python service and is called through RPC.
 */

const MAIN_QUEUE_NAME = "timbre-palette-enrichment";
const DLQ_QUEUE_NAME = "timbre-palette-enrichment-dlq";
const MAX_RETRY_DELAY_SECONDS = 60 * 60;

interface QueueRetryOptions {
  delaySeconds?: number;
}

interface QueueMessage {
  readonly body: unknown;
  readonly id: string;
  readonly attempts?: number;
  ack(): void;
  retry(options?: QueueRetryOptions): void;
}

interface QueueBatch {
  readonly queue: string;
  readonly messages: readonly QueueMessage[];
}

interface QueueDecision {
  readonly action: "ack" | "retry";
  readonly delay_seconds?: number;
}

interface PythonEnricherService {
  process_queue_message(
    body: unknown,
    messageId: string | null,
    attempts: number,
    queueName: string,
  ): Promise<QueueDecision>;
}

interface Env {
  readonly ENRICHER: PythonEnricherService;
}

export default {
  async queue(batch: QueueBatch, env: Env): Promise<void> {
    for (const message of batch.messages) {
      const attempts = Math.max(1, message.attempts ?? 1);

      try {
        const decision = await env.ENRICHER.process_queue_message(
          message.body,
          message.id || null,
          attempts,
          batch.queue,
        );
        applyDecision(message, decision);
      } catch (error) {
        console.error(
          JSON.stringify({
            event: "enrichment_python_service_error",
            queue_name: batch.queue,
            message_id: message.id,
            attempt: attempts,
            ...errorFields(error),
          }),
        );
        message.retry({
          delaySeconds: fallbackRetryDelaySeconds(attempts),
        });
      }
    }
  },
};

function applyDecision(message: QueueMessage, decision: QueueDecision): void {
  if (decision?.action === "ack") {
    message.ack();
    return;
  }

  if (decision?.action === "retry") {
    message.retry({
      delaySeconds: normalizeDelay(decision.delay_seconds),
    });
    return;
  }

  throw new Error("The Python service returned an invalid Queue decision.");
}

function fallbackRetryDelaySeconds(attempts: number): number {
  const exponent = Math.min(Math.max(1, attempts) - 1, 7);
  return Math.min(MAX_RETRY_DELAY_SECONDS, 30 * 2 ** exponent);
}

function normalizeDelay(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return 0;
  }
  return Math.min(MAX_RETRY_DELAY_SECONDS, Math.max(0, Math.round(value)));
}

function errorFields(error: unknown): Record<string, string> {
  if (error instanceof Error) {
    return {
      error_type: error.name,
      error_message: error.message.slice(0, 300),
    };
  }
  return {
    error_type: "UnknownError",
    error_message: String(error).slice(0, 300),
  };
}

export { DLQ_QUEUE_NAME, MAIN_QUEUE_NAME, fallbackRetryDelaySeconds };
