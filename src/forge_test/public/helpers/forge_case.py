from __future__ import annotations

import json as _json
from typing import Any, Dict, List, Optional, Union

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from forge_test.public.helpers.forge_model_factory import ForgeModelFactory
from forge_test.public.helpers.login_user_for_test import login_user_for_test
from forge_test.public.type import (
    ConfigForgeCase,
    Fixture,
    FixtureJson,
    HTTPClientParams,
    ResponseValidationParams,
    TestCaseConfig,
)

User = get_user_model()


class ForgeCase(TestCase):
    """
    Classe de base pour les tests d'endpoints auto-générés.

    Chaque status code attendu dans `expected_responses` peut contenir un ou
    plusieurs scénarios (dict ou liste de dicts). Chaque scénario déclenche
    une requête indépendante avec son propre `authenticated`, `reverse_params`,
    `http_client_params`, etc.

    Pour référencer une fixture créée plus tôt dans une URL (reverse_params.kwargs),
    utiliser une lambda plutôt qu'une string magique — validée par l'IDE/mypy :

        "reverse_params": {"kwargs": {"pk": lambda t: t.user.pk}}

    Usage :
        class MyTests(ForgeCase):
            config: ConfigForgeCase = {
                "factory_params": {...},
                "tests": [
                    {
                        "path_name": "api:resource-detail",
                        "method": "GET",
                        "fixture": {"model": MyModel, "object_name": "obj"},
                        "reverse_params": {"kwargs": {"pk": lambda t: t.obj.pk}},
                        "expected_responses": {
                            200: {"authenticated": True, "expected_fields": ["id"]},
                            404: [
                                {"authenticated": True, "reverse_params": {"kwargs": {"pk": 999999}}},
                                {"authenticated": False},
                            ],
                        },
                    }
                ],
            }
    """

    config: ConfigForgeCase

    STATUS_SUFFIX: Dict[int, str] = {
        200: "success",
        201: "created",
        204: "no_content",
        400: "bad_request",
        401: "not_authenticated",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        422: "unprocessable",
        500: "server_error",
    }

    # ------------------------------------------------------------------
    # Django TestCase hooks
    # ------------------------------------------------------------------

    def setUp(self) -> None:
        super().setUp()
        self.factory = self._build_factory()
        self.user = self.config.get("user") or self.factory.create(User)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._validate_config()
        cls._attach_all_tests()

    # ------------------------------------------------------------------
    # Validation de la config
    # ------------------------------------------------------------------

    @classmethod
    def _validate_config(cls) -> None:
        if not hasattr(cls, "config"):
            return
        if not isinstance(cls.config, dict):
            raise TypeError("config must be a dict")
        tests = cls.config.get("tests")
        if tests is None:
            return
        if not isinstance(tests, list):
            raise TypeError("config['tests'] must be a list")
        factory_params = cls.config.get("factory_params")
        if factory_params is not None and not isinstance(factory_params, dict):
            raise TypeError("config['factory_params'] must be a dict")
        for test in tests:
            cls._validate_test_entry(test)

    @classmethod
    def _validate_test_entry(cls, test: Dict[str, Any]) -> None:
        if not isinstance(test, dict):
            raise TypeError("each test must be a dict")
        if "fixture" in test:
            cls._validate_fixture_entry(test["fixture"])

    @classmethod
    def _validate_fixture_entry(cls, fixture: Any) -> None:
        if not isinstance(fixture, dict):
            raise TypeError("fixture must be a dict")
        if "object_name" not in fixture:
            raise TypeError("object_name is required in fixture")

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    def _build_factory(self) -> ForgeModelFactory:
        params = self.config.get("factory_params") or {}
        return ForgeModelFactory(**params)

    # ------------------------------------------------------------------
    # Client / auth
    # ------------------------------------------------------------------

    def _build_authenticated_client(self) -> Client:
        return login_user_for_test(self.user)

    def _build_anonymous_client(self) -> Client:
        return Client()

    def _resolve_client(self, authenticated: bool) -> Client:
        return self._build_authenticated_client() if authenticated else self._build_anonymous_client()

    # ------------------------------------------------------------------
    # URL
    # ------------------------------------------------------------------

    def _resolve_url(self, test: TestCaseConfig, scenario_reverse_params: Optional[Dict] = None) -> str:
        """
        Résout l'URL en fusionnant les reverse_params du test (niveau global)
        avec ceux du scénario courant (priorité au scénario).
        """
        base_reverse = dict(test.get("reverse_params") or {})
        if scenario_reverse_params:
            base_reverse.update(scenario_reverse_params)

        query = base_reverse.pop("query", None)
        kwargs = base_reverse.pop("kwargs", {}) or {}
        base_reverse["kwargs"] = self._resolve_kwargs(kwargs)

        url = reverse(test["path_name"], **base_reverse)
        if query:
            url = _append_query_string(url, query)
        return url

    def _resolve_kwargs(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Appelle les valeurs callables (lambdas) avec self, laisse les autres telles quelles."""
        return {key: self._resolve_kwarg_value(key, value) for key, value in kwargs.items()}

    def _resolve_kwarg_value(self, key: str, value: Any) -> Any:
        if not callable(value):
            return value
        try:
            return value(self)
        except AttributeError as e:
            raise AttributeError(
                f"reverse_params.kwargs['{key}'] : la lambda a levé une AttributeError : {e}. "
                "Vérifiez que l'objet référencé existe bien (object_name correct dans fixture)."
            ) from e

    # ------------------------------------------------------------------
    # Fixture data
    # ------------------------------------------------------------------

    def _resolve_fixture_json_data(self, fixture_json: FixtureJson) -> Dict[str, Any]:
        if fixture_json.get("data"):
            return fixture_json["data"]
        return self.factory.generate_fields_dict(
            model=fixture_json["model"],
            fields=fixture_json.get("fields"),
        )

    def _resolve_fixture_instance(self, fixture: Fixture) -> Any:
        """Crée ou retourne une instance, la stocke sous self.<object_name>."""
        instance = fixture.get("data") or self.factory.create(
            fixture["model"], **(fixture.get("kwargs") or {})
        )
        setattr(self, fixture["object_name"], instance)
        return instance

    # ------------------------------------------------------------------
    # HTTP request
    # ------------------------------------------------------------------

    def _extract_request_data(self, http_params: HTTPClientParams) -> Optional[Dict[str, Any]]:
        fixture_json = http_params.pop("fixture", None)
        if fixture_json is None:
            return None
        return self._resolve_fixture_json_data(fixture_json)

    def _serialize_json_body(self, data: Any, http_params: HTTPClientParams) -> Any:
        http_params.setdefault("content_type", "application/json")
        if http_params["content_type"] == "application/json":
            return _json.dumps(data)
        return data

    def _send_request(self, url: str, method: str, http_params: HTTPClientParams) -> Any:
        data = self._extract_request_data(http_params)
        if data is not None:
            data = self._serialize_json_body(data, http_params)
        client_method = getattr(self.client, method.lower())
        return client_method(url, data, **http_params)

    # ------------------------------------------------------------------
    # Assertions — une méthode par responsabilité
    # ------------------------------------------------------------------

    def _assert_status_code(self, response: Any, expected_status: int) -> None:
        self.assertEqual(
            response.status_code,
            expected_status,
            msg=f"Status attendu {expected_status}, reçu {response.status_code}. Body: {_safe_response_body(response)}",
        )

    def _assert_fields_present(self, data: Union[Dict, List], fields: List[str]) -> None:
        missing = object()
        for field in fields:
            value = _resolve_nested_field(data, field, default=missing)
            self.assertIsNot(value, missing, msg=f"Champ attendu '{field}' absent de la réponse.")

    def _assert_field_values(self, data: Union[Dict, List], expected_values: Dict[str, Any]) -> None:
        for field, expected in expected_values.items():
            actual = _resolve_nested_field(data, field)
            self.assertEqual(actual, expected, msg=f"Champ '{field}': attendu {expected!r}, reçu {actual!r}.")

    def _assert_field_types(self, data: Union[Dict, List], expected_types: Dict[str, type]) -> None:
        for field, expected_type in expected_types.items():
            actual = _resolve_nested_field(data, field)
            self.assertIsInstance(
                actual, expected_type,
                msg=f"Champ '{field}': type attendu {expected_type.__name__}, reçu {type(actual).__name__}.",
            )

    def _assert_fields_absent(self, data: Union[Dict, List], forbidden_fields: List[str]) -> None:
        for field in forbidden_fields:
            value = _resolve_nested_field(data, field)
            self.assertIsNone(value, msg=f"Champ interdit '{field}' présent dans la réponse.")

    def _assert_response_type(self, response: Any, expected_type: type) -> None:
        self.assertIsInstance(
            response.data, expected_type,
            msg=f"Type de body attendu {expected_type.__name__}, reçu {type(response.data).__name__}.",
        )

    def _assert_response_body(self, response: Any, params: ResponseValidationParams) -> None:
        data = _parse_response_json(response)
        if data is None:
            return

        if fields := params.get("expected_fields"):
            self._assert_fields_present(data, fields)
        if values := params.get("expected_value_of_fields"):
            self._assert_field_values(data, values)
        if types := params.get("expected_type_of_fields"):
            self._assert_field_types(data, types)
        if forbidden := params.get("forbidden_fields"):
            self._assert_fields_absent(data, forbidden)
        if expected_response := params.get("expected_response"):
            self._assert_response_type(response, expected_response)

    # ------------------------------------------------------------------
    # Test generation
    # ------------------------------------------------------------------

    @classmethod
    def _build_single_test(cls, test: TestCaseConfig, scenario: ResponseValidationParams, status_code: int):
        """Retourne une fonction de test pour un (test, scénario, status_code) donné."""

        def test_func(self: ForgeCase) -> None:
            if user := test.get("user"):
                self.user = user

            if fixture := test.get("fixture"):
                self._resolve_fixture_instance(fixture)

            self.client = self._resolve_client(scenario.get("authenticated", False))
            url = self._resolve_url(test, scenario.get("reverse_params"))

            http_params: HTTPClientParams = {
                **(test.get("http_client_params") or {}),
                **(scenario.get("http_client_params") or {}),
            }

            response = self._send_request(url, test["method"], http_params)

            self._assert_status_code(response, status_code)
            self._assert_response_body(response, scenario)

        return test_func

    @classmethod
    def _attach_test_to_class(cls, test_name: str, test_func) -> None:
        setattr(cls, test_name, test_func)

    @classmethod
    def _build_test_name(cls, test: TestCaseConfig, test_index: int, status_code: int, scenario_index: int) -> str:
        base = test.get("test_name") or (
            test.get("path_name", f"test_{test_index}").replace(":", "_").replace("-", "_")
        )
        method = test.get("method", "GET").lower()
        suffix = cls.STATUS_SUFFIX.get(status_code, str(status_code))
        return f"test_{method}_{base}_{suffix}_{scenario_index}"

    @classmethod
    def _normalize_scenarios(
        cls, raw: Union[ResponseValidationParams, List[ResponseValidationParams]]
    ) -> List[ResponseValidationParams]:
        """Un dict unique devient une liste à un élément ; une liste reste telle quelle."""
        return raw if isinstance(raw, list) else [raw]

    @classmethod
    def _attach_all_tests(cls) -> None:
        if not hasattr(cls, "config"):
            return
        tests = cls.config.get("tests") or []
        for test_index, test in enumerate(tests):
            cls._attach_tests_for_single_test_config(test, test_index)

    @classmethod
    def _attach_tests_for_single_test_config(cls, test: TestCaseConfig, test_index: int) -> None:
        expected_responses: Dict[int, Any] = test.get("expected_responses") or {}
        for status_code, raw_scenarios in expected_responses.items():
            scenarios = cls._normalize_scenarios(raw_scenarios)
            for scenario_index, scenario in enumerate(scenarios):
                cls._attach_one_scenario_test(test, test_index, status_code, scenario, scenario_index)

    @classmethod
    def _attach_one_scenario_test(
        cls,
        test: TestCaseConfig,
        test_index: int,
        status_code: int,
        scenario: ResponseValidationParams,
        scenario_index: int,
    ) -> None:
        name = cls._build_test_name(test, test_index, status_code, scenario_index)
        func = cls._build_single_test(test, scenario, status_code)
        func.__name__ = name
        cls._attach_test_to_class(name, func)


# ------------------------------------------------------------------
# Module-level helpers (pures, sans état)
# ------------------------------------------------------------------


def _resolve_nested_field(data: Union[Dict, List], field_path: str, default: Any = None) -> Any:
    """
    Résout un champ potentiellement imbriqué via notation pointée.
    Supporte les dictionnaires et les listes (via des index numériques).

    Ex:
        "user.profile.age" -> data["user"]["profile"]["age"]
        "results.0.name"   -> data["results"][0]["name"]
        "0.id"              -> data[0]["id"]
    """
    parts = field_path.split(".")
    current = data

    for part in parts:
        if isinstance(current, list):
            if not part.isdigit():
                return default
            idx = int(part)
            if idx < 0 or idx >= len(current):
                return default
            current = current[idx]
        elif isinstance(current, dict):
            if part not in current:
                return default
            current = current[part]
        else:
            return default

    return current


def _parse_response_json(response: Any) -> Optional[Dict]:
    """Tente de parser le body JSON de la réponse. Retourne None si impossible."""
    try:
        return response.json()
    except Exception:
        return None


def _safe_response_body(response: Any) -> str:
    """Retourne le body de la réponse sous forme de string pour les messages d'erreur."""
    try:
        return str(response.json())
    except Exception:
        return getattr(response, "content", b"").decode("utf-8", errors="replace")[:300]


def _append_query_string(url: str, query: Any) -> str:
    """Ajoute un query string à une URL."""
    from urllib.parse import urlencode
    if isinstance(query, dict):
        return f"{url}?{urlencode(query)}"
    return f"{url}?{query}"
