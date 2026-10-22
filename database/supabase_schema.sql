-- ============================================================================

-- StudentReplica Database Schema for Supabase (PostgreSQL)

-- Project: ixoxcwaharigczkhpexv

-- ============================================================================


CREATE TABLE accounts (
	user_id VARCHAR(36) NOT NULL, 
	username VARCHAR(64) NOT NULL, 
	password_hash VARCHAR(128) NOT NULL, 
	salt VARCHAR(64) NOT NULL, 
	display_name VARCHAR(120) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (user_id), 
	UNIQUE (username)
);

ALTER TABLE "accounts" ENABLE ROW LEVEL SECURITY;


CREATE TABLE ai_cache (
	id SERIAL NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	cache_key VARCHAR(128) NOT NULL, 
	response_json TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_ai_cache_user_key UNIQUE (user_id, cache_key)
);

CREATE INDEX ix_ai_cache_user_id ON ai_cache (user_id);

ALTER TABLE "ai_cache" ENABLE ROW LEVEL SECURITY;


CREATE TABLE chat_messages (
	id SERIAL NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	role VARCHAR(32) NOT NULL, 
	content TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_chat_messages_user_id ON chat_messages (user_id);

ALTER TABLE "chat_messages" ENABLE ROW LEVEL SECURITY;


CREATE TABLE generated_artifacts (
	id SERIAL NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	kind VARCHAR(64) NOT NULL, 
	payload_json TEXT NOT NULL, 
	prompt_text TEXT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_generated_artifacts_user_id ON generated_artifacts (user_id);

ALTER TABLE "generated_artifacts" ENABLE ROW LEVEL SECURITY;


CREATE TABLE twin_snapshots (
	id SERIAL NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	version INTEGER NOT NULL, 
	twin_json TEXT NOT NULL, 
	label VARCHAR(200), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_twin_snapshots_user_id ON twin_snapshots (user_id);

ALTER TABLE "twin_snapshots" ENABLE ROW LEVEL SECURITY;


CREATE TABLE twins (
	user_id VARCHAR(36) NOT NULL, 
	twin_json TEXT NOT NULL, 
	version INTEGER NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (user_id)
);

ALTER TABLE "twins" ENABLE ROW LEVEL SECURITY;


CREATE TABLE external_identities (
	provider VARCHAR(32) NOT NULL, 
	subject_hash VARCHAR(64) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (provider, subject_hash), 
	CONSTRAINT uq_external_identity_user_provider UNIQUE (user_id, provider), 
	FOREIGN KEY(user_id) REFERENCES accounts (user_id)
);

CREATE INDEX ix_external_identities_user_id ON external_identities (user_id);

ALTER TABLE "external_identities" ENABLE ROW LEVEL SECURITY;
