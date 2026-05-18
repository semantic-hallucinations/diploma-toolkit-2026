# Diagram Generator

Инструментарий для подготовки диаграмм дипломного проекта.

## Prototype

Сейчас есть прототип генератора для пояснительных диаграмм:

```bash
PYTHONPATH=diagram-generator/src python3 -m diagram_toolkit examples \
  --source-dir diagram-generator/examples/sources \
  --out diagram-generator/examples/generated
```

Проверить source-файлы без записи PNG:

```bash
PYTHONPATH=diagram-generator/src python3 -m diagram_toolkit validate \
  diagram-generator/examples/sources
```

На выходе для каждого примера создаются:

- `.drawio` - редактируемый исходник diagrams.net/draw.io;
- `.png` - изображение для вставки в пояснительную записку.

Команда `validate` проверяет модель до визуального просмотра: пересечения
линий с фигурами, наложение подписей, пересечения фигур, пустые маршруты и
выход элементов за холст. Если находится критичная ошибка, команда завершается
с ненулевым кодом.

Поддерживаемые демонстрационные профили:

- `sequence` из Mermaid `sequenceDiagram`;
- `class` из Mermaid `classDiagram`;
- `ERD` из Mermaid `erDiagram`;
- `C4` из C4-PlantUML-like source;
- `deployment` из PlantUML deployment-like source;
- `ML pipeline` из Mermaid `flowchart` с `%% profile: ml-pipeline`;
- `use case` из PlantUML use-case-like source.

Пока здесь лежит документация по выбору диаграмм и правилам их применения:

- `docs/diagram-checklist.md` - чек-лист видов диаграмм, из которого можно
  выбрать набор для диплома.
- `docs/drawio-toolkit-architecture.md` - архитектура будущего конвертера в
  draw.io и PNG.
- `docs/layout-methodology.md` - методика автоматического расположения
  элементов и критерии качества layout.
- `docs/code-flowchart-tools.md` - готовые инструменты для извлечения
  блок-схем/графов из кода и как их безопасно использовать.
- `docs/target-diagram-profiles.md` - целевые профили для sequence, class,
  ERD, C4, deployment, ML pipeline, use case и ГОСТ-блок-схем.
- `docs/software-architecture-diagrams.md` - какие UML, ERD, BPMN, DMN, DFD,
  C4, SysML, ArchiMate, ML/data pipeline и другие software/AI диаграммы
  уместны в дипломе.
- `docs/formatting-requirements.md` - формальные требования к оформлению
  рисунков, линий, стрелок, цветов, подписей и ГОСТ-схем.
- `docs/generation-capabilities.md` - из каких источников можно генерировать
  диаграммы, какими инструментами и где есть риск не выполнить требования
  идеально.
- `docs/sources.md` - источники по нотациям, инструментам и локальным
  материалам БГУИР/ГОСТ.
- `options/` - внешние варианты и референсы, которые можно оценить перед
  разработкой собственного инструментария.
- `reports/` - отчеты по экспериментам и прототипам.

Будущие генераторы, шаблоны и примеры диаграмм нужно добавлять сюда, а не в
`standards/`. Директория `standards/` остается только для стандартов,
официальных материалов и выжимок по оформлению.
