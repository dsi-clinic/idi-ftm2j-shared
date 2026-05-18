"""Tests for api.py."""

import threading
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from idi_ftm2j_shared.api import ApiClient


class ConcreteClient(ApiClient):
    """Minimal concrete subclass for testing the abstract ApiClient."""

    def query_endpoint(self, **kwargs: object) -> dict:
        """Delegate to _query_with_error_handling for testing."""
        return self._query_with_error_handling(**kwargs)


@pytest.fixture(autouse=True)
def mock_get_logger():
    """Prevent real logger creation side effects during tests."""
    with patch("idi_ftm2j_shared.api.get_logger", return_value=MagicMock()):
        yield


@pytest.fixture
def client() -> ConcreteClient:
    """Return a default ConcreteClient instance."""
    return ConcreteClient()


def _mock_session(client: ConcreteClient) -> MagicMock:
    """Inject a mock session into the client's cached_property slot."""
    mock = MagicMock(spec=requests.Session)
    client.__dict__["session"] = mock
    return mock


class TestApiClientInit:
    """Tests for ApiClient.__init__."""

    def test_default_api_key_is_empty_string(self):
        assert ConcreteClient().api_key == ""

    def test_custom_api_key_stored(self):
        assert ConcreteClient(api_key="secret").api_key == "secret"

    def test_default_max_retries(self):
        assert ConcreteClient().max_retries == ApiClient.DEFAULT_MAX_RETRIES

    def test_custom_max_retries(self):
        assert ConcreteClient(max_retries=5).max_retries == 5

    def test_none_max_retries_falls_back_to_default(self):
        assert ConcreteClient(max_retries=None).max_retries == ApiClient.DEFAULT_MAX_RETRIES

    def test_rate_limit_none_uses_nullcontext(self):
        client = ConcreteClient(rate_limit=None)
        assert isinstance(client._lock, type(nullcontext()))

    def test_rate_limit_set_uses_threading_lock(self):
        client = ConcreteClient(rate_limit=0.5)
        assert isinstance(client._lock, threading.Lock)

    def test_rate_limit_stored(self):
        assert ConcreteClient(rate_limit=1.5)._rate_limit == 1.5

    def test_logger_assigned(self):
        assert ConcreteClient().logger is not None


class TestApiClientRateLimit:
    """Tests for ApiClient.rate_limit."""

    def test_no_op_when_rate_limit_is_none(self):
        client = ConcreteClient(rate_limit=None)
        with patch("idi_ftm2j_shared.api.time.sleep") as mock_sleep:
            client.rate_limit()
        mock_sleep.assert_not_called()

    def test_sleeps_when_not_enough_time_has_elapsed(self):
        client = ConcreteClient(rate_limit=1.0)
        # _last_request=0.0, first time.time() returns 0.3 → elapsed=0.3 → sleep 0.7
        with (
            patch("idi_ftm2j_shared.api.time.time", side_effect=[0.3, 0.3]),
            patch("idi_ftm2j_shared.api.time.sleep") as mock_sleep,
        ):
            client._last_request = 0.0
            client.rate_limit()
        mock_sleep.assert_called_once()
        assert abs(mock_sleep.call_args[0][0] - 0.7) < 0.01

    def test_no_sleep_when_enough_time_has_elapsed(self):
        client = ConcreteClient(rate_limit=1.0)
        with (
            patch("idi_ftm2j_shared.api.time.time", side_effect=[2.0, 2.0]),
            patch("idi_ftm2j_shared.api.time.sleep") as mock_sleep,
        ):
            client._last_request = 0.0
            client.rate_limit()
        mock_sleep.assert_not_called()

    def test_updates_last_request_after_call(self):
        client = ConcreteClient(rate_limit=1.0)
        with (
            patch("idi_ftm2j_shared.api.time.time", return_value=99.0),
            patch("idi_ftm2j_shared.api.time.sleep"),
        ):
            client._last_request = 0.0
            client.rate_limit()
        assert client._last_request == 99.0


