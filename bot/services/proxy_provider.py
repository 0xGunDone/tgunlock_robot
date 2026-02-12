from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol, Tuple


class ProxyProvider(Protocol):
    async def create_proxy(self, login: str, password: str) -> Tuple[str, int]:
        ...

    async def update_password(self, login: str, new_password: str) -> None:
        ...

    async def disable_proxy(self, login: str) -> None:
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
