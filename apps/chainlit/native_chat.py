from __future__ import annotations

import csv
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _csv_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    """Defuse CSV/formula injection (DDE attack) before writing a row.

    Spreadsheet apps (Excel, LibreOffice) treat a cell starting with =, +, -,
    or @ as a formula. User-controlled values (username, feedback comments,
    chat content) end up in these admin-facing exports, so prefix such cells
    with a single quote to force plain-text rendering.
    """
    safe: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, str) and value.startswith(_CSV_FORMULA_PREFIXES):
            safe[key] = "'" + value
        else:
            safe[key] = value
    return safe


SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS "User" (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  identifier TEXT UNIQUE NOT NULL,
  email TEXT UNIQUE,
  password_hash TEXT,
  email_verified BOOLEAN NOT NULL DEFAULT FALSE,
  verification_token TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  "createdAt" TIMESTAMP NOT NULL DEFAULT NOW(),
  "updatedAt" TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Add columns for existing tables (idempotent migrations)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'User' AND column_name = 'email') THEN
    ALTER TABLE "User" ADD COLUMN email TEXT UNIQUE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'User' AND column_name = 'password_hash') THEN
    ALTER TABLE "User" ADD COLUMN password_hash TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'User' AND column_name = 'email_verified') THEN
    ALTER TABLE "User" ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT FALSE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'User' AND column_name = 'verification_token') THEN
    ALTER TABLE "User" ADD COLUMN verification_token TEXT;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS "Thread" (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT,
  "userId" UUID REFERENCES "User"(id) ON DELETE SET NULL,
  metadata TEXT NOT NULL DEFAULT '{}',
  tags TEXT,
  "createdAt" TIMESTAMP NOT NULL DEFAULT NOW(),
  "updatedAt" TIMESTAMP NOT NULL DEFAULT NOW(),
  "deletedAt" TIMESTAMP NULL
);

