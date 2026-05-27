"""Tests for sec.py."""

from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest

from idi_ftm2j_shared.sec import _daily_index_url, _parse_daily_index, get_daily_index
from idi_ftm2j_shared.types import DiscoveredFiling

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_SAMPLE_INDEX = (
    "Company Name                                                  Form Type   CIK\n"
    "      Date Filed  URL \n"
    "-----------------------------------------------------------------------------------\n"
    "Acme Corp                                                     10-K             0001234567  20240115    https://www.sec.gov/Archives/edgar/data/1234567/000123456724000001-index.htm\n"
    "Beta Inc                                                      8-K              0009876543  20240115    https://www.sec.gov/Archives/edgar/data/9876543/000987654324000001-index.htm\n"
)

_SINGLE_ROW = DiscoveredFiling(
    company_name="Acme Corp",
    form_type="10-K",
    cik="0001234567",
    filing_date=date(2024, 1, 15),
    accession_number="000123456724000001",
    url="https://www.sec.gov/Archives/edgar/data/1234567/000123456724000001-index.htm",
)


def _ok(data: str) -> dict:
    return {"status_code": 200, "url": "https://www.sec.gov/...", "data": data}


def _err() -> dict:
    return {"status_code": 404, "error": "Not Found", "url": "https://www.sec.gov/..."}


# ---------------------------------------------------------------------------
# _daily_index_url
# ---------------------------------------------------------------------------


class TestDailyIndexUrl:
    """Tests for _daily_index_url."""

    def test_q1(self):
        assert _daily_index_url(date(2024, 1, 15)) == (
            "https://www.sec.gov/Archives/edgar/daily-index/2024/QTR1/crawler.20240115.idx"
        )

    def test_q2(self):
        assert _daily_index_url(date(2024, 4, 1)) == (
            "https://www.sec.gov/Archives/edgar/daily-index/2024/QTR2/crawler.20240401.idx"
        )

    def test_q3(self):
        assert _daily_index_url(date(2024, 7, 31)) == (
            "https://www.sec.gov/Archives/edgar/daily-index/2024/QTR3/crawler.20240731.idx"
        )

    def test_q4(self):
        assert _daily_index_url(date(2024, 10, 1)) == (
            "https://www.sec.gov/Archives/edgar/daily-index/2024/QTR4/crawler.20241001.idx"
        )


# ---------------------------------------------------------------------------
# _parse_daily_index
# ---------------------------------------------------------------------------


class TestParseDailyIndex:
    """Tests for _parse_daily_index."""

    def test_parses_two_rows(self):
        rows = list(_parse_daily_index(_SAMPLE_INDEX))
        assert len(rows) == 2

    def test_first_row_fields(self):
        rows = list(_parse_daily_index(_SAMPLE_INDEX))
        assert rows[0] == _SINGLE_ROW

    def test_second_row_url(self):
        rows = list(_parse_daily_index(_SAMPLE_INDEX))
        assert (
            rows[1].url
            == "https://www.sec.gov/Archives/edgar/data/9876543/000987654324000001-index.htm"
        )

    def test_skips_header(self):
        rows = list(_parse_daily_index(_SAMPLE_INDEX))
        assert all(r.form_type != "Form Type" for r in rows)

    def test_skips_malformed_lines(self):
        text = (
            "Company Name                                                  Form Type   CIK\n"
            "not a valid data line\n"
            "Acme Corp                                                     10-K             0001234567  20240101    https://www.sec.gov/Archives/edgar/data/1/1-index.htm\n"
        )
        rows = list(_parse_daily_index(text))
        assert len(rows) == 1
        assert rows[0].form_type == "10-K"

    def test_empty_string_yields_nothing(self):
        assert list(_parse_daily_index("")) == []


# ---------------------------------------------------------------------------
# get_daily_index
# ---------------------------------------------------------------------------


class TestGetDailyIndex:
    """Tests for get_daily_index."""

    def _mock_client(self, responses: list[dict]) -> MagicMock:
        client = MagicMock()
        client.query_endpoint.side_effect = responses
        return client

    def test_yields_discovered_filings(self):
        client = self._mock_client([_ok(_SAMPLE_INDEX)])
        rows = list(get_daily_index(date(2024, 1, 15), date(2024, 1, 15), client=client))
        assert len(rows) == 2
        assert rows[0] == _SINGLE_ROW

    def test_iterates_over_date_range(self):
        client = self._mock_client([_ok(_SAMPLE_INDEX), _ok(_SAMPLE_INDEX)])
        rows = list(get_daily_index(date(2024, 1, 15), date(2024, 1, 16), client=client))
        assert len(rows) == 4
        assert client.query_endpoint.call_count == 2

    def test_calls_correct_urls(self):
        client = self._mock_client([_ok(_SAMPLE_INDEX), _ok(_SAMPLE_INDEX)])
        list(get_daily_index(date(2024, 1, 15), date(2024, 1, 16), client=client))
        client.query_endpoint.assert_has_calls(
            [
                call(
                    sec_url="https://www.sec.gov/Archives/edgar/daily-index/2024/QTR1/crawler.20240115.idx",
                    return_json=False,
                ),
                call(
                    sec_url="https://www.sec.gov/Archives/edgar/daily-index/2024/QTR1/crawler.20240116.idx",
                    return_json=False,
                ),
            ]
        )

    def test_skips_days_with_errors(self):
        client = self._mock_client([_err(), _ok(_SAMPLE_INDEX)])
        rows = list(get_daily_index(date(2024, 1, 15), date(2024, 1, 16), client=client))
        assert len(rows) == 2

    def test_skips_days_with_empty_data(self):
        client = self._mock_client([_ok(""), _ok(_SAMPLE_INDEX)])
        rows = list(get_daily_index(date(2024, 1, 15), date(2024, 1, 16), client=client))
        assert len(rows) == 2

    def test_raises_if_start_after_end(self):
        client = self._mock_client([])
        with pytest.raises(ValueError, match="start_date"):
            list(get_daily_index(date(2024, 1, 16), date(2024, 1, 15), client=client))

    def test_same_start_and_end(self):
        client = self._mock_client([_ok(_SAMPLE_INDEX)])
        rows = list(get_daily_index(date(2024, 1, 15), date(2024, 1, 15), client=client))
        assert len(rows) == 2

    def test_creates_default_client_when_not_provided(self):
        with patch("idi_ftm2j_shared.sec.SecClient") as MockClient:
            instance = MockClient.return_value
            instance.query_endpoint.return_value = _err()
            list(get_daily_index(date(2024, 1, 15), date(2024, 1, 15)))
            MockClient.assert_called_once()

    def test_is_a_generator(self):
        client = self._mock_client([_ok(_SAMPLE_INDEX)])
        result = get_daily_index(date(2024, 1, 15), date(2024, 1, 15), client=client)
        import inspect

        assert inspect.isgenerator(result)
