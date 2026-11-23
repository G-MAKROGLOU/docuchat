-- The ParadeDB image installs these in every new database. Nothing here uses them: drug names
-- are matched in Python, and there is no geodata. Dependents first.
DROP EXTENSION IF EXISTS postgis_tiger_geocoder;
DROP EXTENSION IF EXISTS postgis_topology;
DROP EXTENSION IF EXISTS postgis;
DROP EXTENSION IF EXISTS fuzzystrmatch;
DROP EXTENSION IF EXISTS pg_ivm;
