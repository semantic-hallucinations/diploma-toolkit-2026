# Diagram Generation Capabilities

Дата формализации: 2026-04-26.

Эта заметка описывает, какие диаграммы стоит генерировать, из каких входных
данных их можно получать и насколько реально довести результат до требований
оформления диплома.

## Ключевой Вывод

Нет одного генератора, который идеально закрывает все типы диаграмм и все
требования `СТП 01-2024`/`ГОСТ 19.701-90`.

Практичная архитектура инструментария:

1. Mermaid/PlantUML/Structurizr использовать для пояснительных software
   диаграмм.
2. Для строгих ГОСТ-блок-схем сделать отдельный генератор SVG/PDF с
   собственными шаблонами УГО и проверками.
3. Все результаты пропускать через единый постпроцессинг: стиль, размер,
   шрифт, толщина линий, экспорт, sanity-check итогового файла.

## Уровни Соответствия

`High` - можно довести до требований пояснительной записки генератором и
проверками.

`Medium` - можно сделать качественный черновик, но нужна ручная проверка
компоновки и смысла.

`Low` - автоматическая генерация рискованна; лучше ручное моделирование или
специализированный редактор.

`Strict ГОСТ` - нужен отдельный renderer или очень жесткие шаблоны; обычные
Mermaid/PlantUML не дают полной гарантии.

## Матрица Диаграмм

| Диаграмма | Что показывает | Возможный вход | Генератор | Соответствие |
| --- | --- | --- | --- | --- |
| C4 System Context | система, пользователи, внешние системы | YAML/JSON model, Structurizr DSL, ручной DSL | Structurizr, PlantUML C4, Mermaid C4-like | High для пояснительного рисунка |
| C4 Container | приложения, сервисы, БД, broker, model service | Structurizr DSL, Docker Compose, Kubernetes, ручной YAML | Structurizr, PlantUML C4 | High |
| C4 Component | компоненты внутри сервиса | ручной YAML, package/module scan, dependency graph | Structurizr, PlantUML C4 | Medium |
| C4 Dynamic | сценарий взаимодействия | сценарий в YAML, sequence DSL | Structurizr, PlantUML, Mermaid sequence | Medium |
| C4 Deployment | окружения и nodes | Docker Compose, Kubernetes, Terraform, ручной YAML | Structurizr, PlantUML deployment | Medium |
| UML Use Case | акторы и цели | requirements YAML, user stories | PlantUML, Mermaid | High |
| UML Sequence | обмен сообщениями во времени | сценарий YAML, OpenAPI flow, ручной DSL, trace/log | PlantUML, Mermaid | High |
| UML Class | классы и связи | code AST, TypeScript/Python/Java models, ручной DSL | PlantUML, Mermaid class | Medium |
| UML Package | модули и зависимости | imports, package metadata, code scan | PlantUML, Graphviz-style renderer | Medium |
| UML Component | компоненты и интерфейсы | architecture YAML, code modules | PlantUML | High |
| UML Activity | процесс, ветвления, параллельность | workflow YAML, BPMN-like DSL, partial code analysis | PlantUML, Mermaid flowchart | Medium |
| UML State Machine | состояния и переходы | enum/status model, state machine config | PlantUML, Mermaid state | High |
| UML Deployment | узлы, артефакты, runtime | Docker Compose, Kubernetes, Terraform | PlantUML | Medium |
| ERD logical | сущности, атрибуты, связи | SQL schema, Prisma, Django/SQLAlchemy models | Mermaid ERD, PlantUML IE/ER, custom | Medium |
| ERD physical | реальные таблицы и foreign keys | DB schema, migrations | Mermaid ERD, PlantUML IE/ER, custom | Medium |
| DFD | процессы, хранилища, внешние сущности, потоки | ручной YAML, threat-model YAML | Mermaid/PlantUML/custom | Medium |
| BPMN | бизнес-процесс | BPMN XML, ручная модель | BPMN renderer, diagrams.net | Medium |
| DMN | решения и таблицы решений | DMN XML, decision tables | DMN tooling, custom tables | Medium |
| ГОСТ схема алгоритма | алгоритм/программа/данные/система | structured YAML, упрощенный AST, ручной DSL | custom ГОСТ renderer | Strict ГОСТ |
| Flowchart из кода | черновик логики функции | AST/CFG конкретного языка | custom AST parser + renderer | Medium, не строгий без доработки |
| Call graph | вызовы функций | static analysis, language server, traces | Graphviz/custom | Medium |
| Module dependency graph | зависимости модулей | imports, package manager, build graph | Graphviz/custom | Medium |
| Control-flow graph | переходы внутри алгоритма | AST/bytecode/CFG | custom/Graphviz | Low как дипломный рисунок |
| API map | endpoints и consumers | OpenAPI/Swagger, GraphQL schema | custom, Mermaid/PlantUML | Medium |
| CI/CD pipeline | этапы build/test/deploy | GitHub Actions, GitLab CI, Jenkinsfile | Mermaid, PlantUML, custom | High |
| Infrastructure topology | сеть, nodes, storage, firewall | Terraform, Kubernetes, Compose, ручной YAML | PlantUML network, custom | Medium |
| Threat model | trust boundaries, data flows, actors | threat-model YAML, DFD | custom, Mermaid/PlantUML | Medium |
| ML/data pipeline | данные, preprocessing, training, inference | pipeline config, notebooks, ручной YAML | Mermaid, PlantUML, custom | High |
| Model architecture | слои модели и тензоры | PyTorch/Keras model summary, ONNX, ручной YAML | custom, Graphviz, Netron export | Medium |
| Experiment tracking flow | параметры, метрики, артефакты | MLflow/W&B metadata, ручной YAML | Mermaid/PlantUML/custom | Medium |
| Screen flow | переходы экранов | routes, frontend router config, ручной YAML | Mermaid, PlantUML, diagrams.net | Medium |

