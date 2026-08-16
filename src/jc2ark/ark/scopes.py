"""S1-2 の対策。**これが無いと権限昇格になる。**

DOT の `OAuth2Validator.validate_scopes` は
`get_scopes_backend().get_available_scopes(application=client, …)` を呼ぶので、
**拡張点は `SCOPES_BACKEND_CLASS`**（`OAUTH2_VALIDATOR_CLASS` に書いても呼ばれない）。
既定の `SettingsScopes` は設定の全 scope を返すため、放置するとどのクライアントも
全 scope のトークンを取得できる。

実測（`ark_s1_spike_result.md` S1-2）:
    既定       ark:update を要求（未付与） -> 200  scope='ark:update'
    対策後     ark:update を要求（未付与） -> 400  invalid_scope
"""

from oauth2_provider.scopes import SettingsScopes


class PerClientScopes(SettingsScopes):
    def _allowed(self, application):
        allowed = getattr(application, "allowed_scopes", None)
        return allowed.split() if allowed else None

    def get_available_scopes(self, application=None, request=None, *args, **kwargs):
        return self._allowed(application) or super().get_available_scopes(
            application, request, *args, **kwargs
        )

    def get_default_scopes(self, application=None, request=None, *args, **kwargs):
        return self._allowed(application) or super().get_default_scopes(
            application, request, *args, **kwargs
        )
