import sqlite3
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from palette_api.domain import Track
from palette_api.enrichment import D1QueueEnrichmentScheduler, _job_key
from palette_api.musicbrainz import MusicBrainzUnavailableError


if "workers" not in sys.modules:
    workers_stub = ModuleType("workers")

    class WorkerEntrypoint:
        pass

    workers_stub.WorkerEntrypoint = WorkerEntrypoint
    sys.modules["workers"] = workers_stub

from enrichment_worker import (  # noqa: E402
    DLQ_QUEUE_NAME,
    MAIN_QUEUE_NAME,
    Default,
)


class D1Statement:
    def __init__(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple = (),
        fail_completed: bool = False,
    ) -> None:
        self.conn = conn
        self.query = query
        self.params = params
        self.fail_completed = fail_completed

    def bind(self, *params: object) -> "D1Statement":
        return D1Statement(
            self.conn,
            self.query,
            params,
            fail_completed=self.fail_completed,
        )

    async def first(self) -> dict | None:
        cursor = self.conn.execute(self.query, self.params)
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(zip([column[0] for column in cursor.description], row))

    async def all(self) -> object:
        cursor = self.conn.execute(self.query, self.params)
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description]
        return SimpleNamespace(results=[dict(zip(columns, row)) for row in rows])

    async def run(self) -> object:
        if self.fail_completed and "SET status = 'completed'" in self.query:
            self.fail_completed = False
            raise RuntimeError("D1 indisponível")
        cursor = self.conn.execute(self.query, self.params)
        self.conn.commit()
        return SimpleNamespace(meta=SimpleNamespace(changes=max(cursor.rowcount, 0)))


class D1Database:
    def __init__(self, conn: sqlite3.Connection, fail_completed: bool = False) -> None:
        self.conn = conn
        self.fail_completed = fail_completed

    def prepare(self, query: str) -> D1Statement:
        return D1Statement(self.conn, query, fail_completed=self.fail_completed)


class Message:
    def __init__(self, body: object, *, attempts: int = 1) -> None:
        self.body = body
        self.id = f"message-{attempts}"
        self.attempts = attempts
        self.ack_count = 0
        self.retry_calls: list[dict[str, object]] = []

    def ack(self) -> None:
        self.ack_count += 1

    def retry(self, **kwargs: object) -> None:
        self.retry_calls.append(kwargs)


@pytest.fixture
def seeded_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    root = Path(__file__).resolve().parent.parent
    for name in (
        "0001_initial_schema.sql",
        "0002_seed_taxonomy.sql",
        "0005_analysis_contract.sql",
        "0006_enrichment_outbox.sql",
        "0007_family_claims_and_conservative_mapping.sql",
    ):
        conn.executescript((root / "migrations" / name).read_text())
    yield conn
    conn.close()


def seed_job(conn: sqlite3.Connection, track: Track) -> str:
    job_key = _job_key(track)
    conn.execute(
        "INSERT INTO recordings (id, title, artist, canonical_mbid) VALUES (42, ?, ?, ?)",
        (track.title, track.artist, f"recording-{track.mbid}"),
    )
    conn.execute(
        """
        INSERT INTO enrichment_jobs
            (job_key, source_mbid, source_entity_type, artist, title, dispatch_status)
        VALUES (?, ?, 'unknown', ?, ?, 'queued')
        """,
        (job_key, track.mbid, track.artist, track.title),
    )
    conn.commit()
    return job_key


def make_worker(db: D1Database) -> Default:
    worker = object.__new__(Default)
    worker.env = SimpleNamespace(
        DB=db,
        MUSICBRAINZ_USER_AGENT="test-agent",
    )
    return worker


