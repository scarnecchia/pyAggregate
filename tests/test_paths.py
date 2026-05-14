"""Tests for request ID parser."""

from pyaggregate.core.paths import (
    RequestId,
    parse_request_id,
    pick_latest_approved,
    verid_sort_key,
)


class TestParseRequestId:
    """Test RequestId parser."""

    def test_valid_qar_parse(self) -> None:
        """Parse valid QAR request ID."""
        result = parse_request_id("soc_qar_wp041_aeos_v01")
        assert result is not None
        assert result.reqtype == "qar"
        assert result.wpid == "wp041"
        assert result.dpid == "aeos"
        assert result.verid == "v01"
        assert result.raw == "soc_qar_wp041_aeos_v01"

    def test_valid_qmr_parse(self) -> None:
        """Parse valid QMR request ID."""
        result = parse_request_id("soc_qmr_wp041_cms_v03")
        assert result is not None
        assert result.reqtype == "qmr"
        assert result.wpid == "wp041"
        assert result.dpid == "cms"
        assert result.verid == "v03"
        assert result.raw == "soc_qmr_wp041_cms_v03"

    def test_missing_verid(self) -> None:
        """Reject names missing verid."""
        result = parse_request_id("soc_qar_wp041_aeos")
        assert result is None

    def test_bad_reqtype(self) -> None:
        """Reject invalid reqtype."""
        result = parse_request_id("soc_xyz_wp041_aeos_v01")
        assert result is None

    def test_malformed_wpid(self) -> None:
        """Reject malformed wpid."""
        result = parse_request_id("soc_qar_notawpid_aeos_v01")
        assert result is None

    def test_malformed_verid(self) -> None:
        """Reject malformed verid."""
        result = parse_request_id("soc_qar_wp041_aeos_notyav")
        assert result is None

    def test_totally_wrong(self) -> None:
        """Reject completely wrong names."""
        result = parse_request_id("totally_wrong")
        assert result is None

    def test_empty_string(self) -> None:
        """Reject empty string."""
        result = parse_request_id("")
        assert result is None


class TestVeridSortKey:
    """Test version ID sorting."""

    def test_v01_less_than_v02(self) -> None:
        """v01 should sort before v02."""
        assert verid_sort_key("v01") < verid_sort_key("v02")

    def test_v02_less_than_v10(self) -> None:
        """v02 should sort before v10 (numeric, not lexicographic)."""
        assert verid_sort_key("v02") < verid_sort_key("v10")

    def test_v01_less_than_v10(self) -> None:
        """v01 should sort before v10."""
        assert verid_sort_key("v01") < verid_sort_key("v10")

    def test_numeric_ordering(self) -> None:
        """Verify numeric ordering: v1 < v2 < v10."""
        keys = [verid_sort_key(v) for v in ["v01", "v02", "v10"]]
        assert keys == sorted(keys)


class TestPickLatestApproved:
    """Test selection of latest approved version."""

    def test_picks_highest_approved(self) -> None:
        """Pick highest version where has_msoc=True."""
        rid_v01 = RequestId(
            reqtype="qar", wpid="wp041", dpid="aeos", verid="v01", raw="soc_qar_wp041_aeos_v01"
        )
        rid_v02 = RequestId(
            reqtype="qar", wpid="wp041", dpid="aeos", verid="v02", raw="soc_qar_wp041_aeos_v02"
        )
        entries = [(rid_v01, True), (rid_v02, True)]

        result = pick_latest_approved(entries)
        assert result == rid_v02

    def test_skips_unapproved_versions(self) -> None:
        """Skip versions with has_msoc=False."""
        rid_v01 = RequestId(
            reqtype="qar", wpid="wp041", dpid="aeos", verid="v01", raw="soc_qar_wp041_aeos_v01"
        )
        rid_v02 = RequestId(
            reqtype="qar", wpid="wp041", dpid="aeos", verid="v02", raw="soc_qar_wp041_aeos_v02"
        )
        entries = [(rid_v01, True), (rid_v02, False)]

        result = pick_latest_approved(entries)
        assert result == rid_v01

    def test_returns_none_for_no_approved(self) -> None:
        """Return None when no approved versions exist."""
        rid_v01 = RequestId(
            reqtype="qar", wpid="wp041", dpid="aeos", verid="v01", raw="soc_qar_wp041_aeos_v01"
        )
        rid_v02 = RequestId(
            reqtype="qar", wpid="wp041", dpid="aeos", verid="v02", raw="soc_qar_wp041_aeos_v02"
        )
        entries = [(rid_v01, False), (rid_v02, False)]

        result = pick_latest_approved(entries)
        assert result is None

    def test_returns_none_for_empty_list(self) -> None:
        """Return None for empty list."""
        result = pick_latest_approved([])
        assert result is None

    def test_ac21_version_ranking(self) -> None:
        """AC2.1: Given v01 and v02, pick v02."""
        rid_v01 = RequestId(
            reqtype="qar", wpid="wp041", dpid="aeos", verid="v01", raw="soc_qar_wp041_aeos_v01"
        )
        rid_v02 = RequestId(
            reqtype="qar", wpid="wp041", dpid="aeos", verid="v02", raw="soc_qar_wp041_aeos_v02"
        )
        entries = [(rid_v01, True), (rid_v02, True)]

        result = pick_latest_approved(entries)
        assert result == rid_v02
