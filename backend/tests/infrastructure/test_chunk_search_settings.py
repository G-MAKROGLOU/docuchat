from app.infrastructure.chunk_search import ef_search


def test_the_candidate_list_is_the_measured_size_or_twice_the_limit() -> None:
    assert ef_search(20, 120) == 120
    assert ef_search(120, 120) == 240
