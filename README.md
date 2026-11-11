# TaskListBackend
Сервис учета выполняемых работ

🚀 Запуск сервера на разных операционных системах

Команды запуска приложения в терминале также имеют небольшие различия:
• Запуск на Linux (Ubuntu/Debian/CentOS):bash
# Установка зависимостей
pip3 install fastapi uvicorn python-jose[cryptography] passlib python-multipart python-dotenv aiosqlite ldap3

# Запуск в режиме разработки
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
Используйте код с осторожностью.
• Запуск на Windows (PowerShell / CMD):powershell
# Установка зависимостей
pip install fastapi uvicorn python-jose[cryptography] passlib python-multipart python-dotenv aiosqlite ldap3

# Запуск в режиме разработки
uvicorn main:app --host 0.0.0.0 --port 8000 --reload




📋 Важные правила для файла .env при кроссплатформенном запуске

В зависимости от ОС, на которой вы запускаете бэкенд, формат строки подключения DATABASE_URL в файле .env будет немного отличаться:
• Для Linux / macOS:
Используется стандартный относительный путь через три слэша:ini
DATABASE_URL=sqlite+aiosqlite:///./database.db
Используйте код с осторожностью.
• Для Windows:
Если вы используете относительный путь, формат остается таким же. Но если вам потребуется указать абсолютный путь к файлу базы данных на диске Windows (например, на диске C: или D:), необходимо использовать четыре слэша:ini
DATABASE_URL=sqlite+aiosqlite:////C:/project/asutp_journal/database.db
Используйте код с осторожностью.
Скопировать код в буфер обмена.
