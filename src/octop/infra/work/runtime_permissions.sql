-- Installed by the migration owner, never by a runtime credential.
CREATE TABLE public.work_database_principals (
    role_name TEXT PRIMARY KEY,
    runtime_id TEXT,
    organization_id TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('entry', 'runtime', 'manager')),
    CHECK (kind='manager' OR runtime_id IS NOT NULL),
    CHECK (kind='entry' OR organization_id IS NOT NULL)
);
CREATE TABLE public.work_executors (
    executor_id TEXT PRIMARY KEY,
    role_name TEXT NOT NULL,
    runtime_id TEXT NOT NULL,
    backend_pid INTEGER NOT NULL
);

CREATE FUNCTION public.work_principal() RETURNS public.work_database_principals
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    SELECT p FROM public.work_database_principals p WHERE p.role_name=session_user;
$$;

CREATE FUNCTION public.work_executor_live(eid TEXT) RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.work_executors e JOIN pg_catalog.pg_locks l ON l.pid=e.backend_pid
        WHERE e.executor_id=eid AND e.role_name=session_user
        AND l.locktype='advisory' AND l.granted AND l.objsubid=1
        AND l.classid::bigint=((hashtextextended(eid,0) >> 32) & 4294967295)
        AND l.objid::bigint=(hashtextextended(eid,0) & 4294967295)
    );
$$;

CREATE FUNCTION public.work_register_executor(eid TEXT, rid TEXT) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE p public.work_database_principals := public.work_principal();
BEGIN
    IF p.runtime_id IS DISTINCT FROM rid OR p.kind NOT IN ('entry','runtime') THEN
        RAISE insufficient_privilege;
    END IF;
    PERFORM pg_advisory_lock(hashtextextended(eid,0));
    INSERT INTO public.work_executors VALUES (eid,session_user,rid,pg_backend_pid());
    RETURN TRUE;
END;
$$;

CREATE FUNCTION public.work_context_allowed(c JSONB, eid TEXT, statuses TEXT[])
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
    SELECT public.work_executor_live(eid) AND EXISTS (
        SELECT 1 FROM public.work_runs r
        JOIN public.work_database_principals d ON d.role_name=session_user AND d.kind='runtime'
            AND d.runtime_id=r.runtime_id AND d.organization_id=r.organization_id
        JOIN public.work_identities i ON i.runtime_id=r.runtime_id
            AND i.octop_user_id=r.octop_user_id AND i.work_user_id=r.work_user_id AND i.status='active'
        JOIN public.work_users u ON u.work_user_id=r.work_user_id AND u.status='active'
        JOIN public.work_memberships m ON m.work_user_id=r.work_user_id
            AND m.organization_id=r.organization_id AND m.status='active' AND m.revision=r.membership_revision
        JOIN public.work_agent_bindings a ON a.agent_id=r.agent_id
            AND a.runtime_id=r.runtime_id AND a.organization_id=r.organization_id AND a.status='active'
        JOIN public.work_organization_policies p ON p.organization_id=r.organization_id
            AND p.available AND p.revision=r.policy_revision
        WHERE r.executor_id=eid AND r.run_id=c->>'run_id'
            AND r.octop_user_id=(c->>'octop_user_id')::bigint AND r.work_user_id=c->>'work_user_id'
            AND r.organization_id=c->>'organization_id' AND r.agent_id=c->>'agent_id'
            AND r.runtime_id=c->>'runtime_id' AND r.thread_id=c->>'budget_scope_id'
            AND r.connection_id=c->>'connection_id'
            AND r.membership_revision=(c->>'membership_revision')::integer
            AND r.policy_revision=(c->>'policy_revision')::integer
            AND r.issued_at<=now() AND r.expires_at>now() AND r.status=ANY(statuses)
    );
$$;

CREATE FUNCTION public.work_recover_runs(rid TEXT) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE p public.work_database_principals := public.work_principal(); e TEXT;
BEGIN
    IF p.runtime_id IS DISTINCT FROM rid OR p.kind NOT IN ('entry','runtime') THEN
        RAISE insufficient_privilege;
    END IF;
    FOR e IN SELECT DISTINCT executor_id FROM public.work_runs r
        WHERE runtime_id=rid AND (status IN ('queued','running') OR EXISTS (
            SELECT 1 FROM public.work_external_attempts a
            WHERE a.run_id=r.run_id AND a.status='reserved')) LOOP
        IF e IS NULL OR pg_try_advisory_xact_lock(hashtextextended(e,0)) THEN
            UPDATE public.work_runs SET status='blocked_restart', finished_at=now()
                WHERE runtime_id=rid AND executor_id IS NOT DISTINCT FROM e
                AND status IN ('queued','running');
            UPDATE public.work_external_attempts a SET status='uncertain', finished_at=now()
                FROM public.work_runs r WHERE a.run_id=r.run_id AND r.runtime_id=rid
                AND r.executor_id IS NOT DISTINCT FROM e
                AND a.status='reserved';
        END IF;
    END LOOP;
