"""
Tests de forge_test.public.helpers.forge_case.

Couvre l'intégralité de l'API publique et interne :
    - _resolve_value / _resolve_dict_values  (résolution universelle des lambdas)
    - _resolve_fixture_instance              (fixture.kwargs / fixture.data)
    - _resolve_fixtures                      (fixture unique ou liste)
    - _resolve_fixture_json_data             (FixtureJson.data)
    - _extract_request_data                  (http_client_params.fixture unique ou liste fusionnée)
    - _resolve_url                            (reverse_params.kwargs avec lambdas, fusion scénario)
    - _build_authenticated_client            (auth_backend dans config)
    - _assert_*                              (status, fields, values, types, absent, response type)
    - _assert_field_values                   (expected_value_of_fields avec lambdas)
    - _build_single_test / pre_test          (ordre d'exécution, mutation de self)
    - _attach_all_tests / _normalize_scenarios  (génération, nommage, scénarios multiples)
    - _validate_config                       (fixture liste, object_name manquant)
    - helpers module-level                   (_resolve_nested_field, _parse_response_json, etc.)

Run : uv run pytest tests/test_forge_case.py -v
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
    """Instancie ForgeCase sans setUp Django avec les assert* d'un vrai TestCase."""
    instance = ForgeCase.__new__(ForgeCase)
    instance.config = {}
    real = unittest.TestCase()
    for name in ("assertEqual", "assertIsNone", "assertIsNotNone", "assertIsInstance", "assertIsNot"):
        setattr(instance, name, getattr(real, name))
    return instance


def _make_fake_client(response: MagicMock, method: str = "get") -> MagicMock:
    client = MagicMock()
    getattr(client, method).__name__ = method
    setattr(client, method, MagicMock(return_value=response))
    return client


# ---------------------------------------------------------------------------
# _resolve_value
# ---------------------------------------------------------------------------

class TestResolveValue(unittest.TestCase):

    def _case(self) -> ForgeCase:
        return _make_forge_case()

    def test_literal_int_passthrough(self) -> None:
        self.assertEqual(self._case()._resolve_value("ctx", 42), 42)

    def test_literal_str_passthrough(self) -> None:
        self.assertEqual(self._case()._resolve_value("ctx", "active"), "active")

    def test_literal_dict_passthrough(self) -> None:
        d = {"key": "val"}
        self.assertIs(self._case()._resolve_value("ctx", d), d)

    def test_literal_none_passthrough(self) -> None:
        self.assertIsNone(self._case()._resolve_value("ctx", None))

    def test_lambda_called_with_self(self) -> None:
        case = self._case()
        case.user = MagicMock()
        case.user.pk = 7
        self.assertEqual(case._resolve_value("ctx", lambda t: t.user.pk), 7)

    def test_lambda_returning_none_is_valid(self) -> None:
        self.assertIsNone(self._case()._resolve_value("ctx", lambda t: None))

    def test_lambda_attribute_error_includes_context(self) -> None:
        with self.assertRaises(AttributeError) as ctx:
            self._case()._resolve_value("fixture.kwargs['owner']", lambda t: t.missing)
        self.assertIn("fixture.kwargs['owner']", str(ctx.exception))

    def test_mock_object_not_called_passthrough(self) -> None:
        """MagicMock est callable mais pas une fonction — doit passer tel quel."""
        case = self._case()
        mock = MagicMock()
        result = case._resolve_value("ctx", mock)
        self.assertIs(result, mock)
        mock.assert_not_called()

    def test_class_not_called_passthrough(self) -> None:
        """Une classe est callable mais ne doit pas être appelée."""
        case = self._case()
        result = case._resolve_value("ctx", int)
        self.assertIs(result, int)


# ---------------------------------------------------------------------------
# _resolve_dict_values
# ---------------------------------------------------------------------------

