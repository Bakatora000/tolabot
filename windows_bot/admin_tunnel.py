from __future__ import annotations

import socket
import subprocess
import time
from dataclasses import dataclass

from bot_config import AppConfig


@dataclass
class TunnelStatus:
    running: bool
    local_port_open: bool
    pid: int | None = None


def is_local_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def build_ssh_tunnel_command(config: AppConfig) -> list[str]:
    if not config.admin_ssh_host or not config.admin_ssh_user:
        raise ValueError("ADMIN_SSH_HOST and ADMIN_SSH_USER are required.")

    destination = f"{config.admin_ssh_user}@{config.admin_ssh_host}"
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ExitOnForwardFailure=yes",
        "-L",
        f"{config.admin_ssh_local_port}:127.0.0.1:{config.admin_ssh_remote_port}",
        destination,
        "-N",
    ]


class AdminTunnelManager:
    def __init__(self, config: AppConfig):
        self.config = config
        self.process: subprocess.Popen | None = None

    def status(self) -> TunnelStatus:
        running = self.process is not None and self.process.poll() is None
        local_port_open = is_local_port_open("127.0.0.1", self.config.admin_ssh_local_port)
        return TunnelStatus(
            running=running,
            local_port_open=local_port_open,
            pid=self.process.pid if running and self.process else None,
        )

    def start(self, startup_timeout_seconds: float = 5.0) -> TunnelStatus:
        current_status = self.status()
        if current_status.local_port_open:
            return current_status

        command = build_ssh_tunnel_command(self.config)
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags |= subprocess.CREATE_NO_WINDOW

        self.process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )

        deadline = time.time() + startup_timeout_seconds
        while time.time() < deadline:
            if self.process.poll() is not None:
                break
            if is_local_port_open("127.0.0.1", self.config.admin_ssh_local_port):
                return self.status()
            time.sleep(0.1)

        raise RuntimeError("SSH tunnel did not become ready in time.")

    def stop(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.process = None
