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

# Toute valeur dans la config peut être :
#   - une valeur littérale   : "active", 42, True, {"name": "Alice"}
#   - une lambda             : lambda t: t.user.pk
# La lambda reçoit l'instance du TestCase (t) et est résolue au moment de
# l'exécution du test. C'est valide partout : fixture.kwargs, fixture.data,
# FixtureJson.data, reverse_params.kwargs, expected_value_of_fields, user.
LazyValue = Union[Any, Callable[[Any], Any]]


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
    kwargs: Optional[Dict[str, LazyValue]]   # ex: {"pk": lambda t: t.obj.pk}
    current_app: Optional[str]
    query: Optional[Union[Dict[str, Any], QueryDict]]
    fragment: Optional[str]


class FixtureJson(TypedDict, total=False):
    """Body d'une requête HTTP généré ou fourni directement."""
    model: Type[models.Model]
    fields: Optional[List[str]]
    data: Optional[Dict[str, LazyValue]]     # ex: {"email": lambda t: t.user.email}


class HTTPClientParams(TypedDict, total=False):
    fixture: FixtureJson
    content_type: str
    follow: bool
    secure: bool
    QUERY_STRING: str
    headers: Optional[Mapping[str, Any]]


class Fixture(TypedDict, total=False):
    """Instance de modèle créée avant la requête et stockée sur self.<object_name>."""
    object_name: str                          # requis — validé au chargement de la classe
    model: Type[models.Model]
    kwargs: Dict[str, LazyValue]             # ex: {"owner": lambda t: t.user}
    data: LazyValue                          # instance existante ou lambda retournant une instance


class ResponseValidationParams(TypedDict, total=False):
    """
    Décrit un scénario pour un status code donné.

    Plusieurs scénarios peuvent partager le même status code via une liste
    — voir TestCaseConfig.expected_responses.
    """
    reverse_params: ReverseParams
    http_client_params: HTTPClientParams
    authenticated: bool
    expected_response: Type[Any]
    expected_fields: List[str]
    expected_value_of_fields: Dict[str, LazyValue]  # ex: {"owner_id": lambda t: t.user.pk}
    expected_type_of_fields: Dict[str, Type[Any]]
    forbidden_fields: List[str]


# Pour un même status code : un seul scénario, OU plusieurs scénarios
# couvrant des chemins différents menant au même code.
ExpectedResponseEntry = Union[ResponseValidationParams, List[ResponseValidationParams]]


class TestCaseConfig(TypedDict, total=False):
    user: Optional[LazyValue]               # ex: lambda t: t.company.owner
    test_name: str
    path_name: str
    method: HttpMethod
    reverse_params: ReverseParams
    http_client_params: HTTPClientParams
    fixture: Fixture
    expected_responses: Dict[int, ExpectedResponseEntry]


class ConfigForgeCase(TypedDict, total=False):
    user: Optional[LazyValue]               # ex: lambda t: t.admin_user
    factory_params: Optional[ForgeModelFactoryParams]
    tests: Optional[List[TestCaseConfig]]