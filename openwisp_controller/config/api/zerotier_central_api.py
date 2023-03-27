import requests
from django.core.exceptions import ValidationError


class ZerotierCentralAPI:
    def _get_endpoint(self, property, operation, id):
        _API_ENDPOINTS = {
            'network': {
                'create': '/network',
                'get': f'/network/{id}',
                'update': f'/network/{id}',
                'delete': f'/network/{id}',
            }
        }
        return _API_ENDPOINTS.get(property).get(operation)

    def __init__(self, host, token) -> None:
        self.host = host
        self.token = token
        self.url = f'https://{host}/api/v1'
        self.headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }

    def create_network(self, network_id, private=False, enableBroadcast=True):
        data = {
            'config': {
                'name': network_id,
                'private': private,
                'enableBroadcast': enableBroadcast,
            }
        }
        url = f"{self.url}{self._get_endpoint('network', 'create', network_id)}"
        response = requests.post(url, json=data, headers=self.headers, timeout=5)
        if response.status_code != 200:
            raise ValidationError(
                {
                    'ZerotierCentralAPI create network error': (
                        f'({response.status_code}) {response.reason}'
                    )
                }
            )
        return response.json()

    def delete_network(self, network_id):
        url = f"{self.url}{self._get_endpoint('network', 'delete', network_id)}"
        response = requests.delete(url, headers=self.headers)
        if response.status_code != 200:
            raise ValidationError(
                {
                    'ZerotierCentralAPI delete network error': (
                        f'({response.status_code}) {response.reason}'
                    )
                }
            )