class TestResolveDictValues(unittest.TestCase):

    def _case(self, pk: int = 5) -> ForgeCase:
        case = _make_forge_case()
        case.user = MagicMock()
        case.user.pk = pk
        return case

    def test_all_literals(self) -> None:
        self.assertEqual(
            self._case()._resolve_dict_values("ctx", {"a": 1, "b": "x"}),
            {"a": 1, "b": "x"},
        )

    def test_all_lambdas(self) -> None:
        result = self._case(pk=5)._resolve_dict_values("ctx", {"pk": lambda t: t.user.pk})
        self.assertEqual(result["pk"], 5)

    def test_mixed_literal_and_lambda(self) -> None:
        case = self._case(pk=7)
        result = case._resolve_dict_values("ctx", {"pk": lambda t: t.user.pk, "status": "active"})
        self.assertEqual(result, {"pk": 7, "status": "active"})

    def test_error_includes_key_and_context(self) -> None:
        with self.assertRaises(AttributeError) as ctx:
            self._case()._resolve_dict_values("fixture.kwargs", {"owner": lambda t: t.missing})
        self.assertIn("fixture.kwargs", str(ctx.exception))
        self.assertIn("owner", str(ctx.exception))


# ---------------------------------------------------------------------------
# _resolve_fixture_instance
# ---------------------------------------------------------------------------

class TestResolveFixtureInstance(unittest.TestCase):

    def _case(self) -> ForgeCase:
        case = _make_forge_case()
        case.factory = MagicMock()
        case.factory.create.return_value = MagicMock()
        return case

    def test_kwargs_literal_passed_to_create(self) -> None:
        case = self._case()
        case._resolve_fixture_instance({"model": MagicMock(), "object_name": "obj", "kwargs": {"status": "active"}})
        _, kwargs = case.factory.create.call_args
        self.assertEqual(kwargs["status"], "active")

    def test_kwargs_lambda_resolved_before_create(self) -> None:
        case = self._case()
        case.user = MagicMock()
        case._resolve_fixture_instance({"model": MagicMock(), "object_name": "obj", "kwargs": {"owner": lambda t: t.user}})
        _, kwargs = case.factory.create.call_args
        self.assertIs(kwargs["owner"], case.user)

    def test_data_literal_instance_stored(self) -> None:
        case = self._case()
        existing = object()
        case._resolve_fixture_instance({"model": MagicMock(), "object_name": "item", "data": existing})
        case.factory.create.assert_not_called()
        self.assertIs(case.item, existing)

    def test_data_lambda_resolved_and_stored(self) -> None:
        case = self._case()
        target = MagicMock()
        case.other = target
        case._resolve_fixture_instance({"model": MagicMock(), "object_name": "item", "data": lambda t: t.other})
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
        case._resolve_fixture_instance({"model": MagicMock(), "object_name": "group"})
        self.assertIs(case.group, fake)


# ---------------------------------------------------------------------------
# _resolve_fixtures — fixture unique ou liste
# ---------------------------------------------------------------------------

