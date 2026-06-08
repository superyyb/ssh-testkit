import paramiko
import logging


class SSHClient:
    def __init__(self, host, port, username, password):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.client = None

    def connect(self):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            timeout=10
        )
        logging.info(f"Connected to {self.host}:{self.port} as {self.username}")

    def run_command(self, command, timeout=30):
        if self.client is None:
            raise RuntimeError("SSH client is not connected. Call connect() first.")

        logging.info(f"Executing: {command}")
        stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)

        out = stdout.read().decode()
        err = stderr.read().decode()
        exit_code = stdout.channel.recv_exit_status()

        return {
            "command": command,
            "stdout": out,
            "stderr": err,
            "exit_code": exit_code
        }

    def close(self):
        if self.client:
            self.client.close()
            self.client = None
            logging.info("SSH connection closed")

    # Support `with SSHClient(...) as ssh:` syntax
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
