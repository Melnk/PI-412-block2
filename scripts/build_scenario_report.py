"""Build the monochrome milestone report from explicitly selected real result files.

Requires python-docx (optional report dependency). Rendering/visual QA is a separate step.
"""
import argparse
import json
from pathlib import Path
from statistics import median

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
LABELS = {
    "database_pool_exhaustion": "Пул соединений БД",
    "deployment_regression": "Регрессия релиза",
    "application_error": "Ошибка приложения",
    "unknown": "Недостаточно данных",
}


def table(doc, headers, rows, widths):
    result = doc.add_table(rows=1, cols=len(headers))
    result.autofit = False
    for col, width in zip(result.columns, widths, strict=True):
        col.width = Inches(width)
    for cell, text, width in zip(result.rows[0].cells, headers, widths, strict=True):
        cell.width = Inches(width)
        cell.text = text
        shade = OxmlElement('w:shd')
        shade.set(qn('w:fill'), 'EDEDED')
        cell._tc.get_or_add_tcPr().append(shade)
        for run in cell.paragraphs[0].runs:
            run.bold = True
    for row in rows:
        cells = result.add_row().cells
        for cell, text, width in zip(cells, row, widths, strict=True):
            cell.text = str(text)
            cell.width = Inches(width)
    for row in result.rows:
        trpr = row._tr.get_or_add_trPr()
        trpr.append(OxmlElement('w:cantSplit'))
        for cell in row.cells:
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            tcpr = cell._tc.get_or_add_tcPr()
            margin = OxmlElement('w:tcMar')
            for side in ('top', 'left', 'bottom', 'right'):
                node = OxmlElement('w:' + side)
                node.set(qn('w:w'), '90')
                node.set(qn('w:type'), 'dxa')
                margin.append(node)
            tcpr.append(margin)
            borders = OxmlElement('w:tcBorders')
            for side in ('top', 'left', 'bottom', 'right'):
                edge = OxmlElement('w:' + side)
                edge.set(qn('w:val'), 'single')
                edge.set(qn('w:sz'), '4')
                edge.set(qn('w:color'), 'D9D9D9')
                borders.append(edge)
            tcpr.append(borders)
            for p in cell.paragraphs:
                p.paragraph_format.space_after = Pt(2)
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.line_spacing = 1.05
                for run in p.runs:
                    run.font.size = Pt(10)
    header = OxmlElement('w:tblHeader')
    result.rows[0]._tr.get_or_add_trPr().append(header)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return result


def paragraph(doc, text):
    return doc.add_paragraph(text)


