#!/bin/bash

echo "========================================"
echo "  KnowClaw - 智能知识问答系统"
echo "========================================"
echo ""

echo "[1/3] 安装后端依赖..."
cd backend
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "安装后端依赖失败"
    exit 1
fi

echo ""
echo "[2/3] 启动后端服务 (http://localhost:8000)..."
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

echo ""
echo "[3/3] 启动前端服务 (http://localhost:5173)..."
cd ../frontend
npm install
npm run dev &
FRONTEND_PID=$!

echo ""
echo "========================================"
echo "  服务已启动"
echo "  前端: http://localhost:5173"
echo "  后端: http://localhost:8000"
echo "  API文档: http://localhost:8000/docs"
echo "========================================"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 捕获退出信号
trap "kill $BACKEND_PID $FRONTEND_PID; exit" SIGINT SIGTERM

wait
