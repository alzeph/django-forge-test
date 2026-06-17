# Forge Test

Génération de fixtures et tests d'API auto-générés pour Django + DRF.

Forge Test élimine le boilerplate des tests d'endpoints REST. Au lieu d'écrire une méthode `test_*` par cas, vous décrivez une configuration déclarative — Forge Test génère, exécute et nomme les tests pour vous.

## Sommaire

- [Composants](#composants)
- [ForgeModelFactory](#forgemodelfactory)
- [ForgeCase](#forgecase)
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
| `fill_images` | `bool` | `False` | Génère une image pour les `ImageField` optionnels. Les champs requis sont toujours remplis, indépendamment de ce flag |
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
# shop.full_name      -> "Claire Dupont"   (Faker.name)
# shop.shop_name       -> "Dupont & Fils"   (Faker.company)
# shop.description    -> phrase de 15 à 30 mots
```

### Méthodes principales

#### `create(model, **overrides) -> M`

Crée et persiste une instance en base, avec gestion automatique des FK/O2O/M2M.

```python
user = factory.create(User)
# user est un User réellement sauvegardé en base, avec toutes ses FK résolues

user_custom = factory.create(User, email="custom@test.com", first_name="Alice")
# les valeurs passées en kwargs écrasent celles générées par la factory
```

Exemple avec relations imbriquées :

```python
# Si Order a une FK vers Customer, et Customer une FK vers Address,
# create() résout toute la chaîne automatiquement (jusqu'à max_depth)
order = factory.create(Order)
print(order.customer.address.city)  # une vraie valeur générée, pas None
```

#### `build(model, **overrides) -> M`

Construit une instance sans la sauvegarder.

```python
draft = factory.build(User)
print(draft.pk)  # None — rien n'est en base

draft.email = "verifie@avant-save.com"
draft.save()
```

#### `generate_fields_dict(model, fields=None, **overrides) -> Dict[str, Any]`

Retourne un simple `dict` de valeurs — utile pour le body d'une requête POST/PATCH, sans toucher la base.

```python
payload = factory.generate_fields_dict(
    User,
    fields=["first_name", "last_name", "email"],
)
# {'first_name': 'Alice', 'last_name': 'Dupont', 'email': 'alice123@test.com'}

response = client.post(url, payload, content_type="application/json")
```

Exemple — tous les champs, avec un override :

```python
payload = factory.generate_fields_dict(User, email="forced@test.com")
# tous les champs du modèle sont générés, sauf 'email' qui vaut 'forced@test.com'
```

### Gestion des fichiers et images

| Cas | Comportement |
|---|---|
| `ImageField` requis (`null=False, blank=False`) | Image générée systématiquement, peu importe `fill_images` |
| `ImageField` optionnel | Dépend de `fill_images` (`True` -> image, `False` -> `None`) |
| `FileField` requis, extensions non-image (`pdf`, `csv`, etc.) | Fichier généré selon l'extension acceptée |
| `FileField` requis, extensions image uniquement | Image générée, même si `fill_images=False` |
| `FileField` optionnel, extensions image uniquement | Dépend de `fill_images` |

Règle générale : un champ requis est toujours rempli. `fill_images` ne s'applique qu'aux champs optionnels.

```python
factory = ForgeModelFactory(fill_images=False)

# avatar = models.ImageField(null=True, blank=True)   -> None
# photo_identite = models.ImageField()                -> image générée (requis)

user = factory.create(User)
print(user.avatar)           # None
print(user.photo_identite)   # InMemoryUploadedFile
```

---

## ForgeCase

### Principe

```python
from forge_test.public.helpers import ForgeCase, ConfigForgeCase

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

Pas de méthode `test_*` à écrire : `ForgeCase` les génère automatiquement à la définition de la classe, un test par scénario par status code.

### Anatomie d'une entrée `tests`

| Clé | Type | Description |
|---|---|---|
| `path_name` | `str` | Nom de la route Django (`reverse()`) |
| `method` | `"GET" \| "POST" \| "PUT" \| "PATCH" \| "DELETE"` | Méthode HTTP |
| `test_name` | `str` (optionnel) | Override du nom généré (sinon dérivé de `path_name`) |
| `fixture` | `Fixture` (optionnel) | Instance créée avant la requête, accessible via `object_name` |
| `reverse_params` | `ReverseParams` (optionnel) | `kwargs`/`args`/`query` pour `reverse()` |
| `http_client_params` | `HTTPClientParams` (optionnel) | Paramètres transmis au client de test |
| `expected_responses` | `Dict[int, Scenario \| List[Scenario]]` | Cœur de la config — voir ci-dessous |

### expected_responses

Chaque status code est une clé. La valeur est soit un scénario unique, soit une liste de scénarios, pour couvrir plusieurs chemins menant au même code.

#### Exemple — scénario unique par status code

```python
"expected_responses": {
    200: {"authenticated": True, "expected_fields": ["id", "name"]},
    401: {"authenticated": False},
}
```

Génère deux tests : un pour 200, un pour 401.

#### Exemple — plusieurs scénarios pour un même status code

```python
"expected_responses": {
    404: [
        {"authenticated": True, "reverse_params": {"kwargs": {"pk": 999999}}},
        {"authenticated": False},
    ],
}
```

Génère deux tests distincts, tous deux attendant un 404, mais via deux chemins différents : un pk inexistant pour le premier, l'absence d'authentification pour le second.

#### Clés disponibles dans un scénario (`ResponseValidationParams`)

| Clé | Type | Effet |
|---|---|---|
| `authenticated` | `bool` | `True` -> client connecté ; `False` -> client anonyme |
| `reverse_params` | `ReverseParams` | Fusionné par-dessus celui du test (priorité au scénario) |
| `http_client_params` | `HTTPClientParams` | Fusionné par-dessus celui du test |
| `expected_fields` | `List[str]` | Vérifie la présence de chaque champ |
| `expected_value_of_fields` | `Dict[str, Any]` | Vérifie la valeur exacte d'un champ |
| `expected_type_of_fields` | `Dict[str, type]` | Vérifie le type Python d'un champ |
| `forbidden_fields` | `List[str]` | Vérifie l'absence d'un champ |
| `expected_response` | `Type[Any]` | Vérifie le type du body entier |

#### Exemple — toutes les clés combinées

```python
"expected_responses": {
    200: {
        "authenticated": True,
        "expected_fields": ["pk", "first_name", "email"],
        "expected_value_of_fields": {"is_active": True},
        "expected_type_of_fields": {"pk": int},
        "forbidden_fields": ["password", "raw_token"],
        "expected_response": dict,
    },
}
```

### Notation pointée — champs imbriqués et listes

`expected_fields`, `expected_value_of_fields`, etc. acceptent des chemins imbriqués.

```python
"expected_fields": [
    "results",
    "results.0.pk",
    "results.0.author.email",
]
```

Fonctionne sur les `dict` et les `list` : les segments numériques sont interprétés comme des index de liste.

#### Exemple — réponse paginée

```python
# Réponse réelle de l'API :
# {"count": 12, "results": [{"pk": 1, "name": "Alice"}, {"pk": 2, "name": "Bob"}]}

"expected_responses": {
    200: {
        "expected_fields": ["count", "results.0.pk", "results.0.name", "results.1.pk"],
        "expected_value_of_fields": {"results.0.name": "Alice"},
    }
}
```

### Référencer une fixture dans l'URL — lambdas

Pour injecter le `pk` (ou autre) d'une fixture créée dans `reverse_params.kwargs`, utilisez une lambda recevant l'instance du test en argument.

```python
"fixture": {"model": Group, "object_name": "group"},
"reverse_params": {"kwargs": {"pk": lambda t: t.group.pk}},
```

#### Exemple — référence imbriquée

```python
"fixture": {"model": Order, "object_name": "order"},
"reverse_params": {"kwargs": {"pk": lambda t: t.order.customer.pk}},
```

#### Exemple — mélange de lambda et de valeur fixe

```python
"reverse_params": {
    "kwargs": {
        "pk": lambda t: t.user.pk,
        "version": "v2",
    }
}
```

Si la lambda référence un attribut inexistant (fixture absente, faute de frappe dans le nom de l'attribut), `ForgeCase` lève une `AttributeError` explicite indiquant la clé de `kwargs` concernée et rappelant de vérifier `object_name` dans `fixture`.

```python
# Erreur typique si "group" n'a pas été créé via une fixture nommée "group" :
# AttributeError: reverse_params.kwargs['pk'] : la lambda a levé une AttributeError :
# 'GroupTestCase' object has no attribute 'group'. Vérifiez que l'objet référencé
# existe bien (object_name correct dans fixture).
```

### fixture — créer une instance et la rendre accessible

```python
"fixture": {
    "model": User,
    "object_name": "user",
    "kwargs": {"email": "x@y.com"},
}
```

`object_name` est obligatoire dès qu'une `fixture` est définie. C'est validé au chargement de la classe (avant l'exécution de tout test), pas seulement au runtime.

#### Exemple — fixture avec données fixes plutôt que générées

```python
"fixture": {
    "object_name": "admin_user",
    "data": existing_admin_instance,
}
```

Si `data` est fourni, il prime sur `model` + `kwargs` : aucune création n'a lieu, l'instance fournie est simplement stockée sous `self.admin_user`.

#### Exemple — utiliser la fixture dans une méthode de test manuelle

```python
class OrderTests(ForgeCase):
    config: ConfigForgeCase = {
        "tests": [
            {
                "path_name": "api:order-detail",
                "method": "GET",
                "fixture": {"model": Order, "object_name": "order"},
                "reverse_params": {"kwargs": {"pk": lambda t: t.order.pk}},
                "expected_responses": {200: {"authenticated": True}},
            }
        ]
    }

    def test_order_total_is_positive(self):
        order = self.factory.create(Order)
        self.assertGreater(order.total, 0)
```

### Envoyer un body — http_client_params.fixture

Pour un POST/PATCH, le body est généré via une `FixtureJson` (différente de `Fixture` — pas de persistance en base).

#### Exemple — body généré automatiquement

```python
"http_client_params": {
    "fixture": {
        "model": User,
        "fields": ["first_name", "last_name", "email"],
    },
    "content_type": "application/json",
}
```

#### Exemple — body avec des données fixes

```python
"http_client_params": {
    "fixture": {"data": {"first_name": "Alice", "last_name": "Dupont"}}
}
```

#### Exemple — body différent selon le status code attendu

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

### Convention de nommage des tests générés

```
test_{method}_{base}_{status_suffix}_{scenario_index}
```

- `base` correspond à `test_name` si fourni, sinon à `path_name` slugifié
- `status_suffix` est un libellé lisible (`success`, `not_found`, `bad_request`, etc.) ou le code brut si inconnu
- `scenario_index` correspond à la position dans la liste de scénarios (0 si scénario unique)

#### Exemple — noms générés

```python
{
    "test_name": "users_detail",
    "method": "GET",
    "expected_responses": {
        200: {"authenticated": True},
        404: [
            {"authenticated": True, "reverse_params": {"kwargs": {"pk": 999999}}},
            {"authenticated": False},
        ],
    },
}

# Génère :
# test_get_users_detail_success_0
# test_get_users_detail_not_found_0
# test_get_users_detail_not_found_1
```

### Combiner config déclarative et tests manuels

`ForgeCase` reste une `TestCase` Django classique — ajoutez des méthodes `test_*` normales pour les scénarios trop spécifiques (login, refresh token, etc.).

```python
class UserTestCase(ForgeCase):
    config: ConfigForgeCase = {
        "tests": [
            {
                "path_name": "forge_auth:users-detail",
                "method": "GET",
                "fixture": {"model": User, "object_name": "user"},
                "reverse_params": {"kwargs": {"pk": lambda t: t.user.pk}},
                "expected_responses": {200: {"authenticated": True}},
            },
        ]
    }

    def test_login_success(self):
        url = reverse("forge_auth:users-login")
        response = self.client.post(url, {"username": self.user.username, "password": "qwerty123"})
        self.assertEqual(response.status_code, 200)

    def test_refresh_token_returns_new_access(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        token = RefreshToken.for_user(self.user)
        response = self.client.post(reverse("forge_auth:users-refresh"), {"refresh": str(token)})
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
```

`self.user` et `self.factory` sont disponibles dans `setUp()`, donc accessibles dans toute méthode manuelle.

---

## Référence des types

```python
ConfigForgeCase = {
    "user": Optional[User],
    "factory_params": Optional[ForgeModelFactoryParams],
    "tests": Optional[List[TestCaseConfig]],
}

TestCaseConfig = {
    "user": Optional[User],
    "test_name": str,
    "path_name": str,
    "method": Literal["GET", "POST", "PUT", "PATCH", "DELETE"],
    "reverse_params": ReverseParams,
    "http_client_params": HTTPClientParams,
    "fixture": Fixture,
    "expected_responses": Dict[int, Union[ResponseValidationParams, List[ResponseValidationParams]]],
}

Fixture = {
    "object_name": str,            # requis si fixture présente
    "model": Type[models.Model],
    "kwargs": Dict[str, Any],
    "data": Any,                    # si fourni, prime sur model+kwargs
}

ResponseValidationParams = {
    "reverse_params": ReverseParams,
    "http_client_params": HTTPClientParams,
    "authenticated": bool,
    "expected_response": Type[Any],
    "expected_fields": List[str],
    "expected_value_of_fields": Dict[str, Any],
    "expected_type_of_fields": Dict[str, Type[Any]],
    "forbidden_fields": List[str],
}
```

---

## Exemples complets

### Exemple 1 — CRUD complet sur une ressource

```python
from forge_test.public.helpers import ForgeCase, ConfigForgeCase
from myapp.models import Article

class ArticleTestCase(ForgeCase):
    config: ConfigForgeCase = {
        "factory_params": {"max_depth": 3},
        "tests": [
            # LIST
            {
                "test_name": "articles_list",
                "path_name": "api:article-list",
                "method": "GET",
                "fixture": {"model": Article, "object_name": "article"},
                "expected_responses": {
                    200: {"authenticated": True, "expected_fields": ["results.0.pk", "results.0.title"]},
                    401: {"authenticated": False},
                },
            },
            # DETAIL
            {
                "test_name": "articles_detail",
                "path_name": "api:article-detail",
                "method": "GET",
                "fixture": {"model": Article, "object_name": "article"},
                "reverse_params": {"kwargs": {"pk": lambda t: t.article.pk}},
                "expected_responses": {
                    200: {"authenticated": True, "expected_fields": ["pk", "title", "body"]},
                    404: {"authenticated": True, "reverse_params": {"kwargs": {"pk": 999999}}},
                },
            },
            # CREATE
            {
                "test_name": "articles_create",
                "path_name": "api:article-list",
                "method": "POST",
                "http_client_params": {
                    "fixture": {"model": Article, "fields": ["title", "body"]},
                    "content_type": "application/json",
                },
                "expected_responses": {
                    201: {"authenticated": True, "expected_fields": ["pk", "title"]},
                    401: {"authenticated": False},
                },
            },
            # UPDATE
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
                },
            },
            # DELETE
            {
                "test_name": "articles_delete",
                "path_name": "api:article-detail",
                "method": "DELETE",
                "fixture": {"model": Article, "object_name": "article"},
                "reverse_params": {"kwargs": {"pk": lambda t: t.article.pk}},
                "expected_responses": {
                    204: {"authenticated": True},
                    401: {"authenticated": False},
                },
            },
        ],
    }
```

### Exemple 2 — endpoint avec relation imbriquée

```python
from forge_test.public.helpers import ForgeCase, ConfigForgeCase
from myapp.models import Comment

class CommentTestCase(ForgeCase):
    config: ConfigForgeCase = {
        "tests": [
            {
                "path_name": "api:article-comment-detail",
                "method": "GET",
                "fixture": {"model": Comment, "object_name": "comment"},
                "reverse_params": {
                    "kwargs": {
                        "article_pk": lambda t: t.comment.article.pk,
                        "pk": lambda t: t.comment.pk,
                    }
                },
                "expected_responses": {
                    200: {
                        "authenticated": True,
                        "expected_fields": ["pk", "body", "author.pk", "author.username"],
                        "forbidden_fields": ["author.password"],
                    },
                },
            },
        ],
    }
```

### Exemple 3 — endpoint d'action personnalisée (non-CRUD)

```python
from forge_test.public.helpers import ForgeCase, ConfigForgeCase
from myapp.models import User

class VerifyEmailTestCase(ForgeCase):
    config: ConfigForgeCase = {
        "tests": [
            {
                "path_name": "api:users-verify-email",
                "method": "POST",
                "fixture": {
                    "model": User,
                    "object_name": "user_test",
                    "kwargs": {"email": "test@test.com"},
                },
                "expected_responses": {
                    200: {
                        "authenticated": True,
                        "http_client_params": {"fixture": {"data": {"verify": "test@test.com"}}},
                        "expected_type_of_fields": {"exists": bool},
                        "expected_value_of_fields": {"exists": True},
                    },
                    400: {"authenticated": True},
                },
            },
        ],
    }
```

---

## Erreurs fréquentes

| Symptôme | Cause probable | Comportement |
|---|---|---|
| `TypeError: object_name is required in fixture` | `fixture` sans `object_name` | Levé à la définition de la classe, avant tout test |
| `AttributeError: ... la lambda a levé une AttributeError` | Lambda référence un attribut inexistant (fixture non créée, typo) | Précise la clé `kwargs` concernée |
| `AssertionError: Status attendu 200, reçu 404` | Mauvais code retourné par l'API | Inclut le body complet de la réponse |
| `AssertionError: Champ attendu 'x.y' absent de la réponse` | Chemin imbriqué incorrect ou champ manquant côté API | Précise le chemin exact testé |

---

## Bonnes pratiques

- Un scénario correspond à une cause d'échec précise. Si un même status code peut être atteint par deux chemins différents (mauvais `pk` contre absence d'authentification), utilisez une liste de scénarios plutôt qu'un seul scénario fourre-tout.
- Vérifiez systématiquement `forbidden_fields` sur les endpoints sensibles (`password`, `token`) pour éviter les fuites silencieuses.
- Donnez un `test_name` explicite dès que `path_name` ne suffit pas à distinguer deux tests sur la même route.
- Limitez `max_depth` sur les modèles avec relations profondes pour éviter des temps de génération excessifs.
- Préférez les lambdas aux chemins de chaînes pour toute référence à une fixture dans `reverse_params.kwargs` — l'IDE détecte les fautes de frappe avant l'exécution.
