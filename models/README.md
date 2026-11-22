# Локальные LLM

Веса не публикуются в Git. Точные ревизии и SHA-256 находятся в `config/model-manifest.json`.
`python scripts/fetch_assets.py --models` скачивает и проверяет их.

Qwen3.5 0.8B Q4_0; LFM2.5 1.2B Instruct Q8_0; SmolLM3 3B Q4_K_M; Qwen3.5 4B Q4_K_M.
Суммарный размер GGUF 6 756 686 848 байт (около 6.76 GB).
Оперативная память дополнительно расходуется на контекст и runtime.
Текущие роли: LFM — исследователь, SmolLM — аналитик, Qwen 4B — валидатор.
Qwen 0.8B сохранена как дополнительный кандидат, её ошибки описаны в docs/readiness.md.
