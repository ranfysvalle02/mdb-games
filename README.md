# mdb-games

A production-ready, extensible multiplayer game server built with **FastAPI**, **WebSockets**, and **MongoDB**. This platform can host multiple games (Blackjack, Dominoes, and more) from a single unified server architecture.

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- MongoDB (running locally or remotely)
- Node.js (optional, for frontend development)

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd mdb-games

# Install Python dependencies
cd backend
pip install -r requirements.txt

# Start MongoDB (if not already running)
# macOS: brew services start mongodb-community
# Linux: sudo systemctl start mongod
# Windows: net start MongoDB

# Run the server
python main.py
# Server will start on http://localhost:8000
```

### Project Structure

```
mdb-games/
├── backend/
│   ├── main.py              # FastAPI server (the "Conductor")
│   ├── blackjack_logic.py  # Blackjack game engine
│   ├── domino_logic.py     # Dominoes game engine
│   └── requirements.txt     # Python dependencies
├── frontend/
│   ├── index.html          # Main UI
│   └── app.js              # Frontend WebSocket client
└── README.md
```

---

## Building an Extensible Multiplayer Game Server with FastAPI and MongoDB

The creation of a video game, even a simple one, is an intricate dance of logic, state, and user interaction. When you introduce multiple players and real-time communication, the complexity compounds. But what if the goal is even more ambitious: to build a single platform, a "Game Portal," that can host *multiple* different games—from Blackjack to Dominoes to Checkers—all from one unified server?

This is a challenge of architecture. A monolithic server that hard-codes the rules for every game is a technical dead end. It becomes unmaintainable, untestable, and impossible to extend.

The solution is abstraction. The key is to design a "Game Server" that is completely ignorant of game rules. This server's only job is to be a powerful, real-time "Conductor"—managing players, lobbies, and connections. The game's rules, the "Rulebook," are then "plugged in" as self-contained, interchangeable modules.

This article provides a comprehensive guide to this architectural pattern. We will explore the theory of game design, the technical implementation of an extensible server using **FastAPI**, **WebSockets**, and **MongoDB**, and a practical, step-by-step guide for building and plugging in your own game.

-----

### Part 1: The Philosophy of Game Design (The "Why")

Before writing a single line of server code, we must understand what a "game" fundamentally is. Misunderstanding this leads to flawed architecture.

#### 1.1 What is a "Game"?

At its core, a game is a structured form of play. We can define it as a system with four key components:

1.  **Rules:** Constraints that define what players *can* and *cannot* do.
2.  **Goals:** A specific, desirable outcome (a "win state") that players are working toward.
3.  **Interaction:** A mechanism for players to make choices that affect the game state.
4.  **Feedback:** A system that clearly communicates the game state and the consequences of actions back to the players.

Our server architecture must be a direct reflection of these components.

#### 1.2 A Developer's Primer on Game Theory

"Game Theory" is not just an academic field for economists; it is a practical framework for game developers. It is the formal study of **systems of choice and consequence**. When you design a game, you are designing one of these systems.

Here are the key concepts and how they map directly to our code:

  * **Players:** The decision-making entities in the game. In our system, this is any `player_id`, whether a human connected via a WebSocket or an AI `AutoBot` running a simple logic function.
  * **Actions:** The set of all possible choices a player can make on their turn. In our code, this becomes the `move_data` dictionary. For Blackjack, the actions are `{"action": "hit"}` or `{"action": "stand"}`. For Dominoes, they are `{"action": "play", "tile": [6,6], "side": "left"}`.
  * **Outcomes & Payoffs:** The result of a set of actions. This is the change in the **game state**. A `hit` action has the outcome of a new card being added to a hand, which has a payoff of either getting closer to 21, or busting.
  * **Information:** What does each player know, and when? This is one of the most critical parts of server design.
      * **Perfect Information:** All players know the complete game state (e.g., Chess, Checkers, Go).
      * **Imperfect Information:** Players have hidden information (e.g., Blackjack's hole card, a Dominoes player's hand, Poker).

Our server *must* be able to enforce imperfect information, which is why we will need a **State Sanitization** function.

#### 1.3 The Developer's Core Loop: The "Game Loop"

Every game, from a simple text adventure to a AAA shooter, runs on a fundamental "Game Loop." This loop is the engine of play.

1.  **Process Input:** Wait for and receive a choice from a player.
2.  **Update State:** Apply that choice to the game's "master" state, validating it against the rules.
3.  **Render State:** Show the *new* state to all players.
4.  **Repeat:** Wait for the next input from the (now current) player.

Our server architecture is a web-based, asynchronous version of this loop.

  * **Process Input:** The FastAPI server's WebSocket handler (`/ws/game/{...}`) waits for a `make_move` JSON message.
  * **Update State:** This is the most important part. The server *delegates* this step to a "Game Engine" module (`blackjack_logic.play_move(...)`).
  * **Render State:** The server broadcasts the new, sanitized state to all connected clients, where JavaScript renders it.

-----

### Part 2: Architecting the Extensible Platform (The "How")

Now we can design the system. Our goal is to build the "Conductor" (`main.py`) and a "Rulebook" (`blackjack_logic.py`) and ensure they can communicate through a standardized interface.

#### 2.1 The Core Abstraction: Server vs. Engine

This separation is the most important concept in this guide.

**The Game Server (The Conductor / `main.py`)**
This is our FastAPI application. It is "rule-agnostic." It knows *nothing* about pips, suits, or kings.

Its responsibilities are purely infrastructural:

  * **HTTP API:** Handles the "lobby" system: `POST /api/game/create` and `POST /api/game/{game_id}/join`.
  * **Connection Management:** A `ConnectionManager` class tracks which WebSocket belongs to which `player_id` in which `game_id`.
  * **State Persistence:** Connects to a MongoDB database. Its job is to `find` a `game` document, `update` its `game_state` field, and nothing more.
  * **Message Routing:** It listens for WebSocket messages. If it sees a `make_move` message, it doesn't try to understand it. It just "routes" it to the correct Game Engine.

**The Game Engine (The Rulebook / `_logic.py`)**
This is a "pure" Python module (e.g., `blackjack_logic.py`, `domino_logic.py`).

  * It has **no** FastAPI, WebSocket, or MongoDB imports. It is 100% self-contained.
  * Its only job is to know the rules of its game.
  * It takes a `game_state` dictionary as input.
  * It returns a *new* `game_state` dictionary as output.
  * If a move is invalid, it raises a `ValueError`, which the server will catch and relay to the user.

#### 2.2 The "Contract": A Universal Game Interface

For the server to "plug in" any game, both sides must agree on a "contract," or an interface. In our architecture, this contract is beautifully simple and consists of two functions.

Any "Game Engine" module we create *must* provide:

1.  **`create_new_game(player_ids: list[str], game_mode: str) -> dict`**

      * This function takes the list of players who have joined the lobby and initializes the very first `game_state` for them. It shuffles the deck, deals the hands, and sets `current_turn_index` to `0`. It returns the complete state dictionary.

2.  **`play_move(game_state: dict, player_id: str, move_data: dict) -> dict`**

      * This is the core of the engine. It takes the *current state* from the database, the `player_id` who sent the move, and a generic `move_data` dictionary.
      * It validates the move (e.g., "Is it this player's turn?", "Can this player 'hit'?", "Is this move valid?").
      * If invalid, it `raise ValueError("It's not your turn.")`.
      * If valid, it modifies the `game_state` dictionary and returns the *new* state.

#### 2.3 The Server's "Router": `main.py` Deep Dive

The Game Server (`main.py`) uses a simple Python dictionary as a "plug-in router" to manage these engines.

```python
# backend/main.py

