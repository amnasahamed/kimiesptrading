#!/bin/bash

# Chartink Trading Bot - Server Setup & Coolify Installation
# Subdomain: coolify.themelon.in

echo "🚀 Starting Server Setup..."

# 1. Update system
sudo apt update && sudo apt upgrade -y

# 2. Install Docker
if ! command -v docker &> /dev/null; then
    echo "🐳 Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
fi

# 3. Install Coolify
echo "🌀 Installing Coolify..."
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash

# 4. Prepare Trading Bot Directory
echo "📁 Preparing Trading Bot for coolify.themelon.in..."
mkdir -p ~/trading-bot
cd ~/trading-bot

# 5. Create basic files
echo "📄 Writing Docker configurations..."
cat > Dockerfile <<EOF
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "chartink_webhook:app", "--host", "0.0.0.0", "--port", "8000"]
EOF

cat > docker-compose.yml <<EOF
version: '3.8'
services:
  trading-bot:
    build: .
    container_name: trading-bot
    restart: always
    ports:
      - "8000:8000"
    volumes:
      - ./config.json:/app/config.json
      - ./trades_log.json:/app/trades_log.json
    environment:
      - PYTHONUNBUFFERED=1
EOF

echo "✅ Server is prepared."
echo "--------------------------------------------------"
echo "Next Steps for Domain: coolify.themelon.in"
echo "1. Access Coolify at: http://$(curl -s ifconfig.me):3000"
echo "2. Create a NEW 'Docker Compose' resource in Coolify."
echo "3. Paste the contents of ~/trading-bot/docker-compose.yml"
echo "4. In the 'Domains' field, enter: https://coolify.themelon.in"
echo "5. Ensure your DNS CNAME/A record for coolify.themelon.in points to $(curl -s ifconfig.me)"
echo "--------------------------------------------------"
