"""Tests for failures.py."""

import json
from enum import StrEnum
from unittest.mock import patch

import pytest
from failures import FailureClassifier, FailureRegistry


class SampleFailure(StrEnum):
    """Sample failure types for tests."""

    PERMANENT = "permanent"
    RETRYABLE = "retryable"


class SampleClassifier(FailureClassifier):
    """Concrete classifier that marks only PERMANENT as non-retryable."""

    @property
    def do_not_retry(self) -> frozenset:
        """Return non-retryable failure types."""
        return frozenset({SampleFailure.PERMANENT})

    def classify_from_response(self, response: dict, **kwargs: object) -> SampleFailure:
        """Classify based on presence of error key."""
        return SampleFailure.PERMANENT if response.get("error") else SampleFailure.RETRYABLE


@pytest.fixture
def classifier() -> SampleClassifier:
    """Return a SampleClassifier instance."""
    return SampleClassifier()


@pytest.fixture
def registry(classifier: SampleClassifier) -> FailureRegistry:
    """Return a FailureRegistry with an empty file_path (skips load_json)."""
    return FailureRegistry(file_path="", classifier=classifier)


class TestFailureClassifier:
    """Tests for FailureClassifier base class."""

    def test_is_retryable_true_for_retryable_type(self, classifier):
        assert classifier.is_retryable(SampleFailure.RETRYABLE) is True

    def test_is_retryable_false_for_permanent_type(self, classifier):
        assert classifier.is_retryable(SampleFailure.PERMANENT) is False

    def test_cannot_instantiate_without_implementing_abstract_methods(self):
        with pytest.raises(TypeError):
            FailureClassifier()  # type: ignore[abstract]

    def test_subclass_missing_classify_from_response_raises(self):
        class Incomplete(FailureClassifier):
            @property
            def do_not_retry(self) -> frozenset:
                """Return non-retryable types."""
                return frozenset()

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_subclass_missing_do_not_retry_raises(self):
        class Incomplete(FailureClassifier):
            def classify_from_response(self, response: dict, **kwargs: object) -> StrEnum:
                """Classify a response."""
                return SampleFailure.RETRYABLE

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]


class TestFailureRegistryInit:
    """Tests for FailureRegistry.__init__."""

    def test_file_path_stored(self, classifier):
        assert FailureRegistry("some/path.json", classifier).file_path == "some/path.json"

    def test_classifier_stored(self, classifier):
        assert FailureRegistry("", classifier)._classifier is classifier

    def test_default_flush_every_is_10(self, classifier):
        assert FailureRegistry("", classifier)._flush_every == 10

    def test_custom_flush_every_stored(self, classifier):
        assert FailureRegistry("", classifier, flush_every=5)._flush_every == 5

    def test_pending_initialises_to_zero(self, classifier):
        assert FailureRegistry("", classifier)._pending == 0

    def test_entries_initialises_empty(self, classifier):
        assert FailureRegistry("", classifier)._entries == set()

    def test_reasons_initialises_empty(self, classifier):
        assert FailureRegistry("", classifier)._reasons == {}

    def test_load_called_on_init(self, classifier):
        with patch.object(FailureRegistry, "load") as mock_load:
            FailureRegistry("", classifier)
        mock_load.assert_called_once()


