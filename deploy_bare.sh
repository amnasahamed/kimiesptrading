#!/bin/bash

# Chartink Trading Bot - Bare Metal Setup (No Docker/Coolify)
# Domain: coolify.themelon.in

echo "🚀 Starting Bare Metal Setup..."

# 1. Update system and install Python + PM2
sudo apt update
sudo apt install -y python3-pip python3-venv nodejs npm
sudo npm install -g pm2

# 2. Prepare Trading Bot Directory
mkdir -p ~/trading-bot
cd ~/trading-bot

# 3. Create Virtual Environment
python3 -m venv venv
source venv/bin/activate

# 4. Install requirements
pip install -r requirements.txt

# 5. Setup PM2 for Autostart
echo "🔄 Starting Bot with PM2..."
pm2 start "venv/bin/uvicorn chartink_webhook:app --host 0.0.0.0 --port 8000" --name trading-bot
pm2 save
pm2 startup

echo "✅ Bot is running via PM2."
echo "--------------------------------------------------"
echo "Public Access: http://$(curl -s ifconfig.me):8000/dashboard"
echo "--------------------------------------------------"
