"""
Tests de forge_test.public.helpers.forge_case, exécutés via pytest-django
contre un vrai environnement Django (settings minimal en mémoire).

Run : uv run pytest
"""
from __future__ import annotations

import unittest
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from forge_test.public.helpers.forge_case import (
    ForgeCase,
    _append_query_string,
    _parse_response_json,
    _resolve_nested_field,
    _safe_response_body,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers de test
# ---------------------------------------------------------------------------

def _make_response(json_data: Any = None, status: int = 200, content: bytes = b"") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.content = content
    if json_data is not None:
        r.json.return_value = json_data
    else:
        r.json.side_effect = ValueError("no JSON")
    return r


def _make_forge_case() -> ForgeCase:
    """Instancie ForgeCase sans setUp Django, avec les assert* d'un vrai TestCase."""
    instance = ForgeCase.__new__(ForgeCase)
    real = unittest.TestCase()
    for name in ("assertEqual", "assertIsNone", "assertIsNotNone", "assertIsInstance", "assertIsNot"):
        setattr(instance, name, getattr(real, name))
    return instance


# ---------------------------------------------------------------------------
# _resolve_nested_field
# ---------------------------------------------------------------------------

class TestResolveNestedField(unittest.TestCase):

    def test_flat_field_found(self) -> None:
        self.assertEqual(_resolve_nested_field({"id": 1}, "id"), 1)

    def test_flat_field_missing_returns_default(self) -> None:
        self.assertIsNone(_resolve_nested_field({"id": 1}, "name"))

    def test_custom_default_returned_when_missing(self) -> None:
        sentinel = object()
        self.assertIs(_resolve_nested_field({"id": 1}, "name", default=sentinel), sentinel)

    def test_nested_two_levels(self) -> None:
        data = {"user": {"profile": {"age": 30}}}
        self.assertEqual(_resolve_nested_field(data, "user.profile.age"), 30)

    def test_list_index_access(self) -> None:
        data = {"results": [{"name": "Alice"}, {"name": "Bob"}]}
        self.assertEqual(_resolve_nested_field(data, "results.0.name"), "Alice")
        self.assertEqual(_resolve_nested_field(data, "results.1.name"), "Bob")

    def test_list_index_out_of_range_returns_default(self) -> None:
        data = {"results": [{"name": "Alice"}]}
        self.assertIsNone(_resolve_nested_field(data, "results.5.name"))

    def test_list_non_numeric_index_returns_default(self) -> None:
        data = {"results": [{"name": "Alice"}]}
        self.assertIsNone(_resolve_nested_field(data, "results.abc.name"))

    def test_top_level_list(self) -> None:
        data = [{"id": 1}, {"id": 2}]
        self.assertEqual(_resolve_nested_field(data, "0.id"), 1)

    def test_intermediate_primitive_returns_default(self) -> None:
        data = {"user": "string"}
        self.assertIsNone(_resolve_nested_field(data, "user.name"))


# ---------------------------------------------------------------------------
# _parse_response_json / _safe_response_body / _append_query_string
# ---------------------------------------------------------------------------

class TestParseResponseJson(unittest.TestCase):

    def test_valid_json(self) -> None:
        r = _make_response(json_data={"id": 1})
        self.assertEqual(_parse_response_json(r), {"id": 1})

    def test_invalid_json_returns_none(self) -> None:
        r = _make_response(json_data=None)
        self.assertIsNone(_parse_response_json(r))


class TestSafeResponseBody(unittest.TestCase):

    def test_json_preferred(self) -> None:
        r = _make_response(json_data={"error": "bad"})
        self.assertIn("bad", _safe_response_body(r))

    def test_falls_back_to_content(self) -> None:
        r = _make_response(json_data=None, content=b"raw error")
        self.assertIn("raw error", _safe_response_body(r))


class TestAppendQueryString(unittest.TestCase):

    def test_dict_query(self) -> None:
        url = _append_query_string("/api/", {"page": 2})
        self.assertIn("page=2", url)

    def test_string_query(self) -> None:
        self.assertEqual(_append_query_string("/api/", "page=1"), "/api/?page=1")


# ---------------------------------------------------------------------------
# _resolve_kwargs — lambdas
# ---------------------------------------------------------------------------

class TestResolveKwargs(unittest.TestCase):

    def _case_with_user(self, pk: int = 42) -> ForgeCase:
        case = _make_forge_case()
        case.user = MagicMock()
        case.user.pk = pk
        return case

    def test_lambda_is_called_with_self(self) -> None:
        case = self._case_with_user(pk=42)
        result = case._resolve_kwargs({"pk": lambda t: t.user.pk})
        self.assertEqual(result["pk"], 42)

    def test_literal_value_passthrough(self) -> None:
        case = _make_forge_case()
        result = case._resolve_kwargs({"pk": 999999})
        self.assertEqual(result["pk"], 999999)

    def test_mixed_lambda_and_literal(self) -> None:
        case = self._case_with_user(pk=7)
        result = case._resolve_kwargs({"pk": lambda t: t.user.pk, "slug": "fixed-slug"})
        self.assertEqual(result, {"pk": 7, "slug": "fixed-slug"})

    def test_lambda_attribute_error_raises_explicit_message(self) -> None:
        case = _make_forge_case()
        with self.assertRaises(AttributeError) as ctx:
            case._resolve_kwargs({"pk": lambda t: t.missing_obj.pk})
        self.assertIn("pk", str(ctx.exception))
        self.assertIn("object_name", str(ctx.exception))

    def test_nested_lambda_attribute(self) -> None:
        case = _make_forge_case()
        case.group = MagicMock()
        case.group.owner.pk = 5
        result = case._resolve_kwargs({"pk": lambda t: t.group.owner.pk})
        self.assertEqual(result["pk"], 5)


# ---------------------------------------------------------------------------
# _resolve_fixture_instance
# ---------------------------------------------------------------------------

class TestResolveFixtureInstance(unittest.TestCase):

    def _case(self) -> ForgeCase:
        case = _make_forge_case()
        case.factory = MagicMock()
        return case

    def test_stores_instance_under_object_name(self) -> None:
        case = self._case()
        fake_instance = MagicMock()
        case.factory.create.return_value = fake_instance

        case._resolve_fixture_instance({"model": MagicMock(), "object_name": "group"})

        self.assertIs(case.group, fake_instance)

    def test_data_overrides_factory_create(self) -> None:
        case = self._case()
        existing = MagicMock()

        case._resolve_fixture_instance({"model": MagicMock(), "data": existing, "object_name": "item"})

        case.factory.create.assert_not_called()
        self.assertIs(case.item, existing)


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

class TestAssertions(unittest.TestCase):

    def _case(self) -> ForgeCase:
        return _make_forge_case()

    def test_assert_status_code_passes(self) -> None:
        self._case()._assert_status_code(_make_response(status=200), 200)

    def test_assert_status_code_fails(self) -> None:
        with self.assertRaises(AssertionError):
            self._case()._assert_status_code(_make_response(status=404), 200)

    def test_assert_fields_present_with_list_path(self) -> None:
        case = self._case()
        data = {"results": [{"pk": 1, "name": "Alice"}]}
        case._assert_fields_present(data, ["results.0.pk", "results.0.name"])

    def test_assert_fields_present_fails_on_missing_nested(self) -> None:
        case = self._case()
        data = {"results": [{"pk": 1}]}
        with self.assertRaises(AssertionError):
            case._assert_fields_present(data, ["results.0.name"])

    def test_assert_field_values_nested_list(self) -> None:
        case = self._case()
        data = {"results": [{"status": "active"}]}
        case._assert_field_values(data, {"results.0.status": "active"})

    def test_assert_field_types_passes(self) -> None:
        case = self._case()
        case._assert_field_types({"id": 1}, {"id": int})

    def test_assert_fields_absent_passes(self) -> None:
        case = self._case()
        case._assert_fields_absent({"id": 1}, ["password"])

    def test_assert_fields_absent_fails_when_present(self) -> None:
        case = self._case()
        with self.assertRaises(AssertionError):
            case._assert_fields_absent({"password": "hash"}, ["password"])

    def test_assert_response_type_passes(self) -> None:
        case = self._case()
        r = MagicMock()
        r.data = {"id": 1}
        case._assert_response_type(r, dict)

    def test_assert_response_type_fails(self) -> None:
        case = self._case()
        r = MagicMock()
        r.data = [1, 2, 3]
        with self.assertRaises(AssertionError):
            case._assert_response_type(r, dict)

    def test_assert_response_body_orchestrates_all_checks(self) -> None:
        case = self._case()
        r = _make_response(json_data={"id": 1, "name": "Alice", "role": "admin"})
        case._assert_response_body(r, {
            "expected_fields": ["id", "name"],
            "expected_value_of_fields": {"role": "admin"},
            "expected_type_of_fields": {"id": int},
            "forbidden_fields": ["password"],
        })

    def test_assert_response_body_skips_when_no_json(self) -> None:
        case = self._case()
        r = _make_response(json_data=None)
        case._assert_response_body(r, {"expected_fields": ["id"]})


# ---------------------------------------------------------------------------
# Validation de config
# ---------------------------------------------------------------------------

class TestValidateConfig(unittest.TestCase):

    def test_missing_object_name_raises(self) -> None:
        with self.assertRaises(TypeError):
            class Sub(ForgeCase):
                config = {"tests": [{"fixture": {"model": MagicMock()}}]}

    def test_object_name_present_does_not_raise(self) -> None:
        class Sub(ForgeCase):
            config = {"tests": [{"fixture": {"model": MagicMock(), "object_name": "x"}, "expected_responses": {}}]}
        self.assertTrue(hasattr(Sub, "config"))

    def test_no_config_does_not_crash(self) -> None:
        class Sub(ForgeCase):
            pass
        self.assertTrue(True)

    def test_tests_not_list_raises(self) -> None:
        with self.assertRaises(TypeError):
            class Sub(ForgeCase):
                config = {"tests": "not-a-list"}


# ---------------------------------------------------------------------------
# Génération de tests : scénarios multiples par status code
# ---------------------------------------------------------------------------

class TestScenarioGeneration(unittest.TestCase):

    def test_single_dict_scenario_generates_one_test(self) -> None:
        class Sub(ForgeCase):
            config = {
                "tests": [
                    {"path_name": "x:y", "method": "GET", "expected_responses": {200: {"authenticated": True}}}
                ]
            }
        attached = [m for m in dir(Sub) if m.startswith("test_get_x_y_success")]
        self.assertEqual(len(attached), 1)
        self.assertTrue(attached[0].endswith("_0"))

    def test_list_of_scenarios_generates_one_test_per_scenario(self) -> None:
        class Sub(ForgeCase):
            config = {
                "tests": [
                    {
                        "path_name": "x:y",
                        "method": "GET",
                        "expected_responses": {
                            404: [
                                {"authenticated": True, "reverse_params": {"kwargs": {"pk": 999999}}},
                                {"authenticated": False},
                            ]
                        },
                    }
                ]
            }
        attached = sorted(m for m in dir(Sub) if "not_found" in m)
        self.assertEqual(len(attached), 2)
        self.assertTrue(attached[0].endswith("_0"))
        self.assertTrue(attached[1].endswith("_1"))

    def test_multiple_status_codes_each_get_own_tests(self) -> None:
        class Sub(ForgeCase):
            config = {
                "tests": [
                    {
                        "path_name": "x:y",
                        "method": "GET",
                        "expected_responses": {
                            200: {"authenticated": True},
                            401: {"authenticated": False},
                        },
                    }
                ]
            }
        attached = [m for m in dir(Sub) if m.startswith("test_get_x_y")]
        self.assertEqual(len(attached), 2)

    def test_test_name_uses_custom_test_name_field(self) -> None:
        class Sub(ForgeCase):
            config = {
                "tests": [
                    {
                        "test_name": "users_list",
                        "path_name": "x:y",
                        "method": "GET",
                        "expected_responses": {200: {"authenticated": True}},
                    }
                ]
            }
        attached = [m for m in dir(Sub) if "users_list" in m]
        self.assertEqual(len(attached), 1)


# ---------------------------------------------------------------------------
# Intégration : un scénario complet via _build_single_test
# ---------------------------------------------------------------------------

class TestBuildSingleTestIntegration(unittest.TestCase):

    def test_full_scenario_runs_request_and_assertions(self) -> None:
        test_config: Dict[str, Any] = {
            "path_name": "x:y",
            "method": "GET",
            "fixture": {"model": MagicMock(), "object_name": "obj"},
            "reverse_params": {"kwargs": {"pk": lambda t: t.obj.pk}},
        }
        scenario: Dict[str, Any] = {"authenticated": False, "expected_fields": ["id"]}

        test_func = ForgeCase._build_single_test(test_config, scenario, 200)

        case = _make_forge_case()
        case.factory = MagicMock()
        fake_obj = MagicMock()
        fake_obj.pk = 10
        case.factory.create.return_value = fake_obj

        fake_client = MagicMock()
        fake_response = _make_response(json_data={"id": 1}, status=200)
        fake_client.get = MagicMock(return_value=fake_response)
        case._resolve_client = MagicMock(return_value=fake_client)

        with patch("forge_test.public.helpers.forge_case.reverse", return_value="/fake/10/"):
            test_func(case)

        self.assertIs(case.obj, fake_obj)
        fake_client.get.assert_called_once()
