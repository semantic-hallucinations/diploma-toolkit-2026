# Code Flowchart Tools

Дата исследования: 2026-04-26.

Готовые инструменты полезны как extractors, но не как финальные генераторы
ГОСТ-диаграмм. Их задача - помочь получить черновую структуру из кода, после
чего модель нужно упростить, проверить и отрисовать нашим draw.io renderer.

## Кандидаты

### PyFlowchart

Источник: `https://pypi.org/project/pyflowchart/`

Что умеет:

- парсит Python-код;
- умеет выбирать функцию/метод через `field`;
- генерирует flowchart.js DSL;
- поддерживает упрощение простых тел и частично try/except, match/case.

Как использовать:

- только для Python;
- брать как extractor `Python code -> flowchart-like model`;
- не использовать его HTML/PNG как финальный результат;
- после extraction обязательно преобразовывать в нашу normalized model.

Риск:

- output не ГОСТ;
- сложный Python-код дает слишком подробную и шумную схему;
- exceptions/async/comprehensions требуют ручной проверки.

### Flomatic

Источник: `https://github.com/romilly/flomatic`

Что умеет:

- генерирует Mermaid flowcharts из Python source.

Как использовать:

- как альтернативный Python extractor;
- дальше идти через наш Mermaid flowchart parser subset.

Риск:

- нужно отдельно проверить поддержку современных конструкций Python;
- Mermaid output не является ГОСТ-схемой сам по себе.

### Code2flow

Источники:

- `https://code2flow.com/`
- `https://github.com/scottrogowski/code2flow`

Что полезно:

- коммерческий code2flow хорошо подходит для ручного описания процессов;
- open-source `scottrogowski/code2flow` полезнее для call graphs, чем для
  строгих алгоритмических блок-схем.

Как использовать:

- не брать как основу ГОСТ-блок-схем;
- можно изучить для call graph/module graph задач;
- не делать внешние cloud-сервисы обязательной частью toolkit.

## Рекомендуемый Подход

Для ГОСТ-блок-схем из кода:

```text
source code
  -> language-specific extractor
  -> rough flow model
  -> simplifier
  -> editable YAML/JSON
  -> ГОСТ validator
  -> draw.io renderer
  -> PNG
```

Почему нужен editable YAML/JSON слой:

- дипломная блок-схема должна объяснять алгоритм, а не дампить AST;
- часть операций нужно объединять в смысловые блоки;
- названия блоков должны совпадать с текстом диплома;
- сложные ветки иногда нужно заменить соединителями или вынести на отдельную
  схему.

## Языки

MVP:

- Python через `pyflowchart` или собственный `ast` extractor.

Следующие кандидаты:

- TypeScript/JavaScript через TypeScript compiler API, Babel или ts-morph;
- Java через JavaParser;
- C# через Roslyn;
- SQL/ORM schemas для ERD через миграции или schema introspection.

Не стоит начинать с поддержки всех языков. Для дипломного toolkit важнее
предсказуемый результат на одном языке, чем поверхностная поддержка многих.

## Что Проверять После Extraction

- выбрана одна функция/сценарий, а не весь проект;
- количество блоков не превышает лимит профиля;
- нет неподдерживаемых control-flow конструкций;
- условия имеют понятные подписи;
- циклы и ветки явно выражены;
- low-level операции сгруппированы;
- результат можно прочитать на странице A4.
