-- 1. Create client_configurations table
CREATE TABLE IF NOT EXISTS client_configurations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(255) UNIQUE NOT NULL,
    organization_name VARCHAR(255) NOT NULL,
    epic_client_id VARCHAR(255),
    epic_fhir_base_url TEXT,
    ingestion_mode VARCHAR(50) DEFAULT 'etl_batch', -- 'fhir_api' or 'etl_batch'
    dollar_threshold_default NUMERIC DEFAULT 500.00,
    is_onboarding_completed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. Enable Row-Level Security
ALTER TABLE client_configurations ENABLE ROW LEVEL SECURITY;

-- 3. Create RLS Policy for Tenant Isolation
CREATE POLICY client_config_tenant_isolation ON client_configurations
    FOR ALL
    USING (tenant_id = current_setting('request.jwt.claims', true)::json->>'tenant_id');
