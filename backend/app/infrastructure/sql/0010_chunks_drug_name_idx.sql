-- Most questions name a drug. With 2000 labels the HNSW scan with that filter took 60 to 80 ms;
-- this index lets Postgres read the drug's few chunks and rank them exactly (1 to 3 ms).
CREATE INDEX IF NOT EXISTS chunks_drug_name_idx ON chunks (drug_name);
