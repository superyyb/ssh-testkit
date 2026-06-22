import os
import logging
from datetime import datetime
import psycopg2


def _connect():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "testframework"),
        user=os.getenv("POSTGRES_USER", "testuser"),
        password=os.getenv("POSTGRES_PASSWORD", "testpass"),
        connect_timeout=5,
    )


def init_schema():
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS test_runs (
                    id            SERIAL PRIMARY KEY,
                    config_file   VARCHAR(255),
                    started_at    TIMESTAMP,
                    finished_at   TIMESTAMP,
                    total_pass    INTEGER DEFAULT 0,
                    total_fail    INTEGER DEFAULT 0,
                    total_flaky   INTEGER DEFAULT 0,
                    total_unknown INTEGER DEFAULT 0,
                    duration_s    FLOAT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS test_results (
                    id          SERIAL PRIMARY KEY,
                    run_id      INTEGER REFERENCES test_runs(id),
                    test_name   VARCHAR(255),
                    status      VARCHAR(20),
                    attempts    INTEGER DEFAULT 1,
                    duration_s  FLOAT,
                    stdout      TEXT,
                    stderr      TEXT,
                    ai_analysis TEXT,
                    created_at  TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute("""
                ALTER TABLE test_results
                ADD COLUMN IF NOT EXISTS duration_s FLOAT
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alert_events (
                    id           SERIAL PRIMARY KEY,
                    run_id       INTEGER REFERENCES test_runs(id),
                    triggered_at TIMESTAMP,
                    log_line     TEXT,
                    ai_analysis  TEXT
                )
            """)
            # Mark any runs left incomplete by a previous crash
            cur.execute("""
                UPDATE test_runs
                SET finished_at = started_at, duration_s = -1
                WHERE finished_at IS NULL
            """)
        conn.commit()
    logging.info("[DB] Schema initialized")


def create_test_run(config_file):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO test_runs (config_file, started_at) VALUES (%s, %s) RETURNING id",
                (config_file, datetime.now())
            )
            run_id = cur.fetchone()[0]
        conn.commit()
    return run_id


def save_test_result(run_id, result):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO test_results (run_id, test_name, status, attempts, duration_s, stdout, stderr)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                run_id,
                result["name"],
                result["status"],
                result["attempts"],
                result.get("duration_s"),
                result.get("stdout", ""),
                result.get("stderr", ""),
            ))
            result_id = cur.fetchone()[0]
        conn.commit()
    return result_id


def update_result_ai(result_id, ai_analysis):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE test_results SET ai_analysis = %s WHERE id = %s",
                (ai_analysis, result_id)
            )
        conn.commit()


def save_alert_event(run_id, log_line):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO alert_events (run_id, triggered_at, log_line)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (run_id, datetime.now(), log_line))
            alert_id = cur.fetchone()[0]
        conn.commit()
    return alert_id


def update_alert_ai(alert_id, ai_analysis):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE alert_events SET ai_analysis = %s WHERE id = %s",
                (ai_analysis, alert_id)
            )
        conn.commit()


def finish_test_run(run_id, results, started_at):
    passed  = sum(1 for r in results if r["status"] == "PASS")
    failed  = sum(1 for r in results if r["status"] == "FAIL")
    flaky   = sum(1 for r in results if r["status"] == "FLAKY")
    unknown = sum(1 for r in results if r["status"] == "UNKNOWN")
    finished_at = datetime.now()
    duration_s  = (finished_at - started_at).total_seconds()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE test_runs
                SET finished_at = %s, duration_s = %s,
                    total_pass = %s, total_fail = %s,
                    total_flaky = %s, total_unknown = %s
                WHERE id = %s
            """, (finished_at, duration_s, passed, failed, flaky, unknown, run_id))
        conn.commit()
    logging.info(f"[DB] Run #{run_id} completed — {passed}P {flaky}FL {failed}F {unknown}U")