# --- Import Game Engines ---
import domino_logic
import blackjack_logic
# To add a new game, we would just `import checkers_logic`

# --- The "Router" Dictionary ---
GAME_LOGIC_MODULES = {
    "dominoes": domino_logic,
    "blackjack": blackjack_logic,
    # "checkers": checkers_logic  <-- Adding a new game is this simple
}
```

When a player sends a `make_move` message, the WebSocket handler performs this logic. This is the heart of the entire system:

```python
# backend/main.py (simplified WebSocket handler)

async def websocket_endpoint(websocket: WebSocket, game_id: str, player_id: str):
    ...
    try:
        while True:
            data = await websocket.receive_json()
            action_type = data.get('type')
            
            # --- Get fresh game doc for every action ---
            current_game = await games_collection.find_one({"_id": game_id})
            
            # 1. Dynamically find the correct logic module
            logic_module = GAME_LOGIC_MODULES.get(current_game['game_type'])
            
            if action_type == 'make_move':
                try:
                    # 2. Delegate the "Update State" step to the engine
                    new_state = logic_module.play_move(
                        current_game['game_state'], 
                        player_id, 
                        data['move_data']
                    )
                    
                    # 3. Save the new state back to the database
                    await games_collection.update_one(
                        {"_id": game_id},
                        {"$set": {"game_state": new_state}}
                    )
                    
                    # 4. Broadcast the new state to all players
                    await broadcast_state_update(game_id, new_state)

                except ValueError as e:
                    # 5. Catch invalid moves and tell the player
                    await websocket.send_json({"type": "error", "message": str(e)})

    except WebSocketDisconnect:
        ...
