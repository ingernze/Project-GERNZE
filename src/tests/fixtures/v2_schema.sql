
CREATE TABLE IF NOT EXISTS lessons (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
 id TEXT PRIMARY KEY, lesson_id TEXT NOT NULL REFERENCES lessons(id),
 answers TEXT NOT NULL, outcome TEXT NOT NULL, tags TEXT NOT NULL,
 note TEXT NOT NULL, source TEXT NOT NULL, minutes INTEGER NOT NULL,
 recorded_at TEXT NOT NULL, next_review TEXT);
CREATE INDEX IF NOT EXISTS sessions_lesson ON sessions(lesson_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS sessions_review ON sessions(next_review);
CREATE INDEX IF NOT EXISTS sessions_recorded ON sessions(recorded_at);
CREATE TABLE IF NOT EXISTS records (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
 source TEXT NOT NULL, occurred_at TEXT NOT NULL, created_at TEXT NOT NULL,
 decision TEXT NOT NULL, implementation TEXT NOT NULL, auto_check TEXT NOT NULL,
 manual_check TEXT NOT NULL, evidence TEXT NOT NULL, scope TEXT NOT NULL,
 memory_confirmed INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 superseded_by TEXT REFERENCES records(id));
CREATE INDEX IF NOT EXISTS records_current ON records(active, memory_confirmed, created_at DESC);
CREATE TABLE IF NOT EXISTS reminders (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, due_epoch REAL NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','queued','delivered','cancelled')));
CREATE INDEX IF NOT EXISTS reminders_due ON reminders(status, due_epoch);
CREATE TABLE IF NOT EXISTS handoffs (
 id TEXT PRIMARY KEY, lesson_id TEXT NOT NULL REFERENCES lessons(id),
 lesson_hash TEXT NOT NULL, base_session_id TEXT REFERENCES sessions(id),
 mode TEXT NOT NULL, created_at TEXT NOT NULL,
 result_session_id TEXT REFERENCES sessions(id), result_digest TEXT,
 result_reminder_id TEXT REFERENCES reminders(id));
CREATE TABLE IF NOT EXISTS module_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
PRAGMA user_version = 2;