class TestResolveFixtures(unittest.TestCase):

    def _case(self) -> ForgeCase:
        case = _make_forge_case()
        case.factory = MagicMock()
        case.factory.create.return_value = MagicMock()
        return case

    def test_single_fixture_dict(self) -> None:
        case = self._case()
        case._resolve_fixtures({"model": MagicMock(), "object_name": "obj"})
        self.assertTrue(hasattr(case, "obj"))

    def test_list_of_two_fixtures_both_stored(self) -> None:
        case = self._case()
        m1, m2 = MagicMock(), MagicMock()
        case.factory.create.side_effect = [m1, m2]
        case._resolve_fixtures([
            {"model": MagicMock(), "object_name": "first"},
            {"model": MagicMock(), "object_name": "second"},
        ])
        self.assertIs(case.first, m1)
        self.assertIs(case.second, m2)

    def test_second_fixture_references_first_via_lambda(self) -> None:
        case = self._case()
        first_obj = MagicMock()
        first_obj.pk = 10
        second_obj = MagicMock()
        case.factory.create.side_effect = [first_obj, second_obj]

        case._resolve_fixtures([
            {"model": MagicMock(), "object_name": "company"},
            {"model": MagicMock(), "object_name": "branch", "kwargs": {"parent": lambda t: t.company}},
        ])
        _, branch_kwargs = case.factory.create.call_args
        self.assertIs(branch_kwargs["parent"], first_obj)

    def test_create_called_once_per_fixture(self) -> None:
        case = self._case()
        case.factory.create.side_effect = [MagicMock(), MagicMock(), MagicMock()]
        case._resolve_fixtures([
            {"model": MagicMock(), "object_name": "a"},
            {"model": MagicMock(), "object_name": "b"},
            {"model": MagicMock(), "object_name": "c"},
        ])
        self.assertEqual(case.factory.create.call_count, 3)

    def test_validation_accepts_fixture_list(self) -> None:
        class Sub(ForgeCase):
            config = {"tests": [{
                "fixture": [
                    {"model": MagicMock(), "object_name": "a"},
                    {"model": MagicMock(), "object_name": "b"},
                ],
                "expected_responses": {},
            }]}
        self.assertTrue(hasattr(Sub, "config"))

    def test_validation_list_missing_object_name_raises(self) -> None:
        with self.assertRaises(TypeError):
            class Sub(ForgeCase):
                config = {"tests": [{
                    "fixture": [
                        {"model": MagicMock(), "object_name": "a"},
                        {"model": MagicMock()},
                    ],
                }]}


# ---------------------------------------------------------------------------
# _resolve_fixture_json_data — FixtureJson.data comme LazyValue
# ---------------------------------------------------------------------------

class TestResolveFixtureJsonData(unittest.TestCase):

    def _case(self) -> ForgeCase:
        case = _make_forge_case()
        case.factory = MagicMock()
        case.factory.generate_fields_dict.return_value = {"generated": True}
        return case

    def test_data_literal_dict_returned(self) -> None:
        result = self._case()._resolve_fixture_json_data({"data": {"name": "Alice"}})
        self.assertEqual(result, {"name": "Alice"})

    def test_data_dict_with_lambda_resolved(self) -> None:
        case = self._case()
        case.user = MagicMock()
        case.user.email = "x@y.com"
        result = case._resolve_fixture_json_data({"data": {"email": lambda t: t.user.email, "role": "admin"}})
        self.assertEqual(result, {"email": "x@y.com", "role": "admin"})

    def test_no_data_delegates_to_factory(self) -> None:
        case = self._case()
        result = case._resolve_fixture_json_data({"model": MagicMock(), "fields": ["name"]})
        case.factory.generate_fields_dict.assert_called_once()
        self.assertEqual(result, {"generated": True})


# ---------------------------------------------------------------------------
# _extract_request_data — http_client_params.fixture unique ou liste fusionnée
# ---------------------------------------------------------------------------

class TestExtractRequestData(unittest.TestCase):

    def _case(self) -> ForgeCase:
        case = _make_forge_case()
        case.factory = MagicMock()
        return case

    def test_no_fixture_returns_none(self) -> None:
        self.assertIsNone(self._case()._extract_request_data({}))

    def test_single_fixture_dict(self) -> None:
        result = self._case()._extract_request_data({"fixture": {"data": {"name": "Alice"}}})
        self.assertEqual(result, {"name": "Alice"})

    def test_single_fixture_in_list(self) -> None:
        result = self._case()._extract_request_data({"fixture": [{"data": {"name": "Alice"}}]})
        self.assertEqual(result, {"name": "Alice"})

    def test_list_of_two_fixtures_merged(self) -> None:
        result = self._case()._extract_request_data({"fixture": [
            {"data": {"name": "Alice", "role": "user"}},
            {"data": {"email": "a@b.com", "role": "admin"}},
        ]})
        self.assertEqual(result, {"name": "Alice", "email": "a@b.com", "role": "admin"})

    def test_later_fixture_overwrites_earlier_on_same_key(self) -> None:
        result = self._case()._extract_request_data({"fixture": [
            {"data": {"pk": 1, "status": "draft"}},
            {"data": {"status": "active"}},
        ]})
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["pk"], 1)

    def test_list_with_lambda_resolved(self) -> None:
        case = self._case()
        case.user = MagicMock()
        case.user.pk = 42
        result = case._extract_request_data({"fixture": [
            {"data": {"owner_pk": lambda t: t.user.pk}},
            {"data": {"name": "Test"}},
        ]})
        self.assertEqual(result["owner_pk"], 42)
        self.assertEqual(result["name"], "Test")

    def test_fixture_key_removed_from_params_after_extraction(self) -> None:
        params = {"fixture": {"data": {"name": "x"}}, "content_type": "application/json"}
        self._case()._extract_request_data(params)
        self.assertNotIn("fixture", params)


