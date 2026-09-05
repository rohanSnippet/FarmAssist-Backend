from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'api'

    def ready(self):
        from . import queue_worker
        queue_worker.start_worker()
