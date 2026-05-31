@echo off
echo ========================================
echo   KnowClaw - 智能知识问答系统
echo ========================================
echo.

echo [1/3] 安装后端依赖...
cd backend
pip install -r requirements.txt
if errorlevel 1 (
    echo 安装后端依赖失败
    pause
    exit /b 1
)

echo.
echo [2/3] 启动后端服务 (http://localhost:8000)...
start "KnowClaw Backend" cmd /k "cd /d %cd% && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

echo.
echo [3/3] 启动前端服务 (http://localhost:5173)...
cd ..\frontend
start "KnowClaw Frontend" cmd /k "cd /d %cd% && npm install && npm run dev"

echo.
echo ========================================
echo   服务已启动
echo   前端: http://localhost:5173
echo   后端: http://localhost:8000
echo   API文档: http://localhost:8000/docs
echo ========================================
echo.
pause
