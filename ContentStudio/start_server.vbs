Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """C:\Users\VPX01\Documents\Default Project\.venv-paddle\Scripts\pythonw.exe"" -m uvicorn content_studio.web.app:app --host 127.0.0.1 --port 8000 --app-dir ""C:\Users\VPX01\Documents\Default Project""", 0, False