END;
$$;

CREATE FUNCTION public.work_create_run(c JSONB, eid TEXT) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE p public.work_database_principals := public.work_principal();
BEGIN
    IF p.kind IS DISTINCT FROM 'runtime' OR p.runtime_id IS DISTINCT FROM c->>'runtime_id'
        OR p.organization_id IS DISTINCT FROM c->>'organization_id'
        OR NOT public.work_executor_live(eid)
        OR NOT EXISTS (
            SELECT 1 FROM public.work_identities i
            JOIN public.work_users u ON u.work_user_id=i.work_user_id AND u.status='active'
            JOIN public.work_memberships m ON m.work_user_id=i.work_user_id
            JOIN public.work_agent_bindings a ON a.organization_id=m.organization_id
            JOIN public.work_organization_policies op ON op.organization_id=m.organization_id
            WHERE i.runtime_id=p.runtime_id AND i.octop_user_id=(c->>'octop_user_id')::bigint
            AND i.work_user_id=c->>'work_user_id' AND i.status='active' AND m.status='active'
            AND m.organization_id=p.organization_id AND m.revision=(c->>'membership_revision')::integer
            AND a.agent_id=c->>'agent_id' AND a.runtime_id=p.runtime_id AND a.status='active'
            AND op.available AND op.revision=(c->>'policy_revision')::integer
        ) OR (c->>'issued_at')::timestamptz>now()
        OR (c->>'expires_at')::timestamptz<=now()
        OR (c->>'expires_at')::timestamptz>now()+interval '15 minutes'
        OR COALESCE(c->>'budget_scope_id','')='' OR c->>'connection_id' !~ '^[0-9a-f]{32}$'
    THEN RAISE insufficient_privilege; END IF;
    INSERT INTO public.work_runs (run_id,octop_user_id,work_user_id,organization_id,agent_id,
        runtime_id,thread_id,connection_id,executor_id,membership_revision,policy_revision,
        issued_at,expires_at,status)
    VALUES (c->>'run_id',(c->>'octop_user_id')::bigint,c->>'work_user_id',p.organization_id,
        c->>'agent_id',p.runtime_id,c->>'budget_scope_id',c->>'connection_id',eid,
        (c->>'membership_revision')::integer,(c->>'policy_revision')::integer,
        (c->>'issued_at')::timestamptz,(c->>'expires_at')::timestamptz,'queued');
END;
$$;

CREATE FUNCTION public.work_run_transition(c JSONB, eid TEXT, target TEXT) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE changed INTEGER; p public.work_database_principals := public.work_principal();
BEGIN
    IF target='running' THEN
        IF NOT public.work_context_allowed(c,eid,ARRAY['queued']) THEN RETURN FALSE; END IF;
        UPDATE public.work_runs SET status='running' WHERE run_id=c->>'run_id'
            AND executor_id=eid AND status='queued';
    ELSIF target IN ('completed','failed','blocked') THEN
        -- Revoked members still need terminal bookkeeping, never fresh execution rights.
        IF NOT public.work_executor_live(eid) THEN RETURN FALSE; END IF;
        UPDATE public.work_runs SET status=target, finished_at=now()
            WHERE run_id=c->>'run_id' AND executor_id=eid AND runtime_id=p.runtime_id
            AND organization_id=p.organization_id AND
            (status='running' OR (target='blocked' AND status='queued'));
    ELSE RAISE invalid_parameter_value; END IF;
    GET DIAGNOSTICS changed=ROW_COUNT;
    RETURN changed=1;
END;
$$;