## Mermaid

Mermaid хорошо подходит для:

- flowchart;
- sequence diagram;
- class diagram;
- state diagram;
- entity relationship diagram;
- user journey;
- requirement diagram;
- C4-like diagram;
- timeline, mindmap, kanban, architecture diagram и других вспомогательных
  рисунков.

Плюсы:

- текстовый формат;
- легко хранить в git;
- удобно генерировать из YAML/JSON;
- можно экспортировать в SVG;
- есть темы и `themeVariables`.

Ограничения:

- layout не всегда предсказуем;
- не гарантирует минимальное количество пересечений;
- не гарантирует ГОСТ-формы и ГОСТ-стрелки;
- C4 в Mermaid помечен как отдельный тип с ограничениями, для серьезного C4
  лучше Structurizr или C4-PlantUML;
- ERD в Mermaid нужно проверять на поддержку нужной нотации и читаемость.

Вывод: Mermaid годится для пояснительных диаграмм, но не как единственный
инструмент для строгих ГОСТ-блок-схем.

## PlantUML

PlantUML хорошо подходит для:

- sequence;
- use case;
- class;
- object;
- activity;
- component;
- deployment;
- state;
- timing;
- network;
- ArchiMate;
- mindmap/WBS;
- ER в Chen notation и Information Engineering notation;
- JSON/YAML visualizations.

Плюсы:

- много UML-типов;
- есть настройка цветов, шрифтов и линий через `skinparam`;
- умеет SVG, EPS, LaTeX и PNG;
- есть разные layout engines: Graphviz, Smetana, VizJs, ELK;
- лучше Mermaid подходит для UML.

Ограничения:

- сам PlantUML предупреждает, что хороший layout не всегда тривиален;
- автоматический layout не гарантирует отсутствие пересечений;
- не является ГОСТ 19.701 renderer;
- настройками можно приблизить стиль, но нельзя доказать полное соответствие
  ГОСТ-схемы без отдельной проверки.

Вывод: PlantUML - основной кандидат для UML и части ER/network/deployment
диаграмм, но строгие блок-схемы лучше делать отдельным renderer.

## Structurizr DSL

Structurizr DSL хорошо подходит для C4:

- system context;
- container;
- component;
- code;
- system landscape;
- dynamic;
- deployment.

Плюсы:

- модель архитектуры хранится как код;
- можно экспортировать в PlantUML, Mermaid, PNG/SVG и другие форматы;
- лучше соответствует идее C4, чем ручное рисование C4 в универсальном
  редакторе.

