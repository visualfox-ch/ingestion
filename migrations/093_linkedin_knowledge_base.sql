-- Migration 093: LinkedIn Knowledge Base
-- Generische Dokument-Tabelle + Chunk-Tracking für Qdrant-Idempotenz

-- Dokument-Tabelle
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'internal_markdown',
    owner TEXT NOT NULL DEFAULT 'michael_bohl',
    domain TEXT NOT NULL,
    subdomain TEXT,
    channel TEXT,
    language TEXT DEFAULT 'de',
    quality TEXT DEFAULT 'high',
    version TEXT NOT NULL,
    content_hash TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(),

    CONSTRAINT unique_document_version UNIQUE (title, version)
);

-- Indizes für schnelle Suche
CREATE INDEX IF NOT EXISTS idx_documents_domain ON documents(domain);
CREATE INDEX IF NOT EXISTS idx_documents_subdomain ON documents(subdomain);
CREATE INDEX IF NOT EXISTS idx_documents_owner ON documents(owner);
CREATE INDEX IF NOT EXISTS idx_documents_version ON documents(version);

-- Chunk-Tracking (für Qdrant-Idempotenz)
CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_title TEXT,
    qdrant_point_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),

    CONSTRAINT unique_chunk UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_doc_id ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_qdrant_id ON document_chunks(qdrant_point_id);

-- Kommentar für Dokumentation
COMMENT ON TABLE documents IS 'Generische Dokument-Speicherung für Knowledge Bases (LinkedIn, etc.)';
COMMENT ON TABLE document_chunks IS 'Tracking welche Chunks in Qdrant gespeichert sind (für Idempotenz)';
