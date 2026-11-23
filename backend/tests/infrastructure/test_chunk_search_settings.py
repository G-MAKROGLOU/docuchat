from app.infrastructure.chunk_search import HNSW_EF_SEARCH, ef_search


def test_the_candidate_list_is_the_measured_size_or_twice_the_limit() -> None:
    assert ef_search(20) == HNSW_EF_SEARCH
    assert ef_search(HNSW_EF_SEARCH) == 2 * HNSW_EF_SEARCH
