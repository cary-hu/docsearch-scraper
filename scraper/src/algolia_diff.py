"""Utilities for DocSearch incremental Algolia updates."""

import hashlib
import json
import os


CONTENT_HASH_FIELD = "docsearch_content_hash"
DEFAULT_DIFF_REPORT_PATH = "diff.log"


class IncrementalUpdateError(Exception):
    """Raised when an incremental update should not be applied."""


def compute_content_hash(record):
    """Return a stable hash for the searchable content of a record."""
    payload = {
        key: value for key, value in record.items()
        if key != CONTENT_HASH_FIELD
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def add_content_hash(record):
    """Return a copy of record with a docsearch content hash."""
    hashed_record = record.copy()
    hashed_record[CONTENT_HASH_FIELD] = compute_content_hash(record)
    return hashed_record


def add_content_hashes(records):
    """Return copies of records with docsearch content hashes."""
    return [add_content_hash(record) for record in records]


def find_duplicate_object_ids(records):
    seen = set()
    duplicates = set()

    for record in records:
        object_id = record.get("objectID")
        if object_id is None:
            continue
        if object_id in seen:
            duplicates.add(object_id)
        seen.add(object_id)

    return sorted(duplicates)


def _build_record_map(records):
    duplicates = find_duplicate_object_ids(records)
    if duplicates:
        raise IncrementalUpdateError(
            "Duplicate objectID values in crawl output: {}".format(
                ", ".join([str(object_id) for object_id in duplicates])
            )
        )

    records_by_id = {}
    for record in records:
        object_id = record.get("objectID")
        if object_id is None:
            raise IncrementalUpdateError("Record is missing objectID")
        records_by_id[object_id] = record

    return records_by_id


def diff_records(old_records, new_records):
    """Compute add, update, delete, and unchanged groups by objectID."""
    old_by_id = _build_record_map(old_records)
    new_by_id = _build_record_map(new_records)

    to_add = []
    to_update = []
    unchanged = 0

    for object_id in sorted(new_by_id.keys()):
        new_record = new_by_id[object_id]
        old_record = old_by_id.get(object_id)

        if old_record is None:
            to_add.append(new_record)
        elif old_record.get(CONTENT_HASH_FIELD) != new_record.get(CONTENT_HASH_FIELD):
            to_update.append(new_record)
        else:
            unchanged += 1

    to_delete = [
        old_by_id[object_id]
        for object_id in sorted(set(old_by_id.keys()) - set(new_by_id.keys()))
    ]

    return {
        "to_add": to_add,
        "to_update": to_update,
        "to_delete": to_delete,
        "unchanged": unchanged,
    }


def validate_incremental_update(diff, old_count, new_count,
                                max_delete_ratio, max_delete_count=None):
    """Raise if a computed diff is too risky to apply."""
    if new_count == 0:
        raise IncrementalUpdateError(
            "Incremental update aborted: new crawl produced 0 records"
        )

    delete_count = len(diff["to_delete"])
    delete_ratio = float(delete_count) / old_count if old_count > 0 else 0.0

    if max_delete_ratio is not None and old_count > 0 and delete_ratio > max_delete_ratio:
        raise IncrementalUpdateError(
            "Incremental update aborted: delete ratio {:.4f} exceeds {:.4f}".format(
                delete_ratio, max_delete_ratio
            )
        )

    if max_delete_count is not None and delete_count > max_delete_count:
        raise IncrementalUpdateError(
            "Incremental update aborted: delete count {} exceeds {}".format(
                delete_count, max_delete_count
            )
        )


def _sample_record(record):
    sample = {"objectID": record.get("objectID")}

    if "url" in record:
        sample["url"] = record["url"]
    if CONTENT_HASH_FIELD in record:
        sample[CONTENT_HASH_FIELD] = record[CONTENT_HASH_FIELD]

    return sample


def build_diff_report(index_name, old_count, new_count, diff, sample_size=20):
    delete_count = len(diff["to_delete"])
    delete_ratio = float(delete_count) / old_count if old_count > 0 else 0.0

    return {
        "index_name": index_name,
        "old_count": old_count,
        "new_count": new_count,
        "to_add_count": len(diff["to_add"]),
        "to_update_count": len(diff["to_update"]),
        "to_delete_count": delete_count,
        "unchanged_count": diff["unchanged"],
        "delete_ratio": delete_ratio,
        "samples": {
            "to_add": [_sample_record(record) for record in diff["to_add"][:sample_size]],
            "to_update": [_sample_record(record) for record in diff["to_update"][:sample_size]],
            "to_delete": [_sample_record(record) for record in diff["to_delete"][:sample_size]],
        },
    }


def format_diff_report(report):
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)


def print_diff_report(report):
    print("Incremental diff report:")
    print(format_diff_report(report))


def write_diff_report(report, report_path=None):
    path = report_path or DEFAULT_DIFF_REPORT_PATH
    directory = os.path.dirname(path)

    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(path, "w", encoding="utf-8") as report_file:
        report_file.write(format_diff_report(report))
        report_file.write("\n")

    return path
