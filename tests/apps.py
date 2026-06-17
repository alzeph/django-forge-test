from django.apps import AppConfig


class TestsAppConfig(AppConfig):
    name = "tests"
    label = "testapp"
    default_auto_field = "django.db.models.AutoField"
