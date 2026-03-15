FROM python:3.10-slim

LABEL maintainer="Bridge IDE Team"
LABEL description="Bridge IDE — Multi-Agent Coordination Platform"

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    tmux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend
COPY Backend/ ./Backend/

# Copy frontend
COPY Frontend/ ./Frontend/

# Copy entrypoint
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Create runtime directories and ensure no stale host runtime overlay is baked in
RUN mkdir -p Backend/logs Backend/pids Backend/messages Backend/agent_state /root/.config/bridge \
    && rm -f Backend/runtime_team.json

# Default ports
ENV PORT=9111
ENV WS_PORT=9112
ENV BRIDGE_HTTP_HOST=0.0.0.0
ENV BRIDGE_WS_HOST=0.0.0.0

EXPOSE 9111 9112

ENTRYPOINT ["./entrypoint.sh"]
