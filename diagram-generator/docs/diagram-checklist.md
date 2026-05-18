# Diagram Checklist

Дата формализации: 2026-04-26.

Чек-лист нужен, чтобы выбрать будущий пул диаграмм для диплома. Диаграммы,
которые вставляются в пояснительную записку как рисунки, не требуют рамки и
основной надписи. Для них важны читаемость, единый стиль, корректная нотация,
ГОСТ-совместимые символы там, где схема заявлена как `ГОСТ 19.701-90`, и
правильная подпись вида `Рисунок N - Название`.

## Базовый Набор

- [ ] `Context / C4 System Context` - система, пользователи, внешние системы.
- [ ] `C4 Container` - frontend, backend, БД, broker, model service, storage,
  внешние API.
- [ ] `UML Use Case` - акторы и варианты использования.
- [ ] `UML Sequence` - ключевые сценарии во времени.
- [ ] `ERD` - сущности, таблицы, связи и кардинальности.
- [ ] `ГОСТ 19.701 схема алгоритма` - формальная блок-схема ключевого
  алгоритма.
- [ ] `Deployment` - где и как развернута система.
- [ ] `ML/Data Pipeline` - путь данных, обучение, inference.

## Требования И Предметная Область

- [ ] `UML Use Case` - цели акторов и границы функциональности.
- [ ] `Context diagram` - окружение системы без детализации контейнеров.
- [ ] `User journey` - путь пользователя по шагам.
- [ ] `Screen flow / navigation map` - переходы между экранами.
- [ ] `BPMN Process` - бизнес-процесс внутри одного участника.
- [ ] `BPMN Collaboration` - процесс с несколькими участниками и сообщениями.
- [ ] `DMN Decision Requirements` - решения, входные данные и правила.
- [ ] `Decision table / decision tree` - компактное описание правил.

## Архитектура ПО

- [ ] `C4 System Context` - система в окружении.
- [ ] `C4 Container` - исполняемые части системы и хранилища.
- [ ] `C4 Component` - компоненты внутри ключевого сервиса.
- [ ] `C4 Dynamic` - сценарий взаимодействия в стиле C4.
- [ ] `C4 Deployment` - размещение контейнеров по окружениям и узлам.
- [ ] `UML Component` - компоненты, интерфейсы, зависимости.
- [ ] `UML Package` - пакеты, слои, namespace и зависимости кода.
- [ ] `UML Deployment` - узлы, runtime, артефакты.
- [ ] `High-level architecture diagram` - простая пояснительная архитектурная
  схема без строгой C4/UML нотации.

## Взаимодействие И Поведение

- [ ] `UML Sequence` - обмен сообщениями между участниками во времени.
- [ ] `UML Communication` - взаимодействие с упором на связи участников.
- [ ] `UML Activity` - поток работ, ветвления, параллельность.
- [ ] `UML State Machine` - состояния сущности или процесса.
- [ ] `UML Timing` - временные ограничения и сигналы.
- [ ] `Event flow` - события предметной области и реакции системы.
- [ ] `Queue/topic topology` - producers, consumers, topics, queues.
- [ ] `Runtime sequence` - обработка запроса в runtime.

## Данные

- [ ] `Conceptual ERD` - сущности предметной области без технических деталей.
- [ ] `Logical ERD` - атрибуты, ключи, связи, кардинальности.
- [ ] `Physical DB schema` - реальные таблицы, индексы, foreign keys.
- [ ] `Crow's foot ERD` - ERD с практичной нотацией кардинальностей.
- [ ] `IDEF1X` - более формальная модель данных, если ее требует руководитель.
- [ ] `Data Flow Diagram (DFD)` - процессы, хранилища, внешние сущности,
  потоки данных.
- [ ] `Data lineage` - происхождение и путь данных.
- [ ] `Data pipeline` - ingestion, validation, preprocessing, feature
  engineering, storage.
- [ ] `Ontology / knowledge graph` - понятия и связи в предметной области.

## Код И Алгоритмы

- [ ] `ГОСТ 19.701 схема алгоритма` - формальная схема ключевого алгоритма.
- [ ] `ГОСТ 19.701 схема программы` - последовательность операций программы.
- [ ] `ГОСТ 19.701 схема данных` - преобразование или организация данных.
- [ ] `ГОСТ 19.701 схема взаимодействия программ` - обмен между программами.
- [ ] `ГОСТ 19.701 схема ресурсов системы` - ресурсы и их использование.
- [ ] `UML Class` - ключевые классы, интерфейсы и связи.
- [ ] `UML Object` - конкретные объекты и связи в момент времени.
- [ ] `Module dependency graph` - зависимости модулей/пакетов.
- [ ] `Call graph` - вызовы функций в важном участке.
- [ ] `Control-flow graph` - переходы внутри сложного алгоритма.
- [ ] `Nassi-Shneiderman diagram` - структурограмма алгоритма без стрелок.
- [ ] `API map` - endpoints, consumers, contracts, external APIs.

## Развертывание И Эксплуатация

- [ ] `UML Deployment` - узлы, runtime, артефакты.
- [ ] `C4 Deployment` - окружения и размещение контейнеров.
- [ ] `Infrastructure topology` - сеть, подсети, storage, firewall, VPN.
- [ ] `CI/CD pipeline` - build, test, image, deploy, rollback.
- [ ] `Observability flow` - logs, metrics, traces, alerts.
- [ ] `Backup/recovery flow` - резервное копирование и восстановление.

## Безопасность

- [ ] `Threat model / trust boundary diagram` - границы доверия, внешние
  акторы, sensitive data.
- [ ] `DFD for threat modeling` - движение данных для анализа угроз.
- [ ] `Data privacy flow` - где появляются, хранятся и обрабатываются
  персональные или чувствительные данные.
- [ ] `Access control matrix/diagram` - роли, права, защищаемые ресурсы.

## AI/ML

- [ ] `ML/Data Pipeline` - сбор данных, preprocessing, training, evaluation,
  inference.
- [ ] `Model architecture` - слои модели, embeddings, encoder/decoder, heads,
  outputs.
- [ ] `Training workflow` - dataset version, hyperparameters, metrics,
  artifacts, model registry.
- [ ] `Inference pipeline` - request, validation, preprocessing, model call,
  postprocessing, response.
- [ ] `MLOps lifecycle` - drift, retraining trigger, validation, deployment,
  monitoring.
- [ ] `Experiment tracking flow` - параметры, метрики, артефакты и версии.

## Редкие Или Только По Необходимости

- [ ] `ArchiMate` - enterprise architecture: business/application/technology
  layers.
- [ ] `SysML Requirements` - требования и связи в системной инженерии.
- [ ] `SysML Block Definition / Internal Block` - структура сложной технической
  системы.
- [ ] `Mind map / WBS` - декомпозиция темы, задач или работ.
- [ ] `Timeline` - этапы исследования или экспериментов.

## Рекомендуемый Выбор Для Начала

Для типичного диплома по ПО/ИИ сначала выбрать 5-8 диаграмм:

- [ ] `Use Case`;
- [ ] `C4 Context`;
- [ ] `C4 Container`;
- [ ] `Sequence` для основного сценария;
- [ ] `ERD`, если есть БД;
- [ ] `ГОСТ 19.701` для ключевого алгоритма;
- [ ] `Deployment`, если есть контейнеры/сервер/cloud;
- [ ] `ML/Data Pipeline`, если проект связан с данными или моделью.
