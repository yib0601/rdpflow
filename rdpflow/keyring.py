from __future__ import annotations


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
            raise KeyringError("系统钥匙串不可用，请先登录桌面会话并安装 libsecret")
        try:
            stored = self.Secret.password_store_sync(
                self.schema,
                self._attributes(connection_id, kind),
                self.Secret.COLLECTION_DEFAULT,
                f"RDPFlow：{connection_id}",
                password,
                None,
            )
        except Exception as error:
            raise KeyringError(str(error)) from error
        if not stored:
            raise KeyringError("系统钥匙串拒绝了保存请求")

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
