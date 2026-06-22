import re
import time
import logging
import threading
 
 
class LogMonitor:
    """
    Monitors a remote log file in a background thread while tests run concurrently.
    Polls the log file every `interval` seconds and triggers an alert callback
    whenever a failure pattern is detected in new lines.
    """
 
    def __init__(self, ssh_client, log_path, fail_patterns, alert_callback, interval=2):
        """
        Args:
            ssh_client:      Connected SSHClient instance (separate from test runner's)
            log_path:        Path to the log file on the remote device
            fail_patterns:   List of regex patterns that indicate failure
            alert_callback:  Function called with the matching line when failure detected
            interval:        Seconds between each poll
        """
        self.ssh_client     = ssh_client
        self.log_path       = log_path
        self.fail_patterns  = fail_patterns
        self.alert_callback = alert_callback
        self.interval       = interval
        self._stop_event    = threading.Event()
        self._thread        = None
        self._seen_lines    = set()
 
    def start(self):
        """Start the monitor in a background daemon thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logging.info(f"LogMonitor started — watching {self.log_path} every {self.interval}s")
 
    def stop(self):
        """Signal the monitor to stop and wait for the thread to finish."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logging.info("LogMonitor stopped")
 
    def _run(self):
        """Main loop: poll log file, check new lines against fail patterns."""
        while not self._stop_event.is_set():
            try:
                result   = self.ssh_client.run_command(f"tail -n 30 {self.log_path}")
                lines    = result["stdout"].splitlines()
 
                for line in lines:
                    if line in self._seen_lines:
                        continue
 
                    self._seen_lines.add(line)
 
                    for pattern in self.fail_patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            logging.warning(f"LogMonitor: failure detected → {line}")
                            self.alert_callback(line, pattern)
                            break
 
            except Exception as e:
                logging.error(f"LogMonitor error: {e}")
 
            self._stop_event.wait(self.interval)