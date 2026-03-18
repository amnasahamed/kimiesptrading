module.exports = {
  apps: [
    {
      name: 'trading-bot',
      script: 'venv/bin/python3',
      args: '-m uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1',
      cwd: '/root/trading-bot',
      interpreter: 'none',
      autorestart: true,
      watch: false,
      max_restarts: 10,
      restart_delay: 3000,
      env: {
        PYTHONUNBUFFERED: '1',
        PYTHONPATH: '/root/trading-bot',
      },
      error_file: '/root/.pm2/logs/trading-bot-error.log',
      out_file: '/root/.pm2/logs/trading-bot-out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
    },
  ],
};
