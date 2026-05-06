# МПРК — Модуль преобразования режимных карт

## Как запустить

### Backend

```bash
cd backend
# первый раз: создать окружение и установить зависимости
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# запуск
.venv\Scripts\uvicorn main:app --reload
# → http://localhost:8000  |  Swagger: http://localhost:8000/docs
```

### Frontend

```bash
cd frontend
npm install        # первый раз
npm run dev
# → http://localhost:5173
```

### Docker (оба сервиса)

```bash
docker compose up
```
