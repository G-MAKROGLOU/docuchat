import asyncio

import httpx

from loadtest.run import Turn, drug_names, percentile, summary


def test_percentile_of_no_values_is_none() -> None:
    assert percentile([], 0.5) is None


def test_summary_counts_outcomes_and_times_only_answers() -> None:
    turns = [Turn("final", 2.0, 0.5), Turn("final", 4.0, 1.0), Turn("error", 30.0, None)]

    report = summary(turns, wall=10.0, users=2)

    assert report["outcomes"] == {"final": 2, "error": 1}
    assert report["turns_per_second"] == 0.3
    assert report["answered_seconds"] == {"p50": 4.0, "p95": 4.0, "p99": 4.0, "mean": 3.0}
    assert report["first_token_seconds"] == {"p50": 1.0, "p95": 1.0}


def test_the_drug_list_reads_every_page() -> None:
    total = 230

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        start = (page - 1) * 100
        items = [
            {"brand_name": f"Drug{i}", "status": "ingested"}
            for i in range(start, min(start + 100, total))
        ]
        return httpx.Response(200, json={"items": items, "total": total})

    async def names() -> list[str]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(base_url="http://api", transport=transport) as client:
            return await drug_names(client)

    found = asyncio.run(names())

    assert len(found) == total
    assert found[-1] == "Drug229"
