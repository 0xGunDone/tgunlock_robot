from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol, Tuple
import shlex


class ProxyProvider(Protocol):
    async def create_proxy(self, login: str, password: str) -> Tuple[str, int]:
        ...

    async def update_password(self, login: str, new_password: str) -> None:
        ...

    async def disable_proxy(self, login: str) -> None:
        ...

    async def delete_proxy(self, login: str) -> None:
        ...


@dataclass
class MockProxyProvider:
    default_ip: str
    default_port: int

    async def create_proxy(self, login: str, password: str) -> Tuple[str, int]:
        return self.default_ip, self.default_port

    async def update_password(self, login: str, new_password: str) -> None:
        return None

    async def disable_proxy(self, login: str) -> None:
        return None

    async def delete_proxy(self, login: str) -> None:
        return None


@dataclass
class CommandProxyProvider:
    default_ip: str
    default_port: int
    cmd_create: str
    cmd_update: str
    cmd_disable: str

    async def _run(self, cmd: str) -> str:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Proxy command failed: {stderr.decode().strip()}")
        return stdout.decode().strip()

    async def create_proxy(self, login: str, password: str) -> Tuple[str, int]:
        cmd = self.cmd_create.format(login=login, password=password)
        output = await self._run(cmd)
        if output:
            parts = output.split()
            if len(parts) >= 2:
                return parts[0], int(parts[1])
        return self.default_ip, self.default_port

    async def update_password(self, login: str, new_password: str) -> None:
        cmd = self.cmd_update.format(login=login, password=new_password)
        await self._run(cmd)

    async def disable_proxy(self, login: str) -> None:
        cmd = self.cmd_disable.format(login=login)
        await self._run(cmd)

    async def delete_proxy(self, login: str) -> None:
        # Fallback to disable if delete isn't explicitly supported
        await self.disable_proxy(login)


@dataclass
class DantedPamProxyProvider:
    default_ip: str
    default_port: int
    cmd_prefix: str | None = None

    def _build_cmd(self, args: list[str]) -> list[str]:
        if self.cmd_prefix:
            return shlex.split(self.cmd_prefix) + args
        return args

    async def _run(self, args: list[str], input_text: str | None = None, check: bool = True):
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE if input_text else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input_text.encode() if input_text else None)
        if check and proc.returncode != 0:
            raise RuntimeError(stderr.decode().strip() or "Command failed")
        return proc.returncode, stdout.decode().strip(), stderr.decode().strip()

    async def _user_exists(self, login: str) -> bool:
        cmd = self._build_cmd(["getent", "passwd", login])
        code, _, _ = await self._run(cmd, check=False)
        return code == 0

    async def create_proxy(self, login: str, password: str) -> Tuple[str, int]:
        if await self._user_exists(login):
            raise RuntimeError("User already exists")
        cmd = self._build_cmd(["useradd", "--no-create-home", "--shell", "/usr/sbin/nologin", login])
        await self._run(cmd)
        cmd = self._build_cmd(["chpasswd"])
        await self._run(cmd, input_text=f"{login}:{password}\n")
        return self.default_ip, self.default_port

    async def update_password(self, login: str, new_password: str) -> None:
        cmd = self._build_cmd(["chpasswd"])
        await self._run(cmd, input_text=f"{login}:{new_password}\n")

    async def disable_proxy(self, login: str) -> None:
        cmd = self._build_cmd(["usermod", "-L", login])
        await self._run(cmd, check=False)

    async def delete_proxy(self, login: str) -> None:
        cmd = self._build_cmd(["userdel", login])
        await self._run(cmd, check=False)
