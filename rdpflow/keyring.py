from __future__ import annotations

from .i18n import _


class KeyringError(RuntimeError):
    pass


class PasswordKeyring:
    def __init__(self) -> None:
        try:
            import gi

            gi.require_version("Secret", "1")
            from gi.repository import Secret

            self.Secret = Secret
            self.schema = Secret.Schema.new(
                "io.github.rdpflow.Connection",
                Secret.SchemaFlags.NONE,
                {
                    "connection_id": Secret.SchemaAttributeType.STRING,
                    "kind": Secret.SchemaAttributeType.STRING,
                },
            )
        except (ImportError, ValueError) as error:
            self.Secret = None
            self.schema = None
            self.error = str(error)
        else:
            self.error = ""

    @property
    def available(self) -> bool:
        return self.Secret is not None

    @staticmethod
    def _attributes(connection_id: str, kind: str = "rdp") -> dict[str, str]:
        return {"connection_id": connection_id, "kind": kind}

    def save(self, connection_id: str, password: str, kind: str = "rdp") -> None:
        if not self.available:
            raise KeyringError(_("这台机器没有可用的密码库（需要已登录的桌面会话与 libsecret）"))
        try:
            stored = self.Secret.password_store_sync(
                self.schema,
                self._attributes(connection_id, kind),
                self.Secret.COLLECTION_DEFAULT,
                _("RDPFlow：{id}").format(id=connection_id),
                password,
                None,
            )
        except Exception as error:
            raise KeyringError(_("密码库写入失败：{error}").format(error=error)) from error
        if not stored:
            raise KeyringError(_("密码库拒绝了这次写入，密码没有保存"))

    def get(self, connection_id: str, kind: str = "rdp") -> str | None:
        if not self.available:
            return None
        try:
            return self.Secret.password_lookup_sync(
                self.schema, self._attributes(connection_id, kind), None
            )
        except Exception:
            return None

    def clear(self, connection_id: str, kind: str = "rdp") -> None:
        if not self.available:
            return
        try:
            self.Secret.password_clear_sync(
                self.schema, self._attributes(connection_id, kind), None
            )
        except Exception:
            return