Ограничения:

- это не ГОСТ/ЕСКД;
- подходит именно для архитектуры ПО, а не для блок-схем алгоритмов;
- итоговый экспорт все равно нужно проверять на читаемость и стиль.

Вывод: если в toolkit будет C4, лучше делать его через Structurizr DSL или
C4-PlantUML, а не через произвольные rectangles.

## Генерация Из Кода

Из кода реально генерировать:

- module dependency graph;
- package dependency graph;
- import graph;
- call graph;
- class diagram;
- control-flow graph;
- rough flowchart функции;
- API map из annotations/routes;
- state transition diagram, если состояния описаны явно;
- ERD из ORM models.

Но для диплома нельзя бездумно вставлять автогенерацию всего проекта. Чаще
нужно:

1. Выбрать 1-3 ключевых модуля или сценария.
2. Сгенерировать черновик.
3. Упростить до уровня, который отвечает на вопрос диплома.
4. Применить единый стиль.
5. Проверить читаемость в PDF.

### Блок-Схемы Из Кода

Автоматически получить ГОСТ-идеальную блок-схему из произвольного кода сложно.

Причины:

- код содержит детали реализации, которые не нужны в дипломе;
- циклы, exceptions, async, callbacks и ранние return быстро делают схему
  нечитаемой;
- автоматический layout не гарантирует ортогональность, малое число
  пересечений и правильное использование соединителей;
- ГОСТ-схема должна быть схемой алгоритма, а не механическим дампом AST.

Правильный подход:

1. Парсить код в AST/CFG.
2. Сжимать низкоуровневые операции в смысловые шаги.
3. Давать пользователю YAML/DSL для правки.
4. Рендерить через custom ГОСТ renderer.
5. Проверять УГО, стрелки, направления, толщины, пересечения и размеры.

То есть `код -> черновик -> редактируемая модель -> ГОСТ-render`.

## Что Можно Сделать Идеально

Можно почти идеально автоматизировать:

- единый черно-белый стиль;
- экспорт в SVG/PDF;
- запрет скриншотов;
- размеры canvas;
- толщину линий;
- шрифт;
- проверку текста за границами;
- проверку, что рисунок помещается в область страницы;
- наличие metadata с типом диаграммы;
- наличие рядом исходника диаграммы;
- генерацию LaTeX include-фрагмента;
- raster/vector sanity-check.

Нельзя гарантировать идеально без ручной проверки:

- смысловую полезность диаграммы;
- отсутствие всех ненужных деталей;
- принятие выбранной нотации нормоконтролем;
- идеальный layout для сложного графа;
- полное ГОСТ-соответствие, если diagram source - Mermaid/PlantUML.

## Рекомендуемая Архитектура Toolkit

Предлагаемый pipeline:

```text
input source
  -> extractor/parser
  -> normalized diagram model
  -> simplifier
  -> renderer adapter
  -> SVG/PDF output
  -> style/lint checks
  -> LaTeX include snippet
```

Нормализованная модель должна быть общей:

```text
diagram:
  type: sequence | class | c4-container | gost-flowchart | erd | ...
  title: ...
  source: ...
  nodes: ...
  edges: ...
  style_profile: bsuir-note | gost-19-701 | c4-note
```

Renderer adapters:

- `mermaid` - быстрые пояснительные диаграммы;
- `plantuml` - UML/ER/network/deployment;
- `structurizr` - C4;
- `gost-flowchart` - собственный renderer для ГОСТ 19.701;
- `manual-svg` - ручные схемы, прошедшие style checks.

## Приоритет Реализации

1. Единый style profile для пояснительных диаграмм: черно-белый SVG/PDF,
   читаемый шрифт, единая толщина линий.
2. Mermaid/PlantUML CLI wrapper.
3. Structurizr/C4 support.
4. Проверки SVG: размер, текст, цвета, stroke width, наличие пересечений как
   предупреждение.
5. YAML DSL для ГОСТ-блок-схем.
6. Custom ГОСТ 19.701 renderer.
7. Генерация черновиков из кода и ORM/schema.

Самый рискованный пункт - автоматические блок-схемы из кода. Его лучше делать
после того, как появится строгий renderer и проверяемая модель.
