REM This code is work in progress. Do not ask for support in Discord running this code.
:loop
cmd /k pipenv run python app.py amazon-aio --p "1234" --delay 1.5
timeout 360 /nobreak
goto loop