# ---------------------------------------------------------------------------
# _resolve_url — reverse_params.kwargs avec lambdas + fusion scénario
# ---------------------------------------------------------------------------

class TestResolveUrl(unittest.TestCase):

    def _case(self, pk: int = 42) -> ForgeCase:
        case = _make_forge_case()
        case.user = MagicMock()
        case.user.pk = pk
        return case

    def test_lambda_in_reverse_kwargs(self) -> None:
        case = self._case(pk=7)
        with patch("forge_test.public.helpers.forge_case.reverse", return_value="/x/7/") as mock_r:
            url = case._resolve_url({"path_name": "x:y", "reverse_params": {"kwargs": {"pk": lambda t: t.user.pk}}})
        mock_r.assert_called_once_with("x:y", kwargs={"pk": 7})
        self.assertEqual(url, "/x/7/")

    def test_literal_in_reverse_kwargs(self) -> None:
        with patch("forge_test.public.helpers.forge_case.reverse") as mock_r:
            self._case()._resolve_url({"path_name": "x:y", "reverse_params": {"kwargs": {"pk": 99}}})
        mock_r.assert_called_once_with("x:y", kwargs={"pk": 99})

    def test_scenario_reverse_params_override_test_level(self) -> None:
        with patch("forge_test.public.helpers.forge_case.reverse") as mock_r:
            self._case()._resolve_url(
                {"path_name": "x:y", "reverse_params": {"kwargs": {"pk": 1}}},
                scenario_reverse_params={"kwargs": {"pk": 999}},
            )
        mock_r.assert_called_once_with("x:y", kwargs={"pk": 999})

    def test_query_string_appended(self) -> None:
        with patch("forge_test.public.helpers.forge_case.reverse", return_value="/x/"):
            url = self._case()._resolve_url({"path_name": "x:y", "reverse_params": {"query": {"page": 2}}})
        self.assertIn("page=2", url)

    def test_no_reverse_params_still_works(self) -> None:
        with patch("forge_test.public.helpers.forge_case.reverse", return_value="/x/"):
            url = self._case()._resolve_url({"path_name": "x:y"})
        self.assertEqual(url, "/x/")


# ---------------------------------------------------------------------------
# _build_authenticated_client — auth_backend
# ---------------------------------------------------------------------------

