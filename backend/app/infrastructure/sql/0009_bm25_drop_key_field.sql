-- pg_search 0.26 ignores key_field and warns on each ALTER or REINDEX; the first column is the key.
ALTER INDEX chunks_search_idx RESET (key_field);
