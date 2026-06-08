import time
import logging
import serial
 
 
class SerialClient:
    """
    Serial port client with the same interface as SSHClient.
    TestRunner works with either client — no changes needed there.
 
    How serial communication works:
    - Send a command string followed by newline
    - Read bytes back until the shell prompt appears (e.g. "$ ")
    - Run `echo $?` to capture the exit code
    - Serial doesn't separate stdout/stderr, so stderr is always empty
    """
 
    def __init__(self, port, baudrate=115200, timeout=5, prompt="$ "):
        """
        Args:
            port:     Serial port path, e.g. "/dev/ttyUSB0" (Linux/Mac)
                      or "COM3" (Windows)
            baudrate: Communication speed, must match the device setting.
                      Common values: 9600, 115200
            timeout:  Read timeout in seconds
            prompt:   Shell prompt to look for when a command finishes.
                      Defaults to "$ " (bash). Use "# " for root.
        """
        self.port     = port
        self.baudrate = baudrate
        self.timeout  = timeout
        self.prompt   = prompt
        self.conn     = None
 
    def connect(self):
        self.conn = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            timeout=self.timeout
        )
        time.sleep(0.5)       # give the port time to settle
        self._flush()         # clear any stale bytes
        logging.info(f"Connected to serial port {self.port} at {self.baudrate} baud")
 
    def run_command(self, command, timeout=30):
        """
        Send a command and return its output.
        Returns the same dict shape as SSHClient.run_command() so
        TestRunner and parser.py work without modification.
        """
        if self.conn is None or not self.conn.is_open:
            raise RuntimeError("Serial port not connected. Call connect() first.")
 
        logging.info(f"Serial executing: {command}")
 
        # Send the command
        self.conn.write((command + "\n").encode())
 
        # Read output until the prompt comes back
        stdout = self._read_until_prompt(timeout)
 
        # Capture exit code by running `echo $?`
        self.conn.write(b"echo $?\n")
        exit_str = self._read_until_prompt(timeout=5).strip()
        try:
            # The last non-empty line is the exit code
            exit_code = int([l for l in exit_str.splitlines() if l.strip()][-1])
        except (ValueError, IndexError):
            exit_code = 0
 
        return {
            "command":   command,
            "stdout":    stdout,
            "stderr":    "",     # serial has no separate stderr stream
            "exit_code": exit_code
        }
 
    def close(self):
        if self.conn and self.conn.is_open:
            self.conn.close()
            self.conn = None
            logging.info(f"Serial port {self.port} closed")
 
    # ── Context manager support ───────────────────────────────────────────────
 
    def __enter__(self):
        self.connect()
        return self
 
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
 
    # ── Internal helpers ──────────────────────────────────────────────────────
 
    def _read_until_prompt(self, timeout):
        """Read bytes until the shell prompt appears or timeout is reached."""
        output = ""
        start  = time.time()
 
        while time.time() - start < timeout:
            if self.conn.in_waiting:
                chunk   = self.conn.read(self.conn.in_waiting).decode(errors="replace")
                output += chunk
                if self.prompt in output:
                    # Strip the trailing prompt from output
                    output = output[:output.rfind(self.prompt)]
                    break
            time.sleep(0.05)
 
        return output.strip()
 
    def _flush(self):
        """Clear any stale data in the serial buffers."""
        self.conn.reset_input_buffer()
        self.conn.reset_output_buffer()