CREATE FUNCTION public.work_reserve_attempt(c JSONB,eid TEXT,cap TEXT,aid TEXT) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE day DATE := (now() AT TIME ZONE 'UTC')::date; scope RECORD; count INTEGER;
BEGIN
    -- Lock authority rows through reservation; no client supplied day/billability/limit.
    PERFORM 1 FROM public.work_memberships m JOIN public.work_organization_policies p
        ON p.organization_id=m.organization_id JOIN public.work_capabilities cp
        ON cp.organization_id=p.organization_id
        JOIN public.work_users u ON u.work_user_id=m.work_user_id
        JOIN public.work_identities i ON i.work_user_id=u.work_user_id
            AND i.runtime_id=c->>'runtime_id' AND i.octop_user_id=(c->>'octop_user_id')::bigint
        JOIN public.work_agent_bindings a ON a.organization_id=m.organization_id
            AND a.runtime_id=c->>'runtime_id' AND a.agent_id=c->>'agent_id'
        WHERE m.organization_id=c->>'organization_id' AND m.work_user_id=c->>'work_user_id'
        AND cp.capability=cap AND cp.enabled AND cp.billable FOR SHARE OF i,u,m,a,p,cp;
    IF NOT FOUND OR lower(cap) ~ '(^|[^a-z0-9])(feishu|lark|larksuite|pixelrag)([^a-z0-9]|$)'
        OR NOT public.work_context_allowed(c,eid,ARRAY['running']) THEN RETURN FALSE; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('work-task-budget:'||(c->>'budget_scope_id'),0));
    IF (SELECT COALESCE(sum(used),0) FROM public.work_budget_counters
        WHERE scope_kind='task' AND scope_id=c->>'budget_scope_id')>=20 THEN RETURN FALSE; END IF;
    INSERT INTO public.work_external_attempts(attempt_id,run_id,budget_scope_id,work_user_id,
        organization_id,runtime_id,capability,utc_day,status)
        VALUES(aid,c->>'run_id',c->>'budget_scope_id',c->>'work_user_id',c->>'organization_id',
        c->>'runtime_id',cap,day,'reserved') ON CONFLICT(attempt_id) DO NOTHING;
    IF NOT FOUND THEN RETURN FALSE; END IF;
    FOR scope IN SELECT * FROM (VALUES ('task',c->>'budget_scope_id',20),
        ('user',c->>'work_user_id',100),('organization',c->>'organization_id',500)) AS s(kind,id,ceiling)
    LOOP
        INSERT INTO public.work_budget_counters(scope_kind,scope_id,utc_day,used)
            VALUES(scope.kind,scope.id,day,1) ON CONFLICT(scope_kind,scope_id,utc_day)
            DO UPDATE SET used=public.work_budget_counters.used+1
            WHERE public.work_budget_counters.used<scope.ceiling;
        GET DIAGNOSTICS count=ROW_COUNT;
        IF count=0 THEN RAISE check_violation; END IF;
    END LOOP;
    RETURN TRUE;
EXCEPTION WHEN check_violation THEN RETURN FALSE; -- rolls back the whole reservation block
END;
$$;

CREATE FUNCTION public.work_finish_attempt(eid TEXT,aid TEXT,target TEXT) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE p public.work_database_principals := public.work_principal();
BEGIN
    IF target NOT IN ('completed','uncertain') THEN RAISE invalid_parameter_value; END IF;
    IF NOT public.work_executor_live(eid) THEN RETURN; END IF;
    UPDATE public.work_external_attempts e SET status=target,finished_at=now()
        FROM public.work_runs r WHERE e.run_id=r.run_id AND e.attempt_id=aid
        AND e.runtime_id=p.runtime_id AND e.organization_id=p.organization_id
        AND r.executor_id=eid AND e.status='reserved';
END;
$$;

CREATE FUNCTION public.work_consume_handoff(h JSONB) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE p public.work_database_principals := public.work_principal(); grant_row RECORD;
BEGIN
    IF p.kind IS DISTINCT FROM 'runtime' OR p.runtime_id IS DISTINCT FROM h->>'runtime_id'
        OR p.organization_id IS DISTINCT FROM h->>'organization_id'
        OR (h->>'expires_at')::timestamptz<=now() THEN RETURN NULL; END IF;
    SELECT i.octop_user_id,i.work_user_id,m.organization_id,m.status AS member_status,
        m.revision AS membership_revision,op.revision AS policy_revision,a.* INTO grant_row
        FROM public.work_identities i
        JOIN public.work_users u ON u.work_user_id=i.work_user_id AND u.status='active'
        JOIN public.work_memberships m ON m.work_user_id=i.work_user_id AND m.status='active'
        JOIN public.work_agent_bindings a ON a.organization_id=m.organization_id
        JOIN public.work_organization_policies op ON op.organization_id=m.organization_id
        WHERE i.runtime_id=p.runtime_id AND i.work_user_id=h->>'work_user_id' AND i.status='active'
        AND m.organization_id=p.organization_id AND a.agent_id=h->>'agent_id'
        AND a.runtime_id=p.runtime_id AND a.status='active' AND op.available FOR SHARE OF i,u,m,a,op;
    IF NOT FOUND THEN RETURN NULL; END IF;
    INSERT INTO public.work_runtime_handoffs(handoff_id,connection_id,runtime_id,work_user_id,
        organization_id,agent_id,issued_at,expires_at)
        VALUES(h->>'handoff_id',h->>'connection_id',p.runtime_id,h->>'work_user_id',p.organization_id,
        h->>'agent_id',(h->>'issued_at')::timestamptz,(h->>'expires_at')::timestamptz)
        ON CONFLICT(handoff_id) DO NOTHING;
    IF NOT FOUND THEN RETURN NULL; END IF;
    RETURN to_jsonb(grant_row);
