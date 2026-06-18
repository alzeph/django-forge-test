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
    instance = ForgeCase.__new__(ForgeCase)
    real = unittest.TestCase()
    for name in ("assertEqual", "assertIsNone", "assertIsNotNone", "assertIsInstance", "assertIsNot"):
        setattr(instance, name, getattr(real, name))
    return instance


# ---------------------------------------------------------------------------
# _resolve_value — fonction centrale
# ---------------------------------------------------------------------------

class TestResolveValue(unittest.TestCase):

    def _case(self) -> ForgeCase:
        return _make_forge_case()

    def test_literal_int_returned_as_is(self) -> None:
        case = self._case()
        self.assertEqual(case._resolve_value("ctx", 42), 42)

    def test_literal_str_returned_as_is(self) -> None:
        case = self._case()
        self.assertEqual(case._resolve_value("ctx", "active"), "active")

    def test_literal_dict_returned_as_is(self) -> None:
        case = self._case()
        d = {"key": "val"}
        self.assertIs(case._resolve_value("ctx", d), d)

    def test_literal_none_returned_as_is(self) -> None:
        case = self._case()
        self.assertIsNone(case._resolve_value("ctx", None))

    def test_lambda_called_with_self(self) -> None:
        case = self._case()
        case.user = MagicMock()
        case.user.pk = 7
        result = case._resolve_value("ctx", lambda t: t.user.pk)
        self.assertEqual(result, 7)

    def test_lambda_attribute_error_raises_with_context(self) -> None:
        case = self._case()
        with self.assertRaises(AttributeError) as ctx:
            case._resolve_value("fixture.kwargs['owner']", lambda t: t.missing)
        self.assertIn("fixture.kwargs['owner']", str(ctx.exception))

    def test_lambda_returning_none_is_valid(self) -> None:
        case = self._case()
        result = case._resolve_value("ctx", lambda t: None)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# _resolve_dict_values
# ---------------------------------------------------------------------------

class TestResolveDictValues(unittest.TestCase):

    def _case(self) -> ForgeCase:
        case = _make_forge_case()
        case.user = MagicMock()
        case.user.pk = 5
        return case

    def test_all_literals(self) -> None:
        case = self._case()
        result = case._resolve_dict_values("ctx", {"a": 1, "b": "x"})
        self.assertEqual(result, {"a": 1, "b": "x"})

    def test_all_lambdas(self) -> None:
        case = self._case()
        result = case._resolve_dict_values("ctx", {"pk": lambda t: t.user.pk})
        self.assertEqual(result["pk"], 5)

    def test_mixed(self) -> None:
        case = self._case()
        result = case._resolve_dict_values("ctx", {
            "pk": lambda t: t.user.pk,
            "status": "active",
        })
        self.assertEqual(result["pk"], 5)
        self.assertEqual(result["status"], "active")

    def test_error_includes_key_and_context(self) -> None:
        case = self._case()
        with self.assertRaises(AttributeError) as ctx:
            case._resolve_dict_values("fixture.kwargs", {"owner": lambda t: t.missing})
        self.assertIn("fixture.kwargs", str(ctx.exception))
        self.assertIn("owner", str(ctx.exception))


# ---------------------------------------------------------------------------
# _resolve_fixture_instance — fixture.kwargs et fixture.data comme LazyValue
# ---------------------------------------------------------------------------

class TestResolveFixtureInstance(unittest.TestCase):

    def _case(self) -> ForgeCase:
        case = _make_forge_case()
        case.factory = MagicMock()
        case.factory.create.return_value = MagicMock()
        return case

    def test_kwargs_literal_passed_to_create(self) -> None:
        case = self._case()
        case._resolve_fixture_instance({
            "model": MagicMock(), "object_name": "obj",
            "kwargs": {"status": "active"},
        })
        _, kwargs = case.factory.create.call_args
        self.assertEqual(kwargs["status"], "active")

    def test_kwargs_lambda_resolved_before_create(self) -> None:
        case = self._case()
        case.user = MagicMock()
        case._resolve_fixture_instance({
            "model": MagicMock(), "object_name": "obj",
            "kwargs": {"owner": lambda t: t.user},
        })
        _, kwargs = case.factory.create.call_args
        self.assertIs(kwargs["owner"], case.user)

    def test_data_literal_instance_stored(self) -> None:
        case = self._case()
        existing = MagicMock()
        case._resolve_fixture_instance({
            "model": MagicMock(), "object_name": "item", "data": existing,
        })
        case.factory.create.assert_not_called()
        self.assertIs(case.item, existing)

    def test_data_lambda_resolved_and_stored(self) -> None:
        case = self._case()
        target = MagicMock()
        case.other = target
        case._resolve_fixture_instance({
            "model": MagicMock(), "object_name": "item",
            "data": lambda t: t.other,
        })
        case.factory.create.assert_not_called()
        self.assertIs(case.item, target)

    def test_data_dict_with_lambdas_resolved(self) -> None:
        case = self._case()
        case.user = MagicMock()
        case.user.email = "a@b.com"
        case._resolve_fixture_instance({
            "model": MagicMock(), "object_name": "item",
            "data": {"email": lambda t: t.user.email, "role": "admin"},
        })
        case.factory.create.assert_not_called()
        self.assertEqual(case.item, {"email": "a@b.com", "role": "admin"})

    def test_object_name_stored_on_self(self) -> None:
        case = self._case()
        fake = MagicMock()
        case.factory.create.return_value = fake
        case._resolve_fixture_instance({
            "model": MagicMock(), "object_name": "group",
        })
        self.assertIs(case.group, fake)


