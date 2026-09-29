@echo off
cd /d "%~dp0"

rem External OpenAI-compatible API settings.
rem Fill RS_AGENT_LLM_BASE_URL, RS_AGENT_LLM_MODEL and RS_AGENT_LLM_API_KEY
rem in this terminal if you want to enable external model tool calling.
if "%RS_AGENT_LLM_BASE_URL%"=="" echo RS_AGENT_LLM_BASE_URL is empty; external LLM fallback will be disabled.
if "%RS_AGENT_LLM_MODEL%"=="" echo RS_AGENT_LLM_MODEL is empty; external LLM fallback will be disabled.
if "%RS_AGENT_LLM_API_KEY%"=="" echo RS_AGENT_LLM_API_KEY is empty; the local rule-based pipeline will still run.

echo Random signal agent will run at:
echo http://127.0.0.1:8001/chat
echo.
echo Keep this window open while using the website.
echo.

python server.py --host 127.0.0.1 --port 8001
pause
