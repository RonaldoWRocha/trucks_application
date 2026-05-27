CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.clients (
    id bigserial PRIMARY KEY,
    name text NOT NULL,
    slug text NOT NULL UNIQUE,
    schema_name text NOT NULL UNIQUE,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT clients_slug_format CHECK (slug ~ '^[a-z0-9][a-z0-9_-]*$'),
    CONSTRAINT clients_schema_name_format CHECK (schema_name ~ '^[a-z][a-z0-9_]*$')
);

CREATE TABLE IF NOT EXISTS public.app_users (
    id bigserial PRIMARY KEY,
    name text NOT NULL,
    email text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    is_platform_admin boolean NOT NULL DEFAULT false,
    last_login_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT app_users_email_format CHECK (position('@' in email) > 1)
);

CREATE TABLE IF NOT EXISTS public.user_clients (
    user_id bigint NOT NULL REFERENCES public.app_users(id) ON DELETE CASCADE,
    client_id bigint NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    role text NOT NULL DEFAULT 'viewer',
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, client_id),
    CONSTRAINT user_clients_role_check CHECK (role IN ('owner', 'admin', 'operator', 'viewer'))
);

CREATE TABLE IF NOT EXISTS public.integration_credentials (
    id bigserial PRIMARY KEY,
    client_id bigint NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    provider text NOT NULL DEFAULT 'trucks',
    api_url text NOT NULL DEFAULT 'https://webservice.newrastreamentoonline.com.br/',
    login text NOT NULL,
    password_encrypted text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    last_test_at timestamptz,
    last_test_status text,
    last_test_message text,
    created_by bigint REFERENCES public.app_users(id) ON DELETE SET NULL,
    updated_by bigint REFERENCES public.app_users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (client_id, provider),
    CONSTRAINT integration_credentials_provider_check CHECK (provider IN ('trucks')),
    CONSTRAINT integration_credentials_test_status_check CHECK (
        last_test_status IS NULL OR last_test_status IN ('success', 'error')
    )
);

CREATE TABLE IF NOT EXISTS public.app_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id bigint NOT NULL REFERENCES public.app_users(id) ON DELETE CASCADE,
    active_client_id bigint REFERENCES public.clients(id) ON DELETE SET NULL,
    token_hash text NOT NULL UNIQUE,
    user_agent text,
    ip_address inet,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_clients_enabled
ON public.clients (enabled);

CREATE INDEX IF NOT EXISTS idx_app_users_enabled
ON public.app_users (enabled);

CREATE INDEX IF NOT EXISTS idx_user_clients_client
ON public.user_clients (client_id, enabled);

CREATE INDEX IF NOT EXISTS idx_integration_credentials_client_enabled
ON public.integration_credentials (client_id, provider, enabled);

CREATE INDEX IF NOT EXISTS idx_app_sessions_user
ON public.app_sessions (user_id, expires_at DESC);

CREATE INDEX IF NOT EXISTS idx_app_sessions_active
ON public.app_sessions (token_hash)
WHERE revoked_at IS NULL;

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_clients_updated_at ON public.clients;
CREATE TRIGGER trg_clients_updated_at
BEFORE UPDATE ON public.clients
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS trg_app_users_updated_at ON public.app_users;
CREATE TRIGGER trg_app_users_updated_at
BEFORE UPDATE ON public.app_users
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS trg_user_clients_updated_at ON public.user_clients;
CREATE TRIGGER trg_user_clients_updated_at
BEFORE UPDATE ON public.user_clients
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS trg_integration_credentials_updated_at ON public.integration_credentials;
CREATE TRIGGER trg_integration_credentials_updated_at
BEFORE UPDATE ON public.integration_credentials
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS trg_app_sessions_updated_at ON public.app_sessions;
CREATE TRIGGER trg_app_sessions_updated_at
BEFORE UPDATE ON public.app_sessions
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE OR REPLACE FUNCTION public.clone_schema(
    source_schema text,
    target_schema text,
    copy_data boolean DEFAULT false
)
RETURNS void AS $$
DECLARE
    table_record record;
BEGIN
    IF source_schema !~ '^[a-z][a-z0-9_]*$' OR target_schema !~ '^[a-z][a-z0-9_]*$' THEN
        RAISE EXCEPTION 'Nome de schema invalido';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.schemata WHERE schema_name = source_schema
    ) THEN
        RAISE EXCEPTION 'Schema origem nao existe: %', source_schema;
    END IF;

    EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', target_schema);

    FOR table_record IN
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = source_schema
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
    LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I.%I (LIKE %I.%I INCLUDING ALL)',
            target_schema,
            table_record.table_name,
            source_schema,
            table_record.table_name
        );

        IF copy_data THEN
            EXECUTE format(
                'INSERT INTO %I.%I SELECT * FROM %I.%I ON CONFLICT DO NOTHING',
                target_schema,
                table_record.table_name,
                source_schema,
                table_record.table_name
            );
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;
