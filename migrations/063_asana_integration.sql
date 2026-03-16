-- Migration: Asana Integration Tables
-- Erstellt Tabellen für persistente Asana-Datenhaltung

CREATE TABLE IF NOT EXISTS asana_workspace (
    id SERIAL PRIMARY KEY,
    asana_id VARCHAR(64) NOT NULL UNIQUE,
    name TEXT NOT NULL,
    last_synced TIMESTAMP,
    deleted BOOLEAN DEFAULT FALSE,
    sync_error TEXT,
    extra JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS asana_project (
    id SERIAL PRIMARY KEY,
    asana_id VARCHAR(64) NOT NULL UNIQUE,
    name TEXT NOT NULL,
    workspace_id VARCHAR(64),
    archived BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP,
    modified_at TIMESTAMP,
    last_synced TIMESTAMP,
    deleted BOOLEAN DEFAULT FALSE,
    sync_error TEXT,
    extra JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS asana_task (
    id SERIAL PRIMARY KEY,
    asana_id VARCHAR(64) NOT NULL UNIQUE,
    name TEXT NOT NULL,
    notes TEXT,
    project_id VARCHAR(64),
    workspace_id VARCHAR(64),
    assignee VARCHAR(128),
    completed BOOLEAN DEFAULT FALSE,
    due_on DATE,
    created_at TIMESTAMP,
    modified_at TIMESTAMP,
    last_synced TIMESTAMP,
    deleted BOOLEAN DEFAULT FALSE,
    sync_error TEXT,
    extra JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS asana_event (
    id SERIAL PRIMARY KEY,
    asana_id VARCHAR(64) NOT NULL UNIQUE,
    resource_type VARCHAR(32) NOT NULL,
    action VARCHAR(32) NOT NULL,
    created_at TIMESTAMP,
    user_id VARCHAR(128),
    task_id VARCHAR(64),
    project_id VARCHAR(64),
    workspace_id VARCHAR(64),
    last_synced TIMESTAMP,
    deleted BOOLEAN DEFAULT FALSE,
    sync_error TEXT,
    extra JSONB DEFAULT '{}'
);
