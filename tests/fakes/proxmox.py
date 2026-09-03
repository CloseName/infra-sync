"""Small path-based fake for the proxmoxer API."""

from copy import deepcopy


class FakeProxmoxPath:
    """Collect proxmoxer-style attribute and call path segments."""

    def __init__(self, api, path=()):
        self._api = api
        self._path = path

    def __getattr__(self, name):
        return FakeProxmoxPath(
            self._api,
            self._path + (name,),
        )

    def __call__(self, value):
        return FakeProxmoxPath(
            self._api,
            self._path + (value,),
        )

    def get(self, **params):
        return self._api.get(
            self._path,
            **params,
        )


class FakeProxmox(FakeProxmoxPath):
    """Return fixture values for exact proxmoxer request paths."""

    def __init__(self, responses=None):
        self.responses = dict(responses or {})
        self.calls = []
        super().__init__(self)

    def get(self, path, **params):
        key = tuple(path)
        self.calls.append((key, dict(params)))

        if key not in self.responses:
            raise AssertionError(
                f'Unexpected Proxmox request: {key!r}'
            )

        response = self.responses[key]

        if isinstance(response, BaseException):
            raise response

        if callable(response):
            response = response(**params)

        return deepcopy(response)