# ---------------------------------------------------------------------------
# _resolve_fixture_json_data — FixtureJson.data comme LazyValue
# ---------------------------------------------------------------------------

class TestResolveFixtureJsonData(unittest.TestCase):

    def _case(self) -> ForgeCase:
        case = _make_forge_case()
        case.factory = MagicMock()
        case.factory.generate_fields_dict.return_value = {"generated": True}
        return case

    def test_data_literal_dict_returned_as_is(self) -> None:
        case = self._case()
        result = case._resolve_fixture_json_data({"data": {"name": "Alice"}})
        self.assertEqual(result, {"name": "Alice"})

    def test_data_dict_with_lambda_resolved(self) -> None:
        case = self._case()
        case.user = MagicMock()
        case.user.email = "x@y.com"
        result = case._resolve_fixture_json_data({
            "data": {"email": lambda t: t.user.email, "role": "admin"},
        })
        self.assertEqual(result, {"email": "x@y.com", "role": "admin"})

    def test_no_data_delegates_to_factory(self) -> None:
        case = self._case()
        result = case._resolve_fixture_json_data({"model": MagicMock(), "fields": ["name"]})
        case.factory.generate_fields_dict.assert_called_once()
        self.assertEqual(result, {"generated": True})


# ---------------------------------------------------------------------------
# _assert_field_values — expected_value_of_fields comme LazyValue
# ---------------------------------------------------------------------------

class TestAssertFieldValuesLazy(unittest.TestCase):

    def _case(self) -> ForgeCase:
        return _make_forge_case()

    def test_literal_expected_value(self) -> None:
        case = self._case()
        case._assert_field_values({"status": "active"}, {"status": "active"})

    def test_lambda_expected_value(self) -> None:
        case = self._case()
        case.user = MagicMock()
        case.user.pk = 42
        case._assert_field_values({"owner_id": 42}, {"owner_id": lambda t: t.user.pk})

    def test_lambda_expected_value_mismatch_raises(self) -> None:
        case = self._case()
        case.user = MagicMock()
        case.user.pk = 99
        with self.assertRaises(AssertionError):
            case._assert_field_values({"owner_id": 42}, {"owner_id": lambda t: t.user.pk})


# ---------------------------------------------------------------------------
# _resolve_url — reverse_params.kwargs comme LazyValue (déjà couvert, régression)
# ---------------------------------------------------------------------------

class TestResolveUrl(unittest.TestCase):

    def _case_with_user(self, pk: int = 42) -> ForgeCase:
        case = _make_forge_case()
        case.user = MagicMock()
        case.user.pk = pk
        return case

    def test_lambda_in_reverse_kwargs(self) -> None:
        case = self._case_with_user(pk=7)
        with patch("forge_test.public.helpers.forge_case.reverse", return_value="/x/7/") as mock_reverse:
            url = case._resolve_url(
                {"path_name": "x:y", "reverse_params": {"kwargs": {"pk": lambda t: t.user.pk}}}
            )
        mock_reverse.assert_called_once_with("x:y", kwargs={"pk": 7})
        self.assertEqual(url, "/x/7/")

    def test_literal_in_reverse_kwargs(self) -> None:
        case = _make_forge_case()
        with patch("forge_test.public.helpers.forge_case.reverse", return_value="/x/99/") as mock_reverse:
            case._resolve_url({"path_name": "x:y", "reverse_params": {"kwargs": {"pk": 99}}})
        mock_reverse.assert_called_once_with("x:y", kwargs={"pk": 99})

    def test_scenario_reverse_params_override_test_level(self) -> None:
        case = _make_forge_case()
        with patch("forge_test.public.helpers.forge_case.reverse", return_value="/x/999/") as mock_reverse:
            case._resolve_url(
                {"path_name": "x:y", "reverse_params": {"kwargs": {"pk": 1}}},
                scenario_reverse_params={"kwargs": {"pk": 999}},
            )
        mock_reverse.assert_called_once_with("x:y", kwargs={"pk": 999})


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

    def test_no_config_does_not_crash(self) -> None:
        class Sub(ForgeCase):
            pass

    def test_tests_not_list_raises(self) -> None:
        with self.assertRaises(TypeError):
            class Sub(ForgeCase):
                config = {"tests": "not-a-list"}


