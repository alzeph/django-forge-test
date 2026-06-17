from typing import (
    Any, Callable, Dict, List, Literal, Mapping, Optional,
    Sequence, Tuple, Type, TypedDict, Union,
)

from django.contrib.auth import get_user_model
from django.db import models
from django.http import QueryDict

User = get_user_model()

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
_RequestData = Union[Mapping[str, Any], str, Sequence[Tuple[str, Any]], QueryDict]

# Une valeur de kwargs peut être littérale, ou une lambda résolue au runtime
# avec l'instance du TestCase en argument (ex: lambda t: t.user.pk).
# Préférer la lambda à une string magique : validée par l'IDE/mypy, pas de typo possible.
KwargValue = Union[Any, "Callable[[Any], Any]"]


class ForgeModelFactoryParams(TypedDict, total=False):
    max_depth: int
    create_m2m: bool
    m2m_count: int
    max_retries: int
    person_name_fields: List[str]
    establishment_name_fields: List[str]
    text_description_fields: List[str]
    text_word_range: Tuple[int, int]
    fill_images: bool
    image_dimensions: Tuple[int, int]


class ReverseParams(TypedDict, total=False):
    urlconf: Optional[str]
    args: Optional[Sequence[Any]]
    kwargs: Optional[Dict[str, KwargValue]]
    current_app: Optional[str]
    query: Optional[Union[Dict[str, Any], QueryDict]]
    fragment: Optional[str]


class FixtureJson(TypedDict, total=False):
    model: Type[models.Model]
    fields: Optional[List[str]]
    data: Optional[Dict[str, Any]]


class HTTPClientParams(TypedDict, total=False):
    fixture: FixtureJson
    content_type: str
    follow: bool
    secure: bool
    QUERY_STRING: str
    headers: Optional[Mapping[str, Any]]


class Fixture(TypedDict, total=False):
    object_name: str  # requis en pratique — validé au runtime par ForgeCase
    model: Type[models.Model]
    kwargs: Dict[str, Any]
    data: Any


class ResponseValidationParams(TypedDict, total=False):
    """
    Décrit un scénario de test pour un status code donné.

    Plusieurs scénarios peuvent partager le même status code en les
    regroupant dans une liste — voir TestCaseConfig.expected_responses.
    """
    reverse_params: ReverseParams
    http_client_params: HTTPClientParams
    authenticated: bool
    expected_response: Type[Any]
    expected_fields: List[str]
    expected_value_of_fields: Dict[str, Any]
    expected_type_of_fields: Dict[str, Type[Any]]
    forbidden_fields: List[str]


# Pour un même status code : un seul scénario, OU plusieurs scénarios
# couvrant des chemins différents menant au même code (ex: 404 par mauvais pk
# et 404 par ressource supprimée).
ExpectedResponseEntry = Union[ResponseValidationParams, List[ResponseValidationParams]]


class TestCaseConfig(TypedDict, total=False):
    user: Optional[User]
    test_name: str
    path_name: str
    method: HttpMethod
    reverse_params: ReverseParams
    http_client_params: HTTPClientParams
    fixture: Fixture
    expected_responses: Dict[int, ExpectedResponseEntry]


class ConfigForgeCase(TypedDict, total=False):
    user: Optional[User]
    factory_params: Optional[ForgeModelFactoryParams]
    tests: Optional[List[TestCaseConfig]]
