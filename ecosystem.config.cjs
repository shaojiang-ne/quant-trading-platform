/**
 * pm2 ecosystem for stock project
 *
 * Usage:
 *   pm2 start ecosystem.config.cjs
 *   pm2 save                            # 生成开机自启 dump
 *   pm2 ls                              # 看运行状态
 *   pm2 logs                            # 跟日志
 *   pm2 restart all                     # 改完代码重启
 *
 * 注意：
 *   - backend 用 venv/Scripts/python.exe（Windows）避开 reload 在 anaconda 失效的坑
 *   - frontend 用 vite preview 跑生产 dist，构建产物已就绪
 *   - 端口：backend 8010 / frontend 4175；后端 host=0.0.0.0 供局域网访问
 *     （8000 / 4173 已被本机其它 pm2 应用占用：tf-aip-api、draw）
 */

const path = require('path');

const ROOT = __dirname;
const BACKEND_DIR = path.join(ROOT, 'backend');
const FRONTEND_DIR = path.join(ROOT, 'frontend');

// 端口（可用环境变量覆盖）
const BACKEND_PORT = process.env.STOCK_BACKEND_PORT || '8010';
const FRONTEND_PORT = process.env.STOCK_FRONTEND_PORT || '4175';

// Windows 下 venv 的 python 绝对路径
const BACKEND_PYTHON = path.join(BACKEND_DIR, 'venv', 'Scripts', 'python.exe');

module.exports = {
  apps: [
    {
      name: 'stock-backend',
      cwd: BACKEND_DIR,
      script: BACKEND_PYTHON,
      args: [
        '-m',
        'uvicorn',
        'app.main:app',
        '--host',
        '0.0.0.0',
        '--port',
        BACKEND_PORT,
        '--no-access-log',
      ],
      // 让 uvicorn 走 venv 的 site-packages，不依赖 PATH；关掉 --reload，
      // 改完代码用 pm2 restart stock-backend 加载（避开 Windows --reload 失效坑）
      env: {
        PYTHONUNBUFFERED: '1',
      },
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      // 单实例，重复启动会先 stop 老进程
      exec_mode: 'fork',
      instances: 1,
      out_file: path.join(BACKEND_DIR, 'logs', 'pm2-backend.out.log'),
      error_file: path.join(BACKEND_DIR, 'logs', 'pm2-backend.err.log'),
      merge_logs: true,
      time: true,
    },
    {
      name: 'stock-frontend',
      cwd: FRONTEND_DIR,
      // 直接 node 调 vite.js，避免 pm2 把 npm/vite.cmd 当 JS 跑
      script: 'node',
      args: [
        path.join(FRONTEND_DIR, 'node_modules', 'vite', 'bin', 'vite.js'),
        'preview',
        '--host',
        '0.0.0.0',
        '--port',
        FRONTEND_PORT,
      ],
      autorestart: true,
      max_restarts: 10,
      restart_delay: 3000,
      exec_mode: 'fork',
      instances: 1,
      out_file: path.join(FRONTEND_DIR, 'logs', 'pm2-frontend.out.log'),
      error_file: path.join(FRONTEND_DIR, 'logs', 'pm2-frontend.err.log'),
      merge_logs: true,
      time: true,
    },
  ],
};