#!/bin/bash
# Start FastAPI web server in background
python3 /home/testuser/server.py &
# Start SSH server in foreground (keeps container alive)
/usr/sbin/sshd -D