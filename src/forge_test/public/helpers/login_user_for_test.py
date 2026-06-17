"""
Authentifie un client de test Django pour un utilisateur donné.

Implémentation par défaut basée sur force_login (session Django).
Si votre projet utilise un autre mécanisme d'authentification
(JWT, token DRF, etc.), remplacez le corps de cette fonction.
"""
from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser
from django.test import Client

__all__ = ["login_user_for_test"]


def login_user_for_test(user: AbstractBaseUser) -> Client:
    """
    Retourne un Client Django authentifié pour l'utilisateur fourni.

    Args:
        user: instance utilisateur déjà persistée en base.

    Returns:
        Un Client prêt à effectuer des requêtes authentifiées.
    """
    client = Client()
    client.force_login(user)
    return client
