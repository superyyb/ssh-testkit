FROM ubuntu:22.04
 
RUN apt-get update && apt-get install -y \
    openssh-server \
    python3 \
    python3-pip \
    bash \
    curl \
    net-tools \
    iproute2 \
    && mkdir /var/run/sshd
 
RUN pip3 install fastapi uvicorn
 
RUN useradd -m testuser && echo "testuser:testpass" | chpasswd
 
RUN mkdir -p /home/testuser/app_logs
RUN mkdir -p /home/testuser/device_logs
 
COPY sample_device_log.txt /home/testuser/device_logs/device.log
COPY server.py /home/testuser/server.py
COPY entrypoint.sh /entrypoint.sh
 
EXPOSE 22 8080
 
CMD ["/entrypoint.sh"]