```

#### 2.3.1 HTTP API Endpoints

The server exposes REST endpoints for lobby management. Here are practical examples:

**Create a Game:**

```bash
# Create a new Blackjack game
curl -X POST "http://localhost:8000/api/game/create" \
  -H "Content-Type: application/json" \
  -d '{
    "player_id": "p_abc123",
    "game_type": "blackjack",
    "game_mode": "best_of_5"
  }'

# Response:
{
  "game_id": "A3B7K9",
  "player_id": "p_abc123"
}
```

**Join a Game:**

```bash
# Join an existing game
curl -X POST "http://localhost:8000/api/game/A3B7K9/join" \
  -H "Content-Type: application/json" \
  -d '{
    "player_id": "p_xyz789"
  }'

# Response:
{
  "game_id": "A3B7K9",
  "player_id": "p_xyz789"
}
```

**Python Example:**

```python
import requests

# Create game
response = requests.post("http://localhost:8000/api/game/create", json={
    "player_id": "p_abc123",
    "game_type": "dominoes",
    "game_mode": "classic"
})
game_data = response.json()
game_id = game_data["game_id"]

# Join game
requests.post(f"http://localhost:8000/api/game/{game_id}/join", json={
    "player_id": "p_xyz789"
})
```

#### 2.3.2 WebSocket Message Protocol

Once connected via WebSocket, clients communicate using JSON messages. Here are the message types:

**Connection:**

```javascript
// Connect to game
const ws = new WebSocket(`ws://localhost:8000/ws/game/${gameId}/${playerId}`);

// On connection, server sends:
{
  "type": "connection_success",
  "game_state": { /* sanitized state */ },
  "players": [ /* player list */ ],
  "game_type": "blackjack"
}
```

**Start Game:**

```javascript
// Host starts the game
ws.send(JSON.stringify({
  type: "start_game"
}));

// Server broadcasts to all players:
{
  "type": "game_started",
  "game_state": { /* initial game state */ },
  "players": [ /* player list with AI status */ ]
}
```

**Make a Move:**

```javascript
// Blackjack: Hit
ws.send(JSON.stringify({
  type: "make_move",
  move_data: {
    action: "hit"
  }
}));

// Blackjack: Stand
ws.send(JSON.stringify({
  type: "make_move",
  move_data: {
    action: "stand"
  }
}));

// Dominoes: Play a tile
ws.send(JSON.stringify({
  type: "make_move",
  move_data: {
    action: "play",
    tile: [6, 5],
    side: "right"  // or "left"
  }
}));

// Dominoes: Draw from boneyard
ws.send(JSON.stringify({
  type: "make_move",
  move_data: {
    action: "draw"
  }
}));
```

**State Updates:**

```javascript
// Server broadcasts after each move:
{
  "type": "state_update",
  "game_state": { /* sanitized state for this player */ },
  "players": [ /* updated player list */ ]
}