class TestFailureRegistryLoad:
    """Tests for FailureRegistry.load."""

    def test_empty_file_path_skips_load_json(self, classifier):
        with patch("failures.load_json") as mock_load:
            FailureRegistry("", classifier)
        mock_load.assert_not_called()

    def test_nonexistent_local_file_skips_load_json(self, classifier, tmp_path):
        with patch("failures.load_json") as mock_load:
            r = FailureRegistry(str(tmp_path / "missing.json"), classifier)
        mock_load.assert_not_called()
        assert r._entries == set()
        assert r._reasons == {}

    def test_s3_path_calls_load_json(self, classifier):
        with patch("failures.load_json", return_value={}) as mock_load:
            FailureRegistry("s3://bucket/failures.json", classifier)
        mock_load.assert_called_once_with("s3://bucket/failures.json", return_type="dict")

    def test_existing_local_file_calls_load_json(self, classifier, tmp_path):
        f = tmp_path / "failures.json"
        f.write_text("{}")
        with patch("failures.load_json", return_value={}) as mock_load:
            FailureRegistry(str(f), classifier)
        mock_load.assert_called_once()

    def test_json_decode_error_resets_to_empty(self, classifier, tmp_path):
        f = tmp_path / "failures.json"
        f.write_text("bad json")
        with patch("failures.load_json", side_effect=json.JSONDecodeError("msg", "doc", 0)):
            r = FailureRegistry(str(f), classifier)
        assert r._entries == set()
        assert r._reasons == {}

    def test_non_dict_data_resets_to_empty(self, classifier, tmp_path):
        f = tmp_path / "failures.json"
        f.write_text("[]")
        with patch("failures.load_json", return_value=[]):
            r = FailureRegistry(str(f), classifier)
        assert r._entries == set()
        assert r._reasons == {}

    def test_loads_entries_from_valid_data(self, classifier, tmp_path):
        f = tmp_path / "failures.json"
        f.write_text("{}")
        data = {"entries": [["id1", "file1"], ["id2", "file2"]], "reasons": {}}
        with patch("failures.load_json", return_value=data):
            r = FailureRegistry(str(f), classifier)
        assert ("id1", "file1") in r._entries
        assert ("id2", "file2") in r._entries

    def test_filters_entries_shorter_than_min_length(self, classifier, tmp_path):
        f = tmp_path / "failures.json"
        f.write_text("{}")
        data = {"entries": [["id1"], ["id2", "file2"]], "reasons": {}}
        with patch("failures.load_json", return_value=data):
            r = FailureRegistry(str(f), classifier)
        assert len(r._entries) == 1
        assert ("id2", "file2") in r._entries

    def test_loads_reasons_keyed_by_space_joined_entry(self, classifier, tmp_path):
        f = tmp_path / "failures.json"
        f.write_text("{}")
        data = {
            "entries": [["id1", "file1"]],
            "reasons": {"id1 file1": "permanent"},
        }
        with patch("failures.load_json", return_value=data):
            r = FailureRegistry(str(f), classifier)
        assert r._reasons[("id1", "file1")] == "permanent"

    def test_entry_without_matching_reason_excluded_from_reasons(self, classifier, tmp_path):
        f = tmp_path / "failures.json"
        f.write_text("{}")
        data = {"entries": [["id1", "file1"]], "reasons": {}}
        with patch("failures.load_json", return_value=data):
            r = FailureRegistry(str(f), classifier)
        assert ("id1", "file1") not in r._reasons

    def test_missing_entries_key_results_in_empty(self, classifier, tmp_path):
        f = tmp_path / "failures.json"
        f.write_text("{}")
        with patch("failures.load_json", return_value={}):
            r = FailureRegistry(str(f), classifier)
        assert r._entries == set()

    def test_load_can_be_called_again_to_reload(self, registry, tmp_path):
        f = tmp_path / "failures.json"
        f.write_text("{}")
        data = {"entries": [["id1", "file1"]], "reasons": {}}
        with patch("failures.load_json", return_value=data):
            registry.file_path = str(f)
            registry.load()
        assert ("id1", "file1") in registry._entries


class TestFailureRegistrySave:
    """Tests for FailureRegistry.save."""

    def test_no_op_when_file_path_empty(self, registry):
        with patch("failures.save_json") as mock_save:
            registry.save()
        mock_save.assert_not_called()

    def test_calls_save_json_with_file_path(self, registry):
        registry.file_path = "output.json"
        with patch("failures.save_json") as mock_save:
            registry.save()
        assert mock_save.call_args.args[0] == "output.json"

    def test_entries_serialised_as_lists(self, registry):
        registry.file_path = "output.json"
        registry._entries = {("id1", "file1"), ("id2", "file2")}
        with patch("failures.save_json") as mock_save:
            registry.save()
        saved = mock_save.call_args.args[1]
        assert sorted(saved["entries"]) == [["id1", "file1"], ["id2", "file2"]]

    def test_reasons_keyed_by_space_joined_entry(self, registry):
        registry.file_path = "output.json"
        registry._entries = {("id1", "file1")}
        registry._reasons = {("id1", "file1"): "permanent"}
        with patch("failures.save_json") as mock_save:
            registry.save()
        saved = mock_save.call_args.args[1]
        assert saved["reasons"] == {"id1 file1": "permanent"}

    def test_entry_with_no_reason_saved_as_empty_string(self, registry):
        registry.file_path = "output.json"
        registry._entries = {("id1", "file1")}
        registry._reasons = {}
        with patch("failures.save_json") as mock_save:
            registry.save()
        saved = mock_save.call_args.args[1]
        assert saved["reasons"]["id1 file1"] == ""


