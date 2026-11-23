-- Runs once, when the db volume is empty: a separate database for the backend tests,
-- so the tests never touch the development data.
CREATE DATABASE docuchat_test;
\connect docuchat_test
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_search;
