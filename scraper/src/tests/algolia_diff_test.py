import pytest

from ..algolia_diff import (
    CONTENT_HASH_FIELD,
    DEFAULT_DIFF_REPORT_PATH,
    IncrementalUpdateError,
    add_content_hash,
    build_diff_report,
    diff_records,
    find_duplicate_object_ids,
    validate_incremental_update,
    write_diff_report,
)


def _record(object_id, title):
    return add_content_hash({
        "objectID": object_id,
        "url": "https://example.com/{}".format(object_id),
        "hierarchy": {"lvl0": title},
        "content": title,
    })


def test_diff_records_add_update_delete_unchanged():
    unchanged = _record("unchanged", "Same")
    old_updated = _record("updated", "Before")
    new_updated = _record("updated", "After")
    deleted = _record("deleted", "Gone")
    added = _record("added", "New")

    diff = diff_records(
        [unchanged, old_updated, deleted],
        [unchanged, new_updated, added],
    )

    assert [record["objectID"] for record in diff["to_add"]] == ["added"]
    assert [record["objectID"] for record in diff["to_update"]] == ["updated"]
    assert [record["objectID"] for record in diff["to_delete"]] == ["deleted"]
    assert diff["unchanged"] == 1


def test_duplicate_new_object_ids_are_detected():
    records = [_record("same", "One"), _record("same", "Two")]

    assert find_duplicate_object_ids(records) == ["same"]

    with pytest.raises(IncrementalUpdateError):
        diff_records([], records)


def test_empty_crawl_is_rejected():
    diff = {
        "to_add": [],
        "to_update": [],
        "to_delete": [_record("old", "Old")],
        "unchanged": 0,
    }

    with pytest.raises(IncrementalUpdateError):
        validate_incremental_update(diff, old_count=1, new_count=0,
                                    max_delete_ratio=1.0)


def test_delete_ratio_threshold_is_enforced():
    diff = {
        "to_add": [],
        "to_update": [],
        "to_delete": [_record("old-1", "Old"), _record("old-2", "Old")],
        "unchanged": 1,
    }

    with pytest.raises(IncrementalUpdateError):
        validate_incremental_update(diff, old_count=3, new_count=1,
                                    max_delete_ratio=0.5)


def test_delete_count_threshold_is_enforced():
    diff = {
        "to_add": [],
        "to_update": [],
        "to_delete": [_record("old-1", "Old"), _record("old-2", "Old")],
        "unchanged": 1,
    }

    with pytest.raises(IncrementalUpdateError):
        validate_incremental_update(diff, old_count=3, new_count=1,
                                    max_delete_ratio=1.0,
                                    max_delete_count=1)


def test_content_hash_is_stable_and_ignores_existing_hash():
    record = {
        "objectID": "id",
        "url": "https://example.com",
        "hierarchy": {"lvl0": "Title"},
        "content": "Body",
    }

    first = add_content_hash(record)
    second = add_content_hash(first)

    assert first[CONTENT_HASH_FIELD] == second[CONTENT_HASH_FIELD]


def test_diff_report_contains_counts_and_samples():
    diff = {
        "to_add": [_record("added", "New")],
        "to_update": [],
        "to_delete": [_record("deleted", "Gone")],
        "unchanged": 3,
    }

    report = build_diff_report("docs", old_count=4, new_count=4, diff=diff)

    assert report["index_name"] == "docs"
    assert report["to_add_count"] == 1
    assert report["to_delete_count"] == 1
    assert report["delete_ratio"] == 0.25
    assert report["samples"]["to_add"][0]["objectID"] == "added"


def test_diff_report_defaults_to_diff_log(tmpdir, monkeypatch):
    monkeypatch.chdir(str(tmpdir))
    diff = {
        "to_add": [],
        "to_update": [],
        "to_delete": [],
        "unchanged": 1,
    }
    report = build_diff_report("docs", old_count=1, new_count=1, diff=diff)

    report_path = write_diff_report(report)

    assert report_path == DEFAULT_DIFF_REPORT_PATH
    assert tmpdir.join("diff.log").check()