class TestApiClientSession:
    """Tests for ApiClient.session cached_property."""

    def test_returns_requests_session(self, client):
        assert isinstance(client.session, requests.Session)

    def test_same_session_returned_on_repeated_access(self, client):
        assert client.session is client.session

    def test_http_adapter_mounted(self, client):
        adapter = client.session.get_adapter("http://example.com")
        assert isinstance(adapter, HTTPAdapter)

    def test_https_adapter_mounted(self, client):
        adapter = client.session.get_adapter("https://example.com")
        assert isinstance(adapter, HTTPAdapter)

    def test_retry_total_matches_max_retries(self, client):
        retry: Retry = client.session.get_adapter("https://x").max_retries
        assert retry.total == ApiClient.DEFAULT_MAX_RETRIES

    def test_retry_backoff_factor(self, client):
        retry: Retry = client.session.get_adapter("https://x").max_retries
        assert retry.backoff_factor == ApiClient.RETRY_BACKOFF_FACTOR

    def test_retry_status_forcelist(self, client):
        retry: Retry = client.session.get_adapter("https://x").max_retries
        assert set(retry.status_forcelist) == set(ApiClient.RETRY_STATUS_FORCELIST)

    def test_retry_allowed_methods(self, client):
        retry: Retry = client.session.get_adapter("https://x").max_retries
        assert "GET" in retry.allowed_methods
        assert "POST" in retry.allowed_methods


class TestApiClientGet:
    """Tests for ApiClient.get."""

    def test_calls_session_get_with_url(self, client):
        session = _mock_session(client)
        client.get("https://example.com")
        session.get.assert_called_once()
        # url is passed as the first positional argument
        assert session.get.call_args.args[0] == "https://example.com"

    def test_passes_params_and_headers(self, client):
        session = _mock_session(client)
        client.get("https://example.com", params={"k": "v"}, headers={"H": "1"})
        _, kwargs = session.get.call_args
        assert kwargs.get("params") == {"k": "v"}
        assert kwargs.get("headers") == {"H": "1"}

    def test_default_timeout_applied(self, client):
        session = _mock_session(client)
        client.get("https://example.com")
        _, kwargs = session.get.call_args
        assert kwargs.get("timeout") == ApiClient.REQUEST_TIMEOUT

    def test_custom_timeout_overrides_default(self, client):
        session = _mock_session(client)
        client.get("https://example.com", timeout=99)
        _, kwargs = session.get.call_args
        assert kwargs.get("timeout") == 99

    def test_calls_raise_for_status(self, client):
        session = _mock_session(client)
        response = session.get.return_value
        client.get("https://example.com")
        response.raise_for_status.assert_called_once()

    def test_returns_response(self, client):
        session = _mock_session(client)
        response = MagicMock()
        session.get.return_value = response
        assert client.get("https://example.com") is response


class TestApiClientPost:
    """Tests for ApiClient.post."""

    def test_calls_session_post(self, client):
        session = _mock_session(client)
        client.post("https://example.com", data="payload")
        session.post.assert_called_once()

    def test_passes_data_and_headers(self, client):
        session = _mock_session(client)
        client.post("https://example.com", data={"k": "v"}, headers={"H": "1"})
        _, kwargs = session.post.call_args
        assert kwargs.get("data") == {"k": "v"}
        assert kwargs.get("headers") == {"H": "1"}

    def test_default_timeout_applied(self, client):
        session = _mock_session(client)
        client.post("https://example.com")
        _, kwargs = session.post.call_args
        assert kwargs.get("timeout") == ApiClient.REQUEST_TIMEOUT

    def test_custom_timeout_overrides_default(self, client):
        session = _mock_session(client)
        client.post("https://example.com", timeout=5)
        _, kwargs = session.post.call_args
        assert kwargs.get("timeout") == 5

    def test_calls_raise_for_status(self, client):
        session = _mock_session(client)
        response = session.post.return_value
        client.post("https://example.com")
        response.raise_for_status.assert_called_once()

    def test_returns_response(self, client):
        session = _mock_session(client)
        response = MagicMock()
        session.post.return_value = response
        assert client.post("https://example.com") is response


