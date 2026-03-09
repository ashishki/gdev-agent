INSERT INTO tenants (
    tenant_id,
    name,
    slug,
    plan,
    daily_budget_usd,
    approval_ttl_s,
    auto_approve_threshold,
    approval_categories,
    url_allowlist,
    is_active
)
VALUES
    (
        'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        'Demo Tenant A',
        'test-tenant-a',
        'standard',
        10.0,
        3600,
        0.85,
        ARRAY['billing'],
        ARRAY['kb.example.com'],
        TRUE
    ),
    (
        'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
        'Demo Tenant B',
        'test-tenant-b',
        'standard',
        10.0,
        3600,
        0.85,
        ARRAY['billing'],
        ARRAY['kb.example.com'],
        TRUE
    )
ON CONFLICT (slug) DO UPDATE
SET
    name = EXCLUDED.name,
    is_active = TRUE,
    updated_at = NOW();

DELETE FROM tenant_users
WHERE email IN ('admin-a@example.com', 'admin-b@example.com');

INSERT INTO tenant_users (
    user_id,
    tenant_id,
    email,
    email_hash,
    display_name,
    role,
    is_active,
    password_hash
)
VALUES
    (
        '11111111-1111-1111-1111-111111111111',
        (SELECT tenant_id FROM tenants WHERE slug = 'test-tenant-a'),
        'admin-a@example.com',
        '84d69831458430d0f5f3e7b4e1517eea3b4cb4bb776263e4dab38d2a0fa3e316',
        'Tenant A Admin',
        'tenant_admin',
        TRUE,
        '$2b$12$CmeKxVNVbYrD3sSPlgc4zOvDSbZ.H/3EBAMyMaQROPIAyZ9UnqASW'
    ),
    (
        '22222222-2222-2222-2222-222222222222',
        (SELECT tenant_id FROM tenants WHERE slug = 'test-tenant-b'),
        'admin-b@example.com',
        '504a2aae44e824a3e44ee32b60ac27bba06da2e81316eb2483a9019d681e4492',
        'Tenant B Admin',
        'tenant_admin',
        TRUE,
        '$2b$12$CmeKxVNVbYrD3sSPlgc4zOvDSbZ.H/3EBAMyMaQROPIAyZ9UnqASW'
    );

DELETE FROM webhook_secrets
WHERE tenant_id IN (
    SELECT tenant_id FROM tenants WHERE slug IN ('test-tenant-a', 'test-tenant-b')
);

INSERT INTO webhook_secrets (tenant_id, secret_ciphertext, is_active)
VALUES
    (
        (SELECT tenant_id FROM tenants WHERE slug = 'test-tenant-a'),
        'gAAAAABprmCLKAiMz5wVl9ZXDvtnyuJalRZV3d3XZ8XTl6qngzahf-aBeb5xJiR9vZygghSrn_5eUOEVMs7pcd8foESx9jBacbpdmEiujsORG8rmLIVhqNg=',
        TRUE
    ),
    (
        (SELECT tenant_id FROM tenants WHERE slug = 'test-tenant-b'),
        'gAAAAABprmCL8qKseACmF6YsVMwMpRtcgDgTuHfl83-mktY9wt5Ho2QAWSkKZdYTrJHfUzJhuC9ePvVafApNlFbyaQYf7tUWxiH_4BvlUFCLQwjD8Oj5gVY=',
        TRUE
    );