// Error responses:
{
  "type": "error",
  "message": "It's not your turn."
}
```

#### 2.4 The Database as the "Single Source of Truth"

Our server is **stateless**. It doesn't keep the `game_state` in memory. After a WebSocket disconnects, the server "forgets" everything. The *true* state of the game lives *only* inside our **MongoDB** document.

This is why we use a NoSQL database like MongoDB:

  * **Schema-less:** The `game_state` dictionary for Blackjack is *completely different* from the `game_state` for Dominoes. A relational (SQL) database would require a new, complex table structure for every single game. With MongoDB, we just save the dictionary as-is. It's perfectly flexible.
  * **Atomicity:** When a player moves, we `find` the document, run the logic, and `update` the *entire* `game_state` field in one atomic operation. This ensures the state is never corrupted.

The game's "history" is just the series of `game_state` objects saved to the database, one after another.

#### 2.4.1 MongoDB Document Structure

Here's what a game document looks like in MongoDB:

```python
# Example game document in MongoDB
{
  "_id": "A3B7K9",
  "game_type": "blackjack",
  "game_mode": "best_of_5",
  "host_id": "p_abc123",
  "status": "in_progress",  # "waiting", "in_progress", "finished"
  "players": [
    {"player_id": "p_abc123"},
    {"player_id": "p_xyz789"}
  ],
  "game_state": {
    # Game-specific state (see examples below)
  }
}
```

#### 2.4.2 Game State Examples

**Blackjack Game State:**

```python
{
  "deck": [
    {"rank": "K", "suit": "♠", "value": 10},
    {"rank": "7", "suit": "♥", "value": 7},
    # ... remaining cards
  ],
  "hands": {
    "p_abc123": {
      "hand": [
        {"rank": "A", "suit": "♠", "value": 11},
        {"rank": "K", "suit": "♦", "value": 10}
      ],
      "value": 21,
      "status": "stood",  # "playing", "stood", "busted"
      "bet": 10
    },
    "p_xyz789": {
      "hand": [
        {"rank": "10", "suit": "♣", "value": 10},
        {"rank": "6", "suit": "♥", "value": 6}
      ],
      "value": 16,
      "status": "playing",
      "bet": 10
    }
  },
  "dealer_hand": [
    {"rank": "9", "suit": "♠", "value": 9},
    {"rank": "?", "suit": "", "value": 0}  # Hidden hole card
  ],
  "dealer_value": 9,  # Only up-card value shown
  "players": ["p_abc123", "p_xyz789"],
  "current_turn_index": 1,
  "status": "in_progress",  # "in_progress", "round_finished", "finished"
  "scores": {
    "p_abc123": 25,
    "p_xyz789": 10
  },
  "hand_wins": {
    "p_abc123": 1,
    "p_xyz789": 0
  },
  "round_number": 1,
  "game_mode": "best_of_5",
  "wins_needed": 3,
  "log": [
    "Round 1 started. Dealing hands. (Best of 5)",
    "p_abc123 has Blackjack!",
    "p_xyz789 hits and gets a 7♥."
  ]
}
```

**Dominoes Game State:**

```python
{
  "board": [
    (6, 6),  # Starting tile
    (6, 4),
    (4, 2)
  ],
  "hands": {
    "p_abc123": [
      (5, 5),
      (3, 2),
      (1, 0)
    ],
    "p_xyz789": [
      (2, 1),
      (4, 3)
    ]
  },
  "boneyard": [
    (0, 0),
    (1, 1),
    # ... remaining tiles
  ],
  "players": ["p_abc123", "p_xyz789"],
  "current_turn_index": 1,
  "status": "in_progress",  # "in_progress", "hand_finished", "finished"
  "last_move_was_capicu": False,
  "last_tile_played": (4, 2),
  "passes_in_a_row": 0,
  "winner": None,
  "game_mode": "classic",  # "classic" or "boricua"
  "scores": {
    "p_abc123": 0,
    "p_xyz789": 0
  },
  "hand_wins": {
    "p_abc123": 1,
    "p_xyz789": 0
  },
  "hand_number": 1,
  "teams": None,  # Only for "boricua" mode
  "team_scores": None,  # Only for "boricua" mode
  "log": [
    "Game started (CLASSIC mode). p_abc123 goes first.",
    "p_abc123 started with (6, 6).",
    "p_xyz789 played (6, 4)."
  ]
}
```

#### 2.5 Security by Design: State Sanitization

We have a serious problem. If we just `broadcast(new_state)` as shown in the simplified code above, we are sending the *entire* game state to *every* player. This means:

  * Player 1 sees Player 2's Dominoes hand.
  * All players see the dealer's hidden "hole card."
  * All players see the entire `deck` and `boneyard`.

This is where we must implement the "Imperfect Information" concept from game theory. The server must "sanitize" the state for *each player* before sending it.

```python
# backend/main.py

