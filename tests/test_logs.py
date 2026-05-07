"""Tests for logs.py."""

import logging
import uuid
from unittest.mock import MagicMock, patch

import boto3
import pytest
import watchtower
from moto import mock_aws

import logs
from logs import (
    TqdmLoggingHandler,
    _configure_cloudwatch,
    _get_instance_id,
    get_logger,
)

REGION = "us-east-1"


def _unique_name() -> str:
    return f"test.{uuid.uuid4().hex}"


@pytest.fixture(autouse=True)
def isolate_loggers():
    """Restore _configured_loggers and remove handlers from any loggers created per test."""
    before = frozenset(logs._configured_loggers)
    yield
    added = logs._configured_loggers - before
    for name in added:
        logger = logging.getLogger(name)
        for h in logger.handlers[:]:
            try:
                h.close()
            except Exception:
                pass
            logger.removeHandler(h)
        logging.Logger.manager.loggerDict.pop(name, None)
    logs._configured_loggers.clear()
    logs._configured_loggers.update(before)


@pytest.fixture
def cw(monkeypatch):
    """Moto-backed CloudWatch Logs client with fake AWS credentials."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    with mock_aws():
        yield boto3.client("logs", region_name=REGION)


@pytest.fixture
def cw_logger(cw):
    """Logger with handlers closed (while moto context is still active) after each test."""
    logger = logging.getLogger(_unique_name())
    logger.handlers.clear()
    yield logger
    for h in logger.handlers[:]:
        try:
            h.close()
        except Exception:
            pass
        logger.removeHandler(h)


class TestGetInstanceId:
    """Tests for _get_instance_id."""

    def test_returns_instance_id_env_var(self, monkeypatch):
        monkeypatch.setenv("INSTANCE_ID", "i-env-override")
        assert _get_instance_id() == "i-env-override"

    def test_fetches_from_imdsv2(self, monkeypatch):
        monkeypatch.delenv("INSTANCE_ID", raising=False)
        token_resp = MagicMock()
        token_resp.text = "fake-token\n"
        instance_resp = MagicMock()
        instance_resp.text = "i-1234567890abcdef0\n"

        with patch("logs.requests.put", return_value=token_resp), \
             patch("logs.requests.get", return_value=instance_resp):
            result = _get_instance_id()

        assert result == "i-1234567890abcdef0"

    def test_strips_whitespace_from_imdsv2_response(self, monkeypatch):
        monkeypatch.delenv("INSTANCE_ID", raising=False)
        token_resp = MagicMock()
        token_resp.text = "  token  "
        instance_resp = MagicMock()
        instance_resp.text = "  i-abc123  "

        with patch("logs.requests.put", return_value=token_resp), \
             patch("logs.requests.get", return_value=instance_resp):
            result = _get_instance_id()

        assert result == "i-abc123"

    def test_falls_back_to_hostname_on_request_failure(self, monkeypatch):
        monkeypatch.delenv("INSTANCE_ID", raising=False)
        monkeypatch.setenv("HOSTNAME", "ip-10-0-0-1.ec2.internal")
        with patch("logs.requests.put", side_effect=Exception("timeout")):
            assert _get_instance_id() == "ip-10-0-0-1"

    def test_falls_back_to_unknown_when_no_hostname(self, monkeypatch):
        monkeypatch.delenv("INSTANCE_ID", raising=False)
        monkeypatch.delenv("HOSTNAME", raising=False)
        with patch("logs.requests.put", side_effect=Exception("timeout")):
            assert _get_instance_id() == "unknown"

    def test_imdsv2_token_passed_in_instance_request(self, monkeypatch):
        monkeypatch.delenv("INSTANCE_ID", raising=False)
        token_resp = MagicMock()
        token_resp.text = "my-secret-token"
        instance_resp = MagicMock()
        instance_resp.text = "i-abc"

        with patch("logs.requests.put", return_value=token_resp), \
             patch("logs.requests.get", return_value=instance_resp) as mock_get:
            _get_instance_id()

        called_headers = mock_get.call_args.kwargs["headers"]
        assert called_headers["X-aws-ec2-metadata-token"] == "my-secret-token"


class TestTqdmLoggingHandler:
    """Tests for TqdmLoggingHandler."""

    def test_emit_calls_tqdm_write(self):
        handler = TqdmLoggingHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)

        with patch("logs.tqdm.tqdm.write") as mock_write:
            handler.emit(record)

        mock_write.assert_called_once_with("hello")

    def test_emit_formats_record_before_writing(self):
        handler = TqdmLoggingHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        record = logging.LogRecord("test", logging.WARNING, "", 0, "oops", (), None)

        with patch("logs.tqdm.tqdm.write") as mock_write:
            handler.emit(record)

        mock_write.assert_called_once_with("WARNING: oops")

    def test_emit_calls_handle_error_on_exception(self):
        handler = TqdmLoggingHandler()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)

        with patch("logs.tqdm.tqdm.write", side_effect=RuntimeError("boom")), \
             patch.object(handler, "handleError") as mock_handle_error:
            handler.emit(record)

        mock_handle_error.assert_called_once_with(record)


class TestGetLogger:
    """Tests for get_logger."""

    def test_returns_logger_with_correct_name(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        name = _unique_name()
        assert get_logger(name).name == name

    def test_default_level_is_info(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        assert get_logger(_unique_name()).level == logging.INFO

    def test_explicit_level_is_applied(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        assert get_logger(_unique_name(), level=logging.DEBUG).level == logging.DEBUG

    def test_log_level_env_var_overrides_level(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        assert get_logger(_unique_name()).level == logging.DEBUG

    def test_invalid_log_level_env_var_is_ignored(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "NOTAREALEVEL")
        assert get_logger(_unique_name()).level == logging.INFO

    def test_propagate_is_false(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        assert get_logger(_unique_name()).propagate is False

    def test_has_tqdm_logging_handler(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        logger = get_logger(_unique_name())
        assert any(isinstance(h, TqdmLoggingHandler) for h in logger.handlers)

    def test_second_call_returns_same_logger(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        name = _unique_name()
        assert get_logger(name) is get_logger(name)

    def test_second_call_does_not_add_extra_handlers(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        name = _unique_name()
        get_logger(name)
        count = len(logging.getLogger(name).handlers)
        get_logger(name)
        assert len(logging.getLogger(name).handlers) == count

    def test_name_added_to_configured_loggers(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        name = _unique_name()
        get_logger(name)
        assert name in logs._configured_loggers

    def test_calls_configure_cloudwatch_with_correct_args(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        name = _unique_name()
        with patch("logs._configure_cloudwatch") as mock_cw:
            logger = get_logger(name, log_group_name="my-group", log_stream_prefix="my-prefix")
        mock_cw.assert_called_once_with(logger, name, "my-group", "my-prefix")


class TestConfigureCloudwatch:
    """Tests for _configure_cloudwatch."""

    def test_no_handler_when_env_not_set(self, monkeypatch):
        monkeypatch.delenv("CLOUDWATCH_LOGS_ENABLED", raising=False)
        logger = logging.getLogger(_unique_name())
        _configure_cloudwatch(logger, "test", "group", "prefix")
        assert not logger.handlers

    def test_no_handler_when_env_is_false(self, monkeypatch):
        monkeypatch.setenv("CLOUDWATCH_LOGS_ENABLED", "false")
        logger = logging.getLogger(_unique_name())
        _configure_cloudwatch(logger, "test", "group", "prefix")
        assert not logger.handlers

    def test_no_handler_when_log_group_empty(self, monkeypatch):
        monkeypatch.setenv("CLOUDWATCH_LOGS_ENABLED", "true")
        logger = logging.getLogger(_unique_name())
        _configure_cloudwatch(logger, "test", "", "prefix")
        assert not logger.handlers

    def test_no_handler_when_log_stream_prefix_empty(self, monkeypatch):
        monkeypatch.setenv("CLOUDWATCH_LOGS_ENABLED", "true")
        logger = logging.getLogger(_unique_name())
        _configure_cloudwatch(logger, "test", "group", "")
        assert not logger.handlers

    def test_adds_cloudwatch_handler(self, monkeypatch, cw_logger):
        monkeypatch.setenv("CLOUDWATCH_LOGS_ENABLED", "true")
        monkeypatch.setenv("AWS_REGION", REGION)
        monkeypatch.setenv("INSTANCE_ID", "i-test")
        _configure_cloudwatch(cw_logger, "test", "my-group", "my-prefix")
        assert any(isinstance(h, watchtower.CloudWatchLogHandler) for h in cw_logger.handlers)

    @pytest.mark.parametrize("val", ["true", "1", "yes"])
    def test_enabled_for_all_truthy_env_values(self, monkeypatch, cw_logger, val):
        monkeypatch.setenv("CLOUDWATCH_LOGS_ENABLED", val)
        monkeypatch.setenv("AWS_REGION", REGION)
        monkeypatch.setenv("INSTANCE_ID", "i-test")
        _configure_cloudwatch(cw_logger, "test", "my-group", "my-prefix")
        assert any(isinstance(h, watchtower.CloudWatchLogHandler) for h in cw_logger.handlers)

    def test_log_stream_name_includes_instance_id(self, monkeypatch, cw_logger):
        monkeypatch.setenv("CLOUDWATCH_LOGS_ENABLED", "true")
        monkeypatch.setenv("AWS_REGION", REGION)
        monkeypatch.setenv("INSTANCE_ID", "i-abc123")
        _configure_cloudwatch(cw_logger, "test", "my-group", "my-prefix")
        handler = next(h for h in cw_logger.handlers if isinstance(h, watchtower.CloudWatchLogHandler))
        assert "i-abc123" in handler.log_stream_name

    def test_log_stream_name_includes_prefix(self, monkeypatch, cw_logger):
        monkeypatch.setenv("CLOUDWATCH_LOGS_ENABLED", "true")
        monkeypatch.setenv("AWS_REGION", REGION)
        monkeypatch.setenv("INSTANCE_ID", "i-abc123")
        _configure_cloudwatch(cw_logger, "test", "my-group", "my-prefix")
        handler = next(h for h in cw_logger.handlers if isinstance(h, watchtower.CloudWatchLogHandler))
        assert "my-prefix" in handler.log_stream_name

    def test_uses_aws_region_env_var(self, monkeypatch, cw_logger, cw):
        monkeypatch.setenv("CLOUDWATCH_LOGS_ENABLED", "true")
        monkeypatch.setenv("AWS_REGION", REGION)
        monkeypatch.setenv("INSTANCE_ID", "i-test")
        with patch("logs.boto3.client", return_value=cw) as mock_client:
            _configure_cloudwatch(cw_logger, "test", "my-group", "my-prefix")
        mock_client.assert_called_once_with("logs", region_name=REGION)

    def test_uses_default_client_when_no_aws_region(self, monkeypatch, cw_logger, cw):
        monkeypatch.setenv("CLOUDWATCH_LOGS_ENABLED", "true")
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.setenv("INSTANCE_ID", "i-test")
        with patch("logs.boto3.client", return_value=cw) as mock_client:
            _configure_cloudwatch(cw_logger, "test", "my-group", "my-prefix")
        mock_client.assert_called_once_with("logs")
