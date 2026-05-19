# High-Level Flow

Initialization:

```text
ReadUserInput: raw input -> input

CreateState: input -> State
```

Iterative loop:

```text
CreateGame: input + State -> GameSpec

PlayGame: GameSpec -> DeltaState

IntegrateState: State + DeltaState -> State'
```

The loop repeats:

```text
CreateGame
PlayGame
IntegrateState
```

until completion, stagnation, goal update, or manual stop.


# CreateGame vs PlayGame

## CreateGame

Purpose:

Determine the most valuable missing improvement relative to the current project state and goal.

Contract:

```text
CreateGame: input + State -> GameSpec
```

Responsibilities:

- Inspect current State
- Compare against goal / NorthStar
- Identify the most valuable missing capability / feature / update
- Define WHAT game should be played

Does NOT:

- Produce DeltaState
- Decide exact implementation
- Play the game
- Configure detailed team internals


## PlayGame

Purpose:

Play the adversarial game and produce a proposed state update.

Contract:

```text
PlayGame: GameSpec -> DeltaState
```

Responsibilities:

- Execute Blue / Red / Referee process
- Decide HOW to accomplish the objective
- Produce DeltaState

May internally use:

- One or many Blue agents
- One or many Red agents
- Referee process
- Debate
- Tool use
- Iteration

External contract remains:

```text
GameSpec -> DeltaState
```


# Current Open Question

GameSpec is not fully defined yet.

Current understanding:

GameSpec should contain enough information to play the game, but should not prescribe how the game is played.