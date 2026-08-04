from __future__ import annotations

import os
import secrets
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

MASTER_KEY_BYTES = 32


class KeyStoreError(RuntimeError):
    """The local master key is missing, exposed, or malformed."""


@dataclass(frozen=True, slots=True)
class MasterKeyStore:
    path: Path

    def _read_private_key(self) -> bytes:
        try:
            metadata = self.path.lstat()
        except OSError as error:
            raise KeyStoreError("cannot inspect the local master key") from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise KeyStoreError("the local master key must be a regular file")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise KeyStoreError("the local master key must have mode 0600")

        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.path, flags)
            try:
                key = os.read(descriptor, MASTER_KEY_BYTES + 1)
            finally:
                os.close(descriptor)
        except OSError as error:
            raise KeyStoreError("cannot read the local master key") from error
        if len(key) != MASTER_KEY_BYTES:
            raise KeyStoreError("the local master key must contain exactly 32 bytes")
        return key

    def load_or_create(self) -> bytes:
        if self.path.exists() or self.path.is_symlink():
            return self._read_private_key()

        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.path.parent.chmod(0o700)
        key = secrets.token_bytes(MASTER_KEY_BYTES)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".policyseal-master-",
            dir=self.path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            written = 0
            while written < len(key):
                written += os.write(descriptor, key[written:])
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            try:
                os.link(temporary_path, self.path)
            except FileExistsError:
                return self._read_private_key()
            directory_descriptor = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError as error:
            raise KeyStoreError("cannot create the local master key") from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary_path.unlink(missing_ok=True)
        return self._read_private_key()
