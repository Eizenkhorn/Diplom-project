# МПРК — Модуль преобразования режимных карт

## Цель проекта

Веб-приложение АРМ составителя режимных карт (ВНИИЖТ). Загружает файлы Microsoft Visio (.vsd / .vsdx) с режимными картами движения поездов, отображает их содержимое на интерактивном холсте и позволяет специалисту разметить элементы — присвоить каждому объекту семантический тип (станция, профиль пути, ограничение скорости и т.д.). Результат разметки экспортируется в JSON строго определённой схемы (см. ниже).

Курсовой проект описывает задачу (предпроектный анализ, ТЗ по ГОСТ 34.602-2020), **преддипломная практика** — реализация.

---

## Стек

### Backend (`backend/`)
- Python 3.11+
- FastAPI ≥ 0.110 (REST API, OpenAPI/Swagger UI автогенерация)
- **vsdx** (Python) — парсинг ZIP-XML структуры .vsdx без установки Visio
- **LibreOffice** (headless) — конвертация старого формата `.vsd` → `.vsdx`
- Pydantic v2 — валидация и сериализация моделей
- python-multipart — загрузка файлов
- In-memory хранение сессий (dict / dataclass; никакой СУБД)

### Frontend (`frontend/`)
- React 18 + TypeScript
- Node 20 LTS
- Vite (сборка и dev-server)
- **Konva.js** (react-konva) — интерактивный векторный холст на HTML5 Canvas (zoom, pan, click-select ≥ 500 объектов без деградации)
- Zustand или React Context — состояние разметки
- Tailwind CSS (опционально, для UI)

### Инфраструктура
- Docker: два контейнера — `backend` и `frontend`
- docker-compose.yml в корне монорепо

---

## Чего **не делаем**

| Что | Почему |
|-----|--------|
| База данных (PostgreSQL, SQLite и пр.) | Не требуется по заданию на практику; сессии живут в памяти процесса |
| Аутентификация / авторизация | Нет требования; демо-стенд на localhost |
| RBAC (роли: составитель / аналитик / администратор) | Описано в ТЗ курсовой, но не входит в практику |
| OpenCV / компьютерное зрение | Автоматическое распознавание вне скоупа; только интерактивная разметка |
| CSV-экспорт | Если понадобится — добавить позже; сейчас только JSON |

---

## Структура монорепо

```
<project-root>/
├── backend/
│   ├── main.py              # FastAPI app, роутеры
│   ├── parser/              # vsdx-парсер, LibreOffice-конвертер
│   ├── models/              # Pydantic-схемы (входные/выходные)
│   ├── session/             # In-memory хранилище сессий разметки
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/      # Canvas, AnnotationPanel, ...
│   │   ├── store/           # Состояние разметки
│   │   └── api/             # Fetch-обёртки к бэкенду
│   ├── index.html
│   ├── vite.config.ts
│   └── package.json
├── samples/                 # Примеры .vsd / .vsdx / .json для тестов
├── docker-compose.yml
└── CLAUDE.md
```

---

## REST API (ключевые эндпоинты)

```
POST   /api/upload              # Загрузка .vsd или .vsdx → возвращает session_id + parsed shapes
GET    /api/sessions/{id}       # Получить состояние сессии разметки
POST   /api/sessions/{id}/annotate  # Присвоить тип элементу
DELETE /api/sessions/{id}/annotate/{shape_id}  # Снять аннотацию
GET    /api/sessions/{id}/export    # Экспорт в целевой JSON
GET    /api/annotation-types    # Справочник семантических типов
```

---

## Формат целевого JSON

Схема зафиксирована по образцу `samples/Златоуст-Кропачево (2).json`.