END;
$$;

CREATE FUNCTION public.work_manage_policy(org TEXT,cap TEXT,enabled BOOLEAN,billable BOOLEAN)
RETURNS INTEGER LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE p public.work_database_principals := public.work_principal(); rev INTEGER;
BEGIN
    IF p.kind IS DISTINCT FROM 'manager' OR p.organization_id IS DISTINCT FROM org
        OR (enabled AND lower(cap) ~ '(^|[^a-z0-9])(feishu|lark|larksuite|pixelrag)([^a-z0-9]|$)')
        OR (billable AND NOT enabled) THEN RAISE insufficient_privilege; END IF;
    UPDATE public.work_organization_policies SET revision=revision+1
        WHERE organization_id=org RETURNING revision INTO rev;
    IF NOT FOUND THEN RAISE invalid_parameter_value; END IF;
    INSERT INTO public.work_capabilities VALUES(org,cap,enabled,billable)
        ON CONFLICT(organization_id,capability) DO UPDATE
        SET enabled=EXCLUDED.enabled,billable=EXCLUDED.billable;
    RETURN rev;
END;
$$;

-- PUBLIC cannot execute any of these privileged functions.
REVOKE ALL ON FUNCTION public.work_principal() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.work_executor_live(TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.work_register_executor(TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.work_context_allowed(JSONB,TEXT,TEXT[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.work_recover_runs(TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.work_create_run(JSONB,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.work_run_transition(JSONB,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.work_reserve_attempt(JSONB,TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.work_finish_attempt(TEXT,TEXT,TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.work_consume_handoff(JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.work_manage_policy(TEXT,TEXT,BOOLEAN,BOOLEAN) FROM PUBLIC;

ALTER TABLE public.work_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.work_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.work_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.work_agent_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.work_organization_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.work_capabilities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.work_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.work_budget_counters ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.work_external_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.work_runtime_handoffs ENABLE ROW LEVEL SECURITY;

CREATE POLICY work_read ON public.work_identities FOR SELECT USING
    ((public.work_principal()).kind='entry' OR runtime_id=(public.work_principal()).runtime_id);
CREATE POLICY work_read ON public.work_users FOR SELECT USING
    (EXISTS(SELECT 1 FROM public.work_identities i WHERE i.work_user_id=work_users.work_user_id));
CREATE POLICY work_read ON public.work_memberships FOR SELECT USING
    ((public.work_principal()).kind='entry' OR organization_id=(public.work_principal()).organization_id);
CREATE POLICY work_read ON public.work_agent_bindings FOR SELECT USING
    ((public.work_principal()).kind='entry' OR organization_id=(public.work_principal()).organization_id);
CREATE POLICY work_read ON public.work_organization_policies FOR SELECT USING
    ((public.work_principal()).kind='entry' OR organization_id=(public.work_principal()).organization_id);
CREATE POLICY work_read ON public.work_capabilities FOR SELECT USING
    ((public.work_principal()).kind='entry' OR organization_id=(public.work_principal()).organization_id);
CREATE POLICY work_read ON public.work_runs FOR SELECT USING
    (runtime_id=(public.work_principal()).runtime_id);
CREATE POLICY work_read ON public.work_external_attempts FOR SELECT USING
    (runtime_id=(public.work_principal()).runtime_id);
CREATE POLICY work_read ON public.work_runtime_handoffs FOR SELECT USING
    (runtime_id=(public.work_principal()).runtime_id);
CREATE POLICY work_read ON public.work_budget_counters FOR SELECT USING
    ((scope_kind='organization' AND scope_id=(public.work_principal()).organization_id)
    OR (scope_kind='user' AND EXISTS(SELECT 1 FROM public.work_identities i WHERE i.work_user_id=scope_id))
    OR (scope_kind='task' AND EXISTS(SELECT 1 FROM public.work_runs r WHERE r.thread_id=scope_id)));