class TestQueryWithErrorHandling:
    """Tests for ApiClient._query_with_error_handling."""

    def _ok_response(self, status: int = 200, json_data=None, text="ok", url="https://x.com"):
        resp = MagicMock()
        resp.status_code = status
        resp.url = url
        resp.json.return_value = json_data if json_data is not None else {"result": 1}
        resp.text = text
        resp.content = b"bytes"
        return resp

    def test_get_success_returns_status_url_data(self, client):
        resp = self._ok_response(json_data={"a": 1})
        with patch.object(client, "get", return_value=resp):
            result = client._query_with_error_handling("https://x.com")
        assert result["status_code"] == 200
        assert result["url"] == "https://x.com"
        assert result["data"] == {"a": 1}
        assert "error" not in result

    def test_post_success_uses_post_method(self, client):
        resp = self._ok_response()
        with (
            patch.object(client, "get") as mock_get,
            patch.object(client, "post", return_value=resp) as mock_post,
        ):
            client._query_with_error_handling("https://x.com", method="post", data="body")
        mock_post.assert_called_once()
        mock_get.assert_not_called()

    def test_return_json_false_uses_text(self, client):
        resp = self._ok_response(text="plain text")
        with patch.object(client, "get", return_value=resp):
            result = client._query_with_error_handling("https://x.com", return_json=False)
        assert result["data"] == "plain text"

    def test_return_bytes_true_uses_content(self, client):
        resp = self._ok_response()
        resp.content = b"\x89PNG"
        with patch.object(client, "get", return_value=resp):
            result = client._query_with_error_handling("https://x.com", return_bytes=True)
        assert result["data"] == b"\x89PNG"

    def test_return_bytes_overrides_return_json(self, client):
        resp = self._ok_response()
        resp.content = b"raw"
        with patch.object(client, "get", return_value=resp):
            result = client._query_with_error_handling(
                "https://x.com", return_json=True, return_bytes=True
            )
        assert result["data"] == b"raw"
        resp.json.assert_not_called()

    def test_timeout_sets_error_and_timeout_flag(self, client):
        exc = requests.exceptions.Timeout("timed out")
        with patch.object(client, "get", side_effect=exc):
            result = client._query_with_error_handling("https://x.com")
        assert "error" in result
        assert result.get("timeout") is True

    def test_request_exception_sets_error(self, client):
        exc = requests.exceptions.ConnectionError("refused")
        with patch.object(client, "get", side_effect=exc):
            result = client._query_with_error_handling("https://x.com")
        assert "error" in result
        assert "timeout" not in result

    def test_http_error_with_response_sets_status_code(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 404
        exc = requests.exceptions.HTTPError(response=mock_response)
        with patch.object(client, "get", side_effect=exc):
            result = client._query_with_error_handling("https://x.com")
        assert result["status_code"] == 404
        assert "error" in result

    def test_http_error_without_response_has_no_status_code(self, client):
        exc = requests.exceptions.HTTPError(response=None)
        with patch.object(client, "get", side_effect=exc):
            result = client._query_with_error_handling("https://x.com")
        assert "status_code" not in result

    def test_json_parse_error_omits_data(self, client):
        resp = self._ok_response()
        resp.json.side_effect = ValueError("not json")
        with patch.object(client, "get", return_value=resp):
            result = client._query_with_error_handling("https://x.com")
        assert "data" not in result

    def test_params_forwarded_to_get(self, client):
        resp = self._ok_response()
        with patch.object(client, "get", return_value=resp) as mock_get:
            client._query_with_error_handling("https://x.com", params={"q": "1"})
        assert mock_get.call_args.kwargs.get("params") == {"q": "1"}

    def test_data_forwarded_to_post(self, client):
        resp = self._ok_response()
        with patch.object(client, "post", return_value=resp) as mock_post:
            client._query_with_error_handling("https://x.com", method="post", data="payload")
        assert mock_post.call_args.kwargs.get("data") == "payload"

    def test_headers_forwarded(self, client):
        resp = self._ok_response()
        with patch.object(client, "get", return_value=resp) as mock_get:
            client._query_with_error_handling("https://x.com", headers={"X-Key": "val"})
        assert mock_get.call_args.kwargs.get("headers") == {"X-Key": "val"}

    def test_error_message_includes_url(self, client):
        exc = requests.exceptions.ConnectionError("refused")
        with patch.object(client, "get", side_effect=exc):
            result = client._query_with_error_handling("https://x.com/path")
        assert "https://x.com/path" in result["error"]


class TestQueryEndpoint:
    """Tests for ApiClient.query_endpoint abstract method."""

    def test_cannot_instantiate_abstract_class(self):
        with pytest.raises(TypeError):
            ApiClient()  # type: ignore[abstract]

    def test_concrete_subclass_is_instantiable(self):
        assert ConcreteClient() is not None

    def test_subclass_without_query_endpoint_raises(self):
        class Incomplete(ApiClient):
            pass

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]
