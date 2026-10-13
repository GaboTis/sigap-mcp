module.exports = {
  apps: [{
    name: 'sigap-mcp',
    script: 'C:\\Users\\User\\Documents\\CODE\\sigap-mcp\\venv\\Scripts\\uvicorn.exe',
    args: 'app.main:app --host 0.0.0.0 --port 8100',
    cwd: 'C:\\Users\\User\\Documents\\CODE\\sigap-mcp',
    interpreter: 'none',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '500M',
    error_file: './logs/pm2-error.log',
    out_file: './logs/pm2-out.log',
    log_date_format: 'YYYY-MM-DD HH:mm:ss',
    merge_logs: true,
    min_uptime: '10s',
    max_restarts: 10,
    kill_timeout: 5000
  }]
};