def sanitize_game_state_for_player(game_type: str, game_state: dict, player_id: str):
    # Use json.loads/dumps to create a perfect deep copy
    sanitized_state = json.loads(json.dumps(game_state))

    # --- Generic Sanitization (hides other hands) ---
    if 'hands' in sanitized_state:
        for pid, hand_data in sanitized_state['hands'].items():
            if pid != player_id:
                # The local player should only know *how many* cards others have
                if game_type == 'dominoes':
                    sanitized_state['hands'][pid] = f"{len(hand_data)} tiles"
                elif game_type == 'blackjack':
                    sanitized_state['hands'][pid]['hand'] = f"{len(hand_data['hand'])} cards"
    
    # Hide the boneyard/deck
    if 'boneyard' in sanitized_state:
        sanitized_state['boneyard'] = f"{len(sanitized_state['boneyard'])} tiles"
    if 'deck' in sanitized_state:
        sanitized_state['deck'] = f"{len(sanitized_state['deck'])} cards"

    # --- Game-Specific Sanitization ---
    if game_type == 'blackjack' and sanitized_state['status'] == 'in_progress':
        # Hide dealer's hole card (the second card)
        first_card = sanitized_state['dealer_hand'][0]
        sanitized_state['dealer_hand'] = [first_card, {"rank": "?", "suit": ""}]
        # Only show the value of the up-card
        sanitized_state['dealer_value'] = first_card['value']
        
    return sanitized_state
```

Now, our *real* broadcast function loops through every player and sends them their own unique, sanitized version of the truth.

**Example: Sanitized State for Blackjack**

```python
# Original state (what the server sees):
{
  "hands": {
    "p_abc123": {
      "hand": [{"rank": "A", "suit": "♠"}, {"rank": "K", "suit": "♦"}],
      "value": 21,
      "status": "stood"
    },
    "p_xyz789": {
      "hand": [{"rank": "10", "suit": "♣"}, {"rank": "6", "suit": "♥"}],
      "value": 16,
      "status": "playing"
    }
  },
  "dealer_hand": [
    {"rank": "9", "suit": "♠", "value": 9},
    {"rank": "A", "suit": "♥", "value": 11}  # Hidden!
  ],
  "deck": [/* 40+ cards */]
}

# Sanitized state sent to p_abc123:
{
  "hands": {
    "p_abc123": {
      "hand": [{"rank": "A", "suit": "♠"}, {"rank": "K", "suit": "♦"}],
      "value": 21,
      "status": "stood"
    },
    "p_xyz789": {
      "hand": "2 cards",  # Hidden!
      "status": "playing"
    }
  },
  "dealer_hand": [
    {"rank": "9", "suit": "♠", "value": 9},
    {"rank": "?", "suit": ""}  # Hidden hole card!
  ],
  "dealer_value": 9,  # Only up-card value
  "deck": "42 cards"  # Hidden!
}
```

#### 2.5.1 Frontend Integration Example

Here's how the frontend connects and interacts with the server:

```javascript
// frontend/app.js

// 1. Generate player ID (browser fingerprint)
let playerId = localStorage.getItem('browser_fingerprint') || generateFingerprint();

// 2. Create a game
async function createGame(gameType, gameMode) {
  const response = await fetch('http://localhost:8000/api/game/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      player_id: playerId,
      game_type: gameType,
      game_mode: gameMode
    })
  });
  const data = await response.json();
  return data.game_id;
}

// 3. Join a game
async function joinGame(gameId) {
  const response = await fetch(`http://localhost:8000/api/game/${gameId}/join`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      player_id: playerId
    })
  });
  return await response.json();
}

// 4. Connect via WebSocket
function connectWebSocket(gameId, playerId) {
  const ws = new WebSocket(`ws://localhost:8000/ws/game/${gameId}/${playerId}`);
  
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    
    switch (message.type) {
      case 'connection_success':
        console.log('Connected!', message.game_state);
        renderGame(message.game_state, message.game_type);
        break;
        
      case 'game_started':
        console.log('Game started!', message.game_state);
        renderGame(message.game_state, message.game_type);
        break;
        
      case 'state_update':
        console.log('State updated!', message.game_state);
        renderGame(message.game_state, message.game_type);
        break;
        
      case 'error':
        alert(`Error: ${message.message}`);
        break;
    }
  };
  
  return ws;
}

