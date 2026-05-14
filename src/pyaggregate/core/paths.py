# pattern: Functional Core
"""Request ID parser and path utilities."""

import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RequestId:
    """Parsed request ID from directory name."""

    reqtype: Literal["qar", "qmr"]
    wpid: str
    dpid: str
    verid: str
    raw: str


# Compiled regex for matching soc_<reqtype>_<wpid>_<dpid>_<verid> pattern
_REQUEST_ID_PATTERN = re.compile(r"^soc_(qar|qmr)_(wp\d+)_(.+)_(v\d+)$")


def parse_request_id(dirname: str) -> RequestId | None:
    """Parse package directory name into RequestId.

    Matches pattern: soc_<reqtype>_<wpid>_<dpid>_<verid>
    - reqtype: qar or qmr
    - wpid: wp followed by digits (e.g., wp041)
    - dpid: any string (e.g., aeos, cms)
    - verid: v followed by digits (e.g., v01, v02)

    Args:
        dirname: directory name to parse

    Returns:
        Parsed RequestId or None if malformed
    """
    if not dirname:
        return None

    match = _REQUEST_ID_PATTERN.match(dirname)
    if not match:
        return None

    reqtype, wpid, dpid, verid = match.groups()
    return RequestId(
        reqtype=reqtype,  # type: ignore[arg-type]
        wpid=wpid,
        dpid=dpid,
        verid=verid,
        raw=dirname,
    )


def verid_sort_key(verid: str) -> int:
    """Extract numeric portion of version ID for sorting.

    Converts v01, v02, v10 to 1, 2, 10 for numeric ordering.

    Args:
        verid: version ID string (e.g., v01, v02, v10)

    Returns:
        Numeric sort key (lexicographic would incorrectly order v10 before v2)
    """
    # Remove 'v' prefix and convert to int
    numeric_part = verid.removeprefix("v")
    return int(numeric_part)


def pick_latest_approved(entries: list[tuple[RequestId, bool]]) -> RequestId | None:
    """Select highest version where has_msoc=True.

    Filters to only approved versions (has_msoc=True), sorts by verid descending,
    and returns the highest version's RequestId.

    Pure function: no filesystem access. Caller is responsible for checking
    msoc/ existence and passing the boolean.

    Args:
        entries: list of (RequestId, has_msoc) tuples for same (dpid, wpid, reqtype)

    Returns:
        RequestId of highest approved version or None if no approved version exists
    """
    if not entries:
        return None

    # Filter to only approved versions
    approved = [rid for rid, has_msoc in entries if has_msoc]

    if not approved:
        return None

    # Sort by verid descending and return the highest
    return max(approved, key=lambda rid: verid_sort_key(rid.verid))
