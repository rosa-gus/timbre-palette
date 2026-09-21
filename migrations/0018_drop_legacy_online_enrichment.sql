-- Remove the pre-snapshot online-enrichment and prepared-album schema.
-- The current runtime uses the snapshot projections, editorial tables, and
-- taxonomy tables; these tables are no longer part of the application model.

PRAGMA foreign_keys = OFF;

-- Prepared-album catalog and its source/observation data.
DROP TABLE IF EXISTS credit_observations;
DROP TABLE IF EXISTS album_tracks;
DROP TABLE IF EXISTS album_releases;
DROP TABLE IF EXISTS album_groups;
DROP TABLE IF EXISTS source_documents;
DROP TABLE IF EXISTS prepared_album_targets;
DROP TABLE IF EXISTS catalog_demand;
DROP TABLE IF EXISTS catalog_publications;
DROP TABLE IF EXISTS artists;

-- Online enrichment jobs, work units, and their recording-level outputs.
DROP TABLE IF EXISTS enrichment_work_unit_items;
DROP TABLE IF EXISTS enrichment_work_units;
DROP TABLE IF EXISTS enrichment_state;
DROP TABLE IF EXISTS enrichment_jobs;
DROP TABLE IF EXISTS evidence_items;
DROP TABLE IF EXISTS instrument_claims;
DROP TABLE IF EXISTS instrument_credit_candidates;
DROP TABLE IF EXISTS identity_matches;
DROP TABLE IF EXISTS recording_identifiers;
DROP TABLE IF EXISTS recordings;

PRAGMA foreign_keys = ON;