class TestFailureRegistryAdd:
    """Tests for FailureRegistry.add."""

    def test_retryable_failure_not_added(self, registry):
        registry.add(("id1", "file1"), SampleFailure.RETRYABLE)
        assert ("id1", "file1") not in registry._entries

    def test_permanent_failure_added_to_entries(self, registry):
        registry.add(("id1", "file1"), SampleFailure.PERMANENT)
        assert ("id1", "file1") in registry._entries

    def test_permanent_failure_reason_stored(self, registry):
        registry.add(("id1", "file1"), SampleFailure.PERMANENT)
        assert registry._reasons[("id1", "file1")] == str(SampleFailure.PERMANENT)

    def test_duplicate_not_added_twice(self, registry):
        registry.add(("id1", "file1"), SampleFailure.PERMANENT)
        registry.add(("id1", "file1"), SampleFailure.PERMANENT)
        assert len(registry._entries) == 1

    def test_pending_increments_for_new_permanent(self, registry):
        registry.add(("id1", "file1"), SampleFailure.PERMANENT)
        assert registry._pending == 1

    def test_pending_does_not_increment_for_retryable(self, registry):
        registry.add(("id1", "file1"), SampleFailure.RETRYABLE)
        assert registry._pending == 0

    def test_pending_does_not_increment_for_duplicate(self, registry):
        registry.add(("id1", "file1"), SampleFailure.PERMANENT)
        registry.add(("id1", "file1"), SampleFailure.PERMANENT)
        assert registry._pending == 1

    def test_flush_called_when_pending_reaches_flush_every(self, classifier):
        r = FailureRegistry("", classifier, flush_every=3)
        with patch.object(r, "flush") as mock_flush:
            r.add(("id1", "f"), SampleFailure.PERMANENT)
            r.add(("id2", "f"), SampleFailure.PERMANENT)
            mock_flush.assert_not_called()
            r.add(("id3", "f"), SampleFailure.PERMANENT)
        mock_flush.assert_called_once()

    def test_flush_not_called_before_threshold(self, classifier):
        r = FailureRegistry("", classifier, flush_every=5)
        with patch.object(r, "flush") as mock_flush:
            for i in range(4):
                r.add((f"id{i}", "f"), SampleFailure.PERMANENT)
        mock_flush.assert_not_called()

    def test_pending_reset_to_zero_after_auto_flush(self, classifier):
        r = FailureRegistry("", classifier, flush_every=2)
        r.add(("id1", "f"), SampleFailure.PERMANENT)
        r.add(("id2", "f"), SampleFailure.PERMANENT)
        assert r._pending == 0


class TestFailureRegistryFlush:
    """Tests for FailureRegistry.flush."""

    def test_flush_calls_save(self, registry):
        with patch.object(registry, "save") as mock_save:
            registry.flush()
        mock_save.assert_called_once()

    def test_flush_resets_pending_to_zero(self, registry):
        registry._pending = 7
        registry.flush()
        assert registry._pending == 0

    def test_flush_resets_pending_regardless_of_value(self, registry):
        registry._pending = 0
        registry.flush()
        assert registry._pending == 0


class TestFailureRegistryContains:
    """Tests for FailureRegistry.__contains__."""

    def test_returns_true_for_present_key(self, registry):
        registry._entries.add(("id1", "file1"))
        assert ("id1", "file1") in registry

    def test_returns_false_for_absent_key(self, registry):
        assert ("id1", "file1") not in registry

    def test_false_after_retryable_add(self, registry):
        registry.add(("id1", "file1"), SampleFailure.RETRYABLE)
        assert ("id1", "file1") not in registry

    def test_true_after_permanent_add(self, registry):
        registry.add(("id1", "file1"), SampleFailure.PERMANENT)
        assert ("id1", "file1") in registry