// 5. Send a move
function sendMove(ws, moveData) {
  ws.send(JSON.stringify({
    type: 'make_move',
    move_data: moveData
  }));
}

// 6. Start the game (host only)
function startGame(ws) {
  ws.send(JSON.stringify({
    type: 'start_game'
  }));
}

// Example usage:
const gameId = await createGame('blackjack', 'best_of_5');
const ws = connectWebSocket(gameId, playerId);

// When user clicks "Hit" button:
document.getElementById('hit-btn').onclick = () => {
  sendMove(ws, { action: 'hit' });
};

// When user clicks "Stand" button:
document.getElementById('stand-btn').onclick = () => {
  sendMove(ws, { action: 'stand' });
};
```

-----

### Part 3: Building Your Own Game (A Practical Guide)

This architecture is powerful because it makes adding new games trivial. Let's prove it. We will design and add **Tic-Tac-Toe**.

#### 3.1 Step 1: Define Your Rules (The "Design Doc")

Before coding, we answer our game theory questions:

  * **Players:** 2 (`player_ids[0]` is 'X', `player_ids[1]` is 'O').
  * **Actions:** A single action: `{"action": "play", "cell_index": <0-8>}`.
  * **Outcomes:** Win, Lose, Draw.
  * **Information:** Perfect. Both players see the whole board. (This means our `sanitize` function won't have to do much).

#### 3.2 Step 2: Model Your State (The `game_state` Dict)

What data do we need to *perfectly describe* any moment in a game of Tic-Tac-Toe?

  * A list of 9 items for the board.
  * The list of players.
  * Whose turn it is.
  * The game's status.

<!-- end list -->

```python
# Our 'game_state' dictionary will look like this:
{
    "board": [None, None, None, None, None, None, None, None, None],
    "players": ["player_id_1_X", "player_id_2_O"],
    "current_turn_index": 0,  # 'X' starts
    "status": "in_progress", # "in_progress", "finished"
    "winner": None,          # null, player_id, or "draw"
    "log": ["Game started. X's turn."]
}
```

#### 3.3 Step 3: Write Your Engine (`tictactoe_logic.py`)

We create a new file `backend/tictactoe_logic.py` and implement our two-function "contract."

```python
# backend/tictactoe_logic.py
import random

WIN_CONDITIONS = [
    [0, 1, 2], [3, 4, 5], [6, 7, 8],  # Rows
    [0, 3, 6], [1, 4, 7], [2, 5, 8],  # Cols
    [0, 4, 8], [2, 4, 6]              # Diagonals
]

def create_new_game(player_ids: list[str], game_mode: str = "classic"):
    """Creates an initial game state for Tic-Tac-Toe."""
    if len(player_ids) != 2:
        raise ValueError("Tic-Tac-Toe must have exactly 2 players.")
    
    # Randomize who goes first
    random.shuffle(player_ids)
    
    game_state = {
        "board": [None] * 9,
        "players": player_ids,
        "current_turn_index": 0,
        "status": "in_progress",
        "winner": None,
        "log": [f"Game started. {player_ids[0]}'s turn (X)."]
    }
    return game_state

def _check_for_winner(board, player_symbol):
    for condition in WIN_CONDITIONS:
        if all(board[i] == player_symbol for i in condition):
            return True
    return False

def play_move(game_state: dict, player_id: str, move_data: dict):
    """Handles a Tic-Tac-Toe move."""
    
    # --- 1. Validation ---
    turn_player_id = game_state['players'][game_state['current_turn_index']]
    if player_id != turn_player_id:
        raise ValueError("It is not your turn.")

    if game_state['status'] == 'finished':
        raise ValueError("The game is already over.")

    try:
        cell_index = int(move_data.get('cell_index'))
    except:
        raise ValueError("Invalid move data. 'cell_index' (0-8) required.")

    if not (0 <= cell_index <= 8):
        raise ValueError("Cell index must be between 0 and 8.")
        
    if game_state['board'][cell_index] is not None:
        raise ValueError("This cell is already taken.")
        
    # --- 2. Update State ---
    player_symbol = 'X' if game_state['current_turn_index'] == 0 else 'O'
    game_state['board'][cell_index] = player_symbol
    game_state['log'].append(f"{player_id} places an {player_symbol} at {cell_index}.")

    # --- 3. Check for Win/Draw ---
    if _check_for_winner(game_state['board'], player_symbol):
        game_state['status'] = 'finished'
        game_state['winner'] = player_id
        game_state['log'].append(f"🎉 GAME OVER: {player_id} ({player_symbol}) wins!")
    
    # Check for Draw (all cells full, no winner)
    elif all(cell is not None for cell in game_state['board']):
        game_state['status'] = 'finished'
        game_state['winner'] = 'draw'
        game_state['log'].append("🤝 GAME OVER: It's a draw!")
    
    # --- 4. Advance Turn ---
    else:
        game_state['current_turn_index'] = (game_state['current_turn_index'] + 1) % 2
        next_player_id = game_state['players'][game_state['current_turn_index']]
        game_state['log'].append(f"It is now {next_player_id}'s turn.")
        
    # --- 5. Return new state ---
    return game_state
