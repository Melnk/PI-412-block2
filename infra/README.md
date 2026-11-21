# Среды и запуск

## macOS Intel

Рабочая подготовка и первые запросы LLM проверены на Intel Core i7-9750H, 32 GiB RAM, macOS 26.3.1.
Модели используют CPU. Зависимости Mac зафиксированы отдельно, чтобы не устанавливать старый Intel Torch на Linux.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements/macos-intel-py312.lock
.venv/bin/python -m pip install --no-deps -e .
make assets
make models-start
.venv/bin/python scripts/doctor.py --ml
make smoke
make models-stop
```

На этом Mac пакетный Python также доступен по пути
`/Users/melnikoleg/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`.
Не переносите данный абсолютный путь в конфигурацию чужой машины.

## VM

```sh
limactl validate infra/lima/incidentlab.yaml
make vm-start
limactl shell pi412-block2
make vm-stop
```

`infra/lima/incidentlab.yaml` использует отдельное имя, фиксированный образ Ubuntu 24.04 с SHA-256,
никаких mounts хоста, отдельного пользователя `incidentlab` без sudo и единственный разрешённый forward
API 8140 на loopback хоста. Административный аккаунт Lima нужен только для настройки VM.
Гостевая исходящая сеть на этапе подготовки включена; окончательное ограничение egress ещё предстоит проверить.

Для реализации внутри Linux потребуется скопировать проект в `/opt/incidentlab`, назначить владельцем
`incidentlab` и запускать агент от этого пользователя. Вход через Lima сам по себе не меняет пользователя
на `incidentlab`. Настройки и данные другой VM `ib-lab` не меняются.

Пример установки ML-зависимостей в Linux (после переноса проекта, не выполненный агентный deployment):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pip install 'torch>=2.6,<3' --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -e '.[ml]'
```

Движок llama.cpp на Linux нужно собрать из официальной ревизии `b12359`, либо выбрать официальный Linux archive
и добавить его контрольную сумму. Скрипт `fetch_assets.py --engine` сейчас намеренно поддерживает только
проверенный macOS Intel архив, а не скачивает случайный бинарник для другой ОС.

## Наблюдаемость

OpenTelemetry SDK и HTTP exporter установлены. API уже отдаёт `/metrics`; llama-server запускается с `--metrics`.
Подготовлены `observability/prometheus.yml` и `observability/grafana-datasource.yml`.
Phoenix устанавливается через `pip install -e '.[observability]'` предпочтительно внутри Linux.
Phoenix/Prometheus/Grafana пока не развёрнуты: скриншотов заполненных дашбордов и полноценных agent traces ещё нет.