@pytest.mark.anyio
async def test_redelivery_is_acknowledged_without_reprocessing(
    seeded_db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    track = Track("Song", "Artist", 1, mbid="track-mbid")
    job_key = seed_job(seeded_db, track)
    calls = 0

    class FakeEnricher:
        async def enrich_track(self, received: Track) -> int:
            nonlocal calls
            calls += 1
            assert received.title == track.title
            return 42

        async def accepted_claim_count(self, recording_id: int) -> int:
            assert recording_id == 42
            return 1

    monkeypatch.setattr("enrichment_worker.MusicBrainzResolver", lambda transport: object())
    monkeypatch.setattr(
        "enrichment_worker.MusicBrainzEnricher",
        lambda resolver, repository: FakeEnricher(),
    )

    worker = make_worker(D1Database(seeded_db))
    body = {"schema_version": 2, "job_key": job_key, "generation": 1}
    first = Message(body)
    second = Message(body, attempts=2)

    await worker.queue(SimpleNamespace(queue=MAIN_QUEUE_NAME, messages=[first]), None, None)
    await worker.queue(SimpleNamespace(queue=MAIN_QUEUE_NAME, messages=[second]), None, None)

    assert calls == 1
    assert first.ack_count == 1
    assert second.ack_count == 1
    assert not first.retry_calls
    assert seeded_db.execute(
        "SELECT status, recording_id, dispatch_status FROM enrichment_jobs"
    ).fetchone() == ("completed", 42, "none")


@pytest.mark.anyio
async def test_d1_failure_marks_retryable_job_and_retries_message(
    seeded_db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    track = Track("Song", "Artist", 1, mbid="track-mbid")
    job_key = seed_job(seeded_db, track)

    class FakeEnricher:
        async def enrich_track(self, received: Track) -> int:
            return 42

        async def accepted_claim_count(self, recording_id: int) -> int:
            return 1

    monkeypatch.setattr("enrichment_worker.MusicBrainzResolver", lambda transport: object())
    monkeypatch.setattr(
        "enrichment_worker.MusicBrainzEnricher",
        lambda resolver, repository: FakeEnricher(),
    )

    worker = make_worker(D1Database(seeded_db, fail_completed=True))
    message = Message(
        {"schema_version": 2, "job_key": job_key, "generation": 1},
        attempts=2,
    )

    await worker.queue(SimpleNamespace(queue=MAIN_QUEUE_NAME, messages=[message]), None, None)

    assert message.ack_count == 0
    assert message.retry_calls and message.retry_calls[0]["delaySeconds"] > 0
    assert seeded_db.execute(
        "SELECT status, last_error FROM enrichment_jobs"
    ).fetchone() == ("failed", "D1 indisponível")


@pytest.mark.anyio
async def test_dead_letter_marks_job_terminal(
    seeded_db: sqlite3.Connection,
) -> None:
    track = Track("Song", "Artist", 1, mbid="track-mbid")
    job_key = seed_job(seeded_db, track)
    worker = make_worker(D1Database(seeded_db))
    message = Message({"schema_version": 2, "job_key": job_key, "generation": 1})

    await worker.queue(SimpleNamespace(queue=DLQ_QUEUE_NAME, messages=[message]), None, None)

    assert message.ack_count == 1
    assert seeded_db.execute(
        "SELECT status, terminal_reason_code, dispatch_status FROM enrichment_jobs"
    ).fetchone() == ("terminal", "retry_exhausted", "none")


@pytest.mark.anyio
async def test_musicbrainz_unavailable_is_retryable(
    seeded_db: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    track = Track("Song", "Artist", 1, mbid="track-mbid")
    job_key = seed_job(seeded_db, track)

    class FakeEnricher:
        async def enrich_track(self, received: Track) -> int:
            raise MusicBrainzUnavailableError("timeout")

        async def accepted_claim_count(self, recording_id: int) -> int:
            raise AssertionError("não deveria ser chamado")

    monkeypatch.setattr("enrichment_worker.MusicBrainzResolver", lambda transport: object())
    monkeypatch.setattr(
        "enrichment_worker.MusicBrainzEnricher",
        lambda resolver, repository: FakeEnricher(),
    )

    worker = make_worker(D1Database(seeded_db))
    message = Message({"schema_version": 2, "job_key": job_key, "generation": 1})

    await worker.queue(SimpleNamespace(queue=MAIN_QUEUE_NAME, messages=[message]), None, None)

    assert message.ack_count == 0
    assert message.retry_calls
    assert seeded_db.execute(
        "SELECT status FROM enrichment_jobs"
    ).fetchone()[0] == "failed"


@pytest.mark.anyio
async def test_scheduled_recovers_jobs_with_none_env_argument(
    seeded_db: sqlite3.Connection,
) -> None:
    class Queue:
        def __init__(self) -> None:
            self.messages: list[object] = []

        async def send(self, body: object, **kwargs: object) -> None:
            self.messages.append(body)

    track = Track("Song", "Artist", 1, mbid="track-mbid")
    job_key = seed_job(seeded_db, track)
    worker = make_worker(D1Database(seeded_db))
    queue = Queue()
    worker.env.ENRICHMENT_QUEUE = queue
    seeded_db.execute(
        "UPDATE enrichment_jobs SET next_dispatch_at = datetime('now', '-1 second')"
    )
    seeded_db.commit()

    await worker.scheduled(SimpleNamespace(), None, None)

    assert queue.messages == [
        {"schema_version": 2, "job_key": job_key, "generation": 1}
    ]
    assert seeded_db.execute(
        "SELECT dispatch_status FROM enrichment_jobs"
    ).fetchone()[0] == "queued"


@pytest.mark.anyio
async def test_outbox_recovers_after_queue_send_failure(
    seeded_db: sqlite3.Connection,
) -> None:
    class Queue:
        def __init__(self) -> None:
            self.fail = True
            self.messages: list[object] = []

        async def send(self, body: object, **kwargs: object) -> None:
            if self.fail:
                raise RuntimeError("Queue indisponível")
            self.messages.append(body)

    queue = Queue()
    scheduler = D1QueueEnrichmentScheduler(D1Database(seeded_db), queue)
    track = Track("Song", "Artist", 1, mbid="track-mbid")

    await scheduler.schedule((track,))

    first_state = seeded_db.execute(
        "SELECT status, dispatch_status FROM enrichment_jobs"
    ).fetchone()
    assert first_state == ("pending", "failed")
    seeded_db.execute(
        "UPDATE enrichment_jobs SET next_dispatch_at = datetime('now', '-1 second')"
    )
    seeded_db.commit()
    queue.fail = False

    assert await scheduler.recover_pending() == 1
    assert len(queue.messages) == 1
    assert seeded_db.execute(
        "SELECT status, dispatch_status FROM enrichment_jobs"
    ).fetchone() == ("pending", "queued")
    assert queue.messages[0]["schema_version"] == 2