```

#### 3.4 Step 4: Plug It In

1.  In `backend/main.py`, add `import tictactoe_logic`.
2.  In `backend/main.py`, update the router:
    ```python
    GAME_LOGIC_MODULES = {
        "dominoes": domino_logic,
        "blackjack": blackjack_logic,
        "tictactoe": tictactoe_logic,  # <-- It's now officially supported
    }
    ```

#### 3.5 Step 5: Build the Frontend

1.  In `frontend/index.html`, add `<option value="tictactoe">Tic-Tac-Toe</option>` to the `<select>` list.
2.  In `frontend/app.js`, add a new `renderTicTacToe(state)` function that, like the other renderers, hides the other game UIs and builds an HTML grid based on the `state.board` array, adding click listeners that call `sendMove({ cell_index: i })`.

**Frontend Implementation Example:**

```javascript
// frontend/app.js

function renderTicTacToe(state) {
  // Hide other game UIs
  document.getElementById('blackjack-ui').style.display = 'none';
  document.getElementById('dominoes-ui').style.display = 'none';
  document.getElementById('tictactoe-ui').style.display = 'block';
  
  const board = state.board;
  const currentPlayer = state.players[state.current_turn_index];
  const isMyTurn = currentPlayer === playerId;
  
  // Render the 3x3 grid
  const gridContainer = document.getElementById('tictactoe-grid');
  gridContainer.innerHTML = '';
  
  for (let i = 0; i < 9; i++) {
    const cell = document.createElement('div');
    cell.className = 'tictactoe-cell';
    cell.textContent = board[i] || '';
    cell.onclick = () => {
      if (isMyTurn && !board[i]) {
        sendMove(ws, { cell_index: i });
      }
    };
    gridContainer.appendChild(cell);
  }
  
  // Show game status
  if (state.status === 'finished') {
    if (state.winner === 'draw') {
      document.getElementById('tictactoe-status').textContent = "It's a draw!";
    } else {
      document.getElementById('tictactoe-status').textContent = `${state.winner} wins!`;
    }
  } else {
    document.getElementById('tictactoe-status').textContent = 
      isMyTurn ? "Your turn!" : `${currentPlayer}'s turn`;
  }
}
```

We are finished. We have added an *entirely new game* to our platform, and we did not have to modify *a single line* of our core server infrastructure (`main.py`'s connection or routing logic), database, or existing game engines.

This is the power and payoff of a clean, extensible, and well-abstracted architecture.

-----

## 🎮 Usage Examples

### Example 1: Playing Blackjack

```python
# Python client example
import requests
import websocket
import json

# 1. Create a game
response = requests.post("http://localhost:8000/api/game/create", json={
    "player_id": "player1",
    "game_type": "blackjack",
    "game_mode": "best_of_5"
})
game_id = response.json()["game_id"]
print(f"Created game: {game_id}")

# 2. Connect via WebSocket
ws = websocket.WebSocket()
ws.connect(f"ws://localhost:8000/ws/game/{game_id}/player1")

# 3. Start the game (as host)
ws.send(json.dumps({"type": "start_game"}))

# 4. Wait for game state
message = json.loads(ws.recv())
print("Game started:", message)

# 5. Make a move (hit)
ws.send(json.dumps({
    "type": "make_move",
    "move_data": {"action": "hit"}
}))

# 6. Receive state update
update = json.loads(ws.recv())
print("State updated:", update)
```

### Example 2: Playing Dominoes

```javascript
// JavaScript client example