class TestAuthBackend(unittest.TestCase):

    def _case(self, backend=None) -> ForgeCase:
        case = _make_forge_case()
        case.config = {"auth_backend": backend} if backend else {}
        case.user = MagicMock()
        return case

    def test_auth_backend_called_with_user(self) -> None:
        custom_client = MagicMock()
        backend = MagicMock(return_value=custom_client)
        case = self._case(backend=backend)
        result = case._build_authenticated_client()
        backend.assert_called_once_with(case.user)
        self.assertIs(result, custom_client)

    def test_no_auth_backend_falls_back_to_login_user_for_test(self) -> None:
        case = self._case()
        fallback = MagicMock()
        with patch("forge_test.public.helpers.forge_case.login_user_for_test", return_value=fallback) as mock_login:
            result = case._build_authenticated_client()
        mock_login.assert_called_once_with(case.user)
        self.assertIs(result, fallback)

    def test_jwt_backend_pattern(self) -> None:
        def jwt_backend(user):
            c = MagicMock()
            c.defaults = {"HTTP_AUTHORIZATION": f"Bearer token-{user.pk}"}
            return c

        case = self._case(backend=jwt_backend)
        case.user.pk = 42
        result = case._build_authenticated_client()
        self.assertEqual(result.defaults["HTTP_AUTHORIZATION"], "Bearer token-42")

    def test_resolve_client_authenticated_uses_backend(self) -> None:
        custom_client = MagicMock()
        case = self._case(backend=lambda user: custom_client)
        self.assertIs(case._resolve_client(True), custom_client)

    def test_resolve_client_anonymous_ignores_backend(self) -> None:
        from django.test import Client as DjangoClient
        case = self._case(backend=lambda user: MagicMock())
        self.assertIsInstance(case._resolve_client(False), DjangoClient)


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

    def test_assert_status_code_message_includes_body(self) -> None:
        with self.assertRaises(AssertionError) as ctx:
            self._case()._assert_status_code(_make_response(json_data={"detail": "nope"}, status=403), 200)
        self.assertIn("nope", str(ctx.exception))

    def test_assert_fields_present_flat(self) -> None:
        self._case()._assert_fields_present({"id": 1, "name": "x"}, ["id", "name"])

    def test_assert_fields_present_nested(self) -> None:
        self._case()._assert_fields_present({"results": [{"pk": 1}]}, ["results.0.pk"])

    def test_assert_fields_present_fails_on_missing(self) -> None:
        with self.assertRaises(AssertionError):
            self._case()._assert_fields_present({"id": 1}, ["email"])

    def test_assert_fields_present_fails_on_missing_nested(self) -> None:
        with self.assertRaises(AssertionError):
            self._case()._assert_fields_present({"results": [{"pk": 1}]}, ["results.0.name"])

    def test_assert_field_values_literal(self) -> None:
        self._case()._assert_field_values({"status": "active"}, {"status": "active"})

    def test_assert_field_values_lambda(self) -> None:
        case = self._case()
        case.user = MagicMock()
        case.user.pk = 42
        case._assert_field_values({"owner_id": 42}, {"owner_id": lambda t: t.user.pk})

    def test_assert_field_values_lambda_mismatch_raises(self) -> None:
        case = self._case()
        case.user = MagicMock()
        case.user.pk = 99
        with self.assertRaises(AssertionError):
            case._assert_field_values({"owner_id": 42}, {"owner_id": lambda t: t.user.pk})

    def test_assert_field_values_nested_path(self) -> None:
        self._case()._assert_field_values({"results": [{"status": "active"}]}, {"results.0.status": "active"})

    def test_assert_field_types_passes(self) -> None:
        self._case()._assert_field_types({"id": 1, "name": "x"}, {"id": int, "name": str})

    def test_assert_field_types_fails(self) -> None:
        with self.assertRaises(AssertionError):
            self._case()._assert_field_types({"id": "not-int"}, {"id": int})

    def test_assert_fields_absent_passes(self) -> None:
        self._case()._assert_fields_absent({"id": 1}, ["password", "token"])

    def test_assert_fields_absent_fails_when_present(self) -> None:
        with self.assertRaises(AssertionError):
            self._case()._assert_fields_absent({"password": "hash"}, ["password"])

    def test_assert_response_type_passes(self) -> None:
        r = MagicMock()
        r.data = {"id": 1}
        self._case()._assert_response_type(r, dict)

    def test_assert_response_type_fails(self) -> None:
        r = MagicMock()
        r.data = [1, 2]
        with self.assertRaises(AssertionError):
            self._case()._assert_response_type(r, dict)

    def test_assert_response_body_orchestrates_all(self) -> None:
        case = self._case()
        r = _make_response(json_data={"id": 1, "name": "Alice", "role": "admin"})
        r.data = {"id": 1, "name": "Alice", "role": "admin"}
        case._assert_response_body(r, {
            "expected_fields": ["id", "name"],
            "expected_value_of_fields": {"role": "admin"},
            "expected_type_of_fields": {"id": int},
            "forbidden_fields": ["password"],
            "expected_response": dict,
        })

    def test_assert_response_body_skips_when_no_json(self) -> None:
        self._case()._assert_response_body(_make_response(json_data=None), {"expected_fields": ["id"]})


