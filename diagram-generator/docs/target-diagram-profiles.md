# Target Diagram Profiles

Дата формализации: 2026-04-26.

Эти профили определяют, какие диаграммы делать первыми и какой уровень
формальности у каждой диаграммы.

## Приоритеты

1. `gost-flowchart` - строгая схема алгоритма/программы/данных/системы.
2. `sequence` - UML sequence в строгом черно-белом стиле.
3. `class` - UML class для ключевых классов.
4. `ERD` - logical/physical ERD.
5. `C4` - context/container/component/deployment.
6. `deployment` - runtime/infrastructure deployment.
7. `ML pipeline` - data/training/inference pipeline.
8. `use case` - акторы и варианты использования.

## Общий Профиль Оформления

Для всех диаграмм:

- PNG как итоговый формат;
- `.drawio` как редактируемый исходник;
- черно-белая печатная форма;
- белый фон;
- без рамки и основной надписи, если диаграмма вставляется в записку как
  рисунок;
- единый шрифт и единая толщина линий;
- ортогональные связи, где это применимо;
- без декоративных иконок, теней, градиентов и случайных цветов;
- подпись делается в LaTeX/записке, не внутри PNG.

## gost-flowchart

Назначение:

- схема алгоритма;
- схема программы;
- схема данных;
- схема взаимодействия программ;
- схема ресурсов системы;
- схема работы системы.

Входы:

- Mermaid flowchart subset;
- PlantUML activity subset;
- editable YAML/JSON;
- Python extractor output после ручного упрощения.

Фигуры:

- терминатор;
- процесс;
- решение;
- данные;
- документ;
- предопределенный процесс;
- подготовка;
- соединитель;
- комментарий.

Строгость: `ГОСТ 19.701-90`.

## sequence

Назначение:

- API сценарии;
- authentication/inference/training flows;
- взаимодействие frontend/backend/model/database;
- асинхронные сообщения.

Входы:

- Mermaid sequence subset;
- PlantUML sequence subset;
- YAML scenario.

Draw.io элементы:

- actor/person как простой actor symbol или прямоугольник с stereotype;
- participant/service/database как прямоугольник;
- lifeline как пунктирная вертикальная линия;
- messages как горизонтальные arrows;
- alt/loop/opt как группы.

Строгость: UML-like, оформление по требованиям записки.

## class

Назначение:

- ключевая предметная модель;
- interfaces/services/entities;
- inheritance/composition/dependency relationships.

Входы:

- PlantUML class subset;
- Mermaid class subset;
- code model extractor;
- YAML class model.

Draw.io элементы:

- class box с compartments;
- interface stereotype;
- enum box;
- relationship markers для inheritance, implementation, composition,
  aggregation, association, dependency.

Строгость: UML-like, оформление по требованиям записки.

## ERD

Назначение:

- conceptual/logical/physical data model;
- таблицы, ключи, связи, cardinality.

Входы:

- Mermaid ERD subset;
- PlantUML IE/ER subset;
- SQL schema/migrations;
- ORM models;
- YAML entity model.

Draw.io элементы:

- entity/table box с compartments;
- PK/FK markers текстом;
- crow's foot/cardinality markers у связей;
- join tables как обычные entity boxes.

Строгость: ERD notation, оформление по требованиям записки.

## C4

Назначение:

- system context;
- container;
- component;
- dynamic;
- deployment.

Входы:

- Structurizr DSL;
- C4-PlantUML subset;
- YAML architecture model.

Draw.io элементы:

- person;
- software system;
- container;
- component;
- external system;
- boundary/group.

Строгость: C4-like, оформление по требованиям записки.

## deployment

Назначение:

- где система разворачивается;
- nodes, runtimes, containers, databases, external services;
- environments and network zones.

Входы:

- PlantUML deployment subset;
- Docker Compose;
- Kubernetes manifests;
- Terraform subset;
- YAML deployment model.

Draw.io элементы:

- node/group boxes;
- artifact/container boxes;
- database/storage shapes;
- external service boxes;
- protocol-labeled orthogonal connectors.

Строгость: UML deployment/C4 deployment-like, оформление по требованиям
записки.

## ML pipeline

Назначение:

- сбор данных;
- preprocessing;
- feature engineering;
- training;
- evaluation;
- model registry;
- inference;
- monitoring/retraining.

Входы:

- YAML pipeline model;
- notebooks/pipeline configs как extractor candidates;
- Mermaid/PlantUML activity subset для простых случаев.

Draw.io элементы:

- data source/store shapes;
- process boxes;
- decision boxes для validation/quality gates;
- model artifact boxes;
- feedback loop connectors.

Строгость: пояснительная pipeline diagram, оформление по требованиям записки.

## use case

Назначение:

- акторы;
- границы системы;
- варианты использования;
- include/extend/generalization.

Входы:

- PlantUML use case subset;
- Mermaid flowchart-like subset только если явно маппится в use case model;
- YAML requirements model.

Draw.io элементы:

- actor;
- system boundary;
- use case ellipses;
- association/include/extend/generalization connectors.

Строгость: UML use-case-like, оформление по требованиям записки.

## Неподдерживаемое На Старте

- полный Mermaid;
- полный PlantUML;
- BPMN/DMN;
- ArchiMate/SysML;
- автоматическая генерация диаграммы всего проекта;
- нестандартные цвета и темы;
- ручные координаты внутри Mermaid/PlantUML.
