-- Phase 19.5B: Git History Integration (Causal-Knowledge MVP)

CREATE TABLE IF NOT EXISTS git_commits (
    sha TEXT PRIMARY KEY,
    author_name TEXT,
    author_email TEXT,
    message TEXT,
    committed_at TIMESTAMPTZ,
    source_repo TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS git_commits_committed_at_idx
    ON git_commits (committed_at DESC);

CREATE INDEX IF NOT EXISTS git_commits_message_idx
    ON git_commits (message);