# ---------------------------------------------------------------------------
# Génération de tests
# ---------------------------------------------------------------------------

class TestScenarioGeneration(unittest.TestCase):

    def test_single_dict_generates_one_test(self) -> None:
        class Sub(ForgeCase):
            config = {"tests": [
                {"path_name": "x:y", "method": "GET", "expected_responses": {200: {"authenticated": True}}}
            ]}
        attached = [m for m in dir(Sub) if m.startswith("test_get_x_y_success")]
        self.assertEqual(len(attached), 1)

    def test_list_of_scenarios_generates_multiple_tests(self) -> None:
        class Sub(ForgeCase):
            config = {"tests": [
                {"path_name": "x:y", "method": "GET", "expected_responses": {
                    404: [{"authenticated": True}, {"authenticated": False}]
                }}
            ]}
        attached = sorted(m for m in dir(Sub) if "not_found" in m)
        self.assertEqual(len(attached), 2)
        self.assertTrue(attached[0].endswith("_0"))
        self.assertTrue(attached[1].endswith("_1"))

    def test_custom_test_name_used(self) -> None:
        class Sub(ForgeCase):
            config = {"tests": [
                {"test_name": "users_list", "path_name": "x:y", "method": "GET",
                 "expected_responses": {200: {}}}
            ]}
        self.assertTrue(any("users_list" in m for m in dir(Sub)))


# ---------------------------------------------------------------------------
# Helpers module-level
# ---------------------------------------------------------------------------

class TestResolveNestedField(unittest.TestCase):

    def test_flat(self) -> None:
        self.assertEqual(_resolve_nested_field({"id": 1}, "id"), 1)

    def test_nested(self) -> None:
        self.assertEqual(_resolve_nested_field({"a": {"b": 2}}, "a.b"), 2)

    def test_list_index(self) -> None:
        self.assertEqual(_resolve_nested_field([{"id": 1}], "0.id"), 1)

    def test_missing_returns_default(self) -> None:
        sentinel = object()
        self.assertIs(_resolve_nested_field({}, "x", default=sentinel), sentinel)

    def test_out_of_range_returns_default(self) -> None:
        self.assertIsNone(_resolve_nested_field([], "0"))


class TestParseResponseJson(unittest.TestCase):

    def test_valid(self) -> None:
        r = _make_response(json_data={"id": 1})
        self.assertEqual(_parse_response_json(r), {"id": 1})

    def test_invalid_returns_none(self) -> None:
        r = _make_response(json_data=None)
        self.assertIsNone(_parse_response_json(r))


class TestAppendQueryString(unittest.TestCase):

    def test_dict(self) -> None:
        self.assertIn("page=2", _append_query_string("/api/", {"page": 2}))

    def test_string(self) -> None:
        self.assertEqual(_append_query_string("/api/", "page=1"), "/api/?page=1")


# ---------------------------------------------------------------------------
# Intégration : scénario complet
# ---------------------------------------------------------------------------

class TestBuildSingleTestIntegration(unittest.TestCase):

    def test_full_scenario_with_lambda_kwargs_and_expected_value(self) -> None:
        test_config: Dict[str, Any] = {
            "path_name": "x:y",
            "method": "GET",
            "fixture": {
                "model": MagicMock(), "object_name": "obj",
                "kwargs": {"owner": lambda t: t.user},
            },
            "reverse_params": {"kwargs": {"pk": lambda t: t.obj.pk}},
        }
        scenario: Dict[str, Any] = {
            "authenticated": False,
            "expected_fields": ["id"],
            "expected_value_of_fields": {"owner_id": lambda t: t.user.pk},
        }

        test_func = ForgeCase._build_single_test(test_config, scenario, 200)

        case = _make_forge_case()
        case.factory = MagicMock()
        fake_obj = MagicMock()
        fake_obj.pk = 10
        case.factory.create.return_value = fake_obj
        case.user = MagicMock()
        case.user.pk = 42

        fake_client = MagicMock()
        fake_response = _make_response(json_data={"id": 1, "owner_id": 42}, status=200)
        fake_client.get = MagicMock(return_value=fake_response)
        case._resolve_client = MagicMock(return_value=fake_client)

        with patch("forge_test.public.helpers.forge_case.reverse", return_value="/fake/10/"):
            test_func(case)

        self.assertIs(case.obj, fake_obj)
        _, factory_kwargs = case.factory.create.call_args
        self.assertIs(factory_kwargs["owner"], case.user)
        fake_client.get.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)