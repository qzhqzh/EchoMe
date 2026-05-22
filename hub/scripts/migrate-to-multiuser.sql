-- EchoMe: Migrate existing single-tenant data to multi-user
-- Run this AFTER the first admin user has logged in via GitHub OAuth.
--
-- What this does:
-- 1. Finds the first admin user (the first GitHub OAuth login)
-- 2. Updates all memories/projects/sync_log with user_id='default' to the admin's UUID
--
-- Usage:
--   psql $DATABASE_URL -f migrate-to-multiuser.sql
-- Or via docker:
--   docker exec -i echome-postgres psql -U echome -d echome < migrate-to-multiuser.sql

DO $$
DECLARE
    admin_uuid TEXT;
BEGIN
    -- Get the first admin user's ID
    SELECT id::text INTO admin_uuid
    FROM users
    WHERE role = 'admin'
    ORDER BY created_at ASC
    LIMIT 1;

    IF admin_uuid IS NULL THEN
        RAISE EXCEPTION 'No admin user found. Please login via GitHub OAuth first.';
    END IF;

    RAISE NOTICE 'Migrating data to admin user: %', admin_uuid;

    -- Migrate memories
    UPDATE memories SET user_id = admin_uuid WHERE user_id = 'default';
    RAISE NOTICE 'Memories migrated: % rows', ROW_COUNT;

    -- Migrate projects
    UPDATE projects SET user_id = admin_uuid WHERE user_id = 'default';
    RAISE NOTICE 'Projects migrated: % rows', ROW_COUNT;

    -- Migrate sync_log
    UPDATE sync_log SET user_id = admin_uuid WHERE user_id = 'default';
    RAISE NOTICE 'Sync logs migrated: % rows', ROW_COUNT;

    RAISE NOTICE 'Migration complete!';
END $$;
