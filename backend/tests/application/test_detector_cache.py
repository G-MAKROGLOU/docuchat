import asyncio

from app.application.drug_detection import DetectorCache


class Library:
    def __init__(self) -> None:
        self.version: object = (1, "a")
        self.loads = 0

    async def current_version(self) -> object:
        return self.version

    async def load(self) -> str:
        self.loads += 1
        await asyncio.sleep(0)
        return f"detector-{self.loads}"


def test_the_detector_is_built_once_while_the_library_is_unchanged() -> None:
    library = Library()
    cache = DetectorCache(library.current_version, library.load)

    async def calls() -> list[str]:
        return [await cache(), await cache(), await cache()]

    assert asyncio.run(calls()) == ["detector-1"] * 3
    assert library.loads == 1


def test_a_library_change_rebuilds_the_detector() -> None:
    library = Library()
    cache = DetectorCache(library.current_version, library.load, min_interval=0)

    async def calls() -> tuple[str, str]:
        first = await cache()
        library.version = (2, "b")
        return first, await cache()

    assert asyncio.run(calls()) == ("detector-1", "detector-2")


def test_concurrent_first_calls_build_the_detector_once() -> None:
    library = Library()
    cache = DetectorCache(library.current_version, library.load)

    async def calls() -> list[str]:
        return list(await asyncio.gather(*(cache() for _ in range(20))))

    assert asyncio.run(calls()) == ["detector-1"] * 20
    assert library.loads == 1
