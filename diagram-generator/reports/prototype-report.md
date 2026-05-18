# Diagram Toolkit Prototype Report

Дата реализации: 2026-04-26.

## Что Сделано

Собран первый прототип генератора пояснительных диаграмм:

```text
source file
  -> profile detection
  -> subset parser
  -> normalized model
  -> profile layout
  -> draw.io mxGraphModel
  -> PNG renderer
```

Прототип лежит в `diagram-generator/src/diagram_toolkit`.

Примеры лежат в:

- `diagram-generator/examples/sources`;
- `diagram-generator/examples/generated`.

## Поддержанные Профили

| Профиль | Вход | Выход |
| --- | --- | --- |
| `sequence` | Mermaid `sequenceDiagram` subset | `.drawio`, `.png` |
| `class` | Mermaid `classDiagram` subset | `.drawio`, `.png` |
| `ERD` | Mermaid `erDiagram` subset | `.drawio`, `.png` |
| `C4` | C4-PlantUML-like subset | `.drawio`, `.png` |
| `deployment` | PlantUML deployment-like subset | `.drawio`, `.png` |
| `ML pipeline` | Mermaid `flowchart` + `%% profile: ml-pipeline` | `.drawio`, `.png` |
| `use case` | PlantUML use-case-like subset | `.drawio`, `.png` |

## Как Определяется Тип Диаграммы

Определение профиля сейчас делается по содержимому файла:

- `sequenceDiagram` -> `sequence`;
- `classDiagram` -> `class`;
- `erDiagram` -> `ERD`;
- `flowchart` + `%% profile: ml-pipeline` -> `ML pipeline`;
- `System_Boundary`, `Container`, `Person`, `Rel` -> `C4`;
- `node`, `cloud`, `database`, `artifact` -> `deployment`;
- `actor`, `usecase`, `rectangle` -> `use case`;
- `.json` -> профиль берется из поля `profile`.

Это специально не full Mermaid/PlantUML parser. Прототип поддерживает только
контролируемые subset-ы, чтобы неподдерживаемые конструкции не превращались в
кривую диаграмму молча.

## Две Прослойки

### Flowchart Layer

Отдельный будущий слой для строгих `ГОСТ 19.701-90` блок-схем.

Предполагаемый вход:

- файл кода;
- extractor;
- редактируемая YAML/JSON модель;
- строгий ГОСТ-validator;
- draw.io/PNG renderer.

Этот слой пока не реализован в коде, потому что для него нужна отдельная
проверка УГО, направлений, соединителей и правил схем алгоритмов.

### Diagram Layer

Реализованный прототип для пояснительных software/AI диаграмм:

- sequence;
- class;
- ERD;
- C4;
- deployment;
- ML pipeline;
- use case.

Для этих диаграмм цель - не `ГОСТ 19.701`, а строгий стиль записки:

- черно-белая печатная форма;
- белый фон;
- без декоративных цветов;
- прямые/ортогональные соединения, где это применимо;
- единый шрифт и толщина линий;
- PNG без скриншотов редактора;
- `.drawio` для ручной правки.

## Layout

Реализованы профильные layout-эвристики:

- `sequence`: участники слева направо, сообщения по строкам, lifelines,
  fragment boxes для `loop`/`alt`.
- `class`: классы сеткой, compartments для атрибутов/методов, связи между
  классами.
- `ERD`: сущности сеткой с приоритетом по степени связности, подписи
  cardinality у концов.
- `C4`: person слева, system boundary в центре, external systems справа,
  containers внутри boundary.
- `deployment`: top-level runtime zones колонками, nested nodes/artifacts
  внутри зон.
- `ML pipeline`: directed flow с переносом длинной цепочки по bands и
  поддержкой feedback-связей.
- `use case`: system boundary в центре, primary actors слева, secondary actors
  справа, use cases внутри.

Соединители рисуются ортогональными polyline-сегментами. Подпись связи
ставится на самый длинный сегмент, а не просто в геометрический центр, чтобы
уменьшить наложения.

## Что Использовано

Локально:

- Python standard library;
- Pillow для PNG-renderer;
- собственный writer `mxGraphModel` для `.drawio`.

Внешние материалы как референсы:

- draw.io custom shape library format:
  `https://www.drawio.com/doc/faq/format-custom-shape-library`
- draw.io shapes/XML notes:
  `https://www.drawio.com/blog/shapes`
- draw.io sequence diagrams:
  `https://www.drawio.com/blog/sequence-diagrams.html`
- draw.io UML class diagrams:
  `https://www.drawio.com/blog/uml-class-diagrams`
- draw.io crow's foot ERD:
  `https://www.drawio.com/blog/crows-foot-notation`
- draw.io deployment diagrams:
  `https://drawio-app.com/blog/create-uml-deployment-diagrams-in-draw-io/`
- draw.io use case diagrams:
  `https://drawio-app.com/uml-use-case-diagrams-with-draw-io/`
- C4 notation guidance:
  `https://c4model.com/diagrams/notation`
- mxGraph orthogonal edge styles:
  `https://jgraph.github.io/mxgraph/docs/js-api/files/view/mxEdgeStyle-js.html`
- Graphviz orthogonal splines:
  `https://graphviz.org/docs/attrs/splines/`
- ELK:
  `https://www.eclipse.org/elk/`
- Dagre:
  `https://github.com/dagrejs/dagre`

## Почему PNG Сейчас Не Через Draw.io CLI

В локальном окружении не установлен `drawio` desktop CLI. Поэтому прототип
пишет `.drawio` и параллельно генерирует PNG из той же внутренней модели через
lightweight Pillow renderer.

Следующий технический шаг - добавить optional exporter:

```text
drawio -x -f png -s 2 -o output.png input.drawio
```

Если CLI установлен, он должен стать основным PNG exporter. Pillow renderer
можно оставить как fallback и как быстрый preview в CI.

## Текущие Ограничения

- Это prototype-quality renderer, не финальный production generator.
- Поддерживаются subset-ы Mermaid/PlantUML, а не полные языки.
- Layout пока эвристический, без ELK/dagre integration.
- Нет автоматической проверки пересечений всех линий.
- Нет проверки текста на выход за границы в `.drawio`.
- PNG renderer не гарантирует, что draw.io desktop экспортирует пиксель-в-пиксель
  такой же результат.
- Для строгих ГОСТ-блок-схем нужен отдельный flowchart layer.

## Что Делать Дальше

1. Добавить draw.io CLI exporter как основной способ PNG export.
2. Добавить validator: overlaps, line crossings, text bounds, unsupported
   source constructs.
3. Подключить ELK/dagre как optional layout candidates для class/ERD/C4.
4. Сделать строгий `gost-flowchart` слой отдельно от software diagrams.
5. Добавить snapshot examples в CI, чтобы не ломать генерацию.