def code(doc, lines):
    for line in lines:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing = 1.0
        r = p.add_run(line)
        r.font.name = 'Courier New'
        r.font.size = Pt(9)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evaluation', type=Path, required=True)
    parser.add_argument('--smoke', type=Path, required=True)
    parser.add_argument('--validator', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/incidentlab-report.docx')
    args = parser.parse_args()
    evaluation = json.loads(args.evaluation.read_text())
    smoke = json.loads(args.smoke.read_text())
    critic = json.loads(args.validator.read_text())
    cases = evaluation['cases']
    assert len(cases) == 5, 'Use a completed five-case run'
    assert len(smoke['runs']) == 12, 'Use a completed four-model smoke'
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    sec.top_margin = sec.bottom_margin = Inches(0.7)
    sec.left_margin = sec.right_margin = Inches(0.8)
    normal = doc.styles['Normal']
    normal.font.name, normal.font.size = 'Arial', Pt(11)
    normal.paragraph_format.line_spacing = 1.12
    normal.paragraph_format.space_after = Pt(7)
    for name, size in [('Title', 22), ('Subtitle', 11), ('Heading 1', 15), ('Heading 2', 12)]:
        style = doc.styles[name]
        style.font.name, style.font.size = 'Arial', Pt(size)
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.paragraph_format.space_before = Pt(12)
        style.paragraph_format.space_after = Pt(7)
    doc.core_properties.title = 'IncidentLab Разбор учебных инцидентов'
    doc.core_properties.author = 'Олег Мельник'
    doc.core_properties.subject = 'Первый связанный сценарий проекта по программной инженерии'

    doc.add_paragraph('IncidentLab Разбор учебных инцидентов', 'Title')
    doc.add_paragraph('Олег Мельник · группа 11-412 · КФУ ИТИС\nПрограммная инженерия · второй блок · 23 ноября 2026 года', 'Subtitle')
    paragraph(doc, 'Реализован первый связанный сценарий расследования сбоя: от выбора источников до проверенной гипотезы и сохранённого отчёта. Стенд работает с локальными языковыми моделями и пятью искусственными инцидентами. Он помогает объяснить наблюдаемый отказ, но не устанавливает первопричину без необходимых данных.')
    doc.add_heading('Назначение и границы', 1)
    paragraph(doc, 'Пользователь выбирает инцидент в веб-интерфейсе. Исследователь собирает факты, аналитик предлагает объяснение, а валидатор другого семейства проверяет его. Итог содержит ссылки на факты и следующий шаг инженеру. Автоматическое исправление сервиса в сценарий не входит.')
    paragraph(doc, 'Этот отчёт описывает реализованный этап IncidentLab. Остальные требования второго блока, включая обученный Jev-like scorer, долгосрочную память, защищённый runtime, заполненные dashboards и отдельную RecSys HSTU, остаются в плане разработки.')
    doc.add_heading('Архитектура сценария', 1)
    table(doc, ['Участник', 'Модель или компонент', 'Действие'], [
        ['Исследователь', 'LFM2.5 1.2B Q8_0', 'Выбирает метрики, логи или релизы'],
        ['Аналитик', 'SmolLM3 3B Q4_K_M', 'Предлагает режим отказа и цитаты'],
        ['Проверка ссылок', 'Python и Pydantic', 'Проверяет id и типы источников'],
        ['Валидатор', 'Qwen3.5 4B Q4_K_M', 'Независимо проверяет факты и гипотезу'],
    ], [1.15, 2.25, 3.5])
    paragraph(doc, 'Потоком управляет LangGraph: исследователь → инструмент → исследователь → аналитик → проверка ссылок → валидатор → заключение. После отклонения можно получить дополнительный источник и повторить анализ. При ошибочных ссылках возможна ограниченная повторная попытка. Роли настраиваются в config/models.json.')

    doc.add_page_break()
    doc.add_heading('Источники и правила принятия', 1)
    paragraph(doc, 'У каждого инцидента есть описание, метрики, логи и история релизов. Запись включает id, источник, время и текст. Все данные созданы для учебного стенда; ожидаемые ответы лежат отдельно от инструментов в evals/scenarios.json. Модели их не получают.')
    paragraph(doc, 'Доступны только три инструмента чтения из fixtures/incidents. Проверяются разрешённый путь после раскрытия symlink, размер файла, число записей, происхождение, уникальность id и попадание времени в окно инцидента. Инструмента shell или чтения произвольного файла нет.')
    paragraph(doc, 'Известная гипотеза принимается, когда ссылки существуют, цитаты охватывают хотя бы два типа источников, валидатор выбрал ту же причину и вернул accept. Иначе система получает дополнительный факт либо возвращает unknown. Два типа источников не доказывают истинность и независимость данных; обе модели также могут ошибиться одинаково.')
    paragraph(doc, 'Supported означает прохождение заданных проверок. Insufficient_evidence означает, что гипотезу принять не удалось. Недоступность модели и нарушение JSON-контракта дают error, а достижение лимита — budget_exceeded. Ошибка исполнения не маскируется под нехватку фактов.')
    doc.add_heading('Ограничение выполнения', 2)
    table(doc, ['Ограничение', 'Значение по умолчанию'], [
        ['Инструменты и анализ', '3 обращения к источникам и не более 2 анализов'],
        ['Вызовы LLM', 'Не более 8 на расследование'],
        ['Выходные токены', '1600 зарезервированных суммарно; 96 или 224 на вызов'],
        ['Время', '180 секунд на сценарий; до 60 секунд ожидания HTTP-операции'],
        ['Контекст и параллелизм', '4096 токенов; один сценарий в API, второй запрос получает 429'],
    ], [2.05, 4.85])
    doc.add_heading('Трассировка и интерфейс', 2)
    paragraph(doc, 'FastAPI отдаёт результат, сохранённый запуск, готовность моделей и метрики. В браузере показаны факты, независимый отзыв, траектория и выгрузка JSON. Недоверенный текст отображается через textContent. Для каждого запуска сохраняются настоящие OpenTelemetry spans, промпты, исходные ответы, latency и токены, сообщённые движком. Спаны экспортируются локально в JSONL; Phoenix и Grafana пока не развёрнуты.')

    doc.add_page_break()
    doc.add_heading('Результаты реальных проверок', 1)
    paragraph(doc, f'Полный прогон {evaluation["evaluation_id"]} выполнил {len(cases)} сценариев. Совпадение с ручной разметкой: {sum(c["passed"] for c in cases)}/{len(cases)}. Эти случаи используются при разработке и не являются независимой выборкой для оценки общего качества моделей.')
    rows = []
    for c in cases:
        stats = c['stats']
        rows.append([c['incident_id'], LABELS[c['actual_cause']], 'Да' if c['passed'] else 'Нет',
                     f'{stats["elapsed_seconds"]:.1f}', str(stats['llm_calls'])])
    table(doc, ['Инцидент', 'Фактический вывод', 'Верно', 'Время с', 'LLM'], rows,
          [1.15, 2.85, 0.75, 1.15, 1.0])
    paragraph(doc, 'Checkout-01 проверяет пул БД, checkout-02 — регрессию релиза, checkout-03 — недостаток фактов, checkout-04 — инструкцию злоумышленника внутри лога, checkout-05 — ошибку обработчика. Один injection-пример не подтверждает устойчивость к произвольным атакам.')
    doc.add_heading('Проверка моделей и выбор ролей', 2)
    model_rows = []
    for model in ['qwen', 'liquid', 'smol', 'qwen4']:
        runs = [r for r in smoke['runs'] if r['model'] == model]
        times = [r['latency_ms'] for r in runs if 'latency_ms' in r]
        model_rows.append([model, f'{sum(r["passed"] for r in runs)}/3',
                           f'{median(times)/1000:.2f}' if times else 'Нет данных'])
    table(doc, ['Модель', 'Верно в smoke', 'Медиана ответа с'], model_rows, [2.6, 1.8, 2.5])
    paragraph(doc, f'Отдельная проверка валидатора: {sum(r["passed"] for r in critic["runs"])}/{len(critic["runs"])}. На одних фактах о БД проверены правильная гипотеза и заведомо ложная гипотеза о релизе. Три smoke-вопроса на модель и две проверки критика дают только локальные свидетельства, а не рейтинг интеллекта.')
    paragraph(doc, 'Начальный полный запуск с LFM в роли аналитика завершился unknown: модель ошибочно выбрала application_error, а валидатор отклонил вывод. Qwen 0.8B в отдельной диагностике согласилась с ложным релизом. Все неудачные ответы сохранены в initial-attempt; после этих проверок роли изменены. Смещения от разработки на этих же данных необходимо учитывать в последующем holdout.')

    doc.add_page_break()
    doc.add_heading('Воспроизведение и демонстрация', 1)
    paragraph(doc, 'Среда проверки: Intel Core i7-9750H, 32 GiB RAM, macOS 26.3.1, Python 3.12, llama.cpp b12359, CPU без GPU offload. Зависимости устанавливаются в отдельный venv; версии Mac зафиксированы в requirements. Модели скачиваются из официальных репозиториев, ревизии и SHA-256 — в config/model-manifest.json.')
    code(doc, ['make check', 'make assets', 'make models-start', 'make demo', 'make scenarios', 'make api'])
    paragraph(doc, 'Интерфейс: http://127.0.0.1:8140. Во время демонстрации сначала запустить checkout-01, показать две согласующиеся записи, предложение и отзыв. Затем запустить checkout-03 и объяснить отказ от диагноза. Для проверки недоверенного ввода открыть checkout-04. После показа остановить API через Ctrl+C и выполнить make models-stop.')
    doc.add_heading('Автоматические и ручные проверки', 2)
    paragraph(doc, 'Ruff и 42 pytest-проверки прошли: транспорт, контракты, переходы графа, бюджеты, источники, ограничение путей, отказ при вымышленных цитатах, сохранение, trace и HTTP-ошибки. Тестовый gateway применяется только в unit-тестах. Отдельно проверен настоящий запуск из браузера: гипотеза о БД принята за 38,708 с. HTTP GET вернул сохранённый результат; во время расследования второй запрос получил 429.')
    doc.add_heading('Ограничения и дальнейшая работа', 2)
    paragraph(doc, 'Runbook охватывает три наблюдаемых режима отказа; произвольный инцидент может не подходить под них. Классификация исчерпанного пула не объясняет, почему соединения удерживались. Оценка не измеряет эффект в бизнесе или точность на настоящих инцидентах. Inference этого этапа выполнен на хосте; созданная VM ещё требует проверки egress, доступов и достаточности памяти для выбранных моделей.')
    paragraph(doc, 'Далее нужны независимые шаблоны оценки, сравнение с одиночной LLM и без валидатора, обучение Jev-like scorer, память с TTL и обновлением фактов, проверенная VM и заполненные dashboards. RecSys HSTU выполняется отдельной частью. Помощь ИИ использована при исследовании, написании кода, проверках и подготовке отчёта; материал необходимо разобрать и объяснять самостоятельно.')
    doc.add_heading('Файлы доказательств', 2)
    for path in [args.evaluation, args.smoke, args.validator]:
        try:
            text = str(path.resolve().relative_to(ROOT))
        except ValueError:
            text = path.name
        code(doc, [text])
    paragraph(doc, 'Репозиторий: https://github.com/Melnk/PI-412-block2\nИсточники моделей: huggingface.co/ggml-org и huggingface.co/LiquidAI. Полные адреса и ревизии сохранены в manifest. Архитектура и команды дополнены в docs/incidentlab-scenario.md.')

    # Strip every theme color override, including inherited heading/hyperlink styles.
    for style in doc.styles:
        if hasattr(style, 'font'):
            style.font.color.rgb = RGBColor(0, 0, 0)
    for root in [doc.styles.element, doc.element]:
        for color in root.iter(qn('w:color')):
            color.attrib.clear()
            color.set(qn('w:val'), '000000')
        for border in list(root.iter(qn('w:pBdr'))):
            border.getparent().remove(border)
    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    field = OxmlElement('w:fldSimple')
    field.set(qn('w:instr'), 'PAGE')
    footer._p.append(field)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(args.output)
    print(args.output)


if __name__ == '__main__':
    main()
