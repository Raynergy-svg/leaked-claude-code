"""NDJSON serialization and async stream I/O for Aura's message protocol.

Ports the NDJSON-safe serialization pattern from the TypeScript codebase:
JSON.stringify emits U+2028/U+2029 raw (valid per ECMA-404), but any receiver
using line-terminator semantics to split the stream will cut the JSON mid-string.
Escaping to \\u2028/\\u2029 produces equivalent JSON that cannot be mistaken
for a line terminator by any receiver.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger(__name__)

# U+2028 LINE SEPARATOR and U+2029 PARAGRAPH SEPARATOR — valid in JSON strings
# but treated as line terminators by some receivers.
_JS_LINE_TERMINATORS = str.maketrans({
    "\u2028": "\\u2028",
    "\u2029": "\\u2029",
})


def ndjson_safe_serialize(value: Any) -> str:
    """Serialize *value* to a JSON string safe for NDJSON transport.

    Escapes U+2028 and U+2029 so the output cannot be split by a
    line-splitting receiver.  The result is still valid JSON and parses
    to the same value.

    Args:
        value: Any JSON-serializable Python object.

    Returns:
        A single-line JSON string with U+2028/U+2029 escaped.
    """
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).translate(
        _JS_LINE_TERMINATORS
    )


def ndjson_parse_line(line: str) -> Optional[dict]:
    """Parse a single NDJSON line into a dict.

    Args:
        line: A single line of text (newline already stripped).

    Returns:
        Parsed dict on success, ``None`` on parse error or empty input.
    """
    stripped = line.strip()
    if not stripped:
        return None
    try:
        result = json.loads(stripped)
        if not isinstance(result, dict):
            logger.warning("NDJSON line parsed to non-dict type: %s", type(result).__name__)
            return None
        return result
    except (json.JSONDecodeError, ValueError) as exc:
        logger.debug("Failed to parse NDJSON line: %s", exc)
        return None


class NdjsonReader:
    """Async line reader that yields parsed NDJSON messages.

    Reads from an :class:`asyncio.StreamReader` and yields each
    successfully parsed line as a ``dict``.  Malformed lines are
    logged and skipped.

    Args:
        reader: An asyncio StreamReader providing the raw byte stream.
        encoding: Character encoding for decoding bytes. Defaults to ``utf-8``.
    """

    def __init__(self, reader: asyncio.StreamReader, *, encoding: str = "utf-8") -> None:
        self._reader = reader
        self._encoding = encoding

    async def __aiter__(self) -> AsyncIterator[dict]:
        """Yield parsed dicts from each NDJSON line until EOF."""
        while True:
            try:
                raw = await self._reader.readline()
            except (asyncio.IncompleteReadError, ConnectionError) as exc:
                logger.debug("NDJSON reader stream ended: %s", exc)
                break

            if not raw:
                break  # EOF

            line = raw.decode(self._encoding, errors="replace")
            parsed = ndjson_parse_line(line)
            if parsed is not None:
                yield parsed


class NdjsonWriter:
    """Writes serialized NDJSON lines to an asyncio StreamWriter.

    Each message is serialized with :func:`ndjson_safe_serialize` and
    terminated with a newline.

    Args:
        writer: An asyncio StreamWriter for the outbound byte stream.
        encoding: Character encoding for encoding strings. Defaults to ``utf-8``.
    """

    def __init__(self, writer: asyncio.StreamWriter, *, encoding: str = "utf-8") -> None:
        self._writer = writer
        self._encoding = encoding

    async def write(self, value: Any) -> None:
        """Serialize *value* and write it as a single NDJSON line.

        Args:
            value: Any JSON-serializable Python object.
        """
        line = ndjson_safe_serialize(value) + "\n"
        self._writer.write(line.encode(self._encoding))
        await self._writer.drain()

    async def write_batch(self, values: list[Any]) -> None:
        """Serialize and write multiple values as consecutive NDJSON lines.

        All lines are buffered before a single drain, reducing the number
        of flushes for batch operations.

        Args:
            values: List of JSON-serializable Python objects.
        """
        data = "".join(ndjson_safe_serialize(v) + "\n" for v in values)
        self._writer.write(data.encode(self._encoding))
        await self._writer.drain()

    async def close(self) -> None:
        """Close the underlying writer."""
        self._writer.close()
        await self._writer.wait_closed()
