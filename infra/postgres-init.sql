-- Database-per-service: each service owns its schema and never reads another's tables.
CREATE DATABASE service_a;
CREATE DATABASE service_b;
-- The default POSTGRES_DB (gateway) is created by the image itself.
