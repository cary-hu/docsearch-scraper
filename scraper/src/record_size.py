"""Keep DocSearch records under the Algolia record size limit.

Algolia rejects a whole batch of records when a single one is bigger than the
allowed size (10,000 bytes on most plans), which aborts the whole crawl:

    algoliasearch.exceptions.RequestException: Record at the position 4
    objectID=... is too big size=10505/10000 bytes.

DocSearch records store the page text twice (``content`` and
``content_camel``) and the hierarchy twice as well, so one very long code
block or table is enough to blow the limit.

The main entry point is :func:`split_record`: oversized records are split into
several records sharing the same URL and hierarchy, so the whole page text
stays searchable (Algolia ``distinct`` on ``url`` still shows a single hit per
page). Records that cannot be split, because their size does not come from a
string ``content``, are shortened by :func:`fit_record_to_size` instead.
"""

import copy
import json

MAX_RECORD_SIZE_BYTES = 10000

# Attributes that must never be shortened: they identify the record or are the
# link target of the search result.
PROTECTED_ATTRIBUTES = frozenset([
    'objectID',
    'url',
    'url_without_variables',
    'url_without_anchor',
    'anchor',
])


def record_size_bytes(record):
    """Return the size of `record` in bytes, as Algolia counts it.

    The Algolia client serializes records with ``json.dumps`` defaults, i.e.
    with non-ASCII characters escaped, so the estimate is never too low.
    """
    serialized = json.dumps(record, default=str)
    return len(serialized.encode('utf-8'))


def _escaped_length(value):
    """Length of `value` once JSON-escaped, without the quotes."""
    return len(json.dumps(value)) - 2


_CHAR_COST_CACHE = {}

# Number of characters we look back for a word boundary when cutting a chunk.
WORD_CUT_LOOKBACK = 200


def _char_cost(char):
    """Escaped JSON length of a single character, memoized."""
    cost = _CHAR_COST_CACHE.get(char)
    if cost is None:
        cost = _escaped_length(char)
        _CHAR_COST_CACHE[char] = cost
    return cost


def _find_word_cut(text, start, end):
    """Return the best position <= `end` to cut `text` on a word break."""
    window_start = max(start + 1, end - WORD_CUT_LOOKBACK)
    for position in range(end, window_start - 1, -1):
        if text[position - 1].isspace():
            return position
    return end


def split_text(text, max_size):
    """Cut `text` into pieces whose escaped JSON size stays under `max_size`.

    Words are kept whole when a whitespace is available near the cut, and no
    character is lost: ``''.join(split_text(text, n)) == text``.
    """
    if max_size <= 0:
        return ['']
    if _escaped_length(text) <= max_size:
        return [text]

    chunks = []
    start = 0
    size = 0

    for index, char in enumerate(text):
        cost = _char_cost(char)
        if size + cost > max_size and index > start:
            cut = _find_word_cut(text, start, index)
            chunks.append(text[start:cut])
            start = cut
            size = sum(_char_cost(item) for item in text[start:index + 1])
        else:
            size += cost

    chunks.append(text[start:])
    return chunks


def split_record(record, max_size=MAX_RECORD_SIZE_BYTES):
    """Return the records to index for `record`.

    A record that fits is returned as is (``[record]``). An oversized record
    whose ``content`` is a string is split into several records sharing the
    same URL, hierarchy and weight. The first chunk keeps the original
    ``objectID``, the next ones get a ``-1``, ``-2``, ... suffix, so a page
    that becomes bigger only updates the chunks it has to.
    """
    if record_size_bytes(record) <= max_size:
        return [record]

    content = record.get('content')
    if not isinstance(content, str) or content == '':
        return [fit_record_to_size(record, max_size)]

    # Everything but the content: the room left for the chunks.
    template = dict(record)
    template['content'] = ''
    copies = 1
    if isinstance(template.get('content_camel'), str):
        template['content_camel'] = ''
        copies += 1

    # Leave room for the objectID suffix ('-1', '-2', ...).
    budget = max_size - record_size_bytes(template) - 32
    if budget <= 0:
        return [fit_record_to_size(record, max_size)]

    chunks = split_text(content, budget // copies)
    object_id = record.get('objectID')

    records = []
    for index, chunk in enumerate(chunks):
        chunk_record = dict(record)
        chunk_record['content'] = chunk
        if 'content_camel' in chunk_record:
            chunk_record['content_camel'] = chunk
        if index:
            chunk_record['objectID'] = '{}-{}'.format(object_id, index)
        else:
            chunk_record['objectID'] = object_id
        # Safety net: never send a chunk that is still too big.
        records.append(fit_record_to_size(chunk_record, max_size))

    return records


def truncate_utf8(value, max_bytes):
    """Shorten `value` to at most `max_bytes` UTF-8 bytes."""
    if max_bytes <= 0:
        return ''
    encoded = value.encode('utf-8')
    if len(encoded) <= max_bytes:
        return value
    # 'ignore' drops an incomplete multi-byte character at the cut point.
    return encoded[:max_bytes].decode('utf-8', 'ignore')


def _iter_text_slots(node):
    """Yield ``(container, key)`` for every shorten-able string of `node`."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str):
                if key not in PROTECTED_ATTRIBUTES:
                    yield node, key
            elif isinstance(value, (dict, list, tuple)):
                for slot in _iter_text_slots(value):
                    yield slot
    elif isinstance(node, (list, tuple)):
        for value in node:
            if isinstance(value, (dict, list, tuple)):
                for slot in _iter_text_slots(value):
                    yield slot


def fit_record_to_size(record, max_size=MAX_RECORD_SIZE_BYTES):
    """Return `record` if it fits, otherwise a shortened copy of it.

    The longest text attributes are trimmed first, so a record whose size is
    driven by one large ``content`` is not stripped of its hierarchy.
    """
    if record_size_bytes(record) <= max_size:
        return record

    fitted = copy.deepcopy(record)
    slots = sorted(
        _iter_text_slots(fitted),
        key=lambda slot: len(slot[0][slot[1]].encode('utf-8')),
        reverse=True)

    for container, key in slots:
        excess = record_size_bytes(fitted) - max_size
        if excess <= 0:
            break
        value = container[key]
        container[key] = truncate_utf8(
            value, len(value.encode('utf-8')) - excess)

    return fitted
