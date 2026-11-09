-- Founder's Resource Portal (PostgreSQL)
CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    sector TEXT,
    stage TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('founder', 'staff')),
    company_id INT REFERENCES companies(id),
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS resources (
    id SERIAL PRIMARY KEY,
    company_id INT REFERENCES companies(id),
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    resource_type TEXT,
    review_note TEXT,
    is_portfolio_wide BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sector_updates (
    id SERIAL PRIMARY KEY,
    company_id INT REFERENCES companies(id),
    label TEXT,
    title TEXT NOT NULL,
    summary TEXT,
    sector TEXT,
    source TEXT,
    published_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS connect_entries (
    id SERIAL PRIMARY KEY,
    network_group TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role_title TEXT,
    organization TEXT,
    skills TEXT[] DEFAULT '{}',
    why_relevant TEXT,
    category_tag TEXT,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS founder_help (
    id SERIAL PRIMARY KEY,
    public_ref TEXT UNIQUE NOT NULL,
    company_id INT NOT NULL REFERENCES companies(id),
    user_id INT NOT NULL REFERENCES users(id),
    subject TEXT NOT NULL,
    context TEXT,
    category TEXT,
    resource_id INT REFERENCES resources(id),
    connect_entry_id INT REFERENCES connect_entries(id),
    founder_status TEXT DEFAULT 'Demo Ventures is reviewing your request',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS work_items (
    id SERIAL PRIMARY KEY,
    help_id INT NOT NULL REFERENCES founder_help(id) ON DELETE CASCADE,
    internal_status TEXT DEFAULT 'queued',
    priority TEXT DEFAULT 'normal',
    assigned_to TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS playbook_progress (
    id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES companies(id),
    playbook_name TEXT NOT NULL,
    progress_pct INT DEFAULT 0,
    current_phase TEXT,
    owner_name TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_resources_company ON resources(company_id);
CREATE INDEX IF NOT EXISTS idx_help_company ON founder_help(company_id);

CREATE TABLE IF NOT EXISTS user_sessions (
    token TEXT PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id);

-- Alpha content governance (Resource Repository meeting, 19 Oct 2026): uploaded resources stay
-- in_review until the weekly manual check; only approved resources reach founders.
ALTER TABLE resources ADD COLUMN IF NOT EXISTS slug TEXT;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS subcategory TEXT;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'approved';
ALTER TABLE resources ADD COLUMN IF NOT EXISTS file_name TEXT;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS content_owner TEXT;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}';
ALTER TABLE resources ADD COLUMN IF NOT EXISTS submitted_by TEXT;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS reviewed_by TEXT;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS review_comment TEXT;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
CREATE UNIQUE INDEX IF NOT EXISTS idx_resources_slug ON resources(slug);
CREATE INDEX IF NOT EXISTS idx_resources_status ON resources(status);

-- Founder intake (one-question-at-a-time form in the Resource Library).
CREATE TABLE IF NOT EXISTS founder_intake (
    id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES companies(id),
    user_id INT NOT NULL REFERENCES users(id),
    answers JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_intake_company ON founder_intake(company_id);

-- Download audit (drives founder "recent activity" and content usage reporting).
CREATE TABLE IF NOT EXISTS resource_downloads (
    id SERIAL PRIMARY KEY,
    resource_id INT NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    user_id INT NOT NULL REFERENCES users(id),
    company_id INT REFERENCES companies(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_downloads_company ON resource_downloads(company_id);

-- Failed-login throttling (survives restarts; per email).
CREATE TABLE IF NOT EXISTS login_failures (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_login_failures_email ON login_failures(email, created_at);

-- Admin (Resource Repository meeting follow-up): Demo Ventures team assignments are effective-dated so
-- reassignments keep history (changeable relationship-team assignments).
CREATE TABLE IF NOT EXISTS company_assignments (
    id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('relationship_partner', 'portfolio_analyst')),
    person TEXT NOT NULL,
    effective_from TIMESTAMPTZ DEFAULT NOW(),
    assigned_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_assignments_company ON company_assignments(company_id, role, effective_from);

-- Every admin change is recorded.
CREATE TABLE IF NOT EXISTS admin_audit (
    id SERIAL PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit(created_at);

-- Sector updates are published manually by an admin, with a reliable source.
ALTER TABLE sector_updates ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE sector_updates ADD COLUMN IF NOT EXISTS published_by TEXT;

-- Events with RSVPs (admin-managed). company_id NULL = all portfolio founders.
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    location TEXT,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ,
    company_id INT REFERENCES companies(id) ON DELETE CASCADE,
    recording_url TEXT,
    is_sample BOOLEAN DEFAULT FALSE,
    active BOOLEAN DEFAULT TRUE,
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_events_starts ON events(starts_at);
CREATE TABLE IF NOT EXISTS event_rsvps (
    event_id INT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (event_id, user_id)
);

-- 100-Day Playbook tasks per company; progress is calculated from these.
CREATE TABLE IF NOT EXISTS playbook_tasks (
    id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    phase_no INT NOT NULL CHECK (phase_no BETWEEN 1 AND 4),
    title TEXT NOT NULL,
    sort_order INT DEFAULT 0,
    resource_slug TEXT,
    done BOOLEAN DEFAULT FALSE,
    done_at TIMESTAMPTZ,
    done_by TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tasks_company ON playbook_tasks(company_id, phase_no, sort_order);

-- Per-user read state for founder notifications.
CREATE TABLE IF NOT EXISTS notification_reads (
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_key TEXT NOT NULL,
    read_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, item_key)
);

-- Connect directory managed by admins.
ALTER TABLE connect_entries ADD COLUMN IF NOT EXISTS subcategory TEXT;
ALTER TABLE connect_entries ADD COLUMN IF NOT EXISTS is_sample BOOLEAN DEFAULT FALSE;
ALTER TABLE connect_entries ADD COLUMN IF NOT EXISTS created_by TEXT;

-- Live sector news (near real time). Approved feeds are read every NEWS_FETCH_MINUTES; items are
-- matched to companies by sector and keywords and land in a Suggested queue. Nothing reaches a founder
-- until an admin publishes it, and only from a source Demo Ventures has approved.
CREATE TABLE IF NOT EXISTS news_sources (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    feed_url TEXT NOT NULL UNIQUE,
    site_url TEXT,
    kind TEXT NOT NULL DEFAULT 'news' CHECK (kind IN ('official', 'news')),
    sectors TEXT NOT NULL DEFAULT '*',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    approved BOOLEAN NOT NULL DEFAULT FALSE,
    approved_by TEXT,
    approved_at TIMESTAMPTZ,
    last_fetched_at TIMESTAMPTZ,
    last_status TEXT,
    last_error TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS news_items (
    id SERIAL PRIMARY KEY,
    source_id INT NOT NULL REFERENCES news_sources(id) ON DELETE CASCADE,
    url_hash TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    excerpt TEXT,
    url TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    fetched_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_news_items_published ON news_items(published_at);
CREATE TABLE IF NOT EXISTS news_matches (
    id SERIAL PRIMARY KEY,
    item_id INT NOT NULL REFERENCES news_items(id) ON DELETE CASCADE,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    score INT NOT NULL,
    matched_terms TEXT,
    status TEXT NOT NULL DEFAULT 'suggested' CHECK (status IN ('suggested', 'published', 'dismissed')),
    sector_update_id INT REFERENCES sector_updates(id) ON DELETE SET NULL,
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (item_id, company_id)
);
CREATE INDEX IF NOT EXISTS idx_news_matches_status ON news_matches(status, company_id);
CREATE TABLE IF NOT EXISTS news_fetch_runs (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    trigger TEXT,
    sources_ok INT DEFAULT 0,
    sources_failed INT DEFAULT 0,
    new_items INT DEFAULT 0,
    new_suggestions INT DEFAULT 0
);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS news_keywords TEXT;
ALTER TABLE sector_updates ADD COLUMN IF NOT EXISTS news_item_id INT REFERENCES news_items(id) ON DELETE SET NULL;
ALTER TABLE sector_updates ADD COLUMN IF NOT EXISTS why TEXT;

-- Roles and permissions (21 Oct 2026 meeting). Rebuilt from backend/permissions.py on start-up.
-- users.account_type says founder or staff; what a person may do comes only from user_roles.
CREATE TABLE IF NOT EXISTS roles (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    staff BOOLEAN NOT NULL
);
CREATE TABLE IF NOT EXISTS permissions (
    code TEXT PRIMARY KEY,
    description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS role_permissions (
    role_code TEXT NOT NULL REFERENCES roles(code) ON DELETE CASCADE,
    permission_code TEXT NOT NULL REFERENCES permissions(code) ON DELETE CASCADE,
    scope TEXT NOT NULL DEFAULT 'all' CHECK (scope IN ('all', 'assigned')),
    PRIMARY KEY (role_code, permission_code)
);
CREATE TABLE IF NOT EXISTS user_roles (
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_code TEXT NOT NULL REFERENCES roles(code),
    granted_by TEXT,
    granted_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, role_code)
);
-- Team assignments can point at a staff account, so analysts can be limited to their own companies.
ALTER TABLE company_assignments ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id) ON DELETE SET NULL;

-- One-time migration from the old single users.role column (founder / analyst / admin).
ALTER TABLE users ADD COLUMN IF NOT EXISTS account_type TEXT;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'role') THEN
        INSERT INTO roles (code, name, staff) VALUES
            ('super_admin', 'Super Admin', TRUE), ('analyst', 'Analyst', TRUE), ('founder', 'Founder', FALSE)
        ON CONFLICT (code) DO NOTHING;
        UPDATE users SET account_type = CASE WHEN role = 'founder' THEN 'founder' ELSE 'staff' END
        WHERE account_type IS NULL;
        INSERT INTO user_roles (user_id, role_code, granted_by)
        SELECT id, CASE role WHEN 'admin' THEN 'super_admin' WHEN 'analyst' THEN 'analyst' ELSE 'founder' END,
               'migration 2026-10-21'
        FROM users ON CONFLICT DO NOTHING;
        ALTER TABLE users DROP COLUMN role;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_account_type_check') THEN
        ALTER TABLE users ALTER COLUMN account_type SET NOT NULL;
        ALTER TABLE users ADD CONSTRAINT users_account_type_check CHECK (account_type IN ('founder', 'staff'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_founder_company_check') THEN
        -- Founders always belong to one company; staff never do.
        ALTER TABLE users ADD CONSTRAINT users_founder_company_check
            CHECK ((account_type = 'founder') = (company_id IS NOT NULL));
    END IF;
END $$;

-- Two-level model: exactly one Super Admin. The role moves only via the hand-over.
CREATE UNIQUE INDEX IF NOT EXISTS one_super_admin ON user_roles (role_code) WHERE role_code = 'super_admin';

-- Last successful sign-in, kept on the account (sessions are deleted at sign-out, so they cannot be used).
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;
UPDATE users u SET last_login_at = (SELECT MAX(s.created_at) FROM user_sessions s WHERE s.user_id = u.id)
WHERE u.last_login_at IS NULL;

-- Three staff tiers, approval of everything staff add, activity tracking.
-- Approval for events, Connect profiles and sector updates (resources use resources.status).
ALTER TABLE events ADD COLUMN IF NOT EXISTS approval TEXT NOT NULL DEFAULT 'approved';
ALTER TABLE events ADD COLUMN IF NOT EXISTS review_note TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS reviewed_by TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS join_link TEXT;  -- meeting link or meeting ID (optional)
ALTER TABLE connect_entries ADD COLUMN IF NOT EXISTS approval TEXT NOT NULL DEFAULT 'approved';
ALTER TABLE connect_entries ADD COLUMN IF NOT EXISTS review_note TEXT;
ALTER TABLE connect_entries ADD COLUMN IF NOT EXISTS reviewed_by TEXT;
ALTER TABLE sector_updates ADD COLUMN IF NOT EXISTS approval TEXT NOT NULL DEFAULT 'approved';
ALTER TABLE sector_updates ADD COLUMN IF NOT EXISTS review_note TEXT;
ALTER TABLE sector_updates ADD COLUMN IF NOT EXISTS reviewed_by TEXT;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'events_approval_check') THEN
        ALTER TABLE events ADD CONSTRAINT events_approval_check CHECK (approval IN ('pending', 'approved', 'returned'));
        ALTER TABLE connect_entries ADD CONSTRAINT connect_approval_check CHECK (approval IN ('pending', 'approved', 'returned'));
        ALTER TABLE sector_updates ADD CONSTRAINT sector_updates_approval_check CHECK (approval IN ('pending', 'approved', 'returned'));
    END IF;
END $$;

-- Audit entries know their company, so an Admin sees the trail for their own companies.
ALTER TABLE admin_audit ADD COLUMN IF NOT EXISTS company_id INT REFERENCES companies(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_admin_audit_actor ON admin_audit(actor, created_at);

-- Every successful sign-in (the activity tracker).
CREATE TABLE IF NOT EXISTS sign_ins (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sign_ins_user ON sign_ins(user_id, created_at);

-- 23 Oct: reporting lines (Analyst -> Admin; Admins report to the one Super Admin), company record
-- details from example.org, and an event join link that waits for approval without hiding the event.
ALTER TABLE users ADD COLUMN IF NOT EXISTS reports_to INT REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS city TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS fund TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS invested TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS website TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS about TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS pending_join_link TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS pending_link_by TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS pending_link_at TIMESTAMPTZ;
ALTER TABLE events ADD COLUMN IF NOT EXISTS pending_recording_url TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS pending_recording_by TEXT;
ALTER TABLE events ADD COLUMN IF NOT EXISTS pending_recording_at TIMESTAMPTZ;

-- 23 Oct (O5-O14): request conversations, company notes, exited status, founder contact details,
-- sign-in lock per device, and edits to published resources that wait for approval.
CREATE TABLE IF NOT EXISTS help_messages (
    id SERIAL PRIMARY KEY,
    help_id INT NOT NULL REFERENCES founder_help(id) ON DELETE CASCADE,
    author_id INT REFERENCES users(id) ON DELETE SET NULL,
    author_name TEXT NOT NULL,
    from_fund BOOLEAN NOT NULL DEFAULT FALSE,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_help_messages ON help_messages(help_id, created_at);
CREATE TABLE IF NOT EXISTS company_notes (
    id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'note' CHECK (kind IN ('note', 'call', 'meeting', 'email')),
    body TEXT NOT NULL,
    author_id INT REFERENCES users(id) ON DELETE SET NULL,
    author_name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_company_notes ON company_notes(company_id, created_at);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'companies_status_check') THEN
    ALTER TABLE companies ADD CONSTRAINT companies_status_check CHECK (status IN ('active', 'exited'));
  END IF;
END $$;
ALTER TABLE users ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT;
ALTER TABLE login_failures ADD COLUMN IF NOT EXISTS client TEXT;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS pending_changes TEXT;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS pending_file TEXT;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS pending_by TEXT;
ALTER TABLE resources ADD COLUMN IF NOT EXISTS pending_at TIMESTAMPTZ;

-- 25 Oct (alpha v1.1, manager request): Hiring. A company's open roles, and candidate profiles a Demo Ventures
-- analyst features on that company's dashboard and Hiring page. "Interested" opens a support request,
-- so introductions stay in the one trackable request system.
CREATE TABLE IF NOT EXISTS hiring_roles (
    id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    seniority TEXT NOT NULL DEFAULT 'Senior',
    location TEXT,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'filled', 'closed')),
    created_by INT REFERENCES users(id) ON DELETE SET NULL,
    created_by_name TEXT NOT NULL,
    from_fund BOOLEAN NOT NULL DEFAULT FALSE,
    is_sample BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hiring_roles_company ON hiring_roles(company_id, status);
CREATE TABLE IF NOT EXISTS talent_profiles (
    id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    role_id INT REFERENCES hiring_roles(id) ON DELETE SET NULL,
    full_name TEXT NOT NULL,
    headline TEXT NOT NULL,             -- current role and organisation
    experience_years INT CHECK (experience_years BETWEEN 0 AND 60),
    location TEXT,
    summary TEXT NOT NULL,              -- background in a few lines
    fit_note TEXT NOT NULL,             -- why Demo Ventures thinks this person fits the opening
    profile_url TEXT,                   -- LinkedIn or similar (https only)
    consent_confirmed BOOLEAN NOT NULL DEFAULT FALSE,  -- the candidate agreed to be shared with this company
    status TEXT NOT NULL DEFAULT 'featured'
        CHECK (status IN ('featured', 'interested', 'not_fit', 'withdrawn')),
    founder_note TEXT,
    help_id INT REFERENCES founder_help(id) ON DELETE SET NULL,  -- the request opened on "Interested"
    featured_by INT REFERENCES users(id) ON DELETE SET NULL,
    featured_by_name TEXT NOT NULL,
    featured_at TIMESTAMPTZ DEFAULT NOW(),
    responded_by_name TEXT,
    responded_at TIMESTAMPTZ,
    is_sample BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_talent_profiles_company ON talent_profiles(company_id, status);

-- 26 Oct 2026: real-data safety. A database marked data_mode = 'real' (python -m backend.scripts.mark_real_data)
-- never receives demo data: the demo seed and the demo reset refuse to run on it, and the smoke test refuses
-- to run against it. Releases test on a separate, freshly created founder_portal_test database instead.
CREATE TABLE IF NOT EXISTS portal_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_by TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 26 Oct 2026 (meetings 1 and 2): audience targeting. A resource, event or sector update is either for one
-- company (company_id) or portfolio-wide (company_id NULL), and a portfolio-wide item can be narrowed to
-- chosen companies, sectors and/or stages. Empty lists mean "no restriction". fp_visible() is the one rule
-- every founder screen uses. A company's sector holds one or more comma-separated tags (as on example.org);
-- a sector target matches a company that has any of the chosen tags.
ALTER TABLE resources ADD COLUMN IF NOT EXISTS target_company_ids INT[] NOT NULL DEFAULT '{}';
ALTER TABLE resources ADD COLUMN IF NOT EXISTS target_sectors TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE resources ADD COLUMN IF NOT EXISTS target_stages TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE events ADD COLUMN IF NOT EXISTS target_company_ids INT[] NOT NULL DEFAULT '{}';
ALTER TABLE events ADD COLUMN IF NOT EXISTS target_sectors TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE events ADD COLUMN IF NOT EXISTS target_stages TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE sector_updates ADD COLUMN IF NOT EXISTS target_company_ids INT[] NOT NULL DEFAULT '{}';
ALTER TABLE sector_updates ADD COLUMN IF NOT EXISTS target_sectors TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE sector_updates ADD COLUMN IF NOT EXISTS target_stages TEXT[] NOT NULL DEFAULT '{}';
CREATE OR REPLACE FUNCTION fp_visible(item_company INT, t_companies INT[], t_sectors TEXT[], t_stages TEXT[], cid INT)
RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
    SELECT CASE WHEN item_company IS NOT NULL THEN item_company = cid ELSE
        (cardinality(COALESCE(t_companies, '{}')) = 0 OR cid = ANY(t_companies))
        AND (cardinality(COALESCE(t_sectors, '{}')) = 0
             OR EXISTS (SELECT 1 FROM companies c WHERE c.id = cid
                        AND regexp_split_to_array(trim(c.sector), '\s*,\s*') && t_sectors))
        AND (cardinality(COALESCE(t_stages, '{}')) = 0
             OR EXISTS (SELECT 1 FROM companies c WHERE c.id = cid AND c.stage = ANY(t_stages)))
    END
$$;

-- 26 Oct 2026 (meeting 2): messages to founders and staff. Every email is written to the outbox first, then
-- delivered by SMTP when it is configured (backend/.env SMTP_*); without SMTP it stays "not sent" (test mode)
-- and the workspace offers copy, email-app and WhatsApp links instead.
CREATE TABLE IF NOT EXISTS email_outbox (
    id SERIAL PRIMARY KEY,
    to_email TEXT NOT NULL,
    to_name TEXT,
    to_phone TEXT,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    kind TEXT NOT NULL,                 -- invite, reset, request, reply, distribution, hiring, interest, otp
    company_id INT REFERENCES companies(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'sent', 'failed', 'not_sent')),
    error TEXT,
    attempts INT NOT NULL DEFAULT 0,
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    sent_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_email_outbox_created ON email_outbox(created_at DESC);
-- Single-use sign-in links: an invite to set a first password, or a password reset. Only a hash is stored.
CREATE TABLE IF NOT EXISTS account_tokens (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    purpose TEXT NOT NULL CHECK (purpose IN ('invite', 'reset')),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_account_tokens_user ON account_tokens(user_id);
-- Content sent to founders from the workspace ("Send to founders"): one row per send.
CREATE TABLE IF NOT EXISTS distributions (
    id SERIAL PRIMARY KEY,
    kind TEXT NOT NULL,
    item_id INT,
    subject TEXT NOT NULL,
    audience TEXT,
    recipients INT NOT NULL DEFAULT 0,
    sent_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 26 Oct 2026 (meeting 1): candidate profiles are approved by an Admin (or the Super Admin) before founders
-- see them; candidates can register interest through an opening's shareable link.
ALTER TABLE talent_profiles ADD COLUMN IF NOT EXISTS approval TEXT NOT NULL DEFAULT 'approved';
ALTER TABLE talent_profiles ADD COLUMN IF NOT EXISTS review_note TEXT;
ALTER TABLE talent_profiles ADD COLUMN IF NOT EXISTS reviewed_by TEXT;
ALTER TABLE talent_profiles ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
ALTER TABLE talent_profiles ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'fund';  -- fund | interest | bulk
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'talent_profiles_approval_check') THEN
    ALTER TABLE talent_profiles ADD CONSTRAINT talent_profiles_approval_check CHECK (approval IN ('pending', 'approved', 'returned'));
  END IF;
END $$;
ALTER TABLE hiring_roles ADD COLUMN IF NOT EXISTS public_token TEXT UNIQUE;  -- set = the interest link is on
CREATE TABLE IF NOT EXISTS candidate_interest (
    id SERIAL PRIMARY KEY,
    role_id INT NOT NULL REFERENCES hiring_roles(id) ON DELETE CASCADE,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT,
    headline TEXT NOT NULL,
    experience_years INT,
    location TEXT,
    profile_url TEXT,
    note TEXT,
    consent_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'featured', 'declined')),
    profile_id INT REFERENCES talent_profiles(id) ON DELETE SET NULL,
    handled_by TEXT,
    handled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (role_id, email)
);
CREATE INDEX IF NOT EXISTS idx_candidate_interest_company ON candidate_interest(company_id, status);

-- 26 Oct 2026 (meeting 1): the 100-Day Playbook as a course, chapter by chapter. Chapters belong to a playbook
-- phase; each has short lessons (text, an optional template from the Resource Library and an optional video).
-- Founders mark lessons complete; Demo Ventures sees completion per company.
CREATE TABLE IF NOT EXISTS lms_chapters (
    id SERIAL PRIMARY KEY,
    phase_no INT NOT NULL CHECK (phase_no BETWEEN 1 AND 4),
    sort_order INT NOT NULL DEFAULT 0,
    title TEXT NOT NULL,
    summary TEXT,
    status TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('draft', 'published')),
    created_by TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS lms_lessons (
    id SERIAL PRIMARY KEY,
    chapter_id INT NOT NULL REFERENCES lms_chapters(id) ON DELETE CASCADE,
    sort_order INT NOT NULL DEFAULT 0,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    resource_slug TEXT,
    video_url TEXT,
    minutes INT NOT NULL DEFAULT 5 CHECK (minutes BETWEEN 1 AND 240),
    status TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('draft', 'published')),
    created_by TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_lms_lessons_chapter ON lms_lessons(chapter_id, sort_order);
CREATE TABLE IF NOT EXISTS lms_progress (
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lesson_id INT NOT NULL REFERENCES lms_lessons(id) ON DELETE CASCADE,
    company_id INT REFERENCES companies(id) ON DELETE CASCADE,
    completed_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, lesson_id)
);

-- 29 Oct 2026: submissions through public forms (the opening interest link), counted per address so the
-- hourly limit holds across several API processes. Rows older than a day are removed as the form is used.
CREATE TABLE IF NOT EXISTS public_form_hits (
    id SERIAL PRIMARY KEY,
    client TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_public_form_hits ON public_form_hits(client, created_at);

-- 29 Oct 2026 (alpha v1.2.6, meeting with the MD): company profile. The portal, not the spreadsheet, is the
-- single source of truth. companies.name is the brand name; legal_name is shown smaller beneath it.
-- Firms (auditors, company secretaries, law firms, banks, lenders, investment banks) live in one shared list
-- so the same firm is never entered twice; name_key is the normalised name used to find duplicates.
-- Every change is written to admin_audit (action profile.*) from now on; old history is not backfilled.
ALTER TABLE companies ADD COLUMN IF NOT EXISTS legal_name TEXT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS profile_confirmed_at TIMESTAMPTZ;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS profile_confirmed_by TEXT;
CREATE TABLE IF NOT EXISTS firms (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    kinds TEXT[] NOT NULL DEFAULT '{}',
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS company_profile (
    company_id INT PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
    auditor_firm_id INT REFERENCES firms(id),
    auditor_appointed_on DATE,
    secretary_firm_id INT REFERENCES firms(id),
    legal_counsel_firm_id INT REFERENCES firms(id),
    sha_custody TEXT,
    aop_status TEXT CHECK (aop_status IN ('yes', 'no', 'na')),
    aop_note TEXT,
    dpdp_consent TEXT CHECK (dpdp_consent IN ('yes', 'no', 'na')),
    dpdp_consent_duration TEXT,
    dpdp_renewal TEXT,
    dpdp_sha_annexure TEXT CHECK (dpdp_sha_annexure IN ('yes', 'no', 'na')),
    updated_at TIMESTAMPTZ,
    updated_by TEXT
);
CREATE TABLE IF NOT EXISTS company_bankers (
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    firm_id INT NOT NULL REFERENCES firms(id),
    sort_order INT NOT NULL DEFAULT 0,
    PRIMARY KEY (company_id, firm_id)
);
CREATE TABLE IF NOT EXISTS company_people (
    id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('board', 'advisory', 'independent')),
    full_name TEXT NOT NULL,
    role_note TEXT,
    sort_order INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_company_people ON company_people(company_id, kind, sort_order);
CREATE TABLE IF NOT EXISTS company_compliance (
    id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    item TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('yes', 'no', 'na')),
    certificate_no TEXT,
    issued_on DATE,
    expires_on DATE,
    note TEXT,
    sort_order INT NOT NULL DEFAULT 0,
    UNIQUE (company_id, item)
);
CREATE TABLE IF NOT EXISTS company_credit (
    id SERIAL PRIMARY KEY,
    company_id INT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('credit_line', 'credit_card')),
    firm_id INT REFERENCES firms(id),
    instrument TEXT,
    amount_inr NUMERIC(16, 2),
    interest_rate NUMERIC(6, 2),
    note TEXT,
    sort_order INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_company_credit ON company_credit(company_id, kind, sort_order);

-- 29 Oct 2026 (alpha v1.2.6 update): where a resource is offered to founders. 'library' = the Resource Library;
-- 'playbook' = a Playbook guide (shown on the Playbook page with its lessons, not in the library). Downloads
-- and approval work the same way for both.
ALTER TABLE resources ADD COLUMN IF NOT EXISTS placement TEXT NOT NULL DEFAULT 'library';
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'resources_placement_check') THEN
    ALTER TABLE resources ADD CONSTRAINT resources_placement_check CHECK (placement IN ('library', 'playbook'));
  END IF;
END $$;

-- 30 Oct 2026 (alpha v1.2.6): sign in with a one-time code sent by email. Switched off by default
-- (OTP_SIGNIN_ENABLED). Only a hash of each 6-digit code is kept; a code works once, for OTP_MINUTES,
-- and stops working after OTP_MAX_ATTEMPTS wrong guesses. Old rows are removed as new codes are asked for.
CREATE TABLE IF NOT EXISTS login_codes (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    client TEXT,
    attempts INT NOT NULL DEFAULT 0,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_login_codes_user ON login_codes(user_id, created_at);

-- 2 Nov 2026 (alpha v1.2.6 update): Resource Library sections renamed. Safe to run again: each
-- statement only touches rows that still carry an old name.
UPDATE resources SET category = 'Finance and Compliance' WHERE category = 'Finance';
UPDATE resources SET category = 'Fundraising and Investor Relations' WHERE category = 'Fundraising';
UPDATE resources SET category = 'Growth & Sales' WHERE category = 'Sales & GTM';
UPDATE resources SET category = 'Business Operations' WHERE category = 'Operations';
UPDATE resources SET category = 'Product & Tech Strategy' WHERE category = 'Product';
UPDATE resources SET category = 'Market Intelligence' WHERE category = 'Market';
UPDATE resources SET category = 'People & Hiring' WHERE category = 'Hiring';
UPDATE resources SET category = 'Industry Insights' WHERE category = 'Industry';
UPDATE resources SET category = 'Research and Reports' WHERE category = 'Research';

-- Connect directory from Demo Ventures' connects list (3 Nov 2026): each profile can link to its website.
ALTER TABLE connect_entries ADD COLUMN IF NOT EXISTS website TEXT;
CREATE INDEX IF NOT EXISTS connect_entries_name_idx ON connect_entries (display_name);

-- 3 Nov 2026: fields from Demo Ventures' "Portfolio Tracker" sheet. Shared with founders (company_profile):
ALTER TABLE company_profile
    ADD COLUMN IF NOT EXISTS secretary_engaged_on DATE,
    ADD COLUMN IF NOT EXISTS accounts_signed_on DATE,
    ADD COLUMN IF NOT EXISTS investment_bank_firm_id INT REFERENCES firms(id),
    ADD COLUMN IF NOT EXISTS tax_advisor_firm_id INT REFERENCES firms(id),
    ADD COLUMN IF NOT EXISTS cloud_provider TEXT,
    ADD COLUMN IF NOT EXISTS board_nominee TEXT,
    ADD COLUMN IF NOT EXISTS infosec_policy TEXT CHECK (infosec_policy IN ('yes', 'no', 'na')),
    ADD COLUMN IF NOT EXISTS cos_name TEXT,
    ADD COLUMN IF NOT EXISTS cos_joined_on DATE,
    ADD COLUMN IF NOT EXISTS patents_filed INT CHECK (patents_filed >= 0),
    ADD COLUMN IF NOT EXISTS patents_granted INT CHECK (patents_granted >= 0),
    ADD COLUMN IF NOT EXISTS share_cert_custody TEXT,
    ADD COLUMN IF NOT EXISTS demat_status TEXT CHECK (demat_status IN ('yes', 'no', 'na'));
-- Demo Ventures-only tracking (never sent to founders or printed in the profile PDF). Founders' KYC is recorded as
-- received or not, with the date: PAN, Aadhaar and passport numbers or copies are never stored (DPDP).
CREATE TABLE IF NOT EXISTS company_tracker (
    company_id INT PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
    exit_discussion TEXT,
    exit_discussion_on DATE,
    exit_led_by TEXT,
    sha_review_status TEXT,
    sha_review_period TEXT,
    fundraise_status TEXT,
    action_points TEXT,
    kyc_received TEXT CHECK (kyc_received IN ('yes', 'no', 'na')),
    kyc_received_on DATE,
    updated_at TIMESTAMPTZ,
    updated_by TEXT
);

-- 4 Nov 2026 (partner review): investor cards show stage and cheque size as their own fields.
ALTER TABLE connect_entries ADD COLUMN IF NOT EXISTS stage TEXT;
ALTER TABLE connect_entries ADD COLUMN IF NOT EXISTS cheque_size TEXT;

-- 4 Nov 2026: external events send founders to their own RSVP page.
ALTER TABLE events ADD COLUMN IF NOT EXISTS rsvp_url TEXT;

-- 4 Nov 2026 (partner review): Industry is part of Market Intelligence.
UPDATE resources SET category = 'Market Intelligence' WHERE category IN ('Industry Insights', 'Industry');

-- 4 Nov 2026 (partner review): one-to-one chat between a founder and a Demo Ventures team member, with files.
CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    founder_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    staff_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sender_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT,
    file_name TEXT,
    file_path TEXT,
    file_size INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_chat_pair ON chat_messages(founder_id, staff_id, id);

-- Company logo (partner review, 5 Nov 2026): a small PNG, JPEG or WebP kept as a data URI
ALTER TABLE companies ADD COLUMN IF NOT EXISTS logo_data TEXT;
