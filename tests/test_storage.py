"""Tests for storage.py."""

import io
import json
import zipfile
from unittest.mock import patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from idi_ftm2j_shared.storage import (
    _empty_for_return_type,
    key_exists,
    load_content,
    load_json,
    open_zip,
    save_content,
    save_json,
)

BUCKET = "test-bucket"
REGION = "us-east-1"


def _make_client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "test"}}, "GetObject")


@pytest.fixture
def s3(monkeypatch):
    """Moto-backed S3; yields a boto3 client with the test bucket already created."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=BUCKET)
        yield client


def _s3(key: str) -> str:
    return f"s3://{BUCKET}/{key}"


class TestEmptyForReturnType:
    """Tests for _empty_for_return_type."""

    def test_dict_returns_empty_dict(self):
        assert _empty_for_return_type("dict") == {}

    def test_list_returns_empty_list(self):
        assert _empty_for_return_type("list") == []

    def test_invalid_type_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid return type"):
            _empty_for_return_type("set")

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError):
            _empty_for_return_type("")


class TestLoadJson:
    """Tests for load_json."""

    def test_loads_dict_from_local_file(self, tmp_path):
        data = {"key": "value", "num": 42}
        f = tmp_path / "data.json"
        f.write_text(json.dumps(data))
        assert load_json(str(f)) == data

    def test_loads_list_from_local_file(self, tmp_path):
        data = [1, 2, 3]
        f = tmp_path / "data.json"
        f.write_text(json.dumps(data))
        assert load_json(str(f), return_type="list") == data

    def test_missing_local_file_returns_empty_dict(self, tmp_path):
        assert load_json(str(tmp_path / "missing.json")) == {}

    def test_missing_local_file_returns_empty_list(self, tmp_path):
        assert load_json(str(tmp_path / "missing.json"), return_type="list") == []

    def test_invalid_return_type_raises(self, tmp_path):
        with pytest.raises(ValueError):
            load_json(str(tmp_path / "missing.json"), return_type="tuple")

    def test_invalid_json_raises_decode_error(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not valid json {{")
        with pytest.raises(json.JSONDecodeError):
            load_json(str(f))

    def test_os_error_returns_empty_dict(self):
        with patch(
            "idi_ftm2j_shared.storage.smart_open.open", side_effect=OSError("permission denied")
        ):
            assert load_json("/some/path.json") == {}

    def test_s3_loads_dict(self, s3):
        data = {"a": 1, "b": [1, 2]}
        s3.put_object(Bucket=BUCKET, Key="data.json", Body=json.dumps(data))
        assert load_json(_s3("data.json")) == data

    def test_s3_missing_key_returns_empty_dict(self, s3):
        assert load_json(_s3("missing.json")) == {}

    def test_s3_missing_key_returns_empty_list(self, s3):
        assert load_json(_s3("missing.json"), return_type="list") == []

    def test_s3_other_client_error_raises(self):
        with patch(
            "idi_ftm2j_shared.storage.smart_open.open",
            side_effect=_make_client_error("AccessDenied"),
        ):
            with pytest.raises(ClientError):
                load_json(_s3("file.json"))


class TestSaveJson:
    """Tests for save_json."""

    def test_writes_dict_to_local_file(self, tmp_path):
        data = {"x": 1}
        out = tmp_path / "out.json"
        save_json(str(out), data)
        assert json.loads(out.read_text()) == data

    def test_writes_list_to_local_file(self, tmp_path):
        data = [1, 2, 3]
        out = tmp_path / "out.json"
        save_json(str(out), data)
        assert json.loads(out.read_text()) == data

    def test_append_mode_local_file(self, tmp_path):
        out = tmp_path / "out.json"
        save_json(str(out), {"a": 1})
        save_json(str(out), {"b": 2}, mode="a")
        content = out.read_text()
        assert "a" in content
        assert "b" in content

    def test_s3_writes_dict(self, s3):
        data = {"s3": True, "count": 3}
        save_json(_s3("out.json"), data)
        body = s3.get_object(Bucket=BUCKET, Key="out.json")["Body"].read()
        assert json.loads(body) == data

    def test_s3_writes_list(self, s3):
        data = [1, 2, 3]
        save_json(_s3("out.json"), data)
        body = s3.get_object(Bucket=BUCKET, Key="out.json")["Body"].read()
        assert json.loads(body) == data

    def test_s3_overwrites_existing_key(self, s3):
        s3.put_object(Bucket=BUCKET, Key="out.json", Body=json.dumps({"old": True}))
        save_json(_s3("out.json"), {"new": True})
        body = s3.get_object(Bucket=BUCKET, Key="out.json")["Body"].read()
        assert json.loads(body) == {"new": True}


class TestKeyExists:
    """Tests for key_exists."""

    def test_existing_local_file_returns_true(self, tmp_path):
        f = tmp_path / "exists.txt"
        f.write_text("hello")
        assert key_exists(str(f)) is True

    def test_missing_local_file_returns_false(self, tmp_path):
        assert key_exists(str(tmp_path / "nope.txt")) is False

    def test_os_error_returns_false(self):
        with patch("idi_ftm2j_shared.storage.smart_open.open", side_effect=OSError("no access")):
            assert key_exists("/some/path") is False

    def test_s3_key_exists_returns_true(self, s3):
        s3.put_object(Bucket=BUCKET, Key="present.txt", Body=b"data")
        assert key_exists(_s3("present.txt")) is True

    def test_s3_missing_key_returns_false(self, s3):
        assert key_exists(_s3("absent.txt")) is False

    def test_s3_404_code_returns_false(self):
        with patch(
            "idi_ftm2j_shared.storage.smart_open.open", side_effect=_make_client_error("404")
        ):
            assert key_exists(_s3("file")) is False

    def test_s3_other_client_error_raises(self):
        with patch(
            "idi_ftm2j_shared.storage.smart_open.open",
            side_effect=_make_client_error("AccessDenied"),
        ):
            with pytest.raises(ClientError):
                key_exists(_s3("file"))


class TestLoadContent:
    """Tests for load_content."""

    def test_loads_text_from_local_file(self, tmp_path):
        f = tmp_path / "text.txt"
        f.write_text("hello world")
        assert load_content(str(f)) == "hello world"

    def test_missing_local_file_returns_empty_string(self, tmp_path):
        assert load_content(str(tmp_path / "nope.txt")) == ""

    def test_os_error_returns_empty_string(self):
        with patch("idi_ftm2j_shared.storage.smart_open.open", side_effect=OSError("boom")):
            assert load_content("/some/path") == ""

    def test_s3_loads_content(self, s3):
        s3.put_object(Bucket=BUCKET, Key="file.txt", Body=b"hello from s3")
        assert load_content(_s3("file.txt")) == "hello from s3"

    def test_s3_missing_key_returns_empty_string(self, s3):
        assert load_content(_s3("missing.txt")) == ""

    def test_s3_other_client_error_raises(self):
        with patch(
            "idi_ftm2j_shared.storage.smart_open.open",
            side_effect=_make_client_error("InternalError"),
        ):
            with pytest.raises(ClientError):
                load_content(_s3("file.txt"))


class TestSaveContent:
    """Tests for save_content."""

    def test_writes_text_to_local_file(self, tmp_path):
        out = tmp_path / "out.txt"
        save_content(str(out), "hello")
        assert out.read_text() == "hello"

    def test_overwrites_existing_local_file(self, tmp_path):
        out = tmp_path / "out.txt"
        out.write_text("old content")
        save_content(str(out), "new content")
        assert out.read_text() == "new content"

    def test_s3_writes_content(self, s3):
        save_content(_s3("file.txt"), "written via smart_open")
        body = s3.get_object(Bucket=BUCKET, Key="file.txt")["Body"].read()
        assert body.decode() == "written via smart_open"

    def test_s3_overwrites_existing_key(self, s3):
        s3.put_object(Bucket=BUCKET, Key="file.txt", Body=b"old")
        save_content(_s3("file.txt"), "new")
        body = s3.get_object(Bucket=BUCKET, Key="file.txt")["Body"].read()
        assert body.decode() == "new"

    def test_value_error_wrapped_and_reraised(self):
        with patch("idi_ftm2j_shared.storage.smart_open.open", side_effect=ValueError("bad path")):
            with pytest.raises(ValueError, match="Failed to save content"):
                save_content("/bad/path.txt", "data")


class TestOpenZip:
    """Tests for open_zip."""

    def _make_zip_bytes(self, files: dict[str, str]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        return buf.getvalue()

    def test_opens_local_zip_and_reads_file(self, tmp_path):
        zpath = tmp_path / "archive.zip"
        zpath.write_bytes(self._make_zip_bytes({"hello.txt": "hi there"}))
        with open_zip(str(zpath)) as zf:
            assert zf.read("hello.txt") == b"hi there"

    def test_local_zip_namelist(self, tmp_path):
        zpath = tmp_path / "archive.zip"
        zpath.write_bytes(self._make_zip_bytes({"a.txt": "a", "b.txt": "b"}))
        with open_zip(str(zpath)) as zf:
            assert set(zf.namelist()) == {"a.txt", "b.txt"}

    def test_bad_zip_raises_bad_zip_file(self, tmp_path):
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"not a zip file at all")
        with pytest.raises(zipfile.BadZipFile):
            with open_zip(str(bad)):
                pass

    def test_s3_zip_readable(self, s3):
        zip_bytes = self._make_zip_bytes({"data.txt": "from s3"})
        s3.put_object(Bucket=BUCKET, Key="archive.zip", Body=zip_bytes)
        with open_zip(_s3("archive.zip")) as zf:
            assert zf.read("data.txt") == b"from s3"

    def test_headers_passed_to_transport_params(self):
        zip_bytes = self._make_zip_bytes({"f.txt": "x"})
        mock_file = io.BytesIO(zip_bytes)
        captured = {}

        def fake_open(path, mode="r", transport_params=None, **kwargs):
            captured["transport_params"] = transport_params
            return mock_file

        with patch("idi_ftm2j_shared.storage.smart_open.open", side_effect=fake_open):
            with open_zip("https://example.com/file.zip", headers={"User-Agent": "test"}):
                pass

        assert captured["transport_params"] == {"headers": {"User-Agent": "test"}}

    def test_no_headers_passes_empty_transport_params(self):
        zip_bytes = self._make_zip_bytes({"f.txt": "x"})
        mock_file = io.BytesIO(zip_bytes)
        captured = {}

        def fake_open(path, mode="r", transport_params=None, **kwargs):
            captured["transport_params"] = transport_params
            return mock_file

        with patch("idi_ftm2j_shared.storage.smart_open.open", side_effect=fake_open):
            with open_zip("https://example.com/file.zip"):
                pass

        assert captured["transport_params"] == {}