# ---------------------------------------------------------------------------
# pre_test dans ResponseValidationParams
# ---------------------------------------------------------------------------

class TestPreTest(unittest.TestCase):

    def _run_scenario(self, scenario: Dict[str, Any], status: int = 200) -> ForgeCase:
        test_config: Dict[str, Any] = {"path_name": "x:y", "method": "GET"}
        test_func = ForgeCase._build_single_test(test_config, scenario, status)

        case = _make_forge_case()
        case.factory = MagicMock()
        fake_client = MagicMock()
        fake_client.get = MagicMock(return_value=_make_response(json_data={}, status=status))
        case._resolve_client = MagicMock(return_value=fake_client)

        with patch("forge_test.public.helpers.forge_case.reverse", return_value="/fake/"):
            test_func(case)
        return case

    def test_pre_test_called_before_request(self) -> None:
        call_order = []
        fake_response = _make_response(json_data={}, status=200)

        test_config: Dict[str, Any] = {"path_name": "x:y", "method": "GET"}
        scenario: Dict[str, Any] = {"pre_test": lambda t: call_order.append("pre_test")}
        test_func = ForgeCase._build_single_test(test_config, scenario, 200)

        case = _make_forge_case()
        case.factory = MagicMock()
        fake_client = MagicMock()

        def side_effect(*a, **kw):
            call_order.append("request")
            return fake_response

        fake_client.get = MagicMock(side_effect=side_effect)
        case._resolve_client = MagicMock(return_value=fake_client)

        with patch("forge_test.public.helpers.forge_case.reverse", return_value="/fake/"):
            test_func(case)

        self.assertEqual(call_order, ["pre_test", "request"])

    def test_pre_test_receives_self(self) -> None:
        received = []
        case = self._run_scenario({"pre_test": lambda t: received.append(t)})
        self.assertIs(received[0], case)

    def test_no_pre_test_does_not_crash(self) -> None:
        self._run_scenario({"authenticated": False})

    def test_pre_test_can_mutate_self(self) -> None:
        case = self._run_scenario({"pre_test": lambda t: setattr(t, "deleted", True)})
        self.assertTrue(case.deleted)

    def test_pre_test_common_pattern_delete_before_404(self) -> None:
        """Cas réel : supprimer l'objet avant de tester le 404."""
        test_config: Dict[str, Any] = {
            "path_name": "x:y",
            "method": "DELETE",
            "fixture": {"model": MagicMock(), "object_name": "obj"},
        }
        deleted = []
        scenario: Dict[str, Any] = {
            "pre_test": lambda t: deleted.append(t.obj),
        }
        test_func = ForgeCase._build_single_test(test_config, scenario, 404)

        case = _make_forge_case()
        case.factory = MagicMock()
        fake_obj = MagicMock()
        case.factory.create.return_value = fake_obj
        fake_client = MagicMock()
        fake_client.delete = MagicMock(return_value=_make_response(json_data={}, status=404))
        case._resolve_client = MagicMock(return_value=fake_client)

        with patch("forge_test.public.helpers.forge_case.reverse", return_value="/fake/"):
            test_func(case)

        self.assertIs(deleted[0], fake_obj)


# ---------------------------------------------------------------------------
# Validation de config
# ---------------------------------------------------------------------------

