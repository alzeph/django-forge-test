# Forge Test

Génération de fixtures et tests d'API auto-générés pour Django + DRF.

Forge Test élimine le boilerplate des tests d'endpoints REST. Au lieu d'écrire une méthode `test_*` par cas, vous décrivez une configuration déclarative — Forge Test génère, exécute et nomme les tests pour vous.

## Sommaire

- [Composants](#composants)
- [ForgeModelFactory](#forgemodelfactory)
- [ForgeCase](#forgecase)
  - [LazyValue — lambdas partout](#lazyvalue--lambdas-partout)
  - [expected_responses](#expected_responses)
  - [fixture — créer des instances](#fixture--créer-des-instances)
  - [http_client_params — envoyer un body](#http_client_params--envoyer-un-body)
  - [pre_test — préparer un scénario](#pre_test--préparer-un-scénario)
  - [auth_backend — authentification personnalisée](#auth_backend--authentification-personnalisée)
  - [Notation pointée](#notation-pointée)
  - [Nommage des tests générés](#nommage-des-tests-générés)
  - [Combiner config déclarative et tests manuels](#combiner-config-déclarative-et-tests-manuels)
- [Référence des types](#référence-des-types)
- [Exemples complets](#exemples-complets)
- [Erreurs fréquentes](#erreurs-fréquentes)
- [Bonnes pratiques](#bonnes-pratiques)

---

## Composants

| Composant | Rôle |
|---|---|
| `ForgeModelFactory` | Génère des instances de modèles Django avec des données fake cohérentes |
| `ForgeCase` | Classe de base qui transforme une config en suite de tests `TestCase` |
| `forge_types` | Types (`TypedDict`) qui documentent et valident la config dans l'IDE |

---

## ForgeModelFactory

### Installation rapide

```python
from forge_test.public.helpers import ForgeModelFactory

factory = ForgeModelFactory(
    max_depth=5,
    create_m2m=True,
    m2m_count=2,
    max_retries=3,
)
```

### Paramètres disponibles

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `max_depth` | `int` | `5` | Profondeur max de résolution des relations (anti-récursion infinie) |
| `create_m2m` | `bool` | `True` | Crée des objets liés pour les champs `ManyToManyField` |
| `m2m_count` | `int` | `2` | Nombre d'objets créés par relation M2M |
| `max_retries` | `int` | `3` | Tentatives avant abandon sur `IntegrityError` |
| `person_name_fields` | `List[str]` | `[]` | Champs remplis avec un nom de personne (`Faker.name()`) |
| `establishment_name_fields` | `List[str]` | `[]` | Champs remplis avec un nom d'entreprise (`Faker.company()`) |
| `text_description_fields` | `List[str]` | `[]` | Champs remplis avec une phrase de longueur contrôlée |
| `text_word_range` | `Tuple[int, int]` | `(10, 50)` | Bornes (min, max) du nombre de mots pour `text_description_fields` |
| `fill_images` | `bool` | `False` | Génère une image pour les `ImageField` optionnels. Les champs requis sont toujours remplis indépendamment de ce flag |
| `image_dimensions` | `Tuple[int, int]` | `(800, 600)` | Dimensions des images générées |

#### Exemple — personnaliser la génération de noms

```python
factory = ForgeModelFactory(
    person_name_fields=["full_name", "contact_name"],
    establishment_name_fields=["shop_name"],
    text_description_fields=["bio", "description"],
    text_word_range=(15, 30),
)

shop = factory.create(Shop)
# shop.full_name    -> "Claire Dupont"  (Faker.name)
# shop.shop_name    -> "Dupont & Fils"  (Faker.company)
# shop.description  -> phrase de 15 à 30 mots
```

### Méthodes principales

#### `create(model, **overrides) -> M`

Crée et persiste une instance en base, avec gestion automatique des FK/O2O/M2M.

```python
user = factory.create(User)
# user est un User sauvegardé en base, toutes FK résolues automatiquement

user_custom = factory.create(User, email="custom@test.com", first_name="Alice")
# les kwargs écrasent les valeurs générées
```

Exemple avec relations imbriquées :

```python
# Si Order a une FK vers Customer, et Customer une FK vers Address,
# create() résout toute la chaîne (jusqu'à max_depth)
order = factory.create(Order)
print(order.customer.address.city)  # valeur générée, pas None
```

#### `build(model, **overrides) -> M`

Construit une instance sans la sauvegarder.

```python
draft = factory.build(User)
print(draft.pk)  # None — rien n'est en base

draft.email = "avant-save@test.com"
draft.save()
```

#### `generate_fields_dict(model, fields=None, **overrides) -> Dict[str, Any]`

Retourne un `dict` de valeurs — utile pour le body d'une requête POST/PATCH sans toucher la base.

```python
payload = factory.generate_fields_dict(
    User,
    fields=["first_name", "last_name", "email"],
)
# {"first_name": "Alice", "last_name": "Dupont", "email": "alice123@test.com"}

payload_with_override = factory.generate_fields_dict(User, email="forced@test.com")
# tous les champs générés, sauf email qui vaut "forced@test.com"
```

### Gestion des fichiers et images

| Cas | Comportement |
|---|---|
| `ImageField` requis (`null=False, blank=False`) | Image générée systématiquement, peu importe `fill_images` |
| `ImageField` optionnel | Dépend de `fill_images` (`True` -> image, `False` -> `None`) |
| `FileField` requis, extensions non-image (`pdf`, `csv`, etc.) | Fichier généré selon l'extension acceptée |
| `FileField` requis, extensions image uniquement | Image générée même si `fill_images=False` |
| `FileField` optionnel, extensions image uniquement | Dépend de `fill_images` |

Un champ requis est toujours rempli. `fill_images` ne s'applique qu'aux champs optionnels.

```python
factory = ForgeModelFactory(fill_images=False)

# avatar = models.ImageField(null=True, blank=True) -> None
# photo  = models.ImageField()                      -> image générée (requis)

user = factory.create(User)
print(user.avatar)  # None
print(user.photo)   # InMemoryUploadedFile
```

---

## ForgeCase

### Principe

```python
from forge_test.public.helpers import ForgeCase
from forge_test.public.type import ConfigForgeCase

class MyEndpointTests(ForgeCase):
    config: ConfigForgeCase = {
        "factory_params": {"max_depth": 7, "create_m2m": True},
        "tests": [
            {
                "path_name": "api:resource-detail",
                "method": "GET",
                "fixture": {"model": MyModel, "object_name": "obj"},
                "reverse_params": {"kwargs": {"pk": lambda t: t.obj.pk}},
                "expected_responses": {
                    200: {"authenticated": True, "expected_fields": ["id", "name"]},
                    401: {"authenticated": False},
                },
            },
        ],
    }
```

`ForgeCase` génère automatiquement les méthodes `test_*` à la définition de la classe, un test par scénario par status code. Aucune méthode `test_*` à écrire.

### Anatomie d'une entrée `tests`

| Clé | Type | Description |
|---|---|---|
| `path_name` | `str` | Nom de la route Django passé à `reverse()` |
| `method` | `"GET" \| "POST" \| "PUT" \| "PATCH" \| "DELETE"` | Méthode HTTP |
| `test_name` | `str` (optionnel) | Override du nom généré (sinon dérivé de `path_name`) |
| `fixture` | `Fixture \| List[Fixture]` (optionnel) | Une ou plusieurs instances créées avant la requête |
| `reverse_params` | `ReverseParams` (optionnel) | `kwargs`/`args`/`query` pour `reverse()` |
| `http_client_params` | `HTTPClientParams` (optionnel) | Paramètres transmis au client de test |
| `expected_responses` | `Dict[int, Scenario \| List[Scenario]]` | Cœur de la config |

---

### LazyValue — lambdas partout

Partout où une valeur est attendue dans la config, une lambda `lambda t: ...` peut être utilisée à la place. Elle est appelée au moment de l'exécution du test avec `self` (l'instance du TestCase) en argument.

Cela s'applique à :

| Endroit | Exemple |
|---|---|
| `fixture.kwargs` | `{"owner": lambda t: t.user}` |
| `fixture.data` | `lambda t: t.existing_instance` |
| `fixture.data` (dict) | `{"name": lambda t: t.company.name}` |
| `reverse_params.kwargs` | `{"pk": lambda t: t.obj.pk}` |
| `http_client_params.fixture.data` | `{"email": lambda t: t.user.email}` |
| `expected_value_of_fields` | `{"owner_id": lambda t: t.user.pk}` |
| `config.user` / `test.user` | `lambda t: t.company.owner` |

Les lambdas sont les seules callables résolues. Les classes, `MagicMock` et autres objets callables par accident sont retournés tels quels.

```python
# Exemple complet avec lambdas dans plusieurs endroits
{
    "path_name": "api:order-detail",
    "method": "PATCH",
    "fixture": [
        {"model": Company, "object_name": "company"},
        {"model": Order, "object_name": "order",
         "kwargs": {"company": lambda t: t.company}},  # référence la fixture précédente
    ],
    "reverse_params": {"kwargs": {"pk": lambda t: t.order.pk}},
    "expected_responses": {
        200: {
            "authenticated": True,
            "http_client_params": {
                "fixture": {"data": {"status": "confirmed", "ref": lambda t: t.order.ref}}
            },
            "expected_value_of_fields": {
                "company_id": lambda t: t.company.pk,
            },
        },
    },
}
```

Si une lambda référence un attribut inexistant, une `AttributeError` explicite est levée avec le chemin exact et un rappel sur `object_name` :

```
AttributeError: fixture.kwargs['owner'] : la lambda a levé une AttributeError :
'MyTestCase' object has no attribute 'company'. Vérifiez que l'objet référencé
est bien disponible sur self (créé via object_name dans une fixture précédente,
ou défini dans setUp).
```

---

### expected_responses

Chaque status code est une clé. La valeur est soit un scénario unique, soit une liste de scénarios pour couvrir plusieurs chemins menant au même code.

#### Scénario unique

```python
"expected_responses": {
    200: {"authenticated": True, "expected_fields": ["id", "name"]},
    401: {"authenticated": False},
}
```

Génère deux tests : un pour 200, un pour 401.

#### Liste de scénarios pour le même status code

```python
"expected_responses": {
    404: [
        {"authenticated": True, "reverse_params": {"kwargs": {"pk": 999999}}},
        {"authenticated": False},
    ],
}
```

Génère deux tests 404 distincts, avec des contextes différents.

#### Clés disponibles dans un scénario

| Clé | Type | Description |
|---|---|---|
| `authenticated` | `bool` | `True` -> client connecté ; `False` -> client anonyme |
| `pre_test` | `Callable[[t], None]` | Exécuté avant la requête (voir section dédiée) |
| `reverse_params` | `ReverseParams` | Fusionné par-dessus celui du test (priorité au scénario) |
| `http_client_params` | `HTTPClientParams` | Fusionné par-dessus celui du test |
| `expected_fields` | `List[str]` | Vérifie la présence de chaque champ (notation pointée supportée) |
| `expected_value_of_fields` | `Dict[str, LazyValue]` | Vérifie la valeur exacte — accepte les lambdas |
| `expected_type_of_fields` | `Dict[str, type]` | Vérifie le type Python d'un champ |
| `forbidden_fields` | `List[str]` | Vérifie l'absence d'un champ |
| `expected_response` | `Type[Any]` | Vérifie le type du body entier (`dict`, `list`, etc.) |

#### Exemple — toutes les clés combinées

```python
"expected_responses": {
    200: {
        "authenticated": True,
        "expected_fields": ["pk", "first_name", "email"],
        "expected_value_of_fields": {
            "is_active": True,
            "owner_id": lambda t: t.user.pk,   # valeur dynamique
        },
        "expected_type_of_fields": {"pk": int},
        "forbidden_fields": ["password", "raw_token"],
        "expected_response": dict,
    },
}
```

---

### fixture — créer des instances

`fixture` accepte un seul `Fixture` ou une liste de `Fixture`. Chaque instance est créée dans l'ordre et stockée sous `self.<object_name>`.

`object_name` est obligatoire dès qu'une `fixture` est définie — validé au chargement de la classe, avant tout test.

#### Fixture simple

```python
"fixture": {
    "model": User,
    "object_name": "user",
    "kwargs": {"email": "x@y.com"},   # overrides de la factory
}
```

#### Fixture avec kwargs lambda

```python
"fixture": {
    "model": Order,
    "object_name": "order",
    "kwargs": {"owner": lambda t: t.user},   # référence self.user créé dans setUp
}
```

#### Fixture avec data fixe (pas de création en base)

```python
"fixture": {
    "object_name": "admin_user",
    "data": existing_admin_instance,   # instance directement stockée sous self.admin_user
}
```

`data` prime sur `model` + `kwargs` : aucune création n'a lieu.

#### Fixture avec data dict contenant des lambdas

```python
"fixture": {
    "object_name": "result",
    "data": {
        "email": lambda t: t.user.email,
        "role": "admin",
    },
}
```

#### Liste de fixtures — création séquentielle avec références croisées

Les fixtures sont créées dans l'ordre. Les suivantes peuvent référencer les précédentes via lambda :

```python
"fixture": [
    {"model": Company, "object_name": "company"},
    {
        "model": Branch,
        "object_name": "branch",
        "kwargs": {"company": lambda t: t.company},   # company déjà créé
    },
    {
        "model": Employee,
        "object_name": "employee",
        "kwargs": {
            "branch": lambda t: t.branch,
            "company": lambda t: t.company,
        },
    },
]
```

---

### http_client_params — envoyer un body

`http_client_params.fixture` accepte un `FixtureJson` unique ou une liste de `FixtureJson`. Dans le cas d'une liste, les dicts sont fusionnés dans l'ordre — les clés des éléments suivants écrasent celles des précédents.

#### Body généré automatiquement

```python
"http_client_params": {
    "fixture": {
        "model": User,
        "fields": ["first_name", "last_name", "email"],
    },
    "content_type": "application/json",
}
```

#### Body avec données fixes

```python
"http_client_params": {
    "fixture": {"data": {"first_name": "Alice", "last_name": "Dupont"}}
}
```

#### Body avec lambdas dans data

```python
"http_client_params": {
    "fixture": {
        "data": {
            "owner_pk": lambda t: t.user.pk,
            "name": "Test entreprise",
        }
    }
}
```

#### Liste de fixtures fusionnées

Les dicts sont fusionnés dans l'ordre. Les clés des éléments suivants écrasent celles des précédents :

```python
"http_client_params": {
    "fixture": [
        {
            "model": User,
            "fields": ["first_name", "last_name"],
        },
        {
            "data": {
                "email": lambda t: t.user.email,   # ajoute ou écrase
                "role": "admin",
            }
        },
    ],
    "content_type": "application/json",
}
```

#### Body différent selon le status code

```python
"expected_responses": {
    201: {
        "http_client_params": {
            "fixture": {"model": User, "fields": ["first_name", "last_name", "email"]}
        },
        "expected_fields": ["pk", "first_name"],
    },
    400: {
        "http_client_params": {
            "fixture": {"model": User, "fields": ["first_name"]}  # email manquant -> 400
        },
    },
}
```

---

### pre_test — préparer un scénario

`pre_test` est un callable `(t) -> None` défini dans un scénario. Il est exécuté juste avant la requête HTTP, après la création des fixtures. Il reçoit `self` (l'instance du TestCase).

Utile pour les scénarios qui nécessitent un état intermédiaire impossible à exprimer en config pure : supprimer un objet avant un 404, révoquer un token, changer un statut, etc.

#### Exemple — tester le 404 après suppression

```python
"expected_responses": {
    404: {
        "authenticated": True,
        "pre_test": lambda t: t.obj.delete(),
        "reverse_params": {"kwargs": {"pk": lambda t: t.obj.pk}},
    },
}
```

#### Exemple — révoquer des permissions avant un 403

```python
"expected_responses": {
    403: {
        "authenticated": True,
        "pre_test": lambda t: t.user.groups.clear(),
    },
}
```

#### Exemple — combiner plusieurs actions dans pre_test

```python
def prepare_expired_token(t):
    t.user.token_expires_at = timezone.now() - timedelta(hours=1)
    t.user.save()

"expected_responses": {
    401: {
        "authenticated": True,
        "pre_test": prepare_expired_token,
    },
}
```

`pre_test` peut être une fonction nommée ou une lambda. Elle est exécutée dans l'ordre suivant : création fixtures -> `pre_test` -> build du client -> construction de l'URL -> envoi de la requête -> assertions.

---

### auth_backend — authentification personnalisée

Par défaut, `authenticated: True` utilise `force_login` (session Django). Si votre projet utilise JWT ou un autre mécanisme, configurez `auth_backend` dans `config` :

```python
from rest_framework_simplejwt.tokens import RefreshToken
from django.test import Client

def jwt_auth_client(user) -> Client:
    client = Client()
    token = RefreshToken.for_user(user)
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {str(token.access_token)}"
    return client


class MyTestCase(ForgeCase):
    config: ConfigForgeCase = {
        "auth_backend": jwt_auth_client,
        "tests": [...],
    }
```

`auth_backend` est un callable `(user) -> Client`. Il reçoit `self.user` et doit retourner un `Client` Django configuré.

Pour une logique plus complexe par classe, vous pouvez aussi override la méthode directement :

```python
class MyTestCase(ForgeCase):
    config: ConfigForgeCase = {"tests": [...]}

    def _build_authenticated_client(self) -> Client:
        client = Client()
        token = RefreshToken.for_user(self.user)
        client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {str(token.access_token)}"
        return client
```

---

### Notation pointée

`expected_fields`, `expected_value_of_fields`, `expected_type_of_fields` et `forbidden_fields` acceptent des chemins imbriqués via notation pointée. Les segments numériques sont interprétés comme des index de liste.

```python
"expected_fields": [
    "results",               # data["results"]
    "results.0.pk",          # data["results"][0]["pk"]
    "results.0.author.email" # data["results"][0]["author"]["email"]
]
```

#### Exemple — réponse paginée

```python
# Réponse de l'API :
# {"count": 12, "results": [{"pk": 1, "name": "Alice", "groups": [{"id": 1}]}]}

"expected_responses": {
    200: {
        "expected_fields": ["count", "results.0.pk", "results.0.groups"],
        "expected_value_of_fields": {
            "results.0.name": "Alice",
            "results.0.groups.0.id": lambda t: t.group.pk,
        },
        "expected_type_of_fields": {"results.0.pk": int},
    }
}
```

---

### Nommage des tests générés

```
test_{method}_{base}_{status_suffix}_{scenario_index}
```

- `base` : `test_name` si fourni, sinon `path_name` slugifié (`:` et `-` remplacés par `_`)
- `status_suffix` : libellé lisible ou code brut si inconnu
- `scenario_index` : position dans la liste (0 si scénario unique)

| Status | Suffix généré |
|---|---|
| 200 | `success` |
| 201 | `created` |
| 204 | `no_content` |
| 400 | `bad_request` |
| 401 | `not_authenticated` |
| 403 | `forbidden` |
| 404 | `not_found` |
| 405 | `method_not_allowed` |
| 422 | `unprocessable` |
| 500 | `server_error` |
| autre | code brut (ex: `418`) |

#### Exemple

```python
{
    "test_name": "users_detail",
    "method": "GET",
    "expected_responses": {
        200: {"authenticated": True},
        404: [
            {"authenticated": True, "pre_test": lambda t: t.user.delete()},
            {"authenticated": False},
        ],
    },
}

# Génère :
# test_get_users_detail_success_0
# test_get_users_detail_not_found_0
# test_get_users_detail_not_found_1
```

---

### Combiner config déclarative et tests manuels

`ForgeCase` reste une `TestCase` Django classique. Ajoutez des méthodes `test_*` normales pour les scénarios trop complexes à exprimer en config.

`self.user` et `self.factory` sont disponibles dans `setUp()` et accessibles dans toutes les méthodes manuelles.

```python
class UserTestCase(ForgeCase):
    config: ConfigForgeCase = {
        "auth_backend": jwt_auth_client,
        "tests": [
            {
                "path_name": "api:users-detail",
                "method": "GET",
                "fixture": {"model": User, "object_name": "user"},
                "reverse_params": {"kwargs": {"pk": lambda t: t.user.pk}},
                "expected_responses": {
                    200: {"authenticated": True, "expected_fields": ["pk", "email"]},
                    401: {"authenticated": False},
                },
            },
        ],
    }

    def test_login_success(self):
        url = reverse("api:users-login")
        response = self.client.post(url, {"username": self.user.username, "password": "qwerty"})
        self.assertEqual(response.status_code, 200)

    def test_refresh_returns_new_access(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        token = RefreshToken.for_user(self.user)
        response = self.client.post(reverse("api:users-refresh"), {"refresh": str(token)})
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
```

---

## Référence des types

```python
# Type de base : valeur littérale ou lambda résolue au runtime
LazyValue = Union[Any, Callable[[TestCase], Any]]

ConfigForgeCase = {
    "user": Optional[LazyValue],
    "auth_backend": Optional[Callable[[User], Client]],
    "factory_params": Optional[ForgeModelFactoryParams],
    "tests": Optional[List[TestCaseConfig]],
}

TestCaseConfig = {
    "user": Optional[LazyValue],
    "test_name": str,
    "path_name": str,
    "method": Literal["GET", "POST", "PUT", "PATCH", "DELETE"],
    "reverse_params": ReverseParams,
    "http_client_params": HTTPClientParams,
    "fixture": Union[Fixture, List[Fixture]],
    "expected_responses": Dict[int, Union[ResponseValidationParams, List[ResponseValidationParams]]],
}

Fixture = {
    "object_name": str,                  # requis — validé au chargement de la classe
    "model": Type[models.Model],
    "kwargs": Dict[str, LazyValue],      # ex: {"owner": lambda t: t.user}
    "data": LazyValue,                   # instance directe, dict, ou lambda
}

FixtureJson = {
    "model": Type[models.Model],
    "fields": Optional[List[str]],
    "data": Optional[Dict[str, LazyValue]],
}

HTTPClientParams = {
    "fixture": Union[FixtureJson, List[FixtureJson]],   # liste = fusion dans l'ordre
    "content_type": str,
    "follow": bool,
    "secure": bool,
    "QUERY_STRING": str,
    "headers": Optional[Mapping[str, Any]],
}

ResponseValidationParams = {
    "pre_test": Callable[[TestCase], None],
    "reverse_params": ReverseParams,
    "http_client_params": HTTPClientParams,
    "authenticated": bool,
    "expected_response": Type[Any],
    "expected_fields": List[str],
    "expected_value_of_fields": Dict[str, LazyValue],
    "expected_type_of_fields": Dict[str, Type[Any]],
    "forbidden_fields": List[str],
}
```

---

## Exemples complets

### Exemple 1 — CRUD complet avec auth JWT

```python
from rest_framework_simplejwt.tokens import RefreshToken
from django.test import Client
from forge_test.public.helpers import ForgeCase
from forge_test.public.type import ConfigForgeCase
from myapp.models import Article

def jwt_client(user) -> Client:
    c = Client()
    token = RefreshToken.for_user(user)
    c.defaults["HTTP_AUTHORIZATION"] = f"Bearer {str(token.access_token)}"
    return c


class ArticleTestCase(ForgeCase):
    config: ConfigForgeCase = {
        "auth_backend": jwt_client,
        "factory_params": {"max_depth": 3},
        "tests": [
            {
                "test_name": "articles_list",
                "path_name": "api:article-list",
                "method": "GET",
                "fixture": {"model": Article, "object_name": "article"},
                "expected_responses": {
                    200: {
                        "authenticated": True,
                        "expected_fields": ["results.0.pk", "results.0.title"],
                        "expected_response": dict,
                    },
                    401: {"authenticated": False},
                },
            },
            {
                "test_name": "articles_detail",
                "path_name": "api:article-detail",
                "method": "GET",
                "fixture": {"model": Article, "object_name": "article"},
                "reverse_params": {"kwargs": {"pk": lambda t: t.article.pk}},
                "expected_responses": {
                    200: {
                        "authenticated": True,
                        "expected_fields": ["pk", "title", "body"],
                        "expected_type_of_fields": {"pk": int},
                    },
                    401: {"authenticated": False},
                    404: [
                        {"authenticated": True, "reverse_params": {"kwargs": {"pk": 999999}}},
                        {
                            "authenticated": True,
                            "pre_test": lambda t: t.article.delete(),
                            "reverse_params": {"kwargs": {"pk": lambda t: t.article.pk}},
                        },
                    ],
                },
            },
            {
                "test_name": "articles_create",
                "path_name": "api:article-list",
                "method": "POST",
                "http_client_params": {
                    "fixture": {"model": Article, "fields": ["title", "body"]},
                    "content_type": "application/json",
                },
                "expected_responses": {
                    201: {
                        "authenticated": True,
                        "expected_fields": ["pk", "title"],
                        "expected_response": dict,
                    },
                    400: {
                        "authenticated": True,
                        "http_client_params": {"fixture": {"data": {}}},
                    },
                    401: {"authenticated": False},
                },
            },
            {
                "test_name": "articles_update",
                "path_name": "api:article-detail",
                "method": "PATCH",
                "fixture": {"model": Article, "object_name": "article"},
                "reverse_params": {"kwargs": {"pk": lambda t: t.article.pk}},
                "expected_responses": {
                    200: {
                        "authenticated": True,
                        "http_client_params": {"fixture": {"data": {"title": "Titre modifié"}}},
                        "expected_value_of_fields": {"title": "Titre modifié"},
                    },
                    401: {"authenticated": False},
                    404: {
                        "authenticated": True,
                        "reverse_params": {"kwargs": {"pk": 999999}},
                    },
                },
            },
            {
                "test_name": "articles_delete",
                "path_name": "api:article-detail",
                "method": "DELETE",
                "fixture": {"model": Article, "object_name": "article"},
                "reverse_params": {"kwargs": {"pk": lambda t: t.article.pk}},
                "expected_responses": {
                    204: {"authenticated": True},
                    401: {"authenticated": False},
                    404: {
                        "authenticated": True,
                        "reverse_params": {"kwargs": {"pk": 999999}},
                    },
                },
            },
        ],
    }
```

### Exemple 2 — Fixtures imbriquées et body fusionné

```python
from forge_test.public.helpers import ForgeCase
from forge_test.public.type import ConfigForgeCase
from myapp.models import Company, Employee

class EmployeeTestCase(ForgeCase):
    config: ConfigForgeCase = {
        "tests": [
            {
                "test_name": "employee_create",
                "path_name": "api:company-employee-list",
                "method": "POST",
                "fixture": [
                    {"model": Company, "object_name": "company"},
                ],
                "reverse_params": {"kwargs": {"company_pk": lambda t: t.company.pk}},
                "http_client_params": {
                    "fixture": [
                        {"model": Employee, "fields": ["first_name", "last_name", "email"]},
                        {"data": {"company": lambda t: t.company.pk}},
                    ],
                    "content_type": "application/json",
                },
                "expected_responses": {
                    201: {
                        "authenticated": True,
                        "expected_fields": ["pk", "first_name", "company"],
                        "expected_value_of_fields": {
                            "company": lambda t: t.company.pk,
                        },
                    },
                    400: {"authenticated": True, "http_client_params": {"fixture": {"data": {}}}},
                    401: {"authenticated": False},
                },
            },
        ],
    }
```

### Exemple 3 — pre_test pour des scénarios complexes

```python
from forge_test.public.helpers import ForgeCase
from forge_test.public.type import ConfigForgeCase
from myapp.models import Subscription

def expire_subscription(t):
    from django.utils import timezone
    from datetime import timedelta
    t.subscription.expires_at = timezone.now() - timedelta(days=1)
    t.subscription.save()

class SubscriptionTestCase(ForgeCase):
    config: ConfigForgeCase = {
        "tests": [
            {
                "test_name": "subscription_access",
                "path_name": "api:subscription-content",
                "method": "GET",
                "fixture": {"model": Subscription, "object_name": "subscription",
                            "kwargs": {"user": lambda t: t.user}},
                "reverse_params": {"kwargs": {"pk": lambda t: t.subscription.pk}},
                "expected_responses": {
                    200: {"authenticated": True},
                    403: [
                        {
                            "authenticated": True,
                            "pre_test": expire_subscription,
                        },
                        {
                            "authenticated": True,
                            "pre_test": lambda t: t.user.groups.clear(),
                        },
                    ],
                    401: {"authenticated": False},
                },
            },
        ],
    }
```

---

## Erreurs fréquentes

| Symptôme | Cause | Comportement |
|---|---|---|
| `TypeError: object_name is required in fixture` | `fixture` sans `object_name`, ou un élément de la liste sans `object_name` | Levé à la définition de la classe |
| `AttributeError: fixture.kwargs['x'] : la lambda a levé...` | Lambda référence un attribut absent de `self` (fixture non créée, typo dans `object_name`) | Message précise la clé et rappelle de vérifier `object_name` |
| `AssertionError: Status attendu 200, reçu 401` | Client non authentifié malgré `authenticated: True` | Configurer `auth_backend` si le projet utilise JWT |
| `AssertionError: Status attendu 200, reçu 404` | Mauvais code retourné | Message inclut le body complet de la réponse |
| `AssertionError: Champ attendu 'x.y' absent de la réponse` | Chemin imbriqué incorrect ou champ manquant dans la réponse | Message précise le chemin exact testé |

---

## Bonnes pratiques

Un scénario correspond à une cause d'échec précise. Si un même status code peut être atteint par deux chemins différents (pk inexistant vs non-authentifié), utilisez une liste de scénarios plutôt qu'un scénario fourre-tout.

Utilisez `pre_test` pour les états intermédiaires qui ne peuvent pas être exprimés en config pure (suppression d'objet, expiration de token, révocation de permissions).

Vérifiez systématiquement `forbidden_fields` sur les endpoints sensibles (`password`, `token`, `otp_secret`) pour éviter les fuites silencieuses.

Donnez un `test_name` explicite dès que `path_name` ne suffit pas à distinguer deux tests sur la même route.

Limitez `max_depth` sur les modèles avec relations profondes pour éviter des temps de génération excessifs.

Utilisez les listes de fixtures pour exprimer des dépendances entre objets directement dans la config, en référençant les instances précédentes via lambda.

Configurez `auth_backend` au niveau de `config` pour partager le même mécanisme d'authentification entre toutes les classes de test du projet, plutôt que d'override `_build_authenticated_client` dans chaque classe.