# Зафиксированный стек разработки

Обновлено 23.11.2026 после первого связанного сценария. Это уточнение предварительного ТЗ.
Роли выбраны на небольших проверках разработки; полный независимый benchmark ещё впереди.

## Основная среда

Python 3.12 выбран из-за доступности колёс на Mac Intel и Ubuntu 24.04. LangGraph управляет общим состоянием,
условными переходами и ограниченными повторами. CrewAI рассмотрен как альтернативная организация ролей,
Haystack — как вариант для retrieval pipelines; здесь важнее явно контролировать цикл проверки.

FastAPI и Pydantic задают HTTP-контракт и проверяют схемы. HTTPX обращается только к заданным локальным адресам.
SQLite FTS5 и `langgraph-checkpoint-sqlite` выбраны для малого локального корпуса: рабочее состояние, история
сессии и долгосрочные проверенные факты. TTL, версии и происхождение фактов будут реализованы отдельно.
LangMem и Graphiti остаются исследуемыми альтернативами; в проекте не заявляется, что FTS5 является semantic RAG.

Версии фактически установленного окружения: `requirements/macos-intel-py312.lock` и `results/readiness/environment.json`.

## LLM и маршрутизация

Движок — **llama.cpp b12359**, проверенный официальный macOS x64 архив. Все модели запускаются
через один протокол, без платных API. Контекст 4096, один slot на модель, 4 CPU thread, GPU offload выключен.
Системные промпты/данные не отправляются внешнему API. Платный аккаунт или API-ключ не нужен.

| Модель | Семейство | Использование и ограничение |
|---|---|---|
| Qwen3.5 0.8B Q4_0 | Qwen | Дополнительный кандидат, вне текущего потока. Выдумала причину без данных, затем приняла неверную гипотезу о релизе; сырые ответы сохранены. |
| LFM2.5 1.2B Instruct Q8_0 | LFM | Исследователь: выбор ограниченного инструмента. В роли аналитика неверно классифицировала первый инцидент БД. Своя LFM Open License 1.0. |
| SmolLM3 3B Q4_K_M | SmolLM | Аналитик: в диагностике правильно определила исчерпанный пул БД. |
| Qwen3.5 4B Q4_K_M | Qwen | Более крупный валидатор другого семейства. Проверяется отдельно на правильной и заведомо ложной гипотезах и в полном workflow. |

Версии, источники, размеры и SHA-256: `config/model-manifest.json`; исходный smoke — `results/readiness/llm-smoke.json`, новые проверки — `results/readiness/smoke-runs/`, `results/validator/` и `results/scenarios/`.
Все четыре модели в этом наборе квантованы; более маленькая модель и более сильное квантование — разные факторы.
Финальный роутинг будет учитывать измеренные качество, latency и уверенность scorer, а не размер названия.

**Jev-like компонент:** `vinnylarouge/jevlike`, MIT, исходная ревизия
`94f5fd1b0b11d52bbdfdf4e0ee6aa96b568f8452`. Это независимая открытая модель формы «состояние + варианты → вероятности»,
а не TypeSafe Jev. Выбран небольшой обучаемый option-attention scorer для маршрута инцидента;
веса ещё не обучены. Его не считаем генеративной LLM. Нужны holdout по шаблонам, calibration и fallback.

Ollama удобнее как менеджер моделей, но прямой llama.cpp даёт единый проверяемый запуск GGUF и параметры CPU.
vLLM полезно сравнить при переходе на сервер/GPU и высокой нагрузке; для текущего Mac выбран более простой запуск.

## Изоляция и наблюдаемость

Выбрана отдельная Lima VZ VM `pi412-block2`, Ubuntu 24.04 x86_64, 4 vCPU, 8 GiB RAM, 30 GiB диск.
Пользователь `incidentlab` внутри VM не входит в sudo. Домашний каталог и весь workspace хоста не монтируются.
Административный пользователь Lima предназначен для настройки, агент должен запускаться от `incidentlab`.
Обычный venv не является границей безопасности; обычный Docker не выбран в качестве такой границы.

В dev-VM исходящая сеть нужна для установки зависимостей. Ограничение egress, тесты инструментария и полный
переезд inference в VM пока не завершены. Разработка и smoke LLM сейчас выполнены на хосте;
нельзя выдавать их за финальный запуск защищённого agent runtime.

OpenTelemetry SDK/exporter входят в core; spans первого workflow реально сохраняются в локальный JSONL и JSON результата. Phoenix **22.0.1** выбран для traces и evals (отдельный extra,
предпочтительно Linux). Prometheus получает `/metrics` API и четырёх llama-server; Grafana визуализирует ресурсы
и алерты. Заготовки scrape/datasource есть, заполненные дашборды ещё предстоит сделать.
Langfuse и LangSmith рассмотрены как альтернативы; выбран локальный стек без необходимости внешнего аккаунта.

## RecSys

PyTorch и NumPy/SciPy/scikit-learn готовы для самостоятельного эксперимента HSTU на MovieLens 100K.
На Mac Intel используется **torch 2.2.2 + NumPy 1.26.4** из-за доступных x86_64 wheels; на Linux — современный
CPU PyTorch. Чужие pickle/checkpoints не загружаются. Сам HSTU и конечные эксперименты в этой ветке ещё не реализованы.
База первого блока используется с атрибуцией; её качество пересчитывается по новому протоколу.

## Основные первоисточники

- [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview)
- [llama.cpp server b12359](https://github.com/ggml-org/llama.cpp/blob/b12359/tools/server/README.md)
- [Qwen 4B GGUF](https://huggingface.co/ggml-org/Qwen3.5-4B-GGUF)
- [Qwen 0.8B GGUF](https://huggingface.co/ggml-org/Qwen3.5-0.8B-GGUF)
- [Liquid GGUF](https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct-GGUF)
- [SmolLM GGUF](https://huggingface.co/ggml-org/SmolLM3-3B-GGUF)
- [Jevlike](https://github.com/vinnylarouge/jevlike/tree/94f5fd1b0b11d52bbdfdf4e0ee6aa96b568f8452)
- [Lima](https://lima-vm.io/docs/config/vmtype/)
- [Phoenix](https://arize.com/docs/phoenix/self-hosting)
- [Meta Generative Recommenders](https://github.com/meta-recsys/generative-recommenders)

Полный список исследовательских источников — в ТЗ. Наличие ссылки не заменяет проверку реализованного компонента.