class TestValidateConfig(unittest.TestCase):

    def test_no_config_does_not_crash(self) -> None:
        class Sub(ForgeCase):
            pass

    def test_empty_config_does_not_crash(self) -> None:
        class Sub(ForgeCase):
            config = {}

    def test_tests_not_list_raises(self) -> None:
        with self.assertRaises(TypeError):
            class Sub(ForgeCase):
                config = {"tests": "not-a-list"}

    def test_factory_params_not_dict_raises(self) -> None:
        with self.assertRaises(TypeError):
            class Sub(ForgeCase):
                config = {"factory_params": "bad", "tests": []}

    def test_fixture_missing_object_name_raises(self) -> None:
        with self.assertRaises(TypeError):
            class Sub(ForgeCase):
                config = {"tests": [{"fixture": {"model": MagicMock()}}]}

    def test_fixture_with_object_name_passes(self) -> None:
        class Sub(ForgeCase):
            config = {"tests": [{"fixture": {"model": MagicMock(), "object_name": "x"}, "expected_responses": {}}]}

    def test_fixture_list_all_valid_passes(self) -> None:
        class Sub(ForgeCase):
            config = {"tests": [{
                "fixture": [
                    {"model": MagicMock(), "object_name": "a"},
                    {"model": MagicMock(), "object_name": "b"},
                ],
                "expected_responses": {},
            }]}

    def test_fixture_list_second_missing_object_name_raises(self) -> None:
        with self.assertRaises(TypeError):
            class Sub(ForgeCase):
                config = {"tests": [{
                    "fixture": [
                        {"model": MagicMock(), "object_name": "a"},
                        {"model": MagicMock()},
                    ],
                }]}


# ---------------------------------------------------------------------------
# Génération de tests — nommage, scénarios, scenarios multiples
# ---------------------------------------------------------------------------

class TestScenarioGeneration(unittest.TestCase):

    def test_single_dict_generates_one_test(self) -> None:
        class Sub(ForgeCase):
            config = {"tests": [{"path_name": "x:y", "method": "GET", "expected_responses": {200: {}}}]}
        attached = [m for m in dir(Sub) if "success" in m]
        self.assertEqual(len(attached), 1)
        self.assertTrue(attached[0].endswith("_0"))

    def test_list_of_two_scenarios_generates_two_tests(self) -> None:
        class Sub(ForgeCase):
            config = {"tests": [{"path_name": "x:y", "method": "GET", "expected_responses": {
                404: [{"authenticated": True}, {"authenticated": False}]
            }}]}
        attached = sorted(m for m in dir(Sub) if "not_found" in m)
        self.assertEqual(len(attached), 2)
        self.assertTrue(attached[0].endswith("_0"))
        self.assertTrue(attached[1].endswith("_1"))

    def test_multiple_status_codes_each_get_own_tests(self) -> None:
        class Sub(ForgeCase):
            config = {"tests": [{"path_name": "x:y", "method": "GET", "expected_responses": {
                200: {}, 401: {},
            }}]}
        attached = [m for m in dir(Sub) if m.startswith("test_get_x_y")]
        self.assertEqual(len(attached), 2)

    def test_custom_test_name_used_in_method_name(self) -> None:
        class Sub(ForgeCase):
            config = {"tests": [{"test_name": "my_custom", "path_name": "x:y", "method": "GET", "expected_responses": {200: {}}}]}
        self.assertTrue(any("my_custom" in m for m in dir(Sub)))

    def test_unknown_status_code_uses_raw_number(self) -> None:
        class Sub(ForgeCase):
            config = {"tests": [{"path_name": "x:y", "method": "GET", "expected_responses": {418: {}}}]}
        self.assertTrue(any("_418_" in m for m in dir(Sub)))

    def test_path_name_colons_and_dashes_sanitized(self) -> None:
        class Sub(ForgeCase):
            config = {"tests": [{"path_name": "api:my-resource", "method": "POST", "expected_responses": {201: {}}}]}
        attached = [m for m in dir(Sub) if m.startswith("test_post_api_my_resource")]
        self.assertEqual(len(attached), 1)
        self.assertNotIn(":", attached[0])
        self.assertNotIn("-", attached[0])


# ---------------------------------------------------------------------------
# Helpers module-level
# ---------------------------------------------------------------------------

