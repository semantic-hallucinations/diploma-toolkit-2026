# Diagrams And Flowcharts

Research date: 2026-04-26.

Primary document: `СТП 01-2024`, especially section 3.

## What To Use

For a software or AI diploma project, these are the most relevant diagram
families:

- Explanatory figures inside the note: use `Рисунок ...` captions and keep them
  near the first reference.
- Algorithm, program, data, and system schemes: use `ГОСТ 19.701-90`.
- General scheme classification and codes: use `ГОСТ 2.701-2008`.
- Electrical structural, functional, and schematic diagrams: use the ESKD rules
  referenced by `СТП 01-2024`.

For UML, C4, BPMN, ERD, neural-network architecture figures, dataset pipelines,
and ML experiment pipelines: `СТП 01-2024` does not make these the default
standardized graphical documents. They can be used as explanatory figures in the
note if the supervisor allows them. If a diagram is part of the official
graphical material, clarify with normal control whether it should be converted
to an ESKD/ESPD-style scheme.

## Flowcharts And Algorithm Schemes

`СТП 01-2024` points to `ГОСТ 19.701-90` for schemes of algorithms, programs,
data, and systems.

Relevant scheme types:

- Data scheme: path of data and processing stages.
- Program scheme: sequence of operations in a program.
- System operation scheme: operation control and data flow in a system.
- Program interaction scheme: activation and interaction of programs with data.
- Technical-device/system algorithm scheme: operation sequence in the device or
  system.
- System resources scheme: configuration of data blocks and processing blocks.

Practical rules:

- Main flow direction is top-to-bottom and left-to-right.
- Arrows may be omitted only for the main direction.
- Use arrows for any other direction.
- Use connectors instead of long crossings or remote jumps.
- Use comments only when the text does not fit inside a symbol.
- Keep symbol sizes proportional and consistent.
- Do not mix arbitrary informal shapes with ГОСТ symbols when the diagram is
  meant to be a formal algorithm/program/data/system scheme.

Common symbols mentioned by the standard section:

- Data.
- Stored data.
- Document.
- Manual input.
- Display.
- Process.
- Predefined process.
- Manual operation.
- Preparation.
- Decision.
- Parallel actions.
- Loop boundary.
- Line.
- Control transfer.
- Communication channel.
- Connector.
- Terminator.
- Comment.

## Structural And Functional Schemes

For structural and functional schemes, `СТП 01-2024` relies on ESKD scheme
rules. For an AI/software system, a structural scheme can usually show major
subsystems and data/control links. A functional scheme should emphasize the
sequence and relation of functions, not implementation trivia.

Practical recommendation for this template:

- In the note body, keep figures simple and readable.
- Put large formal sheets into appendices or graphical material.
- If using the LaTeX template, ensure every generated figure has a caption and
  label, and every label is referenced in the text.