```jsonc
{
  "metadata": {
    "id": "nsi-2-<timestamp>",
    "name": "Название участка",
    "createdAt": "2026-04-28T11:02:35.909Z",
    "updatedAt": "2026-04-28T11:02:43.941Z"
  },

  // Координатная линейка
  // startCoordinate/endCoordinate — километры участка пути (убывают по ходу движения,
  // напр. 1943 → 1782 означает: от км 1943 до км 1782 относительно нулевого пикета сети)
  "coordinateRuler": {
    "segments": [
      { "startCoordinate": 1943, "endCoordinate": 1782, "adjustments": [] }
    ]
  },

  // Станции / раздельные пункты
  // coordinate — координата в системе сети: kilometres × 1000 (метры от нулевого пикета).
  // Та же система, что у speedLimits.start/end. Пример: 1940400 = км 1940,4 сети.
  "stations": [
    {
      "name": "Златоуст",
      "coordinate": 1940400,
      "graphical": {
        "layerPosition": 0,
        "coordinate": 1940400,
        "horizontalOffset": 0,
        "verticalPositionPercent": 50, // 0–100, положение по вертикали холста
        "fontSize": 11,
        "fontColor": "#374151",
        "lineHeight": 14,
        "rotation": 0,
        "objectColor": "#1d4ed8"
      }
    }
  ],

  // Профиль пути: сегменты уклонов
  // start/end — ОТДЕЛЬНАЯ система координат: расстояние в метрах от начала данного участка
  // (0 … длина_участка; для Златоуст–Кропачево ~162 000 м = ~162 км).
  // Не связаны с координатами сети из stations/speedLimits.
  // angle — уклон в ‰ (промилле), знак: «+» — подъём, «–» — спуск
  "profile": [
    { "start": 0,   "end": 840,  "angle": -8.3 },
    { "start": 840, "end": 1050, "angle": -0.1 }
  ],

  // Ограничения скорости
  // start/end — координата сети (kilometres × 1000, та же система, что stations.coordinate;
  // убывают по ходу движения, как у coordinateRuler)
  // limit — км/ч; type — "track_category" | "temporary" | ...
  "speedLimits": [
    { "start": 1940900, "end": 1939100, "limit": 45, "type": "track_category" }
  ],

  // Эти массивы также подлежат разметке, но в MVP практики оставляем пустыми.
  // Следующая итерация — расширение справочника типов аннотаций для их заполнения.
  "locomotives": [],
  "cars": [],
  "canvasLayers": [],
  "trackPlan": [],
  "optimalSpeedCurve": [],
  "speedCurve": [],
  "optimalRegimeBands": [],
  "locomotiveRegimeBands": [],
  "longitudinalForces": [],
  "marks": []
}
```

### Семантические типы аннотаций (справочник)

| Тип | Поле JSON | Описание |
|-----|-----------|----------|
| `station` | `stations[]` | Станция / раздельный пункт |
| `profile_segment` | `profile[]` | Элемент продольного профиля (уклон) |
| `speed_limit` | `speedLimits[]` | Постоянное ограничение скорости |
| `coordinate_ruler` | `coordinateRuler` | Граница координатной линейки |

---

## Процесс парсинга .vsdx

1. **Если `.vsd`** — конвертировать через LibreOffice headless:
   ```
   soffice --headless --convert-to vsdx <file.vsd>
   ```
2. Открыть `.vsdx` как ZIP, прочитать XML страниц через библиотеку `vsdx`.
3. Из каждой фигуры (`Shape`) извлечь геометрию с учётом особенностей формата Visio:
   - **Единицы** — все координаты в XML хранятся в **дюймах**; перевод в пиксели: `px = inches × 96`.
   - **PinX / PinY** — координаты *центра* фигуры в системе родителя. Левый верхний угол bounding box:
     `x = PinX - LocPinX`, `y = PinY - LocPinY` (LocPinX/LocPinY — смещение точки привязки внутри фигуры, обычно Width/2 и Height/2).
   - **Ось Y** — в Visio Y растёт **вверх** (как в математике), в Konva — **вниз**. При преобразовании:
     `y_konva = page_height_px - (PinY_px + height_px/2)` (отражение относительно высоты страницы).
   - **Группы** (`Type="Group"`) — обходить рекурсивно; координаты дочерних фигур заданы относительно родителя. Накапливать трансформацию (смещение + масштаб) при обходе дерева, чтобы вычислить абсолютные координаты каждого листового объекта.
   - Из каждой фигуры также извлекать: `id`, `text`, `line_style`, `fill_color`.
4. Вернуть плоский список объектов (shapes) с абсолютными координатами в пикселях фронтенду.
5. Фронтенд рендерит shapes на Konva.js Stage; специалист кликает, выбирает тип → POST /annotate.
6. При экспорте бэкенд собирает аннотированные объекты в целевую JSON-схему.

---

## Как запустить

```bash
# Backend
cd backend
uvicorn main:app --reload          # http://localhost:8000  (Swagger: /docs)

# Frontend
cd frontend
npm run dev                        # http://localhost:5173

# Docker (оба сервиса)
docker compose up                  # из корня монорепо
```

---

## Ключевые ограничения реализации

- Холст должен обрабатывать ≥ 500 объектов без деградации (требование из задания на практику).
- API документируется автоматически через Swagger UI (`/docs`).
- Весь код в Git; демонстрация на `localhost` с реальными `.vsdx` из `samples/`.
- Функциональное тестирование — минимум на 5 файлах из `samples/`.