CREATE TABLE IF NOT EXISTS "Step" (
  id UUID PRIMARY KEY,
  "threadId" UUID REFERENCES "Thread"(id) ON DELETE CASCADE,
  "parentId" UUID NULL,
  input TEXT NULL,
  metadata TEXT NOT NULL DEFAULT '{}',
  name TEXT NULL,
  output TEXT NULL,
  type TEXT NOT NULL,
  "startTime" TIMESTAMP NULL,
  "endTime" TIMESTAMP NULL,
  "showInput" TEXT NULL,
  "isError" BOOLEAN NOT NULL DEFAULT FALSE,
  "createdAt" TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS "Element" (
  id UUID PRIMARY KEY,
  "threadId" UUID REFERENCES "Thread"(id) ON DELETE CASCADE,
  "stepId" UUID REFERENCES "Step"(id) ON DELETE CASCADE,
  metadata TEXT NOT NULL DEFAULT '{}',
  mime TEXT NULL,
  name TEXT NULL,
  "objectKey" TEXT NULL,
  url TEXT NULL,
  "chainlitKey" TEXT NULL,
  display TEXT NULL,
  size BIGINT NULL,
  language TEXT NULL,
  page INTEGER NULL,
  "autoPlay" BOOLEAN NULL,
  "playerConfig" TEXT NULL,
  props TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS "Feedback" (
  id UUID PRIMARY KEY,
  "stepId" UUID REFERENCES "Step"(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  value DOUBLE PRECISION NULL,
  comment TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_thread_user_updated
  ON "Thread"("userId", "updatedAt" DESC);
CREATE INDEX IF NOT EXISTS idx_step_thread_start
  ON "Step"("threadId", "startTime");
CREATE INDEX IF NOT EXISTS idx_element_thread
  ON "Element"("threadId");
-- Dedupliziere Feedback.stepId (nur neueste Zeile bleibt)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_name = 'Feedback'
    ) THEN
        DELETE FROM "Feedback"
        WHERE id::text NOT IN (
            SELECT max(id::text) FROM "Feedback" GROUP BY "stepId"
        );
    END IF;
END $$;

-- Einzigartigkeits-Index für stepId
CREATE UNIQUE INDEX IF NOT EXISTS "Feedback_stepId_unique"
ON "Feedback" ("stepId");

CREATE TABLE IF NOT EXISTS "Survey" (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_identifier TEXT NULL,
  role TEXT NULL,
  usability_feedback TEXT NULL,
  answer_relevance TEXT NULL,
  followup_relevance TEXT NULL,
  overall_satisfaction INTEGER NULL,
  trust_correctness TEXT NULL,
  most_helpful_feature TEXT NULL,
  improvement_suggestions TEXT NULL,
  additional_remarks TEXT NULL,
  submitted BOOLEAN NOT NULL DEFAULT TRUE,
  "createdAt" TIMESTAMP NOT NULL DEFAULT NOW(),
  "updatedAt" TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Migration falls "Survey" bereits ohne submitted/updatedAt existiert
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'Survey' AND column_name = 'submitted') THEN
    ALTER TABLE "Survey" ADD COLUMN submitted BOOLEAN NOT NULL DEFAULT TRUE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'Survey' AND column_name = 'updatedAt') THEN
    ALTER TABLE "Survey" ADD COLUMN "updatedAt" TIMESTAMP NOT NULL DEFAULT NOW();
  END IF;
END $$;
"""


async def ensure_native_schema(database_url: str) -> None:
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(SCHEMA_SQL)
    finally:
        await conn.close()


async def create_user(
    database_url: str,
    username: str,
    email: str,
    password_hash: str,
    *,
    email_verified: bool = False,
    verification_token: str | None = None,
) -> dict[str, Any] | None:
    """Create a new user with hashed password. Returns user dict or None if exists."""
    conn = await asyncpg.connect(database_url)
    try:
        try:
            row = await conn.fetchrow(
                '''
                INSERT INTO "User" (identifier, email, password_hash, email_verified, verification_token, metadata)
                VALUES ($1, $2, $3, $4, $5, '{"provider": "local"}')
                ON CONFLICT DO NOTHING
                RETURNING id, identifier, email, email_verified, metadata, "createdAt"
                ''',
                username,
                email,
                password_hash,
                email_verified,
                verification_token,
            )
            if row is None:
                return None
            return dict(row)
        except asyncpg.UniqueViolationError:
            return None
    finally:
        await conn.close()


async def get_user_by_identifier(
    database_url: str,
    identifier: str,
) -> dict[str, Any] | None:
    """Get user by username OR email.

    Chainlit's built-in login form is hardcoded to label this field "Email
    address", which conflicts with registration asking for a separate
    username. Matching on both columns means login works no matter which
    one the user types, removing the ambiguity at its source.
    """
    conn = await asyncpg.connect(database_url)
    try:
        row = await conn.fetchrow(
            """
            SELECT id, identifier, email, password_hash, email_verified, metadata, "createdAt"
            FROM "User"
            WHERE identifier = $1 OR email = $1
            """,
            identifier,
        )
        return dict(row) if row else None
    finally:
        await conn.close()


async def verify_user_email(
    database_url: str,
    token: str,
) -> dict[str, Any] | None:
    """Verify a user's email by token. Returns user dict or None if token invalid."""
    conn = await asyncpg.connect(database_url)
    try:
        row = await conn.fetchrow(
            """
            UPDATE "User"
            SET email_verified = TRUE, verification_token = NULL, "updatedAt" = NOW()
            WHERE verification_token = $1 AND email_verified = FALSE
            RETURNING id, identifier, email
            """,
            token,
        )
        print(f"[DEBUG] verify_user_email: token={token!r} matched_row={dict(row) if row else None}")
        return dict(row) if row else None
    finally:
        await conn.close()


async def get_user_by_email(
    database_url: str,
    email: str,
) -> dict[str, Any] | None:
    """Get user by email."""
    conn = await asyncpg.connect(database_url)
    try:
        row = await conn.fetchrow(
            """
            SELECT id, identifier, email, password_hash, metadata, "createdAt"
            FROM "User"
            WHERE email = $1
            """,
            email,
        )
        return dict(row) if row else None
    finally:
        await conn.close()


async def check_user_exists(
    database_url: str,
    username: str | None = None,
    email: str | None = None,
) -> dict[str, bool]:
    """Check if username or email already exists."""
    conn = await asyncpg.connect(database_url)
    try:
        result = {"username_exists": False, "email_exists": False}
        if username:
            row = await conn.fetchrow(
                'SELECT 1 FROM "User" WHERE identifier = $1',
                username,
            )
            result["username_exists"] = row is not None
        if email:
            row = await conn.fetchrow(
                'SELECT 1 FROM "User" WHERE email = $1',
                email,
            )
            result["email_exists"] = row is not None
        return result
    finally:
        await conn.close()


async def upsert_feedback(
    database_url: str,
    *,
    feedback_id: str,
    step_id: str,
    value: float,
    comment: str | None = None,
) -> None:
    """Insert or update a feedback row in the Feedback table.

    Uses a unique constraint on ``stepId`` so that repeated clicks on the
    same step always update the existing row instead of creating duplicates.
    """
    import uuid as _uuid

    conn = await asyncpg.connect(database_url)
    try:
        # Ensure the unique index exists (idempotent).
        await conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS "Feedback_stepId_unique"
            ON "Feedback" ("stepId")
            """
        )
        await conn.execute(
            """
            INSERT INTO "Feedback" (id, "stepId", name, value, comment)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT ("stepId") DO UPDATE
              SET value   = EXCLUDED.value,
                  comment = EXCLUDED.comment
            """,
            _uuid.UUID(feedback_id),
            _uuid.UUID(step_id),
            "user-feedback",
            value,
            comment,
        )
    finally:
        await conn.close()


async def export_all_chats_zip(
    *,
    database_url: str,
    out_dir: Path,
    user_id: str | None = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    jsonl_path = out_dir / f"native-chat-export-all-{stamp}.jsonl"
    csv_path = out_dir / f"native-chat-export-all-{stamp}.csv"
    zip_path = out_dir / f"native-chat-export-all-{stamp}.zip"

    conn = await asyncpg.connect(database_url)
    try:
        where_clause = 'WHERE t."deletedAt" IS NULL'
        params: list[Any] = []
        if user_id:
            where_clause += ' AND t."userId" = $1::uuid'
            params.append(user_id)

        threads = await conn.fetch(
            f"""
            SELECT
              t.id,
              t.name,
              t.metadata,
              t."createdAt",
              t."updatedAt",
              t."userId",
              u.identifier AS user_identifier
            FROM "Thread" t
            LEFT JOIN "User" u ON t."userId" = u.id
            {where_clause}
            ORDER BY t."updatedAt" DESC
            """,
            *params,
        )

        with jsonl_path.open("w", encoding="utf-8") as jf, csv_path.open(
            "w", encoding="utf-8", newline=""
        ) as cf:
            writer = csv.DictWriter(
                cf,
                fieldnames=[
                    "thread_id",
                    "thread_name",
                    "user_identifier",
                    "thread_created_at",
                    "thread_updated_at",
                    "step_id",
                    "step_type",
                    "step_name",
                    "step_start",
                    "step_end",
                    "step_input",
                    "step_output",
                    "step_is_error",
                ],
            )
            writer.writeheader()

            for thread in threads:
                steps = await conn.fetch(
                    """
                    SELECT id, type, name, input, output, "isError", "startTime", "endTime", metadata
                    FROM "Step"
                    WHERE "threadId" = $1::uuid
                    ORDER BY "startTime" NULLS LAST, "createdAt" NULLS LAST
                    """,
                    thread["id"],
                )
                payload = {
                    "thread": {
                        "id": str(thread["id"]),
                        "name": thread["name"],
                        "userId": str(thread["userId"]) if thread["userId"] else None,
                        "userIdentifier": thread["user_identifier"],
                        "metadata": json.loads(thread["metadata"] or "{}"),
                        "createdAt": thread["createdAt"].isoformat() if thread["createdAt"] else None,
                        "updatedAt": thread["updatedAt"].isoformat() if thread["updatedAt"] else None,
                    },
                    "steps": [
                        {
                            "id": str(step["id"]),
                            "type": step["type"],
                            "name": step["name"],
                            "input": step["input"],
                            "output": step["output"],
                            "isError": bool(step["isError"]),
                            "startTime": step["startTime"].isoformat() if step["startTime"] else None,
                            "endTime": step["endTime"].isoformat() if step["endTime"] else None,
                            "metadata": json.loads(step["metadata"] or "{}"),
                        }
                        for step in steps
                    ],
                }
                jf.write(json.dumps(payload, ensure_ascii=False))
                jf.write("\n")

                for step in steps:
                    writer.writerow(
                        _csv_safe_row({
                            "thread_id": str(thread["id"]),
                            "thread_name": thread["name"] or "",
                            "user_identifier": thread["user_identifier"] or "",
                            "thread_created_at": (
                                thread["createdAt"].isoformat() if thread["createdAt"] else ""
                            ),
                            "thread_updated_at": (
                                thread["updatedAt"].isoformat() if thread["updatedAt"] else ""
                            ),
                            "step_id": str(step["id"]),
                            "step_type": step["type"] or "",
                            "step_name": step["name"] or "",
                            "step_start": step["startTime"].isoformat() if step["startTime"] else "",
                            "step_end": step["endTime"].isoformat() if step["endTime"] else "",
                            "step_input": step["input"] or "",
                            "step_output": step["output"] or "",
                            "step_is_error": bool(step["isError"]),
                        })
                    )
    finally:
        await conn.close()

    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(jsonl_path, arcname=jsonl_path.name)
        zf.write(csv_path, arcname=csv_path.name)
    return zip_path


async def export_feedback_csv(
    *,
    database_url: str,
    out_dir: Path,
) -> Path:
    """Export all feedback rows joined with question, answer and user as CSV."""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"feedback-export-{_stamp()}.csv"

    conn = await asyncpg.connect(database_url)
    try:
        rows = await conn.fetch(
            """
            SELECT
                u.identifier AS username,
                COALESCE(user_q.output, user_q.input) AS user_question,
                COALESCE(child.output, child.input, s.output, s.input) AS assistant_answer,
                f.value AS feedback_value,
                f.comment AS feedback_comment,
                s."createdAt" AS answer_time,
                t.id AS thread_id,
                f.id AS feedback_id,
                f."stepId" AS step_id
            FROM "Feedback" f
            JOIN "Step" s ON s.id = f."stepId"
            JOIN "Thread" t ON t.id = s."threadId"
            LEFT JOIN "User" u ON u.id = t."userId"
            LEFT JOIN LATERAL (
                SELECT cs.output, cs.input
                FROM "Step" cs
                WHERE cs."parentId" = s.id
                    AND cs.type = 'assistant_message'
                ORDER BY cs."startTime" DESC
                LIMIT 1
            ) child ON true
            LEFT JOIN LATERAL (
                SELECT qs.output, qs.input
                FROM "Step" qs
                WHERE qs."threadId" = s."threadId"
                    AND qs.type = 'user_message'
                    AND qs."startTime" < s."startTime"
                ORDER BY qs."startTime" DESC
                LIMIT 1
            ) user_q ON true
            ORDER BY s."createdAt" DESC
            """
        )

        fieldnames = [
            "username",
            "user_question",
            "assistant_answer",
            "feedback_value",
            "feedback_comment",
            "answer_time",
            "thread_id",
            "feedback_id",
            "step_id",
        ]
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    _csv_safe_row({
                        "username": row["username"] or "",
                        "user_question": row["user_question"] or "",
                        "assistant_answer": row["assistant_answer"] or "",
                        "feedback_value": row["feedback_value"] if row["feedback_value"] is not None else "",
                        "feedback_comment": row["feedback_comment"] or "",
                        "answer_time": row["answer_time"].isoformat() if row["answer_time"] else "",
                        "thread_id": str(row["thread_id"]) if row["thread_id"] else "",
                        "feedback_id": str(row["feedback_id"]) if row["feedback_id"] else "",
                        "step_id": str(row["step_id"]) if row["step_id"] else "",
                    })
                )
    finally:
        await conn.close()

    return csv_path


async def delete_user_by_email(database_url: str, email: str) -> None:
    """Löscht einen Nutzer anhand der E-Mail-Adresse."""
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute('DELETE FROM "User" WHERE email = $1', email)
    finally:
        await conn.close()


async def get_survey_draft(database_url: str, user_identifier: str) -> dict[str, Any] | None:
    """Return this user's saved-but-not-yet-submitted draft, if any."""
    conn = await asyncpg.connect(database_url)
    try:
        row = await conn.fetchrow(
            """
            SELECT * FROM "Survey"
            WHERE user_identifier = $1 AND submitted = FALSE
            ORDER BY "updatedAt" DESC
            LIMIT 1
            """,
            user_identifier,
        )
        return dict(row) if row else None
    finally:
        await conn.close()


async def upsert_survey_response(
    database_url: str,
    *,
    user_identifier: str | None,
    role: str | None,
    usability_feedback: str | None,
    answer_relevance: str | None,
    followup_relevance: str | None,
    overall_satisfaction: int | None,
    trust_correctness: str | None,
    most_helpful_feature: str | None,
    improvement_suggestions: str | None,
    additional_remarks: str | None,
    submitted: bool,
) -> None:
    """Save a Feedback-Formular entry.

    If the user already has an unsubmitted draft, it is updated in place
    (whether saving as draft again or finalizing it). Otherwise a new row
    is inserted. This keeps at most one open draft per user while allowing
    multiple finalized submissions over time.
    """
    conn = await asyncpg.connect(database_url)
    try:
        updated = await conn.fetchrow(
            """
            UPDATE "Survey"
            SET role = $2, usability_feedback = $3, answer_relevance = $4,
                followup_relevance = $5, overall_satisfaction = $6,
                trust_correctness = $7, most_helpful_feature = $8,
                improvement_suggestions = $9, additional_remarks = $10,
                submitted = $11, "updatedAt" = NOW()
            WHERE user_identifier = $1 AND submitted = FALSE
            RETURNING id
            """,
            user_identifier,
            role,
            usability_feedback,
            answer_relevance,
            followup_relevance,
            overall_satisfaction,
            trust_correctness,
            most_helpful_feature,
            improvement_suggestions,
            additional_remarks,
            submitted,
        )
        if updated is None:
            await conn.execute(
                """
                INSERT INTO "Survey" (
                    user_identifier, role, usability_feedback, answer_relevance,
                    followup_relevance, overall_satisfaction, trust_correctness,
                    most_helpful_feature, improvement_suggestions, additional_remarks,
                    submitted
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                user_identifier,
                role,
                usability_feedback,
                answer_relevance,
                followup_relevance,
                overall_satisfaction,
                trust_correctness,
                most_helpful_feature,
                improvement_suggestions,
                additional_remarks,
                submitted,
            )
    finally:
        await conn.close()


async def export_survey_csv(*, database_url: str, out_dir: Path) -> Path:
    """Export all survey responses as CSV."""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"survey-export-{_stamp()}.csv"

    conn = await asyncpg.connect(database_url)
    try:
        rows = await conn.fetch(
            """
            SELECT user_identifier, role, usability_feedback, answer_relevance,
                   followup_relevance, overall_satisfaction, trust_correctness,
                   most_helpful_feature, improvement_suggestions, additional_remarks,
                   "createdAt"
            FROM "Survey"
            WHERE submitted = TRUE
            ORDER BY "createdAt" DESC
            """
        )
    finally:
        await conn.close()

    fieldnames = [
        "user_identifier", "role", "usability_feedback", "answer_relevance",
        "followup_relevance", "overall_satisfaction", "trust_correctness",
        "most_helpful_feature", "improvement_suggestions", "additional_remarks",
        "created_at",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                _csv_safe_row({
                    "user_identifier": row["user_identifier"] or "",
                    "role": row["role"] or "",
                    "usability_feedback": row["usability_feedback"] or "",
                    "answer_relevance": row["answer_relevance"] or "",
                    "followup_relevance": row["followup_relevance"] or "",
                    "overall_satisfaction": row["overall_satisfaction"] if row["overall_satisfaction"] is not None else "",
                    "trust_correctness": row["trust_correctness"] or "",
                    "most_helpful_feature": row["most_helpful_feature"] or "",
                    "improvement_suggestions": row["improvement_suggestions"] or "",
                    "additional_remarks": row["additional_remarks"] or "",
                    "created_at": row["createdAt"].isoformat() if row["createdAt"] else "",
                })
            )

    return csv_path
