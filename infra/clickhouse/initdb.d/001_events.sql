CREATE TABLE IF NOT EXISTS events_v1
(
    organization_id String,
    project_id String,
    event_id String,
    event_type LowCardinality(String),
    resource_type LowCardinality(String),
    resource_id String,
    correlation_id String,
    actor_type LowCardinality(String),
    payload_json String,
    occurred_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (project_id, event_type, occurred_at, resource_id);

ALTER TABLE events_v1 ADD COLUMN IF NOT EXISTS correlation_id String AFTER resource_id;

CREATE TABLE IF NOT EXISTS publication_metric_snapshots_v1
(
    organization_id String,
    project_id String,
    publication_id String,
    platform LowCardinality(String),
    account_id String,
    measurement_window LowCardinality(String),
    post_age_seconds UInt64,
    views Nullable(UInt64),
    engaged_views Nullable(UInt64),
    likes Nullable(UInt64),
    comments Nullable(UInt64),
    shares Nullable(UInt64),
    watch_time_seconds Nullable(Float64),
    average_view_duration_seconds Nullable(Float64),
    average_view_percentage Nullable(Float64),
    subscribers_gained Nullable(Int64),
    subscribers_lost Nullable(Int64),
    raw_json String,
    captured_at DateTime64(3, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(captured_at)
ORDER BY (project_id, platform, measurement_window, captured_at, publication_id);
