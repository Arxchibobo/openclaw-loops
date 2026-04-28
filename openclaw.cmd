@echo off
REM wrapper so users can call `openclaw ...` from this dir on Windows
python "%~dp0cli\openclaw.py" %*