// 1. Create a game
const createResponse = await fetch('http://localhost:8000/api/game/create', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    player_id: 'player1',
    game_type: 'dominoes',
    game_mode: 'classic'
  })
});
const { game_id } = await createResponse.json();

// 2. Join the game
await fetch(`http://localhost:8000/api/game/${game_id}/join`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ player_id: 'player2' })
});

// 3. Connect via WebSocket
const ws = new WebSocket(`ws://localhost:8000/ws/game/${game_id}/player1`);

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log('Received:', message);
  
  if (message.type === 'state_update') {
    const state = message.game_state;
    console.log('Current board:', state.board);
    console.log('My hand:', state.hands['player1']);
    console.log('Current turn:', state.players[state.current_turn_index]);
  }
};

// 4. Start the game
ws.send(JSON.stringify({ type: 'start_game' }));

// 5. Play a tile
ws.send(JSON.stringify({
  type: 'make_move',
  move_data: {
    action: 'play',
    tile: [6, 5],
    side: 'right'
  }
}));
```

### Example 3: Testing Game Logic Directly

You can test game logic modules directly without the server:

```python
# test_blackjack.py
import blackjack_logic

# Create a new game
player_ids = ["player1", "player2", "player3"]
game_state = blackjack_logic.create_new_game(player_ids, "best_of_5")

print("Initial state:")
print(f"Players: {game_state['players']}")
print(f"Current turn: {game_state['players'][game_state['current_turn_index']]}")

# Player 1 hits
game_state = blackjack_logic.play_move(
    game_state,
    "player1",
    {"action": "hit"}
)

print(f"\nAfter player1 hits:")
print(f"Player1 hand: {game_state['hands']['player1']['hand']}")
print(f"Player1 value: {game_state['hands']['player1']['value']}")

# Player 1 stands
game_state = blackjack_logic.play_move(
    game_state,
    "player1",
    {"action": "stand"}
)

print(f"\nAfter player1 stands:")
print(f"Player1 status: {game_state['hands']['player1']['status']}")
print(f"Current turn: {game_state['players'][game_state['current_turn_index']]}")
```

-----

## 🤖 AI Players

The server automatically fills games with AI players when needed. AI players make moves automatically based on simple logic:

**Blackjack AI:**
- Hits if hand value < 17
- Stands if hand value >= 17

**Dominoes AI:**
- Plays the first valid tile
- Draws from boneyard if no valid play
- Passes if boneyard is empty

AI players are identified by the absence of a WebSocket connection. The server processes their moves automatically until it's a human player's turn.

-----

## 🧪 Testing

### Running the Server

```bash
cd backend
python main.py
```

The server will start on `http://localhost:8000`.

### Testing Game Logic

```bash
# Test blackjack logic
python -c "import blackjack_logic; print(blackjack_logic.create_new_game(['p1', 'p2'], 'best_of_5'))"

# Test dominoes logic
python -c "import domino_logic; print(domino_logic.create_new_game(['p1', 'p2'], 'classic'))"
```

### Testing API Endpoints

```bash
# Create a game
curl -X POST http://localhost:8000/api/game/create \
  -H "Content-Type: application/json" \
  -d '{"player_id": "test_player", "game_type": "blackjack", "game_mode": "best_of_5"}'

# Join a game (replace GAME_ID)
curl -X POST http://localhost:8000/api/game/GAME_ID/join \
  -H "Content-Type: application/json" \
  -d '{"player_id": "test_player2"}'
```

-----

## 📚 Additional Resources

- **FastAPI Documentation:** https://fastapi.tiangolo.com/
- **WebSocket Protocol:** https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API
- **MongoDB Python Driver (Motor):** https://motor.readthedocs.io/
- **Game Theory Basics:** Understanding game theory concepts helps design better game engines

-----

## 🎯 Key Takeaways

1. **Separation of Concerns:** The server (Conductor) handles infrastructure; game engines (Rulebooks) handle rules.
2. **Standardized Interface:** All games implement `create_new_game()` and `play_move()`.
3. **State Sanitization:** Each player receives a sanitized view of the game state.
4. **Database as Truth:** MongoDB stores the authoritative game state.
5. **Extensibility:** Adding new games requires only implementing the two-function interface.

This architecture scales from simple card games to complex board games, all from a single, unified platform.