class TestResolveNestedField(unittest.TestCase):

    def test_flat_found(self) -> None:
        self.assertEqual(_resolve_nested_field({"id": 1}, "id"), 1)

    def test_flat_missing_returns_default(self) -> None:
        self.assertIsNone(_resolve_nested_field({}, "x"))

    def test_custom_default(self) -> None:
        s = object()
        self.assertIs(_resolve_nested_field({}, "x", default=s), s)

    def test_nested_two_levels(self) -> None:
        self.assertEqual(_resolve_nested_field({"a": {"b": 2}}, "a.b"), 2)

    def test_nested_three_levels(self) -> None:
        self.assertEqual(_resolve_nested_field({"a": {"b": {"c": 3}}}, "a.b.c"), 3)

    def test_list_index(self) -> None:
        self.assertEqual(_resolve_nested_field([{"id": 1}, {"id": 2}], "1.id"), 2)

    def test_list_inside_dict(self) -> None:
        self.assertEqual(_resolve_nested_field({"results": [{"pk": 7}]}, "results.0.pk"), 7)

    def test_list_out_of_range_returns_default(self) -> None:
        self.assertIsNone(_resolve_nested_field([], "0"))

    def test_list_negative_index_returns_default(self) -> None:
        self.assertIsNone(_resolve_nested_field([1, 2], "-1"))

    def test_list_non_numeric_index_returns_default(self) -> None:
        self.assertIsNone(_resolve_nested_field([1, 2], "abc"))

    def test_intermediate_primitive_returns_default(self) -> None:
        self.assertIsNone(_resolve_nested_field({"x": "string"}, "x.y"))


class TestParseResponseJson(unittest.TestCase):

    def test_valid_json(self) -> None:
        self.assertEqual(_parse_response_json(_make_response(json_data={"id": 1})), {"id": 1})

    def test_invalid_returns_none(self) -> None:
        self.assertIsNone(_parse_response_json(_make_response(json_data=None)))

    def test_any_exception_returns_none(self) -> None:
        r = MagicMock()
        r.json.side_effect = RuntimeError("boom")
        self.assertIsNone(_parse_response_json(r))


class TestSafeResponseBody(unittest.TestCase):

    def test_json_preferred(self) -> None:
        self.assertIn("bad", _safe_response_body(_make_response(json_data={"error": "bad"})))

    def test_falls_back_to_content(self) -> None:
        self.assertIn("raw", _safe_response_body(_make_response(json_data=None, content=b"raw error")))

    def test_truncates_long_content(self) -> None:
        r = _make_response(json_data=None, content=b"x" * 500)
        self.assertLessEqual(len(_safe_response_body(r)), 300)


class TestAppendQueryString(unittest.TestCase):

    def test_dict_query(self) -> None:
        self.assertIn("page=2", _append_query_string("/api/", {"page": 2}))

    def test_string_query(self) -> None:
        self.assertEqual(_append_query_string("/api/", "page=1"), "/api/?page=1")

    def test_empty_dict(self) -> None:
        self.assertEqual(_append_query_string("/api/", {}), "/api/?")


# ---------------------------------------------------------------------------
# Intégration — scénario complet avec fixtures, lambdas, pre_test
# ---------------------------------------------------------------------------

class TestBuildSingleTestIntegration(unittest.TestCase):

    def test_full_scenario_with_lambda_kwargs_and_expected_value(self) -> None:
        """
        Scénario complet :
          - fixture avec kwargs lambda
          - reverse_params kwargs lambda
          - expected_value_of_fields avec lambda
          - pre_test qui mute self
        """
        test_config: Dict[str, Any] = {
            "path_name": "x:y",
            "method": "GET",
            "fixture": [
                {"model": MagicMock(), "object_name": "obj", "kwargs": {"owner": lambda t: t.user}},
            ],
            "reverse_params": {"kwargs": {"pk": lambda t: t.obj.pk}},
        }
        scenario: Dict[str, Any] = {
            "authenticated": False,
            "pre_test": lambda t: setattr(t, "pre_ran", True),
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

        # fixtures créées
        self.assertIs(case.obj, fake_obj)
        _, factory_kwargs = case.factory.create.call_args
        self.assertIs(factory_kwargs["owner"], case.user)

        # pre_test exécuté
        self.assertTrue(case.pre_ran)

        # requête envoyée
        fake_client.get.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)