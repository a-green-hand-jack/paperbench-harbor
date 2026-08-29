from paperbench_harbor.common.scholarly_search import SearchRecord, search


def test_search_enforces_cutoff_and_is_deterministic() -> None:
    records = [
        SearchRecord("Older Segmentation", "audio visual", 2023),
        SearchRecord("Newer Segmentation", "audio visual", 2025),
        SearchRecord("Audio Only", "audio", 2022),
    ]
    result = search(records, "audio visual", cutoff_year=2024)
    assert [record.title for record in result] == ["Older Segmentation", "Audio Only"]


def test_search_limit_and_empty_query() -> None:
    records = [SearchRecord("A", "audio", 2023), SearchRecord("B", "audio", 2022)]
    assert search(records, "audio", cutoff_year=None, limit=1)[0].title == "A"
    assert search(records, "", cutoff_year=None) == []
