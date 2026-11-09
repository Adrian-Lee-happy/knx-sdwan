FROM python:3.13-alpine@sha256:1e1f6334529d1fb26a2ef619d7cffb30a7c7d7cc1cc7338ebee283a58d1aeaca
LABEL org.opencontainers.image.title="HA Customer C remote maintenance node"
RUN apk add --no-cache iproute2 nftables wireguard-tools openssh-server iptables conntrack-tools
WORKDIR /app
COPY node_policy.py linux_backend.py agent_runtime.py agent_service.py bootstrap.py healthcheck.py process_supervisor.py /app/
RUN ln -s /data/node /state
LABEL io.hass.type="addon" io.hass.version="0.1.2" io.hass.name="Customer C remote maintenance"
CMD ["python", "/app/bootstrap.py"]
HEALTHCHECK --interval=30s --timeout=6s --start-period=40s --retries=3 CMD ["python", "/app/healthcheck.py